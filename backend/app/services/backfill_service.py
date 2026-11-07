"""Sincronização histórica (backfill) de Pull Requests de um repositório.

Fluxo:
    1. Lista os PRs do repositório com ``state=all`` (abertos e fechados), mais recentes primeiro.
    2. Descarta os de branches que não são rastreadas.
    3. Para cada PR restante, busca o detalhe (``additions``/``deletions``), que a listagem não traz.
    4. Grava com os mesmos upserts ``ON CONFLICT`` da ingestão ao vivo: rodar de novo não duplica.

Só PRs **novos e mergeados** são devolvidos para análise de IA. Os abertos e os fechados sem
merge são gravados, mas não geram custo de IA.

Não faz commit: a transação pertence a quem chama. Assim, uma falha no meio do caminho
desfaz o lote inteiro, e a re-execução é segura.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pull_request import PullRequest
from app.schemas.github import GitHubPullRequest, GitHubRepository
from app.services.pull_request_ingestion import PullRequestIngestionService

# Quantos PRs examinados entre duas atualizações de progresso.
PROGRESS_BATCH_SIZE = 25


class PullRequestSource(Protocol):
    """Fonte dos dados no GitHub (implementada pelo ``GitHubClient``)."""

    async def get_repository(self, owner: str, repo: str) -> GitHubRepository: ...

    def iter_pull_requests(
        self,
        owner: str,
        repo: str,
        *,
        state: Literal["open", "closed", "all"],
        updated_since: datetime | None,
    ) -> AsyncIterator[GitHubPullRequest]: ...

    async def get_pull_request(self, owner: str, repo: str, number: int) -> GitHubPullRequest: ...


@dataclass(slots=True)
class BackfillCounters:
    """Contagens do progresso. ``new`` são PRs que não existiam antes da execução."""

    examined: int = 0
    stored: int = 0
    new: int = 0
    skipped: int = 0


@dataclass(slots=True)
class BackfillResult:
    counters: BackfillCounters
    # Apenas PRs novos e mergeados: são os que devem ser enviados para análise de IA.
    new_pull_request_ids: list[int] = field(default_factory=list)


ProgressCallback = Callable[[BackfillCounters], Awaitable[None]]


async def sync_repository_history(
    session: AsyncSession,
    *,
    tenant_id: int,
    owner: str,
    repo_name: str,
    source: PullRequestSource,
    tracked_branches: frozenset[str],
    updated_since: datetime | None,
    progress: ProgressCallback | None = None,
) -> BackfillResult:
    """Importa abertos e fechados de um repositório para o tenant, de branches rastreadas.

    Args:
        session: Sessão com transação aberta (quem chama faz o commit).
        tenant_id: Tenant dono do repositório.
        owner: Proprietário do repositório no GitHub.
        repo_name: Nome do repositório no GitHub.
        source: Fonte dos dados (GitHub, ou um dublê nos testes).
        tracked_branches: Branches de destino monitoradas.
        updated_since: Ignora PRs atualizados antes desse instante (``None`` = todo o histórico).
        progress: Callback chamado periodicamente com as contagens atuais.
    """
    repository = await source.get_repository(owner, repo_name)
    ingestion = PullRequestIngestionService(session, tracked_branches)
    counters = BackfillCounters()
    enrichment_ids: list[int] = []

    listing = source.iter_pull_requests(owner, repo_name, state="all", updated_since=updated_since)
    async for listed in listing:
        counters.examined += 1
        if listed.base.ref not in tracked_branches:
            counters.skipped += 1
        else:
            detail = await source.get_pull_request(owner, repo_name, listed.number)
            existed = await _already_stored(session, tenant_id, detail.id)
            pull_request_id = await ingestion.store(detail, repository, tenant_id)
            counters.stored += 1
            if not existed:
                counters.new += 1
                if detail.is_merged:
                    enrichment_ids.append(pull_request_id)

        if progress is not None and counters.examined % PROGRESS_BATCH_SIZE == 0:
            await progress(counters)

    if progress is not None:
        await progress(counters)
    return BackfillResult(counters=counters, new_pull_request_ids=enrichment_ids)


async def _already_stored(session: AsyncSession, tenant_id: int, github_pr_id: int) -> bool:
    found = await session.scalar(
        select(PullRequest.id).where(
            PullRequest.tenant_id == tenant_id,
            PullRequest.github_pr_id == github_pr_id,
        )
    )
    return found is not None
