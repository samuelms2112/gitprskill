"""Rotas de tenants. Todas as consultas de dados são restritas ao tenant da rota."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, TenantContext, require_role
from app.core.database import get_db_session
from app.models.enums import MemberRole
from app.models.repository import Repository
from app.models.tenant import Tenant
from app.models.tenant_member import TenantMember
from app.schemas.repository import RepositoryRead
from app.schemas.tenant import TenantMembershipRead

router = APIRouter(prefix="/tenants", tags=["Tenants"])


@router.get("", response_model=list[TenantMembershipRead], summary="Tenants do usuário autenticado")
async def list_my_tenants(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[TenantMembershipRead]:
    """Lista apenas os tenants em que o usuário é membro."""
    rows = await session.execute(
        select(Tenant.slug, Tenant.name, TenantMember.role)
        .join(TenantMember, TenantMember.tenant_id == Tenant.id)
        .where(TenantMember.user_id == user.id)
        .order_by(Tenant.slug)
    )
    return [
        TenantMembershipRead(slug=slug, name=name, role=MemberRole(role))
        for slug, name, role in rows.all()
    ]


@router.get(
    "/{tenant_slug}/repositories",
    response_model=list[RepositoryRead],
    summary="Repositórios rastreados pelo tenant",
)
async def list_repositories(
    context: Annotated[TenantContext, Depends(require_role(MemberRole.VIEWER))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[RepositoryRead]:
    """Lista repositórios do tenant. Qualquer papel (inclusive VIEWER) pode consultar."""
    rows = await session.scalars(
        select(Repository)
        .where(Repository.tenant_id == context.tenant.id)
        .order_by(Repository.full_name)
        .limit(limit)
    )
    return [RepositoryRead.model_validate(repository) for repository in rows]
