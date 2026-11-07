"""Relatórios de Pull Requests: listagem, resumo agregado e release notes sob demanda.

Todas as rotas exigem autenticação e o tenant informado precisa ser do usuário.
Listagem e resumo usam o mesmo conjunto de filtros (``_filter_conditions``), para que os
números dos KPIs sempre correspondam aos itens exibidos.
"""

from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, get_ai_service, require_ai, resolve_tenant_context
from app.core.database import get_db_session
from app.core.exceptions import InvalidPayloadError
from app.models.contributor import Contributor
from app.models.enums import AICategory, PRSizeCategory, PullRequestState
from app.models.pull_request import PullRequest
from app.models.repository import Repository
from app.schemas.report import (
    PRStateFilter,
    PullRequestReportItem,
    PullRequestReportPage,
    ReleaseNotesRequest,
    ReleaseNotesResponse,
    ReportSummary,
    SizeDistribution,
)
from app.services.ai.base import AIProvider

router = APIRouter(prefix="/reports", tags=["Relatórios"])

NO_PULL_REQUESTS_MARKDOWN = "Nenhum Pull Request mergeado no período informado."
FACET_LIMIT = 500


def _day_start(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=UTC)


def _merged_conditions(
    tenant_id: int,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    base_branch: str | None = None,
) -> list[ColumnElement[bool]]:
    """Condições comuns: PRs mergeados do tenant, opcionalmente em um período e branch."""
    conditions: list[ColumnElement[bool]] = [
        PullRequest.tenant_id == tenant_id,
        PullRequest.is_merged.is_(True),
    ]
    if start_date is not None:
        conditions.append(PullRequest.merged_at >= _day_start(start_date))
    if end_date is not None:
        conditions.append(PullRequest.merged_at < _day_start(end_date + timedelta(days=1)))
    if base_branch is not None:
        conditions.append(PullRequest.base_branch == base_branch)
    return conditions


def _state_conditions(state: PRStateFilter) -> list[ColumnElement[bool]]:
    """Abertos, mergeados ou todos. Abertos são os não mergeados e ainda não fechados."""
    if state == "merged":
        return [PullRequest.is_merged.is_(True)]
    if state == "open":
        return [PullRequest.is_merged.is_(False), PullRequest.state == PullRequestState.OPEN]
    return []


def _filter_conditions(
    tenant_id: int,
    *,
    start_date: date | None,
    end_date: date | None,
    repository: str | None,
    author: str | None,
    ai_category: AICategory | None,
    state: PRStateFilter = "merged",
) -> list[ColumnElement[bool]]:
    """Filtros de negócio aplicados à listagem e ao resumo, sempre restritos ao tenant.

    O período usa a data de referência: ``merged_at`` quando existe, senão ``created_at``.
    Assim um PR aberto também aparece no período em que foi aberto.
    """
    conditions: list[ColumnElement[bool]] = [PullRequest.tenant_id == tenant_id, *_state_conditions(state)]
    reference = func.coalesce(PullRequest.merged_at, PullRequest.created_at)
    if start_date is not None:
        conditions.append(reference >= _day_start(start_date))
    if end_date is not None:
        conditions.append(reference < _day_start(end_date + timedelta(days=1)))
    if repository is not None:
        conditions.append(Repository.full_name == repository)
    if author is not None:
        conditions.append(Contributor.login == author)
    if ai_category is not None:
        conditions.append(PullRequest.ai_category == ai_category)
    return conditions


def _base(*columns: Any) -> Select[Any]:
    """SELECT sobre PRs já unido a repositório e autor (necessários para filtros e exibição)."""
    return (
        select(*columns)
        .select_from(PullRequest)
        .join(Repository, PullRequest.repository_id == Repository.id)
        .join(Contributor, PullRequest.author_id == Contributor.id)
    )


def _validate_period(start_date: date | None, end_date: date | None) -> None:
    if start_date is not None and end_date is not None and start_date > end_date:
        raise InvalidPayloadError("start_date não pode ser posterior a end_date.")


@router.get("/prs", response_model=PullRequestReportPage, summary="PRs com dados de IA, filtráveis")
async def list_pull_request_reports(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    tenant_slug: Annotated[str, Query(min_length=1, max_length=100)],
    start_date: date | None = None,
    end_date: date | None = None,
    repository: Annotated[str | None, Query(min_length=3, max_length=255)] = None,
    author: Annotated[str | None, Query(min_length=1, max_length=150)] = None,
    ai_category: AICategory | None = None,
    state: PRStateFilter = "merged",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> PullRequestReportPage:
    """Lista PRs do tenant (mergeados por padrão), do mais recente para o mais antigo.

    Args:
        state: ``merged`` (padrão), ``open`` ou ``all``.

    Raises:
        NotFoundError: Tenant inexistente ou o usuário não é membro.
        InvalidPayloadError: Quando ``start_date`` é posterior a ``end_date``.
    """
    context = await resolve_tenant_context(session, user, tenant_slug)
    _validate_period(start_date, end_date)
    conditions = _filter_conditions(
        context.tenant.id,
        start_date=start_date,
        end_date=end_date,
        repository=repository,
        author=author,
        ai_category=ai_category,
        state=state,
    )

    total = await session.scalar(_base(func.count()).where(*conditions))
    rows = await session.execute(
        _base(PullRequest, Repository.full_name, Contributor.login)
        .where(*conditions)
        .order_by(PullRequest.merged_at.desc(), PullRequest.id.desc())
        .limit(limit)
        .offset(offset)
    )
    items = [
        PullRequestReportItem(
            id=pr.id,
            number=pr.number,
            title=pr.title,
            repository=repository_name,
            author=author_login,
            base_branch=pr.base_branch,
            state="open" if pr.state is PullRequestState.OPEN else "closed",
            is_merged=pr.is_merged,
            created_at=pr.created_at,
            merged_at=pr.merged_at,
            additions=pr.additions,
            deletions=pr.deletions,
            changed_files=pr.changed_files,
            pr_size_category=pr.pr_size_category,
            time_to_merge_seconds=pr.time_to_merge_seconds,
            ai_category=pr.ai_category,
            ai_risk_level=pr.ai_risk_level,
            ai_summary=pr.ai_summary,
            html_url=pr.html_url,
        )
        for pr, repository_name, author_login in rows.all()
    ]
    return PullRequestReportPage(items=items, total=int(total or 0), limit=limit, offset=offset)


@router.get("/summary", response_model=ReportSummary, summary="Indicadores agregados (KPIs)")
async def summarize_pull_requests(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    tenant_slug: Annotated[str, Query(min_length=1, max_length=100)],
    start_date: date | None = None,
    end_date: date | None = None,
    repository: Annotated[str | None, Query(min_length=3, max_length=255)] = None,
    author: Annotated[str | None, Query(min_length=1, max_length=150)] = None,
    ai_category: AICategory | None = None,
) -> ReportSummary:
    """Total, tempo médio até o merge e distribuição por tamanho, com as opções dos seletores.

    Os seletores (``available_*``) consideram todos os PRs mergeados do tenant, para que
    o usuário sempre possa escolher um valor, mesmo depois de já ter filtrado outro.
    """
    context = await resolve_tenant_context(session, user, tenant_slug)
    _validate_period(start_date, end_date)
    tenant_id = context.tenant.id
    conditions = _filter_conditions(
        tenant_id,
        start_date=start_date,
        end_date=end_date,
        repository=repository,
        author=author,
        ai_category=ai_category,
    )

    total = await session.scalar(_base(func.count()).where(*conditions))
    average = await session.scalar(
        _base(func.avg(PullRequest.time_to_merge_seconds)).where(
            *conditions, PullRequest.time_to_merge_seconds.is_not(None)
        )
    )
    size_rows = await session.execute(
        _base(PullRequest.pr_size_category, func.count())
        .where(*conditions)
        .group_by(PullRequest.pr_size_category)
    )
    authors = await session.scalars(
        _base(Contributor.login)
        .where(*_merged_conditions(tenant_id))
        .distinct()
        .order_by(Contributor.login)
        .limit(FACET_LIMIT)
    )
    repositories = await session.scalars(
        _base(Repository.full_name)
        .where(*_merged_conditions(tenant_id))
        .distinct()
        .order_by(Repository.full_name)
        .limit(FACET_LIMIT)
    )

    return ReportSummary(
        total=int(total or 0),
        average_time_to_merge_seconds=round(float(average)) if average is not None else None,
        size_distribution=_size_distribution(size_rows.all()),
        available_authors=list(authors.all()),
        available_repositories=list(repositories.all()),
    )


def _size_distribution(rows: Any) -> SizeDistribution:
    """Converte ``(categoria, quantidade)`` em contagens fixas por faixa (zero quando ausente)."""
    counts: dict[str, int] = {}
    for category, count in rows:
        if isinstance(category, PRSizeCategory):
            counts[category.value] = int(count)
    return SizeDistribution(**counts)


@router.post(
    "/release-notes",
    response_model=ReleaseNotesResponse,
    summary="Gera release notes em Markdown para um período ou branch",
)
async def create_release_notes(
    payload: ReleaseNotesRequest,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    ai_service: Annotated[AIProvider | None, Depends(get_ai_service)],
) -> ReleaseNotesResponse:
    """Sintetiza os PRs mergeados no escopo pedido (até ``limit``, em ordem cronológica).

    Raises:
        NotFoundError: Tenant inexistente ou o usuário não é membro.
        AINotConfiguredError: ``GEMINI_API_KEY`` ausente (HTTP 503).
        AIRateLimitError: Limite de taxa do modelo (HTTP 429 com ``Retry-After``).
        AIUnavailableError: Modelo indisponível (HTTP 503).
    """
    context = await resolve_tenant_context(session, user, payload.tenant_slug)
    ai = require_ai(ai_service)
    conditions = _merged_conditions(
        context.tenant.id,
        start_date=payload.start_date,
        end_date=payload.end_date,
        base_branch=payload.base_branch,
    )
    prs = (
        await session.scalars(
            select(PullRequest)
            .options(selectinload(PullRequest.author))
            .where(*conditions)
            .order_by(PullRequest.merged_at.asc(), PullRequest.id.asc())
            .limit(payload.limit)
        )
    ).all()

    markdown = await ai.generate_release_notes(prs) if prs else NO_PULL_REQUESTS_MARKDOWN
    return ReleaseNotesResponse(
        tenant_slug=payload.tenant_slug,
        start_date=payload.start_date,
        end_date=payload.end_date,
        base_branch=payload.base_branch,
        pr_count=len(prs),
        markdown=markdown,
    )
