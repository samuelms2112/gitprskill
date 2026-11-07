"""Testes de integração da memória semântica (pgvector) e do enriquecimento com parecer PM/PO."""

from typing import Any

import pytest
from sqlalchemy import select, update

from app.core.database import get_session_factory
from app.models.enums import AICategory, AIRiskLevel
from app.models.pull_request import EMBEDDING_DIMENSIONS, PullRequest
from app.models.repository import Repository
from app.services.ai.memory import PgVectorMemory
from app.services.ai_service import PullRequestAnalysis
from app.services.pr_enrichment import EnrichmentOutcome, enrich_pull_request
from app.tasks.github_events import handle_event
from tests.factories.github import build_pull_request_event
from tests.fakes import FakeAnalyzer, FakeDiffSource
from tests.integration.helpers import create_tenant

pytestmark = pytest.mark.integration

TRACKED = frozenset({"main", "master", "master-tip"})


def _axis(index: int) -> list[float]:
    """Vetor unitário no eixo ``index``: dois eixos diferentes são ortogonais (distância máxima)."""
    return [1.0 if position == index else 0.0 for position in range(EMBEDDING_DIMENSIONS)]


class FakeEmbedder:
    def __init__(self, vector: list[float]) -> None:
        self._vector = vector

    async def embed(self, text: str) -> list[float]:
        return self._vector


class FakeProductAgent:
    async def product_opinion(self, *, tenant_id: int, repository_id: int, title: str, description: str) -> str:
        return "Parecer PM/PO de teste."


async def _merged_pr(number: int) -> int:
    await handle_event(
        get_session_factory(),
        tracked_branches=TRACKED,
        event_name="pull_request",
        delivery_id=f"d-{number}",
        payload=build_pull_request_event(installation_id=111, number=number, pr_id=1000 + number),
    )
    async with get_session_factory()() as session:
        return int(await session.scalar(select(PullRequest.id).where(PullRequest.github_pr_id == 1000 + number)) or 0)


async def _set_embedding(pr_id: int, vector: list[float]) -> None:
    async with get_session_factory()() as session, session.begin():
        await session.execute(update(PullRequest).where(PullRequest.id == pr_id).values(ai_embedding=vector))


async def test_similar_pull_requests_come_back_closest_first() -> None:
    """A busca devolve o PR mais parecido primeiro (distância de cosseno), dentro do mesmo repositório."""
    tenant_id = await create_tenant(slug="acme", installation_id=111)
    closest = await _merged_pr(1)
    middle = await _merged_pr(2)
    far = await _merged_pr(3)
    await _set_embedding(closest, _axis(0))
    await _set_embedding(middle, [0.7, 0.7] + [0.0] * (EMBEDDING_DIMENSIONS - 2))
    await _set_embedding(far, _axis(9))

    async with get_session_factory()() as session:
        repository_id = int(await session.scalar(select(Repository.id).where(Repository.tenant_id == tenant_id)) or 0)
        similar = await PgVectorMemory(session).find_similar(
            tenant_id=tenant_id, repository_id=repository_id, vector=_axis(0), limit=3
        )

    assert [item.number for item in similar] == [1, 2, 3]
    assert similar[0].distance < similar[1].distance < similar[2].distance


async def test_memory_never_crosses_tenants() -> None:
    """O histórico de uma empresa nunca aparece para outra, mesmo com o mesmo repositório."""
    tenant_a = await create_tenant(slug="acme", installation_id=111)
    tenant_b = await create_tenant(slug="globex", installation_id=222)
    pr_a = await _merged_pr(1)
    await _set_embedding(pr_a, _axis(0))
    async with get_session_factory()() as session:
        repository_a = int(await session.scalar(select(Repository.id).where(Repository.tenant_id == tenant_a)) or 0)

    async with get_session_factory()() as session:
        similar = await PgVectorMemory(session).find_similar(
            tenant_id=tenant_b, repository_id=repository_a, vector=_axis(0), limit=5
        )

    assert similar == []


async def test_enrichment_stores_product_opinion_and_embedding() -> None:
    """O enriquecimento grava o parecer PM/PO e o vetor do resumo, para a memória futura."""
    await create_tenant(slug="acme", installation_id=111)
    pr_id = await _merged_pr(1)
    analysis = PullRequestAnalysis(
        summary="Resumo suficientemente longo para validar o schema do PR.",
        category=AICategory.FEATURE,
        risk_level=AIRiskLevel.LOW,
    )

    outcome = await enrich_pull_request(
        get_session_factory(),
        pr_id,
        diffs=FakeDiffSource(),
        analyzer=FakeAnalyzer(analysis),
        product_agent=FakeProductAgent(),
        embedder=FakeEmbedder(_axis(4)),
    )

    assert outcome is EnrichmentOutcome.ENRICHED
    async with get_session_factory()() as session:
        pr: Any = await session.get(PullRequest, pr_id)
    assert pr.ai_product_opinion == "Parecer PM/PO de teste."
    assert pr.ai_embedding is not None
    assert len(pr.ai_embedding) == EMBEDDING_DIMENSIONS
    assert pr.ai_embedding[4] == pytest.approx(1.0)


async def test_enrichment_without_embedder_still_completes() -> None:
    """Sem embedder (modo Gemini), o PR é enriquecido e fica sem vetor, sem erro."""
    await create_tenant(slug="acme", installation_id=111)
    pr_id = await _merged_pr(1)
    analysis = PullRequestAnalysis(
        summary="Resumo suficientemente longo para validar o schema do PR.",
        category=AICategory.CHORE,
        risk_level=AIRiskLevel.LOW,
    )

    outcome = await enrich_pull_request(
        get_session_factory(),
        pr_id,
        diffs=FakeDiffSource(),
        analyzer=FakeAnalyzer(analysis),
    )

    assert outcome is EnrichmentOutcome.ENRICHED
    async with get_session_factory()() as session:
        pr: Any = await session.get(PullRequest, pr_id)
    assert pr.ai_embedding is None
    assert pr.ai_product_opinion is None
