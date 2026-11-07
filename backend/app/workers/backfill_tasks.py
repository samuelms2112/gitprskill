"""Tarefas Celery de sincronização histórica: um repositório, ou todos os repositórios do tenant.

* ``sync_repository_history_task`` importa um repositório.
* ``sync_all_tenant_repositories_task`` importa todos, um após o outro. Executar em sequência
  evita que várias importações disputem a mesma cota da instalação, e o progresso agregado
  mostra a soma de todos os repositórios.

Em ambos, o status é atualizado no Redis a cada lote, a cota esgotada reagenda a tarefa,
e os PRs novos e mergeados vão para análise de IA somente depois do commit.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

import redis
from celery import Task
from kombu.exceptions import OperationalError as BrokerOperationalError
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.celery_app import celery_app
from app.core.config import Settings, get_settings
from app.core.exceptions import (
    GitHubAppNotConfiguredError,
    GitHubError,
    GitHubNotFoundError,
    GitHubRateLimitError,
)
from app.core.logging import configure_logging, get_logger
from app.models.repository import Repository
from app.models.tenant import Tenant
from app.schemas.sync import SyncState, SyncStatus
from app.services.backfill_service import (
    BackfillCounters,
    ProgressCallback,
    sync_repository_history,
)
from app.services.github_app_auth import GitHubAppAuth
from app.services.github_client import GitHubClient
from app.services.sync_status import RedisSyncStatusStore, SyncStatusStore
from app.workers.tasks import enrich_pr_with_ai_backfill_task

logger = get_logger(__name__)

DEFAULT_RETRY_SECONDS = 900
MIN_RETRY_SECONDS = 60
# ``repository_id`` usado no status agregado do sync em massa (não é um repositório real).
ALL_REPOSITORIES = 0


@dataclass(frozen=True, slots=True)
class _Target:
    repository_id: int
    owner: str
    name: str


def _status(
    task_id: str,
    tenant_id: int,
    repository_id: int,
    state: SyncState,
    counters: BackfillCounters | None = None,
    error: str | None = None,
) -> SyncStatus:
    counts = counters or BackfillCounters()
    return SyncStatus(
        task_id=task_id,
        tenant_id=tenant_id,
        repository_id=repository_id,
        state=state,
        examined=counts.examined,
        stored=counts.stored,
        new=counts.new,
        skipped=counts.skipped,
        error=error,
        updated_at=datetime.now(UTC),
    )


def _add(a: BackfillCounters, b: BackfillCounters) -> BackfillCounters:
    return BackfillCounters(
        examined=a.examined + b.examined,
        stored=a.stored + b.stored,
        new=a.new + b.new,
        skipped=a.skipped + b.skipped,
    )


def _build_app_auth(settings: Settings) -> GitHubAppAuth | None:
    """Autenticação como GitHub App, ou ``None`` se o App não estiver configurado."""
    private_key = settings.github_app_private_key
    try:
        return GitHubAppAuth(
            app_id=settings.github_app_id,
            private_key_pem=private_key.get_secret_value() if private_key else None,
            client_factory=lambda token: GitHubClient(
                base_url=settings.github_api_base_url,
                token=token,
                timeout=settings.github_request_timeout_seconds,
            ),
        )
    except GitHubAppNotConfiguredError:
        return None


async def _load_installation(
    session_factory: async_sessionmaker[AsyncSession], tenant_id: int
) -> int | None:
    """Instalação ativa do tenant, ou ``None`` se o tenant não existe ou está desvinculado."""
    async with session_factory() as session:
        tenant = await session.get(Tenant, tenant_id)
        return tenant.github_installation_id if tenant is not None else None


async def _load_targets(
    session_factory: async_sessionmaker[AsyncSession],
    tenant_id: int,
    repository_id: int | None = None,
) -> list[_Target]:
    """Repositórios do tenant: um específico, ou todos se ``repository_id`` for ``None``."""
    async with session_factory() as session:
        statement = select(Repository).where(Repository.tenant_id == tenant_id).order_by(Repository.id)
        if repository_id is not None:
            statement = statement.where(Repository.id == repository_id)
        rows = (await session.scalars(statement)).all()
        return [_Target(repo.id, repo.owner_login, repo.name) for repo in rows]


async def _sync_one(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    app_auth: GitHubAppAuth,
    settings: Settings,
    tenant_id: int,
    installation_id: int,
    target: _Target,
    days_back: int | None,
    progress: ProgressCallback,
) -> BackfillCounters:
    """Sincroniza um repositório com o token da instalação, grava e dispara a IA dos PRs novos."""
    token = await app_auth.get_installation_access_token(installation_id)
    updated_since = datetime.now(UTC) - timedelta(days=days_back) if days_back else None

    async with GitHubClient(
        base_url=settings.github_api_base_url,
        token=token.token,
        timeout=settings.github_request_timeout_seconds,
    ) as source, session_factory() as session, session.begin():
        result = await sync_repository_history(
            session,
            tenant_id=tenant_id,
            owner=target.owner,
            repo_name=target.name,
            source=source,
            tracked_branches=settings.tracked_branches,
            updated_since=updated_since,
            progress=progress,
        )

    _schedule_enrichment(result.new_pull_request_ids)
    return result.counters


def _schedule_enrichment(pull_request_ids: list[int]) -> None:
    """Enfileira a análise de IA de cada PR importado pelo histórico (modelo único). Melhor esforço."""
    if not get_settings().ai_configured:
        return
    for pull_request_id in pull_request_ids:
        try:
            enrich_pr_with_ai_backfill_task.delay(pull_request_id)
        except BrokerOperationalError:
            logger.warning("Não foi possível agendar a análise de IA", extra={"pr_id": pull_request_id})


async def _run_jobs(
    *,
    task_id: str,
    tenant_id: int,
    status_repository_id: int,
    targets: list[_Target],
    days_back: int | None,
    store: SyncStatusStore,
    skip_inaccessible: bool,
) -> str:
    """Núcleo comum: sincroniza os alvos em sequência, emitindo progresso agregado."""
    settings = get_settings()
    configure_logging(settings.log_level)

    def emit(state: SyncState, counters: BackfillCounters | None = None, error: str | None = None) -> None:
        store.save(_status(task_id, tenant_id, status_repository_id, state, counters, error))

    emit("running")
    app_auth = _build_app_auth(settings)
    if app_auth is None:
        emit("failed", error="GitHub App não configurado no servidor.")
        return "failed"

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:
        installation_id = await _load_installation(session_factory, tenant_id)
        if installation_id is None:
            emit("failed", error="A instalação do GitHub App deste tenant está inativa.")
            return "failed"

        total = BackfillCounters()
        for target in targets:
            done_so_far = replace(total)

            async def progress(current: BackfillCounters, base: BackfillCounters = done_so_far) -> None:
                emit("running", _add(base, current))

            try:
                counters = await _sync_one(
                    session_factory=session_factory,
                    app_auth=app_auth,
                    settings=settings,
                    tenant_id=tenant_id,
                    installation_id=installation_id,
                    target=target,
                    days_back=days_back,
                    progress=progress,
                )
            except GitHubNotFoundError:
                if not skip_inaccessible:
                    raise
                logger.warning("Repositório inacessível para a instalação; ignorado", extra={"repository_id": target.repository_id})
                continue
            total = _add(total, counters)
            emit("running", total)

        emit("completed", total)
        logger.info("Sincronização concluída", extra={"task_id": task_id, "new": total.new})
        return "completed"
    except GitHubRateLimitError:
        raise
    except GitHubError as exc:
        emit("failed", error=exc.message)
        return "failed"
    finally:
        await engine.dispose()


async def run_backfill(
    *,
    task_id: str,
    tenant_id: int,
    repository_id: int,
    days_back: int | None,
    store: SyncStatusStore,
) -> str:
    """Importa o histórico de um repositório. Retorna o estado final.

    Raises:
        GitHubRateLimitError: Cota esgotada; quem chama reagenda a tarefa.
    """
    settings = get_settings()
    # Checagem de configuração antes de qualquer acesso ao banco: sem o App, nada a fazer.
    if _build_app_auth(settings) is None:
        store.save(_status(task_id, tenant_id, repository_id, "failed", error="GitHub App não configurado no servidor."))
        return "failed"

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:
        targets = await _load_targets(session_factory, tenant_id, repository_id)
    finally:
        await engine.dispose()
    if not targets:
        store.save(_status(task_id, tenant_id, repository_id, "failed", error="Repositório não encontrado para este tenant."))
        return "failed"

    return await _run_jobs(
        task_id=task_id,
        tenant_id=tenant_id,
        status_repository_id=repository_id,
        targets=targets,
        days_back=days_back,
        store=store,
        skip_inaccessible=False,
    )


async def run_sync_all(*, task_id: str, tenant_id: int, store: SyncStatusStore) -> str:
    """Importa o histórico de todos os repositórios do tenant, em sequência.

    Repositórios sem acesso para a instalação são pulados, sem derrubar o job inteiro.

    Raises:
        GitHubRateLimitError: Cota esgotada; a tarefa é reagendada e repete o trabalho,
            que é seguro porque a gravação é idempotente.
    """
    settings = get_settings()
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:
        targets = await _load_targets(session_factory, tenant_id)
    finally:
        await engine.dispose()

    return await _run_jobs(
        task_id=task_id,
        tenant_id=tenant_id,
        status_repository_id=ALL_REPOSITORIES,
        targets=targets,
        days_back=None,
        store=store,
        skip_inaccessible=True,
    )


def build_status_store() -> SyncStatusStore:
    """Store de produção: Redis configurado em ``REDIS_URL``."""
    client = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
    return RedisSyncStatusStore(client)


def _retry_countdown(exc: GitHubRateLimitError) -> int:
    if exc.reset_at is None:
        return DEFAULT_RETRY_SECONDS
    seconds = int((exc.reset_at - datetime.now(UTC)).total_seconds())
    return max(seconds, MIN_RETRY_SECONDS)


@celery_app.task(
    name="sync_repository_history",
    bind=True,
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,
    acks_late=True,
)
def sync_repository_history_task(
    self: Task,
    tenant_id: int,
    repository_id: int,
    days_back: int | None = None,
) -> str:
    """Importa o histórico de PRs de um repositório em segundo plano.

    Args:
        self: Instância da tarefa; ``self.request.id`` é o ``task_id`` usado no acompanhamento.
        tenant_id: Tenant dono do repositório.
        repository_id: ``id`` interno do repositório.
        days_back: Limite de dias de histórico; ``None`` importa tudo.
    """
    try:
        return asyncio.run(
            run_backfill(
                task_id=self.request.id or "",
                tenant_id=tenant_id,
                repository_id=repository_id,
                days_back=days_back,
                store=build_status_store(),
            )
        )
    except GitHubRateLimitError as exc:
        logger.warning("Cota do GitHub esgotada; reagendando backfill", extra={"repository_id": repository_id})
        raise self.retry(exc=exc, countdown=_retry_countdown(exc)) from exc


@celery_app.task(
    name="sync_all_tenant_repositories",
    bind=True,
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,
    acks_late=True,
)
def sync_all_tenant_repositories_task(self: Task, tenant_id: int) -> str:
    """Sincroniza o histórico de todos os repositórios do tenant, em sequência.

    Args:
        self: Instância da tarefa; ``self.request.id`` é o ``task_id`` do status agregado.
        tenant_id: Tenant cujos repositórios serão sincronizados.
    """
    try:
        return asyncio.run(
            run_sync_all(task_id=self.request.id or "", tenant_id=tenant_id, store=build_status_store())
        )
    except GitHubRateLimitError as exc:
        logger.warning("Cota do GitHub esgotada; reagendando sync de todos os repositórios")
        raise self.retry(exc=exc, countdown=_retry_countdown(exc)) from exc
