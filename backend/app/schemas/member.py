"""Schemas da gestão de membros de um tenant."""

from datetime import datetime

from pydantic import Field

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


class CandidateRead(ReadSchema):
    """Usuário da plataforma que ainda não pertence ao tenant, pronto para ser vinculado."""

    user_id: int
    login: str
    avatar_url: str | None


class MemberAdd(InputSchema):
    """Vínculo de um usuário existente ao tenant, com o papel inicial."""

    user_id: int = Field(gt=0)
    role: MemberRole
