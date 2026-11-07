"""Testes de integração do backfill: filtragem, cálculo de métricas e idempotência da re-execução."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Literal

import pytest
from sqlalchemy import func, select

from app.core.database import get_session_factory
from app.models.enums import PRSizeCategory
from app.models.pull_request import PullRequest
from app.models.repository import Repository
from app.schemas.github import GitHubPullRequest, GitHubRepository
from app.services.backfill_service import (
    BackfillCounters,
    BackfillResult,
    sync_repository_history,
)
from tests.factories.github import build_pull_request, build_repository
from tests.integration.helpers import count_rows, create_tenant

pytestmark = pytest.mark.integration

TRACKED = frozenset({"main", "master", "master-tip"})


@dataclass
class FakeHistorySource:
    """Dublê da API do GitHub: lista de PRs fechados e detalhes com estatísticas de linhas."""

    listing: list[dict[str, object]]
    details: dict[int, dict[str, object]]
    repository_payload: dict[str, object] = field(default_factory=lambda: build_repository())
    calls_to_details: list[int] = field(default_factory=list)

    async def get_repository(self, owner: str, repo: str) -> GitHubRepository:
        return GitHubRepository.model_validate(self.repository_payload)

    def iter_pull_requests(
        self,
        owner: str,
        repo: str,
        *,
        state: Literal["open", "closed", "all"],
        updated_since: datetime | None,
    ) -> AsyncIterator[GitHubPullRequest]:
        async def _items() -> AsyncIterator[GitHubPullRequest]:
            for payload in self.listing:
                yield GitHubPullRequest.model_validate(payload)

        return _items()

    async def get_pull_request(self, owner: str, repo: str, number: int) -> GitHubPullRequest:
        self.calls_to_details.append(number)
        return GitHubPullRequest.model_validate(self.details[number])


def _pr(number: int, *, base: str = "main", merged: bool = True, title: str | None = None) -> dict[str, object]:
    payload = build_pull_request(pr_id=number, number=number, base_ref=base, merged=merged)
    if title is not None:
        payload["title"] = title
    return payload


def _detail(number: int, additions: int, deletions: int, base: str = "main") -> dict[str, object]:
    payload = _pr(number, base=base)
    payload["additions"] = additions
    payload["deletions"] = deletions
    return payload


def _source() -> FakeHistorySource:
    return FakeHistorySource(
        listing=[
            _pr(1),  # mergeado em main: deve ser gravado
            _pr(2, base="feature/x"),  # mergeado fora das branches rastreadas: ignorado
            _pr(3, merged=False),  # fechado sem merge: ignorado
            _pr(4, base="master-tip"),  # mergeado em master-tip: deve ser gravado
        ],
        details={
            1: _detail(1, additions=300, deletions=200),  # 500 linhas: L
            # Fechado sem merge na main: gravado com estado closed, e sem análise de IA.
            3: {**_pr(3, merged=False), "additions": 5, "deletions": 1},
            4: _detail(4, additions=10, deletions=2, base="master-tip"),  # 12 linhas: S
        },
    )


async def _run(
    tenant_id: int, source: FakeHistorySource, progress: list[BackfillCounters] | None = None
) -> BackfillResult:
    async def on_progress(counters: BackfillCounters) -> None:
        if progress is not None:
            progress.append(replace(counters))  # cópia: o contador original continua sendo alterado

    async with get_session_factory()() as session, session.begin():
        return await sync_repository_history(
            session,
            tenant_id=tenant_id,
            owner="org",
            repo_name="api",
            source=source,
            tracked_branches=TRACKED,
            updated_since=None,
            progress=on_progress,
        )


@pytest.fixture
async def tenant_id() -> int:
    return await create_tenant(slug="acme", installation_id=111)


async def test_first_run_imports_open_and_closed_prs_from_tracked_branches(tenant_id: int) -> None:
    """Abertos e fechados de branches rastreadas são gravados; só branches fora da lista são ignoradas.

    Só os mergeados e novos são devolvidos para análise de IA (``new_pull_request_ids``).
    """
    result = await _run(tenant_id, _source())

    assert result.counters.examined == 4
    assert result.counters.stored == 3
    assert result.counters.new == 3
    assert result.counters.skipped == 1
    assert len(result.new_pull_request_ids) == 2
    assert await count_rows(PullRequest) == 3


async def test_metrics_come_from_the_detail_request(tenant_id: int) -> None:
    """Tamanho e tempo até o merge são calculados e gravados; o detalhe é buscado só para os PRs gravados."""
    source = _source()
    await _run(tenant_id, source)

    async with get_session_factory()() as session:
        big = (await session.execute(select(PullRequest).where(PullRequest.github_pr_id == 1))).scalar_one()
        small = (await session.execute(select(PullRequest).where(PullRequest.github_pr_id == 4))).scalar_one()

    assert big.pr_size_category is PRSizeCategory.L
    assert big.additions == 300 and big.deletions == 200
    assert small.pr_size_category is PRSizeCategory.S
    assert big.time_to_merge_seconds == 7200
    assert source.calls_to_details == [1, 3, 4]  # ignorados (branch não rastreada) não geram chamada extra


async def test_rerunning_the_backfill_is_idempotent(tenant_id: int) -> None:
    """Re-executar com os mesmos dados não duplica PRs, repositórios nem contribuidores."""
    await _run(tenant_id, _source())
    first_snapshot = await _snapshot()

    second = await _run(tenant_id, _source())

    assert second.counters.stored == 3
    assert second.counters.new == 0
    assert second.new_pull_request_ids == []
    assert await _snapshot() == first_snapshot
    assert await count_rows(Repository) == 1


async def test_rerun_updates_changed_data_without_duplicating(tenant_id: int) -> None:
    """Se o PR mudou no GitHub (ex.: título), a re-execução atualiza o registro existente."""
    await _run(tenant_id, _source())
    changed = _source()
    # O detalhe é a fonte autoritativa (é dele que o backfill grava), então a mudança vai nos dois.
    changed.listing[0] = _pr(1, title="título revisado")
    changed.details[1]["title"] = "título revisado"

    await _run(tenant_id, changed)

    assert await count_rows(PullRequest) == 3
    async with get_session_factory()() as session:
        title = await session.scalar(select(PullRequest.title).where(PullRequest.github_pr_id == 1))
    assert title == "título revisado"


async def test_same_repository_in_another_tenant_is_stored_separately(tenant_id: int) -> None:
    """O mesmo repositório do GitHub importado por dois tenants gera registros isolados."""
    other_tenant = await create_tenant(slug="globex", installation_id=222)
    await _run(tenant_id, _source())

    result = await _run(other_tenant, _source())

    assert result.counters.new == 3
    assert await count_rows(PullRequest) == 6
    async with get_session_factory()() as session:
        per_tenant = (
            await session.execute(select(PullRequest.tenant_id, func.count()).group_by(PullRequest.tenant_id))
        ).all()
    assert dict(per_tenant) == {tenant_id: 3, other_tenant: 3}


async def test_progress_is_reported_with_running_counts(tenant_id: int) -> None:
    """O callback de progresso recebe contagens crescentes e termina com o total final."""
    reports: list[BackfillCounters] = []

    await _run(tenant_id, _source(), progress=reports)

    assert reports, "o progresso deve ser informado ao menos uma vez"
    assert reports[-1].examined == 4
    assert reports[-1].new == 3


async def _snapshot() -> list[tuple[int, str, str | None]]:
    async with get_session_factory()() as session:
        rows = (
            await session.execute(
                select(PullRequest.github_pr_id, PullRequest.title, PullRequest.pr_size_category).order_by(
                    PullRequest.github_pr_id
                )
            )
        ).all()
    return [(pr_id, title, size.value if size else None) for pr_id, title, size in rows]
