"""Tarefa Celery que processa um evento do GitHub fora do ciclo da requisição.

Cada execução abre uma transação própria, então o evento inteiro é gravado ou nada é.
Falhas transitórias de conexão com o banco são reenviadas com backoff exponencial.
Payloads inválidos não são reenviados: repetir a mesma entrega não corrigiria o erro.
"""

import asyncio
from collections.abc import Mapping
from typing import Any

from kombu.exceptions import OperationalError as BrokerOperationalError
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.celery_app import celery_app
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.services.github_event_processor import GitHubEventProcessor
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
    return result.outcome.value


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
