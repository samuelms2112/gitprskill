"""Ingestão de Pull Requests do GitHub para o banco, isolada por tenant.

Separação de responsabilidades:
    * ``decide`` é uma função pura que decide se um evento ``pull_request`` deve ser persistido.
    * ``store`` grava repositório, autor e PR com upserts idempotentes
      (``INSERT ... ON CONFLICT``), então reenviar a mesma entrega não duplica dados.
    * Não há commit aqui: a transação pertence ao chamador.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.contributor import Contributor
from app.models.enums import PRSizeCategory
from app.models.pull_request import PullRequest
from app.models.repository import Repository
from app.schemas.contributor import ContributorCreate
from app.schemas.github import (
    GitHubPullRequest,
    GitHubRepository,
    GitHubUser,
    PullRequestEventPayload,
)
from app.schemas.pull_request import PullRequestCreate
from app.schemas.repository import RepositoryCreate
from app.services.outcomes import IngestionOutcome, IngestionResult
from app.services.pr_metrics import (
    classify_pr_size,
    compute_time_to_merge_seconds,
    total_changes,
)
from app.services.validation import validate_domain

logger = get_logger(__name__)

# Ações que alteram o estado de um PR e precisam ser gravadas: abertura, reabertura,
# novos commits (synchronize) e fechamento (com ou sem merge).
CAPTURED_ACTIONS = frozenset({"opened", "reopened", "synchronize", "closed"})


def _size_category(pr: GitHubPullRequest) -> PRSizeCategory | None:
    """Tamanho do PR, ou ``None`` quando o payload não traz as estatísticas de linhas."""
    if pr.additions is None or pr.deletions is None:
        return None
    return classify_pr_size(total_changes(pr.additions, pr.deletions))


def decide(event: PullRequestEventPayload, tracked_branches: frozenset[str]) -> IngestionOutcome:
    """Decide se o evento deve ser gravado. Função pura, sem I/O.

    Abertos e fechados (mergeados ou não) em branches rastreadas são gravados desde a
    abertura. A análise de IA não depende daqui: ela é decidida por ``is_merged``.

    Args:
        event: Evento ``pull_request`` já validado.
        tracked_branches: Branches de destino monitoradas.
    """
    if event.action not in CAPTURED_ACTIONS:
        return IngestionOutcome.IGNORED_ACTION
    if event.pull_request.base.ref not in tracked_branches:
        return IngestionOutcome.IGNORED_BRANCH
    return IngestionOutcome.PROCESSED


class PullRequestIngestionService:
    """Persiste PRs e suas entidades relacionadas dentro de um tenant."""

    def __init__(self, session: AsyncSession, tracked_branches: frozenset[str]) -> None:
        """Associa o serviço a uma sessão e às branches rastreadas."""
        self._session = session
        self._tracked_branches = tracked_branches

    @property
    def tracked_branches(self) -> frozenset[str]:
        """Branches de destino consideradas pelo serviço."""
        return self._tracked_branches

    async def process(self, event: PullRequestEventPayload, tenant_id: int) -> IngestionResult:
        """Processa um evento ``pull_request`` para o tenant informado.

        Raises:
            InvalidPayloadError: Quando os dados violam as regras de domínio.
        """
        outcome = decide(event, self._tracked_branches)
        if outcome is not IngestionOutcome.PROCESSED:
            logger.info(
                "Evento de pull_request ignorado",
                extra={"outcome": outcome.value, "action": event.action, "number": event.number},
            )
            return IngestionResult(outcome=outcome)

        pull_request_id = await self.store(event.pull_request, event.repository, tenant_id)
        logger.info(
            "Pull request mergeado persistido",
            extra={"repository": event.repository.full_name, "number": event.number},
        )
        return IngestionResult(
            outcome=IngestionOutcome.PROCESSED,
            pull_request_id=pull_request_id,
            enrich=event.pull_request.is_merged,
        )

    async def store(
        self,
        pull_request: GitHubPullRequest,
        repository: GitHubRepository,
        tenant_id: int,
    ) -> int:
        """Grava (ou atualiza) repositório, autor e PR. Devolve o ``id`` interno do PR."""
        repository_id = await self._upsert_repository(repository, tenant_id)
        author_id = await self.contributor_id(pull_request.user, tenant_id)
        return await self._upsert_pull_request(pull_request, repository_id, author_id, tenant_id)

    async def contributor_id(self, user: GitHubUser, tenant_id: int) -> int:
        """Garante que o contribuidor exista no tenant e devolve seu ``id`` interno."""
        data = validate_domain(
            ContributorCreate,
            tenant_id=tenant_id,
            github_id=user.id,
            login=user.login,
            avatar_url=user.avatar_url,
            html_url=user.html_url,
        )
        statement = pg_insert(Contributor).values(**data.model_dump())
        statement = statement.on_conflict_do_update(
            index_elements=[Contributor.tenant_id, Contributor.github_id],
            set_={
                "login": statement.excluded.login,
                "avatar_url": statement.excluded.avatar_url,
                "html_url": statement.excluded.html_url,
                "updated_at": func.now(),
            },
        ).returning(Contributor.id)
        result = await self._session.execute(statement)
        return int(result.scalar_one())

    async def _upsert_repository(self, repo: GitHubRepository, tenant_id: int) -> int:
        data = validate_domain(
            RepositoryCreate,
            tenant_id=tenant_id,
            github_id=repo.id,
            name=repo.name,
            full_name=repo.full_name,
            owner_login=repo.owner.login,
            html_url=repo.html_url,
            default_branch=repo.default_branch,
            is_private=repo.private,
        )
        statement = pg_insert(Repository).values(**data.model_dump())
        statement = statement.on_conflict_do_update(
            index_elements=[Repository.tenant_id, Repository.github_id],
            set_={
                "name": statement.excluded.name,
                "full_name": statement.excluded.full_name,
                "owner_login": statement.excluded.owner_login,
                "html_url": statement.excluded.html_url,
                "default_branch": statement.excluded.default_branch,
                "is_private": statement.excluded.is_private,
                "updated_at": func.now(),
            },
        ).returning(Repository.id)
        result = await self._session.execute(statement)
        return int(result.scalar_one())

    async def _upsert_pull_request(
        self,
        pr: GitHubPullRequest,
        repository_id: int,
        author_id: int,
        tenant_id: int,
    ) -> int:
        data = validate_domain(
            PullRequestCreate,
            tenant_id=tenant_id,
            github_pr_id=pr.id,
            repository_id=repository_id,
            author_id=author_id,
            number=pr.number,
            title=pr.title,
            body=pr.body,
            state=pr.state,
            is_merged=pr.is_merged,
            head_branch=pr.head.ref,
            base_branch=pr.base.ref,
            # Estatísticas ausentes em um evento são tratadas como zero; o backfill as completa.
            additions=pr.additions or 0,
            deletions=pr.deletions or 0,
            changed_files=pr.changed_files or 0,
            created_at=pr.created_at,
            updated_at=pr.updated_at,
            closed_at=pr.closed_at,
            merged_at=pr.merged_at,
            html_url=pr.html_url,
            pr_size_category=_size_category(pr),
            time_to_merge_seconds=compute_time_to_merge_seconds(pr.created_at, pr.merged_at),
        )
        values = data.model_dump()
        statement = pg_insert(PullRequest).values(**values)
        mutable_columns = [
            column for column in values if column not in ("tenant_id", "github_pr_id", "pr_size_category")
        ]
        set_clause: dict[str, Any] = {
            column: statement.excluded[column] for column in mutable_columns
        }
        # Uma atualização sem estatísticas de linhas (ex.: revisão) não apaga o tamanho já calculado.
        set_clause["pr_size_category"] = func.coalesce(
            statement.excluded.pr_size_category, PullRequest.pr_size_category
        )
        statement = statement.on_conflict_do_update(
            index_elements=[PullRequest.tenant_id, PullRequest.github_pr_id],
            set_=set_clause,
        ).returning(PullRequest.id)
        result = await self._session.execute(statement)
        return int(result.scalar_one())
