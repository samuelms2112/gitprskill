"""Criação e atualização de usuários a partir de perfis do GitHub."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


async def upsert_user(
    session: AsyncSession,
    *,
    github_id: int,
    login: str,
    email: str | None,
    avatar_url: str | None,
) -> User:
    """Cria o usuário ou atualiza seus dados. Devolve a instância com ``id`` preenchido.

    ``email`` só é sobrescrito quando o GitHub informa um valor, para não apagar
    um e-mail já conhecido quando a API deixa de expô-lo.
    """
    user = await session.scalar(select(User).where(User.github_id == github_id))
    if user is None:
        user = User(github_id=github_id, login=login, email=email, avatar_url=avatar_url)
        session.add(user)
    else:
        user.login = login
        user.avatar_url = avatar_url
        if email is not None:
            user.email = email
    await session.flush()
    return user
