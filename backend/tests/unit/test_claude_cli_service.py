"""Testes unitários do cliente do Claude Code CLI: argumentos, saída e falhas de subprocesso."""

import json
import sys

import pytest

from app.core.exceptions import (
    AIResponseError,
    AISessionExpiredError,
    AIUnavailableError,
)
from app.models.enums import AICategory
from app.services.ai.claude_cli_service import (
    ClaudeCliService,
    CliOutput,
    build_argv,
    run_subprocess,
)


def _service(output: CliOutput, captured: list[tuple[list[str], str]] | None = None) -> ClaudeCliService:
    async def runner(argv: list[str], prompt: str, timeout: float) -> CliOutput:
        if captured is not None:
            captured.append((argv, prompt))
        return output

    return ClaudeCliService(command="claude", model="claude-sonnet-5-5", timeout=5, max_diff_chars=2000, runner=runner)


def _result(text: str) -> CliOutput:
    return CliOutput(0, json.dumps({"type": "result", "is_error": False, "result": text}), "")


def test_argv_is_non_interactive_without_tools_and_without_prompt() -> None:
    """O prompt vai pela entrada padrão; o comando não tem ferramentas nem grava sessão."""
    argv = build_argv("claude", "claude-sonnet-5-5")

    assert argv[:3] == ["claude", "-p", "--model"]
    assert "claude-sonnet-5-5" in argv
    assert "--no-session-persistence" in argv
    assert argv[argv.index("--output-format") + 1] == "json"
    assert argv[argv.index("--tools") + 1] == ""


async def test_prompt_is_sent_through_stdin_not_arguments() -> None:
    captured: list[tuple[list[str], str]] = []
    big_prompt = "diff " * 5000

    await _service(_result("ok"), captured).ask(big_prompt)

    argv, prompt = captured[0]
    assert prompt == big_prompt
    assert big_prompt not in argv


async def test_analysis_accepts_json_wrapped_in_code_fence() -> None:
    analysis = {
        "summary": "Refatora o cliente de IA para usar o Claude Code CLI no lugar do Ollama.",
        "category": "REFACTOR",
        "risk_level": "MEDIUM",
    }
    fenced = f"```json\n{json.dumps(analysis)}\n```"

    result = await _service(_result(fenced)).analyze_pull_request("Título", "Descrição", "diff")

    assert result.summary.startswith("Refatora")
    assert result.category == AICategory.REFACTOR


async def test_empty_result_is_a_response_error() -> None:
    with pytest.raises(AIResponseError):
        await _service(_result("   ")).generate_text("qualquer coisa")


async def test_login_error_is_session_expired() -> None:
    output = CliOutput(1, json.dumps({"is_error": True, "result": "Invalid API key · Please run /login"}), "")

    with pytest.raises(AISessionExpiredError):
        await _service(output).ask("ok")


async def test_nonzero_exit_without_json_is_unavailable() -> None:
    with pytest.raises(AIUnavailableError):
        await _service(CliOutput(2, "", "erro inesperado")).ask("ok")


async def test_missing_executable_is_unavailable() -> None:
    with pytest.raises(AIUnavailableError):
        await run_subprocess(["comando-que-nao-existe-xyz"], "ok", 5)


async def test_timeout_kills_the_process_and_is_unavailable() -> None:
    argv = [sys.executable, "-c", "import time; time.sleep(30)"]

    with pytest.raises(AIUnavailableError, match="tempo limite"):
        await run_subprocess(argv, "", 0.5)
