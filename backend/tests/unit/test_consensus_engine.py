"""Testes unitários do conselho de IAs locais: regras de voto, paralelismo e tolerância a falhas."""

import asyncio
import json

import pytest

from app.core.exceptions import AIResponseError, AIUnavailableError
from app.models.enums import AICategory, AIRiskLevel
from app.services.ai.consensus import LocalAIConsensusEngine, consensus
from app.services.ai_service import PullRequestAnalysis

SUMMARY_A = "Primeiro modelo: resume a mudança com detalhes suficientes."
SUMMARY_B = "Segundo modelo: outro resumo válido para o mesmo PR."


def _analysis(category: AICategory, risk: AIRiskLevel, summary: str = SUMMARY_A) -> PullRequestAnalysis:
    return PullRequestAnalysis(summary=summary, category=category, risk_level=risk)


def _json(category: str, risk: str, summary: str = SUMMARY_A) -> str:
    return json.dumps({"summary": summary, "category": category, "risk_level": risk})


class FakeOllama:
    """Cliente falso: respostas por modelo, com medição de concorrência."""

    def __init__(self, responses: dict[str, str | Exception]) -> None:
        self._responses = responses
        self.in_flight = 0
        self.max_in_flight = 0
        self.calls: list[str] = []

    async def chat(self, model: str, prompt: str, *, json_output: bool = False) -> str:
        self.calls.append(model)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(0.01)
        finally:
            self.in_flight -= 1
        response = self._responses[model]
        if isinstance(response, Exception):
            raise response
        return response


# --- Regras de voto (função pura) ------------------------------------------------------


def test_majority_wins_the_category() -> None:
    """A categoria mais votada vence."""
    result = consensus(
        [
            _analysis(AICategory.FEATURE, AIRiskLevel.LOW),
            _analysis(AICategory.SECURITY, AIRiskLevel.LOW),
            _analysis(AICategory.SECURITY, AIRiskLevel.LOW),
        ]
    )
    assert result.category is AICategory.SECURITY


def test_category_tie_goes_to_the_first_model() -> None:
    """Empate de categoria: vence a que apareceu primeiro na ordem dos modelos."""
    result = consensus(
        [
            _analysis(AICategory.BUGFIX, AIRiskLevel.LOW),
            _analysis(AICategory.FEATURE, AIRiskLevel.LOW),
        ]
    )
    assert result.category is AICategory.BUGFIX


def test_risk_tie_goes_to_the_higher_risk() -> None:
    """Empate de risco: vence o mais alto. Na dúvida, o time é alertado."""
    result = consensus(
        [
            _analysis(AICategory.FEATURE, AIRiskLevel.LOW),
            _analysis(AICategory.FEATURE, AIRiskLevel.HIGH),
        ]
    )
    assert result.risk_level is AIRiskLevel.HIGH


def test_summary_comes_from_a_model_that_voted_for_the_winner() -> None:
    """O resumo vem de quem votou na categoria vencedora, para que resumo e categoria combinem."""
    result = consensus(
        [
            _analysis(AICategory.FEATURE, AIRiskLevel.LOW, SUMMARY_A),
            _analysis(AICategory.SECURITY, AIRiskLevel.LOW, SUMMARY_B),
            _analysis(AICategory.SECURITY, AIRiskLevel.LOW, SUMMARY_B),
        ]
    )
    assert result.summary == SUMMARY_B


def test_consensus_requires_at_least_one_analysis() -> None:
    """Sem nenhuma análise, não há consenso possível."""
    with pytest.raises(ValueError):
        consensus([])


# --- Motor com paralelismo e tolerância a falhas ---------------------------------------


async def test_models_run_in_parallel_not_one_after_another() -> None:
    """Os modelos são consultados ao mesmo tempo (``asyncio.gather``), não em fila."""
    fake = FakeOllama({
        "qwen2.5-coder:7b": _json("FEATURE", "LOW"),
        "deepseek-r1:8b": _json("FEATURE", "LOW"),
        "llama3.1:8b": _json("FEATURE", "LOW"),
    })
    engine = LocalAIConsensusEngine(fake, ["qwen2.5-coder:7b", "deepseek-r1:8b", "llama3.1:8b"], 60_000)

    await engine.analyze_pull_request("título", "descrição", "diff")

    assert fake.max_in_flight == 3


async def test_one_failing_model_does_not_block_the_consensus() -> None:
    """Um modelo fora do ar fica de fora do voto; os outros decidem."""
    fake = FakeOllama({
        "qwen2.5-coder:7b": _json("SECURITY", "HIGH"),
        "deepseek-r1:8b": AIUnavailableError("fora do ar"),
        "llama3.1:8b": _json("SECURITY", "MEDIUM"),
    })
    engine = LocalAIConsensusEngine(fake, ["qwen2.5-coder:7b", "deepseek-r1:8b", "llama3.1:8b"], 60_000)

    result = await engine.analyze_pull_request("t", "d", "diff")

    assert result.category is AICategory.SECURITY
    assert result.risk_level is AIRiskLevel.HIGH  # empate 1x1 entre HIGH e MEDIUM: vence o mais alto


async def test_invalid_json_from_a_model_is_discarded() -> None:
    """Um modelo que devolve texto fora do schema não contamina o voto."""
    fake = FakeOllama({
        "qwen2.5-coder:7b": "isto não é JSON",
        "llama3.1:8b": _json("REFACTOR", "LOW"),
    })
    engine = LocalAIConsensusEngine(fake, ["qwen2.5-coder:7b", "llama3.1:8b"], 60_000)

    result = await engine.analyze_pull_request("t", "d", "diff")

    assert result.category is AICategory.REFACTOR


async def test_all_models_failing_is_unavailable() -> None:
    """Se nenhum modelo produzir análise válida, a falha é explícita."""
    fake = FakeOllama({
        "qwen2.5-coder:7b": AIResponseError("ruim"),
        "llama3.1:8b": AIUnavailableError("fora"),
    })
    engine = LocalAIConsensusEngine(fake, ["qwen2.5-coder:7b", "llama3.1:8b"], 60_000)

    with pytest.raises(AIUnavailableError, match="Nenhum modelo"):
        await engine.analyze_pull_request("t", "d", "diff")


async def test_text_generation_falls_back_to_the_next_model() -> None:
    """Para texto livre, o primeiro modelo disponível responde."""
    fake = FakeOllama({
        "qwen2.5-coder:7b": AIUnavailableError("fora"),
        "llama3.1:8b": "release notes geradas",
    })
    engine = LocalAIConsensusEngine(fake, ["qwen2.5-coder:7b", "llama3.1:8b"], 60_000)

    assert await engine.generate_text("prompt") == "release notes geradas"
    assert fake.calls == ["qwen2.5-coder:7b", "llama3.1:8b"]


def test_engine_requires_at_least_one_model() -> None:
    """Conselho vazio não é configuração válida."""
    with pytest.raises(ValueError):
        LocalAIConsensusEngine(FakeOllama({}), [], 60_000)
