"""Schemas de saída para usuários autenticados."""

from pydantic import EmailStr

from app.schemas.base import ReadSchema


class UserRead(ReadSchema):
    """Representação pública do usuário autenticado."""

    id: int
    github_id: int
    login: str
    email: EmailStr | None
    avatar_url: str | None
