"""Memória semântica dos PRs: busca por similaridade de embeddings no PostgreSQL (pgvector).

Cada PR enriquecido guarda o vetor do seu resumo. Para um PR novo, a busca devolve os PRs
mergeados mais parecidos do mesmo repositório: é o "histórico" que contextualiza o parecer.
A busca é sempre filtrada por tenant e repositório, então uma empresa nunca recebe memória
de outra.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.enums import AICategory
from app.models.pull_request import PullRequest


@dataclass(frozen=True, slots=True)
class SimilarPullRequest:
    number: int
    title: str
    summary: str | None
    category: AICategory | None
    distance: float


class PullRequestMemory(Protocol):
    async def find_similar(
        self,
        *,
        tenant_id: int,
        repository_id: int,
        vector: list[float],
        limit: int,
    ) -> list[SimilarPullRequest]: ...


class SessionFactoryMemory:
    """Memória que abre uma sessão curta por consulta. Usada fora de transações longas."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def find_similar(
        self,
        *,
        tenant_id: int,
        repository_id: int,
        vector: list[float],
        limit: int,
    ) -> list[SimilarPullRequest]:
        async with self._session_factory() as session:
            return await PgVectorMemory(session).find_similar(
                tenant_id=tenant_id, repository_id=repository_id, vector=vector, limit=limit
            )


class PgVectorMemory:
    """Implementação da memória sobre a coluna ``ai_embedding`` (índice HNSW, distância cosseno)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_similar(
        self,
        *,
        tenant_id: int,
        repository_id: int,
        vector: list[float],
        limit: int,
    ) -> list[SimilarPullRequest]:
        distance = PullRequest.ai_embedding.cosine_distance(vector)
        rows = await self._session.execute(
            select(
                PullRequest.number,
                PullRequest.title,
                PullRequest.ai_summary,
                PullRequest.ai_category,
                distance.label("distance"),
            )
            .where(
                PullRequest.tenant_id == tenant_id,
                PullRequest.repository_id == repository_id,
                PullRequest.is_merged.is_(True),
                PullRequest.ai_embedding.is_not(None),
            )
            .order_by(distance)
            .limit(limit)
        )
        return [
            SimilarPullRequest(
                number=number,
                title=title,
                summary=summary,
                category=category,
                distance=float(item_distance),
            )
            for number, title, summary, category, item_distance in rows.all()
        ]
