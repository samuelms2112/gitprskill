"""Tarefas Celery de enriquecimento de Pull Requests com IA.

``enrich_pr_with_ai_task`` busca o diff no GitHub com o token de instalação do tenant dono do PR,
gera o parecer de produto (PM/PO), pede a análise ao provedor configurado (Claude Code CLI ou
Gemini) e grava tudo.

Falhas de conexão com o banco são reenviadas com backoff. Limite de uso do Claude ou da cota do
Gemini reagenda a tarefa para depois do ``Retry-After``. Sessão do Claude expirada (``AUTH_REQUIRED``)
pausa a fila: as tarefas são reagendadas sem descartar o PR e sem gastar cota, até o login voltar.
"""

from __future__ import annotations

import asyncio

import redis
from celery import Task
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.audit import audit_event
from app.core.celery_app import celery_app
from app.core.config import get_settings
from app.core.exceptions import (
    AIRateLimitError,
    AISessionExpiredError,
    GitHubAppNotConfiguredError,
)
from app.core.logging import configure_logging, get_logger
from app.services.ai.claude_cli_service import ClaudeCliService
from app.services.ai.factory import open_ai_services
from app.services.ai.memory import SessionFactoryMemory
from app.services.ai.pm_po_agent import PMPOMasterAgent
from app.services.claude_session import (
    AUTH_REQUIRED,
    check_session,
    clear_auth_required,
    read_auth_state,
    set_auth_required,
)
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
# Intervalo entre tentativas enquanto a fila está pausada por falta de login.
AUTH_PAUSE_SECONDS = 300
# Trava curta: entre todas as tarefas pausadas, só uma testa a sessão a cada intervalo.
PROBE_LOCK_KEY = "claude:session:probe_lock"


async def run_enrichment(pr_id: int, *, single_model: bool = False) -> str:
    """Cria os clientes do processo, executa o enriquecimento e libera os recursos.

    ``single_model=True`` é o modo de backfill de PRs históricos: sem o parecer PM/PO.

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
            # Backfill: sem o parecer PM/PO (uma chamada a menos por PR).
            outcome: EnrichmentOutcome = await enrich_pull_request(
                session_factory,
                pr_id,
                diffs=diffs,
                analyzer=services.backfill_provider if single_model else services.provider,
                product_agent=None if single_model else pm_agent,
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
    """Enriquece um PR novo com IA em segundo plano (análise completa).

    Args:
        self: Instância da tarefa (usada para reagendar em caso de limite de taxa).
        pr_id: ``id`` interno do PR em ``pull_requests``.

    Returns:
        Desfecho do enriquecimento.
    """
    return _enrich_or_reschedule(self, pr_id, single_model=False)


@celery_app.task(
    name="enrich_pr_with_ai_backfill",
    bind=True,
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,
    acks_late=True,
)
def enrich_pr_with_ai_backfill_task(self: Task, pr_id: int) -> str:
    """Enriquece um PR histórico no modo de backfill (sem o parecer PM/PO, mais rápido).

    Args:
        self: Instância da tarefa (usada para reagendar em caso de limite de taxa).
        pr_id: ``id`` interno do PR em ``pull_requests``.

    Returns:
        Desfecho do enriquecimento.
    """
    return _enrich_or_reschedule(self, pr_id, single_model=True)


def _state_redis() -> redis.Redis:
    """Cliente Redis do estado da sessão do Claude (fechado pelo chamador)."""
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True)


def _enrich_or_reschedule(self: Task, pr_id: int, *, single_model: bool) -> str:
    client = _state_redis()
    try:
        if read_auth_state(client) == AUTH_REQUIRED and not _session_restored(client):
            logger.info("Fila pausada: sessão do Claude exige login", extra={"pr_id": pr_id})
            # max_retries=None: a pausa não consome as tentativas da tarefa, e o PR não é descartado.
            raise self.retry(countdown=AUTH_PAUSE_SECONDS, max_retries=None)
        return asyncio.run(run_enrichment(pr_id, single_model=single_model))
    except AISessionExpiredError as exc:
        set_auth_required(client, exc.message)
        audit_event("claude_session_expired", pr_id=pr_id)
        raise self.retry(exc=exc, countdown=AUTH_PAUSE_SECONDS, max_retries=None) from exc
    except AIRateLimitError as exc:
        logger.warning("Limite da IA atingido; reagendando", extra={"pr_id": pr_id})
        raise self.retry(exc=exc, countdown=exc.retry_after) from exc
    finally:
        client.close()


def _session_restored(client: redis.Redis) -> bool:
    """Durante a pausa, testa a sessão no máximo uma vez por intervalo (uma única tarefa testa).

    Se o login voltou, retoma a fila e devolve ``True``. Caso contrário, devolve ``False``.
    """
    if not client.set(PROBE_LOCK_KEY, "1", nx=True, ex=AUTH_PAUSE_SECONDS):
        return False
    settings = get_settings()
    service = ClaudeCliService(
        command=settings.claude_cli_command,
        model=settings.claude_cli_model,
        timeout=settings.claude_cli_timeout_seconds,
        max_diff_chars=settings.claude_max_diff_chars,
    )
    status = asyncio.run(check_session(service))
    if not status.authenticated:
        return False
    clear_auth_required(client)
    audit_event("claude_session_restored", source="worker")
    return True
