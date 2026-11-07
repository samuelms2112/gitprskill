"""Tarefas Celery de enriquecimento de Pull Requests com IA.

``enrich_pr_with_ai_task`` busca o diff no GitHub com o token de instalação do tenant dono do PR,
gera o parecer de produto (PM/PO), pede a análise ao provedor configurado (Gemini ou o conselho
local via Ollama) e grava tudo, inclusive o embedding para a memória semântica.

Falhas de conexão com o banco são reenviadas com backoff. Limites de taxa da IA (só existem no
Gemini) reagendam a tarefa para depois do ``Retry-After``. No Ollama, não há 429.
"""

from __future__ import annotations

import asyncio

from celery import Task
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.celery_app import celery_app
from app.core.config import get_settings
from app.core.exceptions import AIRateLimitError, GitHubAppNotConfiguredError
from app.core.logging import configure_logging, get_logger
from app.services.ai.factory import open_ai_services
from app.services.ai.memory import SessionFactoryMemory
from app.services.ai.pm_po_agent import PMPOMasterAgent
from app.services.github_app_auth import (
    ClientFactory,
    GitHubAppAuth,
    GitHubInstallationDiffs,
)
from app.services.github_client import GitHubClient
from app.services.pr_enrichment import EnrichmentOutcome, enrich_pull_request

logger = get_logger(__name__)

SKIPPED_NO_AI_KEY = "skipped_ai_not_configured"
SKIPPED_NO_GITHUB_APP = "skipped_github_app_not_configured"


async def run_enrichment(pr_id: int) -> str:
    """Cria os clientes do processo, executa o enriquecimento e libera os recursos.

    Returns:
        O desfecho do enriquecimento ou um ``skipped_*`` quando a integração não está configurada.
    """
    settings = get_settings()
    configure_logging(settings.log_level)

    if not settings.ai_configured:
        logger.info("Enriquecimento ignorado: IA não configurada", extra={"pr_id": pr_id})
        return SKIPPED_NO_AI_KEY

    private_key = settings.github_app_private_key
    client_factory = _github_client_factory(settings.github_api_base_url, settings.github_request_timeout_seconds)
    try:
        app_auth = GitHubAppAuth(
            app_id=settings.github_app_id,
            private_key_pem=private_key.get_secret_value() if private_key else None,
            client_factory=client_factory,
        )
    except GitHubAppNotConfiguredError:
        logger.error("GitHub App não configurado; enriquecimento ignorado", extra={"pr_id": pr_id})
        return SKIPPED_NO_GITHUB_APP

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:
        diffs = GitHubInstallationDiffs(app_auth, client_factory)
        async with open_ai_services(settings) as services:
            pm_agent = PMPOMasterAgent(
                generator=services.pm_generator,
                embedder=services.embedder,
                memory=SessionFactoryMemory(session_factory) if services.embedder is not None else None,
            )
            outcome: EnrichmentOutcome = await enrich_pull_request(
                session_factory,
                pr_id,
                diffs=diffs,
                analyzer=services.provider,
                product_agent=pm_agent,
                embedder=services.embedder,
            )
    finally:
        await engine.dispose()
    return outcome.value


def _github_client_factory(base_url: str, timeout: float) -> ClientFactory:
    """Fábrica de ``GitHubClient`` para um token dado (JWT do App ou token de instalação)."""

    def factory(token: str) -> GitHubClient:
        return GitHubClient(base_url=base_url, token=token, timeout=timeout)

    return factory


@celery_app.task(
    name="enrich_pr_with_ai",
    bind=True,
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,
    acks_late=True,
)
def enrich_pr_with_ai_task(self: Task, pr_id: int) -> str:
    """Enriquece um PR com IA em segundo plano.

    Args:
        self: Instância da tarefa (usada para reagendar em caso de limite de taxa).
        pr_id: ``id`` interno do PR em ``pull_requests``.

    Returns:
        Desfecho do enriquecimento.
    """
    try:
        return asyncio.run(run_enrichment(pr_id))
    except AIRateLimitError as exc:
        logger.warning("Limite da IA atingido; reagendando", extra={"pr_id": pr_id})
        raise self.retry(exc=exc, countdown=exc.retry_after) from exc
