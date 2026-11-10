"""Claude como provedor de IA, via Claude Code CLI em modo não interativo (``claude -p``).

O CLI roda como subprocesso no servidor, autenticado pelo login salvo em ``/root/.claude``
(sem chave de API). O prompt segue pela entrada padrão, porque diffs grandes não cabem na
linha de comando. Todas as ferramentas do Claude Code ficam desligadas: o modelo só devolve texto.

Falhas:
    * Sessão ausente ou expirada -> ``AISessionExpiredError`` (o worker pausa a fila e não descarta o PR).
    * CLI ausente, tempo esgotado, saída com erro -> ``AIUnavailableError``.
    * Limite de uso da assinatura -> ``AIRateLimitError`` com o tempo informado pelo CLI.
    * Resposta vazia ou fora do formato -> ``AIResponseError``.
"""

from __future__ import annotations

import asyncio
import json
import re
import tempfile
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from app.core.exceptions import (
    AIRateLimitError,
    AIResponseError,
    AISessionExpiredError,
    AIUnavailableError,
)
from app.core.logging import get_logger
from app.models.pull_request import PullRequest
from app.services.ai_prompts import build_analysis_prompt, build_release_notes_prompt
from app.services.ai_service import PullRequestAnalysis, parse_analysis

logger = get_logger(__name__)

MIN_LIMIT_RETRY_SECONDS = 60
# O CLI informa o fim do limite de uso como "usage limit reached|<epoch em segundos>".
_USAGE_LIMIT = re.compile(r"usage limit reached\|(\d+)", re.IGNORECASE)
# Mensagens que o CLI emite quando não há login válido.
_SESSION_ERROR = re.compile(
    r"please run /login|not logged in|invalid api key|authentication_error|"
    r"oauth token has expired|invalid_grant|failed to authenticate",
    re.IGNORECASE,
)
_CODE_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


@dataclass(frozen=True, slots=True)
class CliOutput:
    """Resultado bruto de uma execução do CLI."""

    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[list[str], str, float], Awaitable[CliOutput]]


def build_argv(command: str, model: str) -> list[str]:
    """Argumentos do modo não interativo: saída JSON, sem ferramentas e sem gravar sessão."""
    return [
        command,
        "-p",
        "--model",
        model,
        "--output-format",
        "json",
        "--no-session-persistence",
        "--tools",
        "",
    ]


async def run_subprocess(argv: list[str], stdin_text: str, timeout: float) -> CliOutput:
    """Executa o CLI com o prompt na entrada padrão.

    Raises:
        AIUnavailableError: Executável não encontrado ou tempo limite esgotado (o processo é encerrado).
    """
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            # Fora de qualquer projeto: o CLI não carrega CLAUDE.md nem configurações locais.
            cwd=tempfile.gettempdir(),
        )
    except FileNotFoundError as exc:
        raise AIUnavailableError(f"Claude Code CLI não encontrado: '{argv[0]}'.") from exc

    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(stdin_text.encode("utf-8")), timeout)
    except TimeoutError as exc:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        await process.wait()
        raise AIUnavailableError("O Claude Code CLI excedeu o tempo limite.") from exc

    return CliOutput(
        returncode=process.returncode or 0,
        stdout=stdout.decode("utf-8", "replace"),
        stderr=stderr.decode("utf-8", "replace"),
    )


class ClaudeCliService:
    """Cliente do Claude Code CLI. Implementa análise de PRs, texto livre e release notes."""

    def __init__(
        self,
        *,
        command: str,
        model: str,
        timeout: float,
        max_diff_chars: int,
        runner: CommandRunner = run_subprocess,
    ) -> None:
        self._command = command
        self._model = model
        self._timeout = timeout
        self._max_diff_chars = max_diff_chars
        self._runner = runner

    @property
    def model(self) -> str:
        return self._model

    async def analyze_pull_request(
        self,
        title: str,
        description: str,
        diff_text: str,
        *,
        product_context: str | None = None,
    ) -> PullRequestAnalysis:
        prompt = build_analysis_prompt(
            title, description, diff_text, self._max_diff_chars, product_context=product_context
        )
        return parse_analysis(_strip_code_fence(await self.ask(prompt)))

    async def generate_text(self, prompt: str) -> str:
        text = (await self.ask(prompt)).strip()
        if not text:
            raise AIResponseError("O Claude respondeu vazio.")
        return text

    async def generate_release_notes(self, prs: Sequence[PullRequest]) -> str:
        return await self.generate_text(build_release_notes_prompt(prs))

    async def ask(self, prompt: str) -> str:
        """Envia um prompt ao CLI e devolve o texto da resposta.

        Raises:
            AISessionExpiredError: Login ausente ou expirado.
            AIRateLimitError: Limite de uso da assinatura atingido.
            AIUnavailableError: CLI ausente, tempo esgotado ou falha de execução.
            AIResponseError: Saída fora do formato esperado.
        """
        output = await self._runner(build_argv(self._command, self._model), prompt, self._timeout)
        return _result_text(output, self._model)


def _result_text(output: CliOutput, model: str) -> str:
    """Extrai o texto da saída JSON do CLI, classificando as falhas."""
    data = _load_json_object(output.stdout)
    message = _message_of(data, output)

    if data is None or data.get("is_error") or output.returncode != 0:
        usage = _USAGE_LIMIT.search(message)
        if usage is not None:
            raise AIRateLimitError(retry_after=_seconds_until(usage.group(1)))
        if _SESSION_ERROR.search(message) or _SESSION_ERROR.search(output.stderr):
            logger.warning("Sessão do Claude Code CLI inválida", extra={"model": model})
            raise AISessionExpiredError("A sessão do Claude expirou. É preciso refazer o login no servidor.")
        logger.error(
            "Claude Code CLI falhou",
            extra={"returncode": output.returncode, "model": model, "stderr": output.stderr[:300]},
        )
        if data is None:
            raise AIUnavailableError("O Claude Code CLI falhou sem uma resposta válida.")
        raise AIUnavailableError("O Claude Code CLI retornou erro.")

    result = data.get("result")
    if not isinstance(result, str) or not result.strip():
        raise AIResponseError("O Claude respondeu vazio.")
    return result


def _load_json_object(text: str) -> dict[str, Any] | None:
    try:
        data = json.loads(text.strip())
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _message_of(data: dict[str, Any] | None, output: CliOutput) -> str:
    if data is not None and isinstance(data.get("result"), str):
        return data["result"]
    return output.stderr


def _seconds_until(epoch: str) -> int:
    return max(int(epoch) - int(time.time()), MIN_LIMIT_RETRY_SECONDS)


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    match = _CODE_FENCE.match(stripped)
    return match.group(1) if match else stripped
