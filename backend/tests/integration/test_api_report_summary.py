"""Testes de integração do resumo agregado (KPIs), do filtro por repositório e dos seletores."""

from datetime import datetime, timedelta
from typing import Any

import httpx
import pytest

from app.core.database import get_session_factory
from app.models.enums import MemberRole
from app.tasks.github_events import handle_event
from tests.factories.github import build_pull_request_event, build_user
from tests.integration.helpers import (
    add_member,
    create_tenant,
    create_user,
    session_token,
)

pytestmark = pytest.mark.integration

TRACKED = frozenset({"main", "master", "master-tip"})
SUMMARY = "/api/v1/reports/summary"
LIST = "/api/v1/reports/prs"


async def _ingest(
    *,
    number: int,
    pr_id: int,
    author: tuple[int, str],
    repo_name: str,
    additions: int,
    deletions: int,
    merged_at: str,
) -> None:
    payload = build_pull_request_event(installation_id=111, number=number, pr_id=pr_id)
    payload["pull_request"]["user"] = build_user(user_id=author[0], login=author[1])
    payload["pull_request"]["merged_at"] = merged_at
    # Cada PR é aberto 2 horas antes do merge, então o tempo até o merge é sempre 7200 s.
    merged = datetime.fromisoformat(merged_at.replace("Z", "+00:00"))
    payload["pull_request"]["created_at"] = (merged - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    payload["pull_request"]["updated_at"] = merged_at
    payload["pull_request"]["closed_at"] = merged_at
    payload["pull_request"]["additions"] = additions
    payload["pull_request"]["deletions"] = deletions
    # A identidade do repositório é o github_id: cada repositório precisa do seu próprio.
    payload["repository"]["id"] = 556 if repo_name == "web" else 555
    payload["repository"]["name"] = repo_name
    payload["repository"]["full_name"] = f"org/{repo_name}"
    await handle_event(
        get_session_factory(),
        tracked_branches=TRACKED,
        event_name="pull_request",
        delivery_id=f"d-{pr_id}",
        payload=payload,
    )


@pytest.fixture
async def scenario() -> dict[str, Any]:
    """Tenant com três PRs em dois repositórios, de dois autores, com tamanhos distintos."""
    tenant_id = await create_tenant(slug="tenant-a", installation_id=111)
    other_id = await create_tenant(slug="tenant-b", installation_id=222)
    ana = await create_user(github_id=7001, login="dev-ana")
    carla = await create_user(github_id=7003, login="carla")
    await add_member(tenant_id=tenant_id, user_id=ana, role=MemberRole.VIEWER)
    await add_member(tenant_id=other_id, user_id=carla, role=MemberRole.OWNER)

    # PR 1: 12 linhas (S), TTM 2h, api, dev-ana
    await _ingest(number=1, pr_id=1, author=(7001, "dev-ana"), repo_name="api",
                  additions=10, deletions=2, merged_at="2026-01-10T12:00:00Z")
    # PR 2: 400 linhas (L), TTM 2h, api, dev-bruno
    await _ingest(number=2, pr_id=2, author=(7002, "dev-bruno"), repo_name="api",
                  additions=300, deletions=100, merged_at="2026-02-01T12:00:00Z")
    # PR 3: 12 linhas (S), TTM 2h, web, dev-ana
    await _ingest(number=3, pr_id=3, author=(7001, "dev-ana"), repo_name="web",
                  additions=10, deletions=2, merged_at="2026-02-05T12:00:00Z")
    return {"ana": ana, "carla": carla}


def _auth(user_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {session_token(user_id)}"}


async def test_summary_counts_average_and_size_distribution(
    client: httpx.AsyncClient, scenario: dict[str, Any]
) -> None:
    """Total, tempo médio de merge e distribuição por tamanho refletem os PRs do tenant."""
    response = await client.get(SUMMARY, params={"tenant_slug": "tenant-a"}, headers=_auth(scenario["ana"]))

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["average_time_to_merge_seconds"] == 7200
    assert body["size_distribution"] == {"XS": 0, "S": 2, "M": 0, "L": 1, "XL": 0}


async def test_selectors_list_repositories_and_authors_of_the_tenant(
    client: httpx.AsyncClient, scenario: dict[str, Any]
) -> None:
    """Os seletores trazem as opções do tenant, em ordem alfabética, sem vazar outros tenants."""
    body = (
        await client.get(SUMMARY, params={"tenant_slug": "tenant-a"}, headers=_auth(scenario["ana"]))
    ).json()

    assert body["available_repositories"] == ["org/api", "org/web"]
    assert body["available_authors"] == ["dev-ana", "dev-bruno"]


async def test_repository_filter_applies_to_summary_and_list(
    client: httpx.AsyncClient, scenario: dict[str, Any]
) -> None:
    """Filtrar por repositório restringe KPIs e itens da mesma forma."""
    params = {"tenant_slug": "tenant-a", "repository": "org/web"}

    summary = (await client.get(SUMMARY, params=params, headers=_auth(scenario["ana"]))).json()
    listing = (await client.get(LIST, params=params, headers=_auth(scenario["ana"]))).json()

    assert summary["total"] == 1
    assert summary["size_distribution"]["S"] == 1
    assert listing["total"] == 1
    assert [item["repository"] for item in listing["items"]] == ["org/web"]


async def test_selectors_are_not_narrowed_by_active_filters(
    client: httpx.AsyncClient, scenario: dict[str, Any]
) -> None:
    """Com um filtro ativo, os seletores continuam mostrando todas as opções do tenant."""
    body = (
        await client.get(
            SUMMARY,
            params={"tenant_slug": "tenant-a", "repository": "org/web"},
            headers=_auth(scenario["ana"]),
        )
    ).json()

    assert body["available_repositories"] == ["org/api", "org/web"]
    assert body["available_authors"] == ["dev-ana", "dev-bruno"]


async def test_summary_for_empty_result_has_no_average(
    client: httpx.AsyncClient, scenario: dict[str, Any]
) -> None:
    """Sem PRs no filtro, o tempo médio é ``null`` e as contagens são zero."""
    body = (
        await client.get(
            SUMMARY,
            params={"tenant_slug": "tenant-a", "author": "dev-bruno", "repository": "org/web"},
            headers=_auth(scenario["ana"]),
        )
    ).json()

    assert body["total"] == 0
    assert body["average_time_to_merge_seconds"] is None
    assert body["size_distribution"] == {"XS": 0, "S": 0, "M": 0, "L": 0, "XL": 0}


async def test_summary_is_denied_to_non_members(client: httpx.AsyncClient, scenario: dict[str, Any]) -> None:
    """Carla não é membro do tenant A: o resumo não existe para ela."""
    response = await client.get(SUMMARY, params={"tenant_slug": "tenant-a"}, headers=_auth(scenario["carla"]))
    assert response.status_code == 404


async def test_summary_requires_authentication(client: httpx.AsyncClient) -> None:
    """Sem token, o resumo não é acessível."""
    response = await client.get(SUMMARY, params={"tenant_slug": "tenant-a"})
    assert response.status_code == 401

