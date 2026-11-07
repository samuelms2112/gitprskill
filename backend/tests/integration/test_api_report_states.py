"""Testes de integração dos filtros de estado do feed: todos, em aberto e mergeados."""

from typing import Any

import httpx
import pytest

from app.core.database import get_session_factory
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
LIST = "/api/v1/reports/prs"


def _open_event(number: int, pr_id: int) -> dict[str, Any]:
    payload = build_pull_request_event(action="opened", merged=False, number=number, pr_id=pr_id, installation_id=111)
    payload["pull_request"].update(
        {"state": "open", "merged": False, "merged_at": None, "closed_at": None}
    )
    return payload


async def _ingest(payload: dict[str, Any]) -> None:
    await handle_event(
        get_session_factory(),
        tracked_branches=TRACKED,
        event_name="pull_request",
        delivery_id="d",
        payload=payload,
    )


@pytest.fixture
async def scenario() -> dict[str, Any]:
    tenant_id = await create_tenant(slug="acme", installation_id=111)
    ana = await create_user(github_id=7001, login="ana")
    await add_member(tenant_id=tenant_id, user_id=ana, role=MemberRole.VIEWER)
    await _ingest(_open_event(number=1, pr_id=1))
    await _ingest(build_pull_request_event(installation_id=111, number=2, pr_id=2))  # mergeado
    return {"ana": ana}


def _auth(user_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {session_token(user_id)}"}


async def test_default_feed_shows_only_merged_prs(client: httpx.AsyncClient, scenario: dict[str, Any]) -> None:
    """Sem filtro de estado, o feed mostra só os mergeados (comportamento anterior preservado)."""
    body = (await client.get(LIST, params={"tenant_slug": "acme"}, headers=_auth(scenario["ana"]))).json()

    assert body["total"] == 1
    assert [item["number"] for item in body["items"]] == [2]
    assert body["items"][0]["is_merged"] is True


async def test_open_filter_shows_only_open_prs(client: httpx.AsyncClient, scenario: dict[str, Any]) -> None:
    """A aba "Em aberto" mostra só os PRs ainda abertos, com o estado correto."""
    body = (
        await client.get(LIST, params={"tenant_slug": "acme", "state": "open"}, headers=_auth(scenario["ana"]))
    ).json()

    assert [item["number"] for item in body["items"]] == [1]
    assert body["items"][0]["state"] == "open"
    assert body["items"][0]["is_merged"] is False
    assert body["items"][0]["merged_at"] is None


async def test_all_filter_shows_open_and_merged(client: httpx.AsyncClient, scenario: dict[str, Any]) -> None:
    """A aba "Todos" mostra abertos e mergeados juntos, sem duplicar nenhum."""
    body = (
        await client.get(LIST, params={"tenant_slug": "acme", "state": "all"}, headers=_auth(scenario["ana"]))
    ).json()

    assert body["total"] == 2
    assert sorted(item["number"] for item in body["items"]) == [1, 2]


async def test_open_prs_appear_in_the_period_they_were_opened(
    client: httpx.AsyncClient, scenario: dict[str, Any]
) -> None:
    """Um PR aberto não tem data de merge: o período usa a data de abertura como referência."""
    wide = (
        await client.get(
            LIST,
            params={"tenant_slug": "acme", "state": "open", "start_date": "2000-01-01", "end_date": "2100-01-01"},
            headers=_auth(scenario["ana"]),
        )
    ).json()

    assert wide["total"] == 1


async def test_unknown_state_is_rejected(client: httpx.AsyncClient, scenario: dict[str, Any]) -> None:
    """Estado fora de ``all``, ``open`` e ``merged`` é recusado pela validação."""
    response = await client.get(
        LIST, params={"tenant_slug": "acme", "state": "closed"}, headers=_auth(scenario["ana"])
    )
    assert response.status_code == 422
