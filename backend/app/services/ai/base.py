"""Contratos dos provedores de IA. O restante do sistema depende só destes protocolos.

Um provedor implementa a análise de PRs, a geração de texto livre e as release notes.
Um embedder converte texto em vetor, para a memória semântica (pgvector).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from app.models.pull_request import PullRequest
from app.services.ai_service import PullRequestAnalysis


class AIProvider(Protocol):
    """Provedor de análise e geração (Claude Code CLI, ou Gemini na nuvem)."""

    async def analyze_pull_request(
        self,
        title: str,
        description: str,
        diff_text: str,
        *,
        product_context: str | None = None,
    ) -> PullRequestAnalysis: ...

    async def generate_text(self, prompt: str) -> str: ...

    async def generate_release_notes(self, prs: Sequence[PullRequest]) -> str: ...


class TextGenerator(Protocol):
    """Geração de texto livre por um modelo específico (ex.: o modelo do agente PM/PO)."""

    async def generate_text(self, prompt: str) -> str: ...


class TextEmbedder(Protocol):
    """Converte texto em vetor de embedding para busca por similaridade."""

    async def embed(self, text: str) -> list[float]: ...
