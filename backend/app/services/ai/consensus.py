"""Conselho de IAs locais: vários modelos analisam o mesmo PR em paralelo e votam o resultado.

Regras de consenso (função pura, testável sem rede):
    * Categoria: maioria simples. Em empate, vence a que apareceu primeiro na ordem configurada.
    * Risco: maioria simples. Em empate, vence o **mais alto**: na dúvida, o time é alertado.
    * Resumo: o do primeiro modelo que votou na categoria vencedora.

Modelos que falham (serviço fora, JSON inválido) ficam de fora do voto. Só falha tudo se
nenhum modelo produzir uma análise válida.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Sequence
from typing import TypeVar

from app.core.exceptions import AIError, AIResponseError, AIUnavailableError
from app.core.logging import get_logger
from app.models.enums import AICategory, AIRiskLevel
from app.models.pull_request import PullRequest
from app.services.ai.ollama import OllamaClient
from app.services.ai_prompts import build_analysis_prompt, build_release_notes_prompt
from app.services.ai_service import PullRequestAnalysis, parse_analysis

logger = get_logger(__name__)

_RISK_RANK: dict[AIRiskLevel, int] = {AIRiskLevel.LOW: 0, AIRiskLevel.MEDIUM: 1, AIRiskLevel.HIGH: 2}
_T = TypeVar("_T", AICategory, AIRiskLevel)


def _majority(values: Sequence[_T], tie_break: dict[_T, int]) -> _T:
    """Valor mais votado. Empates são resolvidos pelo peso em ``tie_break`` (maior vence)."""
    counts = Counter(values)
    best = max(counts.values())
    tied = [value for value, count in counts.items() if count == best]
    return max(tied, key=lambda value: tie_break[value])


def consensus(analyses: Sequence[PullRequestAnalysis]) -> PullRequestAnalysis:
    """Combina as análises dos modelos em um resultado único.

    Raises:
        ValueError: Se não houver nenhuma análise para combinar.
    """
    if not analyses:
        raise ValueError("Consenso exige ao menos uma análise.")

    categories = [analysis.category for analysis in analyses]
    # Para categorias, o desempate privilegia quem apareceu primeiro (ordem dos modelos).
    first_seen = {category: -categories.index(category) for category in categories}
    winner_category = _majority(categories, first_seen)
    winner_risk = _majority([analysis.risk_level for analysis in analyses], _RISK_RANK)

    supporting = next(analysis for analysis in analyses if analysis.category is winner_category)
    return PullRequestAnalysis(
        summary=supporting.summary,
        category=winner_category,
        risk_level=winner_risk,
    )


class LocalAIConsensusEngine:
    """Executa o conselho de modelos locais em paralelo e produz um único parecer."""

    def __init__(self, client: OllamaClient, models: Sequence[str], max_diff_chars: int) -> None:
        if not models:
            raise ValueError("O conselho local precisa de ao menos um modelo.")
        self._client = client
        self._models = list(models)
        self._max_diff_chars = max_diff_chars

    async def analyze_pull_request(
        self,
        title: str,
        description: str,
        diff_text: str,
        *,
        product_context: str | None = None,
    ) -> PullRequestAnalysis:
        """Pergunta a todos os modelos em paralelo e combina as análises válidas.

        Raises:
            AIUnavailableError: Nenhum modelo produziu uma análise válida.
        """
        prompt = build_analysis_prompt(
            title, description, diff_text, self._max_diff_chars, product_context=product_context
        )
        results = await asyncio.gather(
            *(self._ask(model, prompt) for model in self._models),
            return_exceptions=True,
        )

        analyses: list[PullRequestAnalysis] = []
        for model, result in zip(self._models, results, strict=True):
            if isinstance(result, PullRequestAnalysis):
                analyses.append(result)
            else:
                logger.warning(
                    "Modelo do conselho ficou de fora do voto",
                    extra={"model": model, "reason": type(result).__name__},
                )

        if not analyses:
            raise AIUnavailableError("Nenhum modelo do conselho local produziu uma análise válida.")
        return consensus(analyses)

    async def generate_text(self, prompt: str) -> str:
        """Texto livre: o primeiro modelo que responder. Ordem configurada = prioridade."""
        last_error: AIError | None = None
        for model in self._models:
            try:
                return await self._client.chat(model, prompt)
            except AIError as exc:
                last_error = exc
                logger.warning("Modelo do conselho indisponível para texto", extra={"model": model})
        raise last_error or AIUnavailableError("Nenhum modelo local disponível.")

    async def generate_release_notes(self, prs: Sequence[PullRequest]) -> str:
        notes = (await self.generate_text(build_release_notes_prompt(prs))).strip()
        if not notes:
            raise AIResponseError("O conselho local retornou release notes vazias.")
        return notes

    async def _ask(self, model: str, prompt: str) -> PullRequestAnalysis:
        text = await self._client.chat(model, prompt, json_output=True)
        return parse_analysis(text)
