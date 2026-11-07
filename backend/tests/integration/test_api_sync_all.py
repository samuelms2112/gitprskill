"""Testes de integração do endpoint de sincronização de todos os repositórios do tenant."""

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from sqlalchemy import update

from app.api.v1.sync import get_sync_status_store
from app.core.database import get_session_factory
from app.main import app
from app.models.enums import MemberRole
from app.models.tenant import Tenant
from app.services.sync_status import InMemorySyncStatusStore
from app.workers.backfill_tasks import (
    ALL_REPOSITORIES,
    sync_all_tenant_repositories_task,
)
from tests.integration.helpers import (
    add_member,
    create_tenant,
    create_user,
    session_token,
)

pytestmark = pytest.mark.integration

SYNC_ALL = "/api/v1/tenants/tenant-a/repositories/sync-all"


class FakeDispatch:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, *, args: list[Any], task_id: str) -> None:
        self.calls.append({"args": args, "task_id": task_id})


@pytest.fixture
def store() -> Iterator[InMemorySyncStatusStore]:
    shared = InMemorySyncStatusStore()
    app.dependency_overrides[get_sync_status_store] = lambda: shared
    yield shared
    app.dependency_overrides.pop(get_sync_status_store, None)


@pytest.fixture
def dispatch(monkeypatch: pytest.MonkeyPatch) -> FakeDispatch:
    fake = FakeDispatch()
    monkeypatch.setattr(sync_all_tenant_repositories_task, "apply_async", fake)
    return fake


@pytest.fixture
async def users() -> dict[str, Any]:
    tenant_a = await create_tenant(slug="tenant-a", installation_id=111)
    tenant_b = await create_tenant(slug="tenant-b", installation_id=222)
    owner = await create_user(github_id=7001, login="ana")
    viewer = await create_user(github_id=7002, login="bruno")
    other_owner = await create_user(github_id=7003, login="carla")
    await add_member(tenant_id=tenant_a, user_id=owner, role=MemberRole.OWNER)
    await add_member(tenant_id=tenant_a, user_id=viewer, role=MemberRole.VIEWER)
    await add_member(tenant_id=tenant_b, user_id=other_owner, role=MemberRole.OWNER)
    return {"tenant_a": tenant_a, "tenant_b": tenant_b, "owner": owner, "viewer": viewer, "other": other_owner}


def _auth(user_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {session_token(user_id)}"}


async def test_sync_all_returns_202_and_enqueues_the_tenant(
    client: httpx.AsyncClient, users: dict[str, Any], store: InMemorySyncStatusStore, dispatch: FakeDispatch
) -> None:
    """O POST responde 202 com um ``task_id`` agregado e enfileira o sync do tenant."""
    response = await client.post(SYNC_ALL, headers=_auth(users["owner"]))

    assert response.status_code == 202
    body = response.json()
    assert body["state"] == "queued"
    assert dispatch.calls == [{"args": [users["tenant_a"]], "task_id": body["task_id"]}]
    saved = store.load(body["task_id"])
    assert saved is not None
    assert saved.repository_id == ALL_REPOSITORIES


async def test_viewer_cannot_start_sync_all(
    client: httpx.AsyncClient, users: dict[str, Any], store: InMemorySyncStatusStore, dispatch: FakeDispatch
) -> None:
    """Leitor não dispara a importação de todos os repositórios."""
    response = await client.post(SYNC_ALL, headers=_auth(users["viewer"]))

    assert response.status_code == 403
    assert dispatch.calls == []


async def test_tenant_without_installation_is_a_conflict(
    client: httpx.AsyncClient, users: dict[str, Any], store: InMemorySyncStatusStore, dispatch: FakeDispatch
) -> None:
    """Sem instalação ativa, não há token para sincronizar."""
    async with get_session_factory()() as session, session.begin():
        await session.execute(update(Tenant).where(Tenant.id == users["tenant_a"]).values(github_installation_id=None))

    response = await client.post(SYNC_ALL, headers=_auth(users["owner"]))

    assert response.status_code == 409
    assert dispatch.calls == []


async def test_aggregated_status_is_visible_to_the_owning_tenant_only(
    client: httpx.AsyncClient, users: dict[str, Any], store: InMemorySyncStatusStore, dispatch: FakeDispatch
) -> None:
    """O progresso agregado aparece para o tenant dono; outro tenant não o vê."""
    started = (await client.post(SYNC_ALL, headers=_auth(users["owner"]))).json()
    status_url = f"{SYNC_ALL}/status/{started['task_id']}"

    own = await client.get(status_url, headers=_auth(users["owner"]))
    other = await client.get(
        f"/api/v1/tenants/tenant-b/repositories/sync-all/status/{started['task_id']}",
        headers=_auth(users["other"]),
    )

    assert own.status_code == 200
    assert own.json()["repository_id"] == ALL_REPOSITORIES
    assert other.status_code == 404


async def test_per_repository_status_is_not_served_by_the_sync_all_route(
    client: httpx.AsyncClient, users: dict[str, Any], store: InMemorySyncStatusStore, dispatch: FakeDispatch
) -> None:
    """Um job de repositório único não pode ser lido pela rota do sync em massa."""
    from datetime import UTC, datetime

    from app.schemas.sync import SyncStatus

    single = SyncStatus(
        task_id="job-unico",
        tenant_id=users["tenant_a"],
        repository_id=42,
        state="running",
        updated_at=datetime.now(UTC),
    )
    store.save(single)

    response = await client.get(f"{SYNC_ALL}/status/job-unico", headers=_auth(users["owner"]))

    assert response.status_code == 404
