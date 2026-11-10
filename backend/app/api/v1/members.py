"""Gestão de membros de um tenant. Restrita a OWNER do tenant da rota.

Regra central: o tenant nunca fica sem nenhum OWNER. Trocar o papel do último dono ou removê-lo
é recusado com 409.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, TenantContext, require_role
from app.core.audit import audit_event
from app.core.database import get_db_session
from app.core.exceptions import ConflictError, NotFoundError
from app.models.enums import MemberRole
from app.models.tenant_member import TenantMember
from app.models.user import User
from app.schemas.member import MemberRead, MemberRoleUpdate

router = APIRouter(prefix="/tenants/{tenant_slug}/members", tags=["Membros"])

OwnerContext = Annotated[TenantContext, Depends(require_role(MemberRole.OWNER))]
DbSession = Annotated[AsyncSession, Depends(get_db_session)]


def ensure_tenant_keeps_an_owner(target_role: MemberRole, other_owner_count: int) -> None:
    """Recusa a mudança se o membro é OWNER e nenhum outro OWNER restaria no tenant.

    Raises:
        ConflictError: Quando o tenant ficaria sem OWNER.
    """
    if target_role is MemberRole.OWNER and other_owner_count == 0:
        raise ConflictError("O tenant precisa manter ao menos um OWNER.")


async def _load_member(session: AsyncSession, tenant_id: int, user_id: int) -> TenantMember:
    member = await session.scalar(
        select(TenantMember).where(TenantMember.tenant_id == tenant_id, TenantMember.user_id == user_id)
    )
    if member is None:
        raise NotFoundError("Membro não encontrado neste tenant.")
    return member


async def _other_owner_count(session: AsyncSession, tenant_id: int, user_id: int) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(TenantMember)
            .where(
                TenantMember.tenant_id == tenant_id,
                TenantMember.role == MemberRole.OWNER,
                TenantMember.user_id != user_id,
            )
        )
        or 0
    )


@router.get("", response_model=list[MemberRead], summary="Membros do tenant")
async def list_members(context: OwnerContext, session: DbSession) -> list[MemberRead]:
    rows = await session.execute(
        select(
            TenantMember.user_id,
            User.login,
            User.avatar_url,
            TenantMember.role,
            TenantMember.created_at,
        )
        .join(User, User.id == TenantMember.user_id)
        .where(TenantMember.tenant_id == context.tenant.id)
        .order_by(User.login)
    )
    return [
        MemberRead(
            user_id=user_id,
            login=login,
            avatar_url=avatar_url,
            role=MemberRole(role),
            joined_at=joined_at,
        )
        for user_id, login, avatar_url, role, joined_at in rows.all()
    ]


@router.patch("/{user_id}", response_model=MemberRead, summary="Altera o papel de um membro")
async def update_member_role(
    user_id: int,
    payload: MemberRoleUpdate,
    context: OwnerContext,
    actor: CurrentUser,
    session: DbSession,
) -> MemberRead:
    member = await _load_member(session, context.tenant.id, user_id)
    previous = MemberRole(member.role)
    if previous is MemberRole.OWNER and payload.role is not MemberRole.OWNER:
        ensure_tenant_keeps_an_owner(
            previous, await _other_owner_count(session, context.tenant.id, user_id)
        )

    member.role = payload.role
    await session.flush()
    audit_event(
        "member_role_changed",
        tenant_slug=context.tenant.slug,
        target_user_id=user_id,
        actor_user_id=actor.id,
        previous_role=previous.value,
        new_role=payload.role.value,
    )
    user = await session.get(User, user_id)
    return MemberRead(
        user_id=user_id,
        login=user.login if user else "",
        avatar_url=user.avatar_url if user else None,
        role=payload.role,
        joined_at=member.created_at,
    )


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove um membro do tenant",
    response_class=Response,
)
async def remove_member(
    user_id: int,
    context: OwnerContext,
    actor: CurrentUser,
    session: DbSession,
) -> Response:
    member = await _load_member(session, context.tenant.id, user_id)
    previous = MemberRole(member.role)
    if previous is MemberRole.OWNER:
        ensure_tenant_keeps_an_owner(
            previous, await _other_owner_count(session, context.tenant.id, user_id)
        )

    await session.delete(member)
    await session.flush()
    audit_event(
        "member_removed",
        tenant_slug=context.tenant.slug,
        target_user_id=user_id,
        actor_user_id=actor.id,
        previous_role=previous.value,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
