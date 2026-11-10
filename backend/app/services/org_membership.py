"""Vínculo automático de membros de uma organização do GitHub aos tenants existentes.

Quando alguém faz login e pertence à organização dona de uma instalação do GitHub App (tenant com
``github_installation_id`` preenchido), recebe um ``TenantMember`` no tenant correspondente, com o
papel padrão ``DEVELOPER``, se ainda não tiver vínculo.

Regras:
    * Só cria vínculos. Um papel já existente nunca é alterado aqui.
    * A correspondência é pelo nome do tenant (que vem do login da conta da instalação), sem
      diferenciar maiúsculas de minúsculas.
    * Falhas ao consultar o GitHub não impedem o login: o usuário entra sem vínculo novo.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import GitHubError
from app.core.logging import get_logger
from app.models.enums import MemberRole
from app.models.tenant import Tenant
from app.models.tenant_member import TenantMember

logger = get_logger(__name__)

DEFAULT_ORG_MEMBER_ROLE = MemberRole.DEVELOPER


@dataclass(frozen=True, slots=True)
class TenantRef:
    """Tenant com instalação ativa, identificado pelo id e pelo slug."""

    id: int
    slug: str


@dataclass(frozen=True, slots=True)
class LinkedTenant:
    """Tenant ao qual o usuário pertence após o login. ``created`` indica vínculo novo nesta chamada."""

    slug: str
    created: bool


class MembershipStore(Protocol):
    """Acesso mínimo aos tenants e aos vínculos, para manter a regra testável sem banco."""

    async def find_attached_tenants(self, lowercase_names: Sequence[str]) -> list[TenantRef]:
        """Tenants com instalação ativa cujo nome, em minúsculas, está na lista."""
        ...

    async def ensure_member(self, tenant_id: int, user_id: int, role: MemberRole) -> bool:
        """Cria o vínculo se não existir. Devolve ``True`` apenas quando criou."""
        ...


class SqlMembershipStore:
    """Implementação sobre a sessão do SQLAlchemy da requisição."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_attached_tenants(self, lowercase_names: Sequence[str]) -> list[TenantRef]:
        if not lowercase_names:
            return []
        rows = await self._session.execute(
            select(Tenant.id, Tenant.slug)
            .where(Tenant.github_installation_id.is_not(None))
            .where(func.lower(Tenant.name).in_(list(lowercase_names)))
            .order_by(Tenant.id)
        )
        return [TenantRef(id=int(row.id), slug=row.slug) for row in rows]

    async def ensure_member(self, tenant_id: int, user_id: int, role: MemberRole) -> bool:
        existing = await self._session.scalar(
            select(TenantMember.id).where(
                TenantMember.tenant_id == tenant_id, TenantMember.user_id == user_id
            )
        )
        if existing is not None:
            return False
        self._session.add(TenantMember(tenant_id=tenant_id, user_id=user_id, role=role))
        await self._session.flush()
        return True


async def link_organization_tenants(
    store: MembershipStore,
    *,
    user_id: int,
    list_organizations: Callable[[], Awaitable[list[str]]],
    role: MemberRole = DEFAULT_ORG_MEMBER_ROLE,
) -> list[LinkedTenant]:
    """Vincula o usuário aos tenants das organizações às quais ele pertence.

    Devolve todos os tenants em que o usuário passa a ter (ou já tinha) vínculo, ordenados pelo id.
    Lista vazia quando não há correspondência ou quando o GitHub não respondeu.
    """
    try:
        organizations = await list_organizations()
    except GitHubError:
        logger.warning("Não foi possível listar as organizações do usuário; login segue sem vínculo")
        return []

    names = sorted({login.lower() for login in organizations if login})
    tenants = await store.find_attached_tenants(names)

    linked: list[LinkedTenant] = []
    for tenant in tenants:
        created = await store.ensure_member(tenant.id, user_id, role)
        if created:
            logger.info("Membro vinculado automaticamente ao tenant", extra={"tenant_slug": tenant.slug})
        linked.append(LinkedTenant(slug=tenant.slug, created=created))
    return linked
