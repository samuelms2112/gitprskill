"""Tarefa Celery que processa um evento do GitHub fora do ciclo da requisição.

Cada execução abre uma transação própria, então o evento inteiro é gravado ou nada é.
Falhas transitórias de conexão com o banco são reenviadas com backoff exponencial.
Payloads inválidos não são reenviados: repetir a mesma entrega não corrigiria o erro.
"""

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import redis
from kombu.exceptions import OperationalError as BrokerOperationalError
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.celery_app import celery_app
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.models.pull_request import PullRequest
from app.models.repository import Repository
from app.services.github_event_processor import GitHubEventProcessor
from app.services.review_store import (
    bot_comment_ids,
    bot_recently_active,
    request_review,
)
from app.services.review_trigger import (
    TRIGGER_EVENTS,
    acquire_debounce,
    decide,
    pr_reference,
)
from app.workers.review_tasks import review_pr_task
from app.workers.tasks import enrich_pr_with_ai_task

logger = get_logger(__name__)


async def handle_event(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tracked_branches: frozenset[str],
    event_name: str,
    delivery_id: str | None,
    payload: Mapping[str, Any],
) -> str:
    """Processa um evento em uma transação e devolve o desfecho como string.

    Após o commit, um PR mergeado é enviado para enriquecimento por IA. O disparo
    acontece fora da transação, para que o worker nunca veja um PR ainda não gravado.
    """
    async with session_factory() as session, session.begin():
        result = await GitHubEventProcessor(session, tracked_branches).process(event_name, payload)
    logger.info(
        "Evento do GitHub processado",
        extra={"event": event_name, "delivery_id": delivery_id, "outcome": result.outcome.value},
    )
    if result.enrich and result.pull_request_id is not None:
        _schedule_ai_enrichment(result.pull_request_id)
    if result.review and result.pull_request_id is not None:
        await schedule_pr_review(session_factory, result.pull_request_id)
    if event_name in TRIGGER_EVENTS:
        await schedule_reanalysis(session_factory, event_name=event_name, payload=payload)
    return result.outcome.value


async def schedule_reanalysis(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    event_name: str,
    payload: Mapping[str, Any],
) -> None:
    """Reavalia um PR após novo push ou comentário que mencione o bot ou responda a uma thread dele.

    Passos: identifica o PR, reúne os ids dos comentários do bot, aplica as regras de disparo,
    pega a trava de debounce no Redis e só então cria a revisão pendente e a enfileira.
    Melhor esforço: sem IA ou sem broker, nada quebra.
    """
    settings = get_settings()
    if not settings.ai_configured:
        return
    # Saída antecipada sem consultar o banco: só push ou comentário pode disparar.
    if event_name == "pull_request" and payload.get("action") != "synchronize":
        return
    reference = pr_reference(event_name, payload)
    if reference is None:
        return
    repository, number = reference

    async with session_factory() as session:
        row = (
            await session.execute(
                select(PullRequest.id, PullRequest.tenant_id)
                .join(Repository, Repository.id == PullRequest.repository_id)
                .where(Repository.full_name == repository, PullRequest.number == number)
            )
        ).first()
        if row is None:
            return
        pull_request_id, tenant_id = int(row[0]), int(row[1])
        known_bot_ids = await bot_comment_ids(session, pull_request_id)

    since = datetime.now(UTC) - timedelta(hours=settings.pr_bot_thread_window_hours)
    async with session_factory() as session:
        recent = await bot_recently_active(session, pull_request_id, since)
    decision = decide(event_name, payload, settings.github_app_slug, known_bot_ids, recent)
    if decision is None:
        return

    client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        allowed = acquire_debounce(
            client,
            tenant_id=tenant_id,
            pull_request_id=pull_request_id,
            ttl_seconds=settings.pr_review_debounce_seconds,
        )
    finally:
        client.close()
    if not allowed:
        logger.info(
            "Reavaliação ignorada pelo debounce",
            extra={"pr_id": pull_request_id, "trigger": decision.trigger.value},
        )
        return

    async with session_factory() as session, session.begin():
        review = await request_review(
            session,
            tenant_id=tenant_id,
            pull_request_id=pull_request_id,
            trigger=decision.trigger.value,
        )
        review_id = review.id
    try:
        review_pr_task.delay(review_id)
    except BrokerOperationalError:
        logger.warning("Não foi possível agendar a reavaliação", extra={"pr_id": pull_request_id})


async def schedule_pr_review(session_factory: async_sessionmaker[AsyncSession], pull_request_id: int) -> None:
    """Registra a revisão como PENDING (o card já mostra 'Revisando') e enfileira a tarefa.

    Melhor esforço: sem IA configurada ou sem broker, nada quebra; a revisão pode ser pedida
    depois pelo portal.
    """
    if not get_settings().ai_configured:
        return
    async with session_factory() as session, session.begin():
        pull_request = await session.get(PullRequest, pull_request_id)
        if pull_request is None:
            return
        review = await request_review(session, tenant_id=pull_request.tenant_id, pull_request_id=pull_request_id)
        review_id = review.id
    try:
        review_pr_task.delay(review_id)
    except BrokerOperationalError:
        logger.warning("Não foi possível agendar a revisão do PR", extra={"pr_id": pull_request_id})


def _schedule_ai_enrichment(pull_request_id: int) -> None:
    """Agenda o enriquecimento por IA como melhor esforço.

    Sem chave de IA configurada, nada é agendado. Se o broker estiver indisponível, o
    evento já foi gravado, então apenas registra um aviso: o PR pode ser enriquecido depois.
    """
    if not get_settings().ai_configured:
        return
    try:
        enrich_pr_with_ai_task.delay(pull_request_id)
    except BrokerOperationalError:
        logger.warning(
            "Não foi possível agendar o enriquecimento por IA",
            extra={"pr_id": pull_request_id},
        )


async def run_github_event(
    *, event_name: str, delivery_id: str | None, payload: Mapping[str, Any]
) -> str:
    """Cria o engine do processo, executa ``handle_event`` e libera as conexões.

    O engine é criado aqui (e não em cache) porque cada ``asyncio.run`` tem seu próprio
    event loop, e conexões asyncpg não podem ser reaproveitadas entre loops.
    """
    settings = get_settings()
    configure_logging(settings.log_level)
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:
        return await handle_event(
            session_factory,
            tracked_branches=settings.tracked_branches,
            event_name=event_name,
            delivery_id=delivery_id,
            payload=payload,
        )
    finally:
        await engine.dispose()


@celery_app.task(
    name="process_github_event",
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=5,
    acks_late=True,
)
def process_github_event(
    event_name: str,
    delivery_id: str | None,
    payload: dict[str, Any],
) -> str:
    """Tarefa de processamento de eventos do GitHub.

    Args:
        event_name: Valor do cabeçalho ``X-GitHub-Event``.
        delivery_id: Valor do cabeçalho ``X-GitHub-Delivery``, usado para rastreio.
        payload: Corpo JSON já autenticado pela assinatura HMAC.

    Returns:
        Desfecho do processamento (ex.: ``processed``, ``ignored_branch``).
    """
    return asyncio.run(
        run_github_event(event_name=event_name, delivery_id=delivery_id, payload=payload)
    )

