"""Endpoints de sincronização histórica (backfill) por repositório.

O POST responde 202 imediatamente com um ``task_id``; o progresso é consultado pelo GET.
Ambos exigem que o repositório pertença ao tenant da rota. O status de um job só é
devolvido ao tenant que o criou, para que o ``task_id`` não sirva de atalho entre tenants.
"""

from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Path, status
from kombu.exceptions import OperationalError as BrokerOperationalError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import TenantContext, get_installation_repository_source, require_role
from app.core.database import get_db_session
from app.core.exceptions import CeleryDispatchError, ConflictError, NotFoundError
from app.core.logging import get_logger
from app.models.enums import MemberRole
from app.models.repository import Repository
from app.schemas.sync import (
    InstallationSyncResult,
    SyncAccepted,
    SyncRequest,
    SyncState,
    SyncStatus,
)
from app.services.installation_repositories import (
    InstallationRepositorySource,
    sync_installation_repositories,
)
from app.services.sync_status import SyncStatusStore
from app.workers.backfill_tasks import (
    ALL_REPOSITORIES,
    build_status_store,
    sync_all_tenant_repositories_task,
    sync_repository_history_task,
)

router = APIRouter(prefix="/tenants", tags=["Sincronização"])
logger = get_logger(__name__)

TaskIdPath = Annotated[str, Path(min_length=1, max_length=64)]


@lru_cache
def get_sync_status_store() -> SyncStatusStore:
    """Store de status compartilhado (Redis). Substituível nos testes via dependency_overrides."""
    return build_status_store()


@router.post(
    "/{tenant_slug}/repositories/{repository_id}/sync",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SyncAccepted,
    summary="Inicia a sincronização histórica de um repositório",
)
async def start_repository_sync(
    repository_id: int,
    context: Annotated[TenantContext, Depends(require_role(MemberRole.DEVELOPER))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    store: Annotated[SyncStatusStore, Depends(get_sync_status_store)],
    body: SyncRequest | None = None,
) -> SyncAccepted:
    """Enfileira o backfill e responde 202 com o ``task_id`` para acompanhamento.

    Raises:
        NotFoundError: Repositório inexistente ou de outro tenant.
        ConflictError: Tenant sem instalação ativa do GitHub App.
        CeleryDispatchError: Fila indisponível (HTTP 503).
    """
    if context.tenant.github_installation_id is None:
        raise ConflictError("A instalação do GitHub App deste tenant está inativa.")

    repository = await session.scalar(
        select(Repository).where(
            Repository.id == repository_id,
            Repository.tenant_id == context.tenant.id,
        )
    )
    if repository is None:
        raise NotFoundError("Repositório não encontrado.")

    task_id = str(uuid4())
    days_back = body.days_back if body is not None else None
    store.save(_status(task_id, context.tenant.id, repository_id, "queued"))
    try:
        sync_repository_history_task.apply_async(
            args=[context.tenant.id, repository_id, days_back],
            task_id=task_id,
        )
    except BrokerOperationalError as exc:
        store.save(_status(task_id, context.tenant.id, repository_id, "failed", "Fila indisponível."))
        logger.error("Broker indisponível ao enfileirar backfill", extra={"repository_id": repository_id})
        raise CeleryDispatchError("Fila de processamento indisponível no momento.") from exc

    logger.info("Backfill enfileirado", extra={"task_id": task_id, "repository_id": repository_id})
    return SyncAccepted(task_id=task_id, state="queued")


@router.get(
    "/{tenant_slug}/repositories/{repository_id}/sync/status/{task_id}",
    response_model=SyncStatus,
    summary="Progresso de uma sincronização histórica",
)
async def get_repository_sync_status(
    repository_id: int,
    task_id: TaskIdPath,
    context: Annotated[TenantContext, Depends(require_role(MemberRole.VIEWER))],
    store: Annotated[SyncStatusStore, Depends(get_sync_status_store)],
) -> SyncStatus:
    """Estado atual do job (``queued``, ``running``, ``completed`` ou ``failed``).

    Raises:
        NotFoundError: Job inexistente, expirado, ou de outro tenant ou repositório.
    """
    current = store.load(task_id)
    if current is None or current.tenant_id != context.tenant.id or current.repository_id != repository_id:
        raise NotFoundError("Sincronização não encontrada.")
    return current


@router.post(
    "/{tenant_slug}/repositories/sync-from-github-app",
    response_model=InstallationSyncResult,
    summary="Atualiza a lista de repositórios consultando a instalação do GitHub App",
)
async def sync_repositories_from_github_app(
    context: Annotated[TenantContext, Depends(require_role(MemberRole.DEVELOPER))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    source: Annotated[InstallationRepositorySource, Depends(get_installation_repository_source)],
) -> InstallationSyncResult:
    """Cadastra todos os repositórios que a instalação pode acessar, mesmo sem PRs mergeados.

    Raises:
        ConflictError: Tenant sem instalação ativa do GitHub App.
        GitHubAppNotConfiguredError: App não configurado no servidor (HTTP 503).
        GitHubError: Falha ao consultar o GitHub.
    """
    if context.tenant.github_installation_id is None:
        raise ConflictError("A instalação do GitHub App deste tenant está inativa.")
    synced = await sync_installation_repositories(
        session,
        tenant_id=context.tenant.id,
        installation_id=context.tenant.github_installation_id,
        source=source,
    )
    logger.info("Repositórios sincronizados pela instalação", extra={"count": synced})
    return InstallationSyncResult(synced=synced)


@router.post(
    "/{tenant_slug}/repositories/sync-all",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SyncAccepted,
    summary="Sincroniza o histórico de todos os repositórios do tenant",
)
async def start_sync_all(
    context: Annotated[TenantContext, Depends(require_role(MemberRole.DEVELOPER))],
    store: Annotated[SyncStatusStore, Depends(get_sync_status_store)],
) -> SyncAccepted:
    """Enfileira a sincronização de todos os repositórios e responde 202 com o ``task_id`` agregado.

    Raises:
        ConflictError: Tenant sem instalação ativa do GitHub App.
        CeleryDispatchError: Fila indisponível (HTTP 503).
    """
    if context.tenant.github_installation_id is None:
        raise ConflictError("A instalação do GitHub App deste tenant está inativa.")

    task_id = str(uuid4())
    store.save(_status(task_id, context.tenant.id, ALL_REPOSITORIES, "queued"))
    try:
        sync_all_tenant_repositories_task.apply_async(args=[context.tenant.id], task_id=task_id)
    except BrokerOperationalError as exc:
        store.save(_status(task_id, context.tenant.id, ALL_REPOSITORIES, "failed", "Fila indisponível."))
        logger.error("Broker indisponível ao enfileirar sync de todos os repositórios")
        raise CeleryDispatchError("Fila de processamento indisponível no momento.") from exc

    logger.info("Sync de todos os repositórios enfileirado", extra={"task_id": task_id})
    return SyncAccepted(task_id=task_id, state="queued")


@router.get(
    "/{tenant_slug}/repositories/sync-all/status/{task_id}",
    response_model=SyncStatus,
    summary="Progresso agregado do sync de todos os repositórios",
)
async def get_sync_all_status(
    task_id: TaskIdPath,
    context: Annotated[TenantContext, Depends(require_role(MemberRole.VIEWER))],
    store: Annotated[SyncStatusStore, Depends(get_sync_status_store)],
) -> SyncStatus:
    """Soma do progresso de todos os repositórios do tenant.

    Raises:
        NotFoundError: Job inexistente, expirado, ou de outro tenant.
    """
    current = store.load(task_id)
    if current is None or current.tenant_id != context.tenant.id or current.repository_id != ALL_REPOSITORIES:
        raise NotFoundError("Sincronização não encontrada.")
    return current


def _status(
    task_id: str,
    tenant_id: int,
    repository_id: int,
    state: SyncState,
    error: str | None = None,
) -> SyncStatus:
    return SyncStatus(
        task_id=task_id,
        tenant_id=tenant_id,
        repository_id=repository_id,
        state=state,
        error=error,
        updated_at=datetime.now(UTC),
    )
