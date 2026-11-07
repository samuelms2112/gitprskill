"""Testes de integração do ciclo de vida de um PR: captura desde a abertura, e IA somente no merge."""

from typing import Any

import pytest
from sqlalchemy import select

import app.tasks.github_events as github_events_module
from app.core.config import get_settings
from app.core.database import get_session_factory
from app.models.enums import PullRequestState
from app.models.pull_request import PullRequest
from app.tasks.github_events import handle_event
from tests.factories.github import build_pull_request_event
from tests.fakes import FakeTaskDispatcher
from tests.integration.helpers import create_tenant

pytestmark = pytest.mark.integration

TRACKED = frozenset({"main", "master", "master-tip"})


def _event(*, action: str, merged: bool, base_ref: str = "main") -> dict[str, Any]:
    payload = build_pull_request_event(action=action, merged=merged, base_ref=base_ref, installation_id=111)
    if not merged:
        # PR em aberto (ou fechado sem merge): sem data de merge, e o estado segue a ação.
        payload["pull_request"]["merged_at"] = None
        payload["pull_request"]["merged"] = False
        payload["pull_request"]["closed_at"] = None if action != "closed" else payload["pull_request"]["updated_at"]
        payload["pull_request"]["state"] = "closed" if action == "closed" else "open"
    return payload


async def _handle(payload: dict[str, Any]) -> str:
    return await handle_event(
        get_session_factory(),
        tracked_branches=TRACKED,
        event_name="pull_request",
        delivery_id="d",
        payload=payload,
    )


async def _pr() -> PullRequest:
    async with get_session_factory()() as session:
        return (await session.execute(select(PullRequest).where(PullRequest.github_pr_id == 1001))).scalar_one()


@pytest.fixture
def ai_dispatch(monkeypatch: pytest.MonkeyPatch) -> FakeTaskDispatcher:
    """Chave de IA configurada e despacho falso: permite verificar quando a análise é pedida."""
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-chave-de-teste")
    get_settings.cache_clear()
    dispatcher = FakeTaskDispatcher()
    monkeypatch.setattr(github_events_module, "enrich_pr_with_ai_task", dispatcher)
    return dispatcher


async def test_pull_request_is_captured_on_opening_with_state_open(ai_dispatch: FakeTaskDispatcher) -> None:
    """A abertura já grava o PR, com estado aberto e sem data de merge."""
    await create_tenant(slug="acme", installation_id=111)

    outcome = await _handle(_event(action="opened", merged=False))

    assert outcome == "processed"
    pr = await _pr()
    assert pr.state is PullRequestState.OPEN
    assert pr.is_merged is False
    assert pr.merged_at is None


async def test_open_pull_request_does_not_trigger_ai(ai_dispatch: FakeTaskDispatcher) -> None:
    """Gravar um PR aberto não gera custo de IA: a análise só acontece no merge."""
    await create_tenant(slug="acme", installation_id=111)

    await _handle(_event(action="opened", merged=False))
    await _handle(_event(action="synchronize", merged=False))

    assert ai_dispatch.calls == []


async def test_merge_updates_the_same_record_and_triggers_ai_once(ai_dispatch: FakeTaskDispatcher) -> None:
    """Abrir e depois mergear atualiza o mesmo registro, e a IA é disparada só uma vez, no merge."""
    await create_tenant(slug="acme", installation_id=111)
    await _handle(_event(action="opened", merged=False))

    await _handle(_event(action="closed", merged=True))

    async with get_session_factory()() as session:
        count = len((await session.execute(select(PullRequest))).scalars().all())
    pr = await _pr()
    assert count == 1
    assert pr.state is PullRequestState.CLOSED
    assert pr.is_merged is True
    assert ai_dispatch.calls == [pr.id]


async def test_closed_without_merge_is_stored_but_not_analyzed(ai_dispatch: FakeTaskDispatcher) -> None:
    """Fechado sem merge fica registrado como fechado, sem análise de IA."""
    await create_tenant(slug="acme", installation_id=111)

    await _handle(_event(action="closed", merged=False))

    pr = await _pr()
    assert pr.state is PullRequestState.CLOSED
    assert pr.is_merged is False
    assert ai_dispatch.calls == []


async def test_open_pull_request_in_untracked_branch_is_ignored(ai_dispatch: FakeTaskDispatcher) -> None:
    """A regra de branch vale desde a abertura: PRs para branches não rastreadas não são gravados."""
    await create_tenant(slug="acme", installation_id=111)

    outcome = await _handle(_event(action="opened", merged=False, base_ref="feature/x"))

    assert outcome == "ignored_branch"
    async with get_session_factory()() as session:
        assert (await session.execute(select(PullRequest))).scalars().first() is None
