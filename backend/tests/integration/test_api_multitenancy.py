"""Testes de integração do isolamento entre tenants nas rotas protegidas."""

from datetime import timedelta

import httpx
import pytest

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.core.security import TokenService
from app.models.enums import MemberRole
from app.tasks.github_events import handle_event
from tests.factories.github import build_pull_request_event
from tests.integration.helpers import (
    add_member,
    create_tenant,
    create_user,
    session_token,
)

pytestmark = pytest.mark.integration

TRACKED = frozenset({"main", "master", "master-tip"})


@pytest.fixture
async def scenario() -> dict[str, object]:
    """Dois tenants com o mesmo repositório do GitHub, e três usuários com vínculos distintos."""
    tenant_a = await create_tenant(slug="tenant-a", installation_id=111)
    tenant_b = await create_tenant(slug="tenant-b", installation_id=222)
    ana = await create_user(github_id=7001, login="ana")
    bruno = await create_user(github_id=7002, login="bruno")
    carla = await create_user(github_id=7003, login="carla")

    await add_member(tenant_id=tenant_a, user_id=ana, role=MemberRole.DEVELOPER)
    await add_member(tenant_id=tenant_b, user_id=bruno, role=MemberRole.OWNER)

    for installation_id, pr_id in ((111, 1), (222, 2)):
        await handle_event(
            get_session_factory(),
            tracked_branches=TRACKED,
            event_name="pull_request",
            delivery_id=f"d-{installation_id}",
            payload=build_pull_request_event(installation_id=installation_id, pr_id=pr_id),
        )

    return {"tenant_a": tenant_a, "tenant_b": tenant_b, "ana": ana, "bruno": bruno, "carla": carla}


def _bearer(user_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {session_token(user_id)}"}


async def test_member_sees_only_their_tenant_repositories(
    client: httpx.AsyncClient, scenario: dict[str, object]
) -> None:
    """Ana vê apenas os repositórios do tenant A, mesmo existindo o mesmo repo no tenant B."""
    response = await client.get(
        "/api/v1/tenants/tenant-a/repositories", headers=_bearer(scenario["ana"])
    )

    assert response.status_code == 200
    repos = response.json()
    assert len(repos) == 1
    assert repos[0]["tenant_id"] == scenario["tenant_a"]


async def test_non_member_gets_404_not_403(client: httpx.AsyncClient, scenario: dict[str, object]) -> None:
    """Quem não é membro não consegue confirmar a existência do tenant."""
    other_tenant = await client.get(
        "/api/v1/tenants/tenant-b/repositories", headers=_bearer(scenario["ana"])
    )
    nonexistent = await client.get(
        "/api/v1/tenants/nao-existe/repositories", headers=_bearer(scenario["ana"])
    )

    assert other_tenant.status_code == 404
    assert nonexistent.status_code == 404
    assert other_tenant.json() == nonexistent.json()


async def test_user_without_any_membership_is_denied(
    client: httpx.AsyncClient, scenario: dict[str, object]
) -> None:
    """Carla, sem vínculo com nenhum tenant, não acessa nenhum deles."""
    response = await client.get(
        "/api/v1/tenants/tenant-a/repositories", headers=_bearer(scenario["carla"])
    )
    assert response.status_code == 404


async def test_request_without_token_is_rejected(client: httpx.AsyncClient) -> None:
    """Sem ``Authorization``, a rota protegida responde 401."""
    response = await client.get("/api/v1/tenants/tenant-a/repositories")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


async def test_tampered_token_is_rejected(client: httpx.AsyncClient, scenario: dict[str, object]) -> None:
    """Qualquer alteração no token invalida a sessão."""
    token = session_token(scenario["ana"])
    tampered = token[:-2] + ("AA" if token[-2:] != "AA" else "BB")

    response = await client.get(
        "/api/v1/tenants/tenant-a/repositories",
        headers={"Authorization": f"Bearer {tampered}"},
    )
    assert response.status_code == 401


async def test_expired_token_is_rejected(client: httpx.AsyncClient, scenario: dict[str, object]) -> None:
    """Token emitido já expirado é recusado."""
    expired_service = TokenService(
        secret=get_settings().jwt_secret_key.get_secret_value(),
        access_token_ttl=timedelta(minutes=-1),
        oauth_state_ttl=timedelta(minutes=1),
    )
    expired, _ = expired_service.create_access_token(scenario["ana"])

    response = await client.get(
        "/api/v1/tenants/tenant-a/repositories",
        headers={"Authorization": f"Bearer {expired}"},
    )
    assert response.status_code == 401


async def test_listing_tenants_returns_only_memberships(
    client: httpx.AsyncClient, scenario: dict[str, object]
) -> None:
    """``GET /tenants`` lista somente os vínculos do usuário, com o papel."""
    response = await client.get("/api/v1/tenants", headers=_bearer(scenario["ana"]))

    assert response.status_code == 200
    assert response.json() == [{"slug": "tenant-a", "name": "Tenant-A", "role": "DEVELOPER"}]


async def test_current_user_endpoint_returns_session_owner(
    client: httpx.AsyncClient, scenario: dict[str, object]
) -> None:
    """``GET /auth/me`` devolve o usuário dono do token."""
    response = await client.get("/api/v1/auth/me", headers=_bearer(scenario["ana"]))

    assert response.status_code == 200
    assert response.json()["login"] == "ana"
    assert response.json()["github_id"] == 7001


@pytest.mark.parametrize("limit", [0, 501])
async def test_limit_out_of_range_is_rejected(
    client: httpx.AsyncClient, scenario: dict[str, object], limit: int
) -> None:
    """O parâmetro ``limit`` é validado pelo FastAPI."""
    response = await client.get(
        f"/api/v1/tenants/tenant-a/repositories?limit={limit}", headers=_bearer(scenario["ana"])
    )
    assert response.status_code == 422
