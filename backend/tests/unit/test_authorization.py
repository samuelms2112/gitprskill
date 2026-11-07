"""Testes unitários da hierarquia de papéis e da dependência ``require_role``."""

import pytest

from app.api.deps import TenantContext, require_role
from app.core.exceptions import AuthorizationError
from app.models.enums import MemberRole
from app.models.tenant import Tenant


@pytest.mark.parametrize(
    ("role", "required", "allowed"),
    [
        (MemberRole.OWNER, MemberRole.OWNER, True),
        (MemberRole.OWNER, MemberRole.VIEWER, True),
        (MemberRole.DEVELOPER, MemberRole.OWNER, False),
        (MemberRole.DEVELOPER, MemberRole.DEVELOPER, True),
        (MemberRole.VIEWER, MemberRole.DEVELOPER, False),
        (MemberRole.VIEWER, MemberRole.VIEWER, True),
    ],
)
def test_role_hierarchy(role: MemberRole, required: MemberRole, allowed: bool) -> None:
    """OWNER > DEVELOPER > VIEWER: um papel atende ao mínimo quando não é inferior a ele."""
    assert role.includes(required) is allowed


async def test_require_role_rejects_insufficient_role() -> None:
    """VIEWER não passa por uma dependência que exige DEVELOPER."""
    context = TenantContext(tenant=Tenant(name="Acme", slug="acme"), role=MemberRole.VIEWER)

    with pytest.raises(AuthorizationError):
        await require_role(MemberRole.DEVELOPER)(context)


async def test_require_role_accepts_sufficient_role() -> None:
    """OWNER passa por uma dependência que exige DEVELOPER e recebe o próprio contexto."""
    context = TenantContext(tenant=Tenant(name="Acme", slug="acme"), role=MemberRole.OWNER)

    assert await require_role(MemberRole.DEVELOPER)(context) is context
