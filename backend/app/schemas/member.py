"""Schemas da gestão de membros de um tenant."""

from datetime import datetime

from app.models.enums import MemberRole
from app.schemas.base import InputSchema, ReadSchema


class MemberRead(ReadSchema):
    """Membro de um tenant, com o papel dele no tenant."""

    user_id: int
    login: str
    avatar_url: str | None
    role: MemberRole
    joined_at: datetime


class MemberRoleUpdate(InputSchema):
    """Novo papel de um membro. Campos desconhecidos são rejeitados."""

    role: MemberRole
