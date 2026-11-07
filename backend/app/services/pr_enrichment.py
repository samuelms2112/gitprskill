"""Enriquecimento de Pull Requests com IA, em etapas.

A função executa em três fases, com a transação do banco fechada durante as chamadas externas:
    1. Lê os dados do PR e a instalação do GitHub App do tenant dono (sessão curta).
    2. Busca o diff; pede o parecer de produto (PM/PO); pede a análise técnica (conselho).
    3. Calcula o embedding do resumo e grava tudo (sessão curta, com nova checagem de idempotência).

O parecer de produto e o embedding são opcionais: se falharem, o PR é analisado mesmo assim.
Sem análise prévia, nenhuma chamada externa é feita quando o PR já foi enriquecido ou quando
o tenant não tem instalação ativa.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.core.exceptions import AIError
from app.core.logging import get_logger
from app.models.pull_request import PullRequest
from app.models.repository import Repository
from app.models.tenant import Tenant
from app.services.ai.base import TextEmbedder
from app.services.ai_service import PullRequestAnalysis

logger = get_logger(__name__)


class EnrichmentOutcome(StrEnum):
    """Desfecho de uma tentativa de enriquecimento."""

    ENRICHED = "enriched"
    ALREADY_ENRICHED = "already_enriched"
    NOT_FOUND = "not_found"
    NO_INSTALLATION = "no_installation"


class InstallationDiffFetcher(Protocol):
    """Busca o diff de um PR autenticando-se como a instalação do tenant dono do PR."""

    async def get_diff(self, installation_id: int, owner: str, repo: str, number: int) -> str: ...


class PullRequestAnalyzer(Protocol):
    """Conselho/provedor de análise técnica de PRs."""

    async def analyze_pull_request(
        self,
        title: str,
        description: str,
        diff_text: str,
        *,
        product_context: str | None = None,
    ) -> PullRequestAnalysis: ...


class ProductOpinionSource(Protocol):
    """Agente PM/PO: parecer de produto contextualizado pelo histórico."""

    async def product_opinion(
        self,
        *,
        tenant_id: int,
        repository_id: int,
        title: str,
        description: str,
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class _Snapshot:
    tenant_id: int
    repository_id: int
    installation_id: int
    owner: str
    repo: str
    number: int
    title: str
    body: str


async def enrich_pull_request(
    session_factory: async_sessionmaker[AsyncSession],
    pr_id: int,
    *,
    diffs: InstallationDiffFetcher,
    analyzer: PullRequestAnalyzer,
    product_agent: ProductOpinionSource | None = None,
    embedder: TextEmbedder | None = None,
) -> EnrichmentOutcome:
    """Enriquece um PR com resumo, categoria, risco, parecer de produto e embedding.

    Exceções de integração essenciais (diff do GitHub, análise técnica) propagam para quem chama,
    que decide se reenvia a tarefa. Parecer e embedding são best-effort.
    """
    loaded = await _load_snapshot(session_factory, pr_id)
    if isinstance(loaded, EnrichmentOutcome):
        return loaded
    snapshot = loaded

    diff = await diffs.get_diff(snapshot.installation_id, snapshot.owner, snapshot.repo, snapshot.number)
    opinion = await _product_opinion(product_agent, snapshot)
    analysis = await analyzer.analyze_pull_request(
        snapshot.title, snapshot.body, diff, product_context=opinion
    )
    embedding = await _embed(embedder, analysis.summary)

    return await _store(session_factory, pr_id, analysis, opinion, embedding)


async def _product_opinion(agent: ProductOpinionSource | None, snapshot: _Snapshot) -> str | None:
    if agent is None:
        return None
    try:
        return await agent.product_opinion(
            tenant_id=snapshot.tenant_id,
            repository_id=snapshot.repository_id,
            title=snapshot.title,
            description=snapshot.body,
        )
    except AIError:
        logger.warning("Parecer de produto indisponível; análise segue sem ele")
        return None


async def _embed(embedder: TextEmbedder | None, summary: str) -> list[float] | None:
    if embedder is None:
        return None
    try:
        return await embedder.embed(summary)
    except AIError:
        logger.warning("Embedding indisponível; PR gravado sem memória semântica")
        return None


async def _load_snapshot(
    session_factory: async_sessionmaker[AsyncSession], pr_id: int
) -> _Snapshot | EnrichmentOutcome:
    async with session_factory() as session:
        pr = await session.get(PullRequest, pr_id, options=[selectinload(PullRequest.repository)])
        if pr is None:
            return EnrichmentOutcome.NOT_FOUND
        if pr.ai_summary is not None:
            return EnrichmentOutcome.ALREADY_ENRICHED

        tenant = await session.get(Tenant, pr.tenant_id)
        if tenant is None or tenant.github_installation_id is None:
            logger.info("Enriquecimento ignorado: tenant sem instalação ativa", extra={"pr_id": pr_id})
            return EnrichmentOutcome.NO_INSTALLATION

        repository: Repository = pr.repository
        return _Snapshot(
            tenant_id=pr.tenant_id,
            repository_id=repository.id,
            installation_id=tenant.github_installation_id,
            owner=repository.owner_login,
            repo=repository.name,
            number=pr.number,
            title=pr.title,
            body=pr.body or "",
        )


async def _store(
    session_factory: async_sessionmaker[AsyncSession],
    pr_id: int,
    analysis: PullRequestAnalysis,
    opinion: str | None,
    embedding: list[float] | None,
) -> EnrichmentOutcome:
    async with session_factory() as session, session.begin():
        pr = await session.get(PullRequest, pr_id)
        if pr is None:
            return EnrichmentOutcome.NOT_FOUND
        if pr.ai_summary is not None:
            # Outra execução concorrente gravou primeiro: mantém o resultado existente.
            return EnrichmentOutcome.ALREADY_ENRICHED
        pr.ai_summary = analysis.summary
        pr.ai_category = analysis.category
        pr.ai_risk_level = analysis.risk_level
        pr.ai_product_opinion = opinion
        pr.ai_embedding = embedding
    logger.info(
        "Pull request enriquecido com IA",
        extra={"pr_id": pr_id, "category": analysis.category.value, "memory": embedding is not None},
    )
    return EnrichmentOutcome.ENRICHED
