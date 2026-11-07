"""Aplicação Celery que processa eventos do GitHub em segundo plano.

Broker e backend: Redis (``REDIS_URL``). O resultado da tarefa não é armazenado,
pois o webhook não espera por ele. ``acks_late`` garante que uma tarefa interrompida
por queda do worker seja reentregue, e as gravações são idempotentes.

Execução: ``celery -A app.core.celery_app:celery_app worker``.
"""

from celery import Celery

from app.core.config import get_settings


def create_celery_app() -> Celery:
    """Cria e configura a aplicação Celery a partir das configurações da aplicação."""
    settings = get_settings()
    celery = Celery(
        "github_management",
        include=["app.tasks.github_events", "app.workers.tasks", "app.workers.backfill_tasks"],
    )
    celery.conf.update(
        broker_url=settings.redis_url,
        result_backend=None,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        broker_connection_retry_on_startup=True,
    )
    return celery


celery_app = create_celery_app()
