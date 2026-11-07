"""Testes de integração do enriquecimento de PRs com IA e do seu disparo pelo fluxo de webhook."""

import pytest
from kombu.exceptions import OperationalError as BrokerOperationalError
from sqlalchemy import select

import app.tasks.github_events as github_events_module
from app.core.config import get_settings
from app.core.database import get_session_factory
from app.core.exceptions import AIRateLimitError
from app.models.enums import AICategory, AIRiskLevel
from app.models.pull_request import PullRequest
from app.services.ai_service import PullRequestAnalysis
from app.services.pr_enrichment import EnrichmentOutcome, enrich_pull_request
from app.tasks.github_events import handle_event
from tests.factories.github import build_pull_request_event
from tests.fakes import FakeAnalyzer, FakeDiffSource, FakeTaskDispatcher
from tests.integration.helpers import create_tenant

pytestmark = pytest.mark.integration

TRACKED = frozenset({"main", "master", "master-tip"})
ANALYSIS = PullRequestAnalysis(
    summary="Primeiro parágrafo com o que mudou. Segundo com impacto.",
    category=AICategory.SECURITY,
    risk_level=AIRiskLevel.HIGH,
)


async def _merge_pr(installation_id: int = 111, pr_id: int = 1001, base_ref: str = "main") -> None:
    await handle_event(
        get_session_factory(),
        tracked_branches=TRACKED,
        event_name="pull_request",
        delivery_id="d",
        payload=build_pull_request_event(installation_id=installation_id, pr_id=pr_id, base_ref=base_ref),
    )


async def _pr_by_github_id(github_pr_id: int) -> PullRequest:
    async with get_session_factory()() as session:
        return (
            await session.execute(select(PullRequest).where(PullRequest.github_pr_id == github_pr_id))
        ).scalar_one()


async def test_enrichment_stores_summary_category_and_risk() -> None:
    """O diff é buscado, o modelo é consultado e os três campos são gravados no PR."""
    await create_tenant(slug="acme", installation_id=111)
    await _merge_pr()
    pr = await _pr_by_github_id(1001)
    diffs, analyzer = FakeDiffSource("diff real"), FakeAnalyzer(ANALYSIS)

    outcome = await enrich_pull_request(get_session_factory(), pr.id, diffs=diffs, analyzer=analyzer)

    assert outcome is EnrichmentOutcome.ENRICHED
    # O diff é pedido com a instalação do tenant dono do PR (111), não com um token global.
    assert diffs.calls == [(111, "org", "api", 42)]
    assert analyzer.calls[0][0] == "feat: alteração 42"
    assert analyzer.calls[0][2] == "diff real"
    stored = await _pr_by_github_id(1001)
    assert stored.ai_summary == ANALYSIS.summary
    assert stored.ai_category is AICategory.SECURITY
    assert stored.ai_risk_level is AIRiskLevel.HIGH


async def test_second_enrichment_is_a_noop_without_external_calls() -> None:
    """PR já enriquecido não consome cota do GitHub nem do modelo."""
    await create_tenant(slug="acme", installation_id=111)
    await _merge_pr()
    pr = await _pr_by_github_id(1001)
    await enrich_pull_request(get_session_factory(), pr.id, diffs=FakeDiffSource(), analyzer=FakeAnalyzer(ANALYSIS))

    diffs, analyzer = FakeDiffSource(), FakeAnalyzer(ANALYSIS)
    outcome = await enrich_pull_request(get_session_factory(), pr.id, diffs=diffs, analyzer=analyzer)

    assert outcome is EnrichmentOutcome.ALREADY_ENRICHED
    assert diffs.calls == []
    assert analyzer.calls == []


async def test_unknown_pull_request_is_reported_as_not_found() -> None:
    """ID inexistente não dispara nenhuma chamada externa."""
    diffs = FakeDiffSource()

    outcome = await enrich_pull_request(
        get_session_factory(), 999_999, diffs=diffs, analyzer=FakeAnalyzer(ANALYSIS)
    )

    assert outcome is EnrichmentOutcome.NOT_FOUND
    assert diffs.calls == []


async def test_rate_limit_propagates_and_leaves_pr_unchanged() -> None:
    """Limite da IA não grava nada parcial: o PR continua sem análise e a exceção sobe para a tarefa."""
    await create_tenant(slug="acme", installation_id=111)
    await _merge_pr()
    pr = await _pr_by_github_id(1001)

    with pytest.raises(AIRateLimitError) as exc_info:
        await enrich_pull_request(
            get_session_factory(),
            pr.id,
            diffs=FakeDiffSource(),
            analyzer=FakeAnalyzer(error=AIRateLimitError(retry_after=30)),
        )

    assert exc_info.value.retry_after == 30
    assert (await _pr_by_github_id(1001)).ai_summary is None


async def test_merged_pr_schedules_enrichment_after_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Com chave de IA configurada, o PR mergeado é enviado para enriquecimento."""
    await create_tenant(slug="acme", installation_id=111)
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-chave-de-teste")
    get_settings.cache_clear()
    dispatcher = FakeTaskDispatcher()
    monkeypatch.setattr(github_events_module, "enrich_pr_with_ai_task", dispatcher)

    await _merge_pr()

    pr = await _pr_by_github_id(1001)
    assert dispatcher.calls == [pr.id]


async def test_no_enrichment_is_scheduled_without_ai_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sem ``GEMINI_API_KEY``, nada é enfileirado e o merge é gravado normalmente."""
    await create_tenant(slug="acme", installation_id=111)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    get_settings.cache_clear()
    dispatcher = FakeTaskDispatcher()
    monkeypatch.setattr(github_events_module, "enrich_pr_with_ai_task", dispatcher)

    await _merge_pr()

    assert dispatcher.calls == []
    assert (await _pr_by_github_id(1001)).is_merged is True


async def test_broker_failure_does_not_lose_the_merged_pr(monkeypatch: pytest.MonkeyPatch) -> None:
    """Falha ao agendar a IA é melhor esforço: o PR já gravado não é desfeito."""
    await create_tenant(slug="acme", installation_id=111)
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-chave-de-teste")
    get_settings.cache_clear()
    monkeypatch.setattr(
        github_events_module,
        "enrich_pr_with_ai_task",
        FakeTaskDispatcher(error=BrokerOperationalError("redis fora")),
    )

    outcome = await handle_event(
        get_session_factory(),
        tracked_branches=TRACKED,
        event_name="pull_request",
        delivery_id="d",
        payload=build_pull_request_event(installation_id=111),
    )

    assert outcome == "processed"
    assert (await _pr_by_github_id(1001)).is_merged is True


async def test_untracked_branch_is_not_scheduled(monkeypatch: pytest.MonkeyPatch) -> None:
    """PRs fora das branches rastreadas não são gravados e, portanto, não são enriquecidos."""
    await create_tenant(slug="acme", installation_id=111)
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-chave-de-teste")
    get_settings.cache_clear()
    dispatcher = FakeTaskDispatcher()
    monkeypatch.setattr(github_events_module, "enrich_pr_with_ai_task", dispatcher)

    await _merge_pr(base_ref="feature/x")

    assert dispatcher.calls == []
