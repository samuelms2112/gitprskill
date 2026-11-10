"""Escolha do provedor de IA pela variável ``AI_PROVIDER``.

Esta é a única função que decide entre o Claude Code CLI e o Gemini. O restante do sistema recebe
os serviços prontos, sem saber de qual provedor eles vieram.

Sem modelo de embeddings disponível no Claude, a memória semântica (pgvector) fica desligada:
``embedder`` é ``None`` e o parecer PM/PO sai sem histórico.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from app.core.config import Settings
from app.core.exceptions import AINotConfiguredError
from app.services.ai.base import AIProvider, TextEmbedder, TextGenerator
from app.services.ai.claude_cli_service import ClaudeCliService
from app.services.ai_service import AIService


@dataclass(frozen=True, slots=True)
class AIServices:
    """Serviços de IA do provedor configurado.

    ``provider``: análise técnica dos PRs novos.
    ``backfill_provider``: análise técnica dos PRs históricos (o mesmo ``provider`` nos provedores atuais).
    ``pm_generator``: texto do agente PM/PO.
    ``embedder``: embeddings da memória semântica; ``None`` enquanto nenhum provedor oferece embeddings.
    """

    provider: AIProvider
    backfill_provider: AIProvider
    pm_generator: TextGenerator
    embedder: TextEmbedder | None


@asynccontextmanager
async def open_ai_services(settings: Settings) -> AsyncIterator[AIServices]:
    """Abre os serviços de IA do provedor configurado e os fecha ao sair.

    Raises:
        AINotConfiguredError: Provedor escolhido sem a credencial ou o executável necessário.
    """
    if settings.ai_provider == "claude_cli":
        if not settings.ai_configured:
            raise AINotConfiguredError(
                f"Claude Code CLI não encontrado no servidor ('{settings.claude_cli_command}')."
            )
        claude = ClaudeCliService(
            command=settings.claude_cli_command,
            model=settings.claude_cli_model,
            timeout=settings.claude_cli_timeout_seconds,
            max_diff_chars=settings.claude_max_diff_chars,
        )
        yield AIServices(provider=claude, backfill_provider=claude, pm_generator=claude, embedder=None)
        return

    api_key = settings.gemini_api_key
    if api_key is None:
        raise AINotConfiguredError("Integração com IA não configurada no servidor.")
    async with AIService(
        api_key=api_key,
        model=settings.gemini_model,
        base_url=settings.gemini_base_url,
        max_diff_chars=settings.gemini_max_diff_chars,
        timeout=settings.gemini_timeout_seconds,
    ) as gemini:
        yield AIServices(provider=gemini, backfill_provider=gemini, pm_generator=gemini, embedder=None)
