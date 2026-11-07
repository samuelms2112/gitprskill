"""Schemas de saída para tenants e vínculos de usuário com eles."""

from app.models.enums import MemberRole
from app.schemas.base import ReadSchema


class TenantMembershipRead(ReadSchema):
    """Tenant do qual o usuário é membro, com o papel dele."""

    slug: str
    name: str
    role: MemberRole
