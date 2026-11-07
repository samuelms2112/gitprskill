"""Auxiliares de preparação de dados para os testes de integração."""

from typing import Any

from sqlalchemy import func, select

from app.api.deps import get_token_service
from app.core.database import get_session_factory
from app.models.enums import MemberRole
from app.models.tenant import Tenant
from app.models.tenant_member import TenantMember
from app.models.user import User


async def create_tenant(*, slug: str, installation_id: int | None) -> int:
    """Cria um tenant e devolve seu ``id``."""
    async with get_session_factory()() as session, session.begin():
        tenant = Tenant(name=slug.title(), slug=slug, github_installation_id=installation_id)
        session.add(tenant)
        await session.flush()
        return tenant.id


async def create_user(*, github_id: int, login: str) -> int:
    """Cria um usuário e devolve seu ``id``."""
    async with get_session_factory()() as session, session.begin():
        user = User(github_id=github_id, login=login)
        session.add(user)
        await session.flush()
        return user.id


async def add_member(*, tenant_id: int, user_id: int, role: MemberRole) -> None:
    """Vincula um usuário a um tenant com o papel informado."""
    async with get_session_factory()() as session, session.begin():
        session.add(TenantMember(tenant_id=tenant_id, user_id=user_id, role=role))


def session_token(user_id: int) -> str:
    """Token de sessão válido para o usuário, emitido com as configurações de teste."""
    token, _ = get_token_service().create_access_token(user_id)
    return token


async def count_rows(model: Any) -> int:
    """Quantidade de linhas de uma tabela."""
    async with get_session_factory()() as session:
        return int((await session.execute(select(func.count()).select_from(model))).scalar_one())
