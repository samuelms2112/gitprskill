"""Escolha do provedor de IA pela variável ``AI_PROVIDER``.

Esta é a única função que decide entre Gemini e Ollama. O restante do sistema recebe os serviços
prontos, sem saber de qual provedor eles vieram.

Embeddings (memória semântica) só são ativados no modo ``ollama``: o modelo de embeddings é
local e gratuito. No modo ``gemini`` a memória fica desligada.

No modo ``ollama``, o agente PM/PO usa o modelo próprio ``OLLAMA_PM_MODEL``, separado do conselho.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from app.core.config import Settings
from app.core.exceptions import AINotConfiguredError
from app.services.ai.base import AIProvider, TextEmbedder, TextGenerator
from app.services.ai.consensus import LocalAIConsensusEngine
from app.services.ai.ollama import OllamaClient, OllamaTextModel
from app.services.ai_service import AIService


@dataclass(frozen=True, slots=True)
class AIServices:
    """Serviços de IA do provedor configurado.

    ``provider``: análise técnica (conselho local ou Gemini).
    ``pm_generator``: texto do agente PM/PO (modelo próprio, ou o próprio Gemini).
    ``embedder``: embeddings da memória semântica (só no modo local).
    """

    provider: AIProvider
    pm_generator: TextGenerator
    embedder: TextEmbedder | None


@asynccontextmanager
async def open_ai_services(settings: Settings) -> AsyncIterator[AIServices]:
    """Abre os serviços de IA do provedor configurado e os fecha ao sair.

    Raises:
        AINotConfiguredError: Provedor escolhido sem a credencial ou modelos necessários.
    """
    if settings.ai_provider == "ollama":
        if not settings.ai_configured:
            raise AINotConfiguredError("Nenhum modelo local configurado (OLLAMA_MODELS).")
        async with OllamaClient(
            base_url=settings.ollama_base_url,
            timeout=settings.ollama_timeout_seconds,
            embedding_model=settings.ollama_embedding_model,
        ) as client:
            engine = LocalAIConsensusEngine(client, settings.ollama_model_list, settings.gemini_max_diff_chars)
            yield AIServices(
                provider=engine,
                pm_generator=OllamaTextModel(client, settings.ollama_pm_model),
                embedder=client,
            )
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
        yield AIServices(provider=gemini, pm_generator=gemini, embedder=None)
