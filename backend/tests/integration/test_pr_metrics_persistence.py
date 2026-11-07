"""Testes de integração: métricas de PR gravadas na ingestão e isolamento por instalação."""

from typing import Any

import pytest
from sqlalchemy import select, update

from app.core.database import get_session_factory
from app.models.enums import PRSizeCategory
from app.models.pull_request import PullRequest
from app.models.tenant import Tenant
from app.services.outcomes import IngestionOutcome
from app.services.pr_enrichment import EnrichmentOutcome, enrich_pull_request
from app.tasks.github_events import handle_event
from tests.factories.github import build_pull_request_event, build_review_event
from tests.fakes import FakeAnalyzer, FakeDiffSource
from tests.integration.helpers import create_tenant

pytestmark = pytest.mark.integration

TRACKED = frozenset({"main", "master", "master-tip"})


async def _handle(event_name: str, payload: dict[str, Any]) -> str:
    return await handle_event(
        get_session_factory(),
        tracked_branches=TRACKED,
        event_name=event_name,
        delivery_id="d",
        payload=payload,
    )


async def _pr(github_pr_id: int) -> PullRequest:
    async with get_session_factory()() as session:
        return (
            await session.execute(select(PullRequest).where(PullRequest.github_pr_id == github_pr_id))
        ).scalar_one()


@pytest.mark.parametrize(
    ("additions", "deletions", "expected"),
    [
        (3, 4, PRSizeCategory.XS),  # 7 linhas
        (5, 5, PRSizeCategory.S),  # 10 linhas: primeira linha da faixa S
        (30, 30, PRSizeCategory.M),  # 60 linhas
        (200, 100, PRSizeCategory.L),  # 300 linhas
        (600, 500, PRSizeCategory.XL),  # 1100 linhas
    ],
)
async def test_size_category_is_persisted_for_each_range(
    additions: int, deletions: int, expected: PRSizeCategory
) -> None:
    """A categoria de tamanho é calculada a partir de adicionadas + removidas e gravada."""
    await create_tenant(slug="acme", installation_id=111)
    payload = build_pull_request_event(installation_id=111)
    payload["pull_request"]["additions"] = additions
    payload["pull_request"]["deletions"] = deletions

    assert await _handle("pull_request", payload) == IngestionOutcome.PROCESSED.value

    assert (await _pr(1001)).pr_size_category is expected


async def test_time_to_merge_is_persisted_in_seconds() -> None:
    """Tempo até o merge = merged_at - created_at (10:00 até 12:00 = 7200 s)."""
    await create_tenant(slug="acme", installation_id=111)

    await _handle("pull_request", build_pull_request_event(installation_id=111))

    assert (await _pr(1001)).time_to_merge_seconds == 7200


async def test_review_without_stats_does_not_erase_size_category() -> None:
    """Uma revisão posterior, sem estatísticas de linhas, mantém o tamanho já calculado."""
    await create_tenant(slug="acme", installation_id=111)
    await _handle("pull_request", build_pull_request_event(installation_id=111, pr_id=1001))
    review = build_review_event(installation_id=111, pr_merged=True)
    for key in ("additions", "deletions", "changed_files"):
        review["pull_request"].pop(key)

    await _handle("pull_request_review", review)

    assert (await _pr(1001)).pr_size_category is PRSizeCategory.S


async def test_detached_tenant_skips_enrichment_without_external_calls() -> None:
    """Tenant sem instalação ativa não gera chamadas ao GitHub nem à IA."""
    tenant_id = await create_tenant(slug="acme", installation_id=111)
    await _handle("pull_request", build_pull_request_event(installation_id=111))
    async with get_session_factory()() as session, session.begin():
        await session.execute(
            update(Tenant).where(Tenant.id == tenant_id).values(github_installation_id=None)
        )
    pr = await _pr(1001)
    diffs, analyzer = FakeDiffSource(), FakeAnalyzer()

    outcome = await enrich_pull_request(get_session_factory(), pr.id, diffs=diffs, analyzer=analyzer)

    assert outcome is EnrichmentOutcome.NO_INSTALLATION
    assert diffs.calls == []
    assert analyzer.calls == []
