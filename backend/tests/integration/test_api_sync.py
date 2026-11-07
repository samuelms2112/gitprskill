"""Testes de integração dos endpoints de sincronização histórica."""

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from kombu.exceptions import OperationalError as BrokerOperationalError
from sqlalchemy import select, update

from app.api.v1.sync import get_sync_status_store
from app.core.database import get_session_factory
from app.main import app
from app.models.enums import MemberRole
from app.models.repository import Repository
from app.models.tenant import Tenant
from app.services.sync_status import InMemorySyncStatusStore
from app.tasks.github_events import handle_event
from app.workers.backfill_tasks import sync_repository_history_task
from tests.factories.github import build_pull_request_event
from tests.integration.helpers import (
    add_member,
    create_tenant,
    create_user,
    session_token,
)

pytestmark = pytest.mark.integration

TRACKED = frozenset({"main", "master", "master-tip"})


class FakeDispatch:
    """Substitui ``apply_async`` e registra os envios à fila."""

    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._error = error

    def __call__(self, *, args: list[Any], task_id: str) -> None:
        self.calls.append({"args": args, "task_id": task_id})
        if self._error is not None:
            raise self._error


@pytest.fixture
def store() -> Iterator[InMemorySyncStatusStore]:
    shared = InMemorySyncStatusStore()
    app.dependency_overrides[get_sync_status_store] = lambda: shared
    yield shared
    app.dependency_overrides.pop(get_sync_status_store, None)


@pytest.fixture
def dispatch(monkeypatch: pytest.MonkeyPatch) -> FakeDispatch:
    fake = FakeDispatch()
    monkeypatch.setattr(sync_repository_history_task, "apply_async", fake)
    return fake


@pytest.fixture
async def scenario() -> dict[str, Any]:
    """Tenant A (com repositório ingerido) e B; Ana é dona de A, Bruno é leitor de A, Carla é de B."""
    tenant_a = await create_tenant(slug="tenant-a", installation_id=111)
    tenant_b = await create_tenant(slug="tenant-b", installation_id=222)
    ana = await create_user(github_id=7001, login="ana")
    bruno = await create_user(github_id=7002, login="bruno")
    carla = await create_user(github_id=7003, login="carla")
    await add_member(tenant_id=tenant_a, user_id=ana, role=MemberRole.OWNER)
    await add_member(tenant_id=tenant_a, user_id=bruno, role=MemberRole.VIEWER)
    await add_member(tenant_id=tenant_b, user_id=carla, role=MemberRole.OWNER)
    await handle_event(
        get_session_factory(),
        tracked_branches=TRACKED,
        event_name="pull_request",
        delivery_id="d",
        payload=build_pull_request_event(installation_id=111),
    )
    async with get_session_factory()() as session:
        repository_id = await session.scalar(select(Repository.id).where(Repository.tenant_id == tenant_a))
    return {
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "ana": ana,
        "bruno": bruno,
        "carla": carla,
        "repository_id": repository_id,
    }


def _auth(user_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {session_token(user_id)}"}


def _start_url(repository_id: int) -> str:
    return f"/api/v1/tenants/tenant-a/repositories/{repository_id}/sync"


async def test_start_returns_202_with_task_id_and_enqueues(
    client: httpx.AsyncClient, scenario: dict[str, Any], store: InMemorySyncStatusStore, dispatch: FakeDispatch
) -> None:
    """O POST responde 202 imediatamente, enfileira o job e deixa o status ``queued`` disponível."""
    response = await client.post(_start_url(scenario["repository_id"]), headers=_auth(scenario["ana"]))

    assert response.status_code == 202
    body = response.json()
    assert body["state"] == "queued"
    assert len(dispatch.calls) == 1
    assert dispatch.calls[0]["task_id"] == body["task_id"]
    assert dispatch.calls[0]["args"] == [scenario["tenant_a"], scenario["repository_id"], None]
    assert store.load(body["task_id"]) is not None


async def test_days_back_is_forwarded_to_the_task(
    client: httpx.AsyncClient, scenario: dict[str, Any], store: InMemorySyncStatusStore, dispatch: FakeDispatch
) -> None:
    """O limite de dias do histórico chega à tarefa."""
    await client.post(
        _start_url(scenario["repository_id"]), json={"days_back": 90}, headers=_auth(scenario["ana"])
    )

    assert dispatch.calls[0]["args"][2] == 90


@pytest.mark.parametrize("days", [0, 3651], ids=["zero", "acima_do_limite"])
async def test_days_back_out_of_range_is_rejected(
    client: httpx.AsyncClient, scenario: dict[str, Any], store: InMemorySyncStatusStore, dispatch: FakeDispatch, days: int
) -> None:
    """Valores fora do intervalo são recusados antes de chegar à fila."""
    response = await client.post(
        _start_url(scenario["repository_id"]), json={"days_back": days}, headers=_auth(scenario["ana"])
    )

    assert response.status_code == 422
    assert dispatch.calls == []


async def test_viewer_cannot_start_a_sync(
    client: httpx.AsyncClient, scenario: dict[str, Any], store: InMemorySyncStatusStore, dispatch: FakeDispatch
) -> None:
    """Leitor não dispara importações pesadas: exige papel DEVELOPER ou superior."""
    response = await client.post(_start_url(scenario["repository_id"]), headers=_auth(scenario["bruno"]))

    assert response.status_code == 403
    assert dispatch.calls == []


async def test_repository_of_another_tenant_is_not_found(
    client: httpx.AsyncClient, scenario: dict[str, Any], store: InMemorySyncStatusStore, dispatch: FakeDispatch
) -> None:
    """Repositório de outro tenant não é acessível, mesmo com o ID correto."""
    response = await client.post(_start_url(scenario["repository_id"]), headers=_auth(scenario["carla"]))

    assert response.status_code == 404
    assert dispatch.calls == []


async def test_tenant_without_installation_is_a_conflict(
    client: httpx.AsyncClient, scenario: dict[str, Any], store: InMemorySyncStatusStore, dispatch: FakeDispatch
) -> None:
    """Sem instalação ativa do GitHub App não há token para sincronizar."""
    async with get_session_factory()() as session, session.begin():
        await session.execute(
            update(Tenant).where(Tenant.id == scenario["tenant_a"]).values(github_installation_id=None)
        )

    response = await client.post(_start_url(scenario["repository_id"]), headers=_auth(scenario["ana"]))

    assert response.status_code == 409
    assert dispatch.calls == []


async def test_broker_outage_marks_job_failed_and_returns_503(
    client: httpx.AsyncClient, scenario: dict[str, Any], store: InMemorySyncStatusStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sem fila, o cliente recebe 503 e o job não fica preso em ``queued``."""
    failing = FakeDispatch(error=BrokerOperationalError("redis fora"))
    monkeypatch.setattr(sync_repository_history_task, "apply_async", failing)

    response = await client.post(_start_url(scenario["repository_id"]), headers=_auth(scenario["ana"]))

    assert response.status_code == 503
    task_id = failing.calls[0]["task_id"]
    saved = store.load(task_id)
    assert saved is not None
    assert saved.state == "failed"


async def test_status_is_visible_to_the_owning_tenant_only(
    client: httpx.AsyncClient, scenario: dict[str, Any], store: InMemorySyncStatusStore, dispatch: FakeDispatch
) -> None:
    """O progresso aparece para o tenant dono; outro tenant recebe 404 mesmo com o ``task_id`` em mãos."""
    started = (await client.post(_start_url(scenario["repository_id"]), headers=_auth(scenario["ana"]))).json()
    status_url = f"{_start_url(scenario['repository_id'])}/status/{started['task_id']}"

    own = await client.get(status_url, headers=_auth(scenario["ana"]))
    stolen = await client.get(
        f"/api/v1/tenants/tenant-b/repositories/{scenario['repository_id']}/sync/status/{started['task_id']}",
        headers=_auth(scenario["carla"]),
    )

    assert own.status_code == 200
    assert own.json()["state"] == "queued"
    assert stolen.status_code == 404


async def test_unknown_task_id_is_not_found(
    client: httpx.AsyncClient, scenario: dict[str, Any], store: InMemorySyncStatusStore
) -> None:
    """Job inexistente ou expirado responde 404."""
    response = await client.get(
        f"{_start_url(scenario['repository_id'])}/status/nao-existe", headers=_auth(scenario["ana"])
    )
    assert response.status_code == 404
