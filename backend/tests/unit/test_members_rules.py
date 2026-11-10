"""Testes unitários das regras de gestão de membros (sem banco e sem HTTP)."""

import pytest
from pydantic import ValidationError

from app.api.v1.members import ensure_tenant_keeps_an_owner
from app.core.exceptions import ConflictError
from app.models.enums import MemberRole
from app.schemas.member import MemberRoleUpdate


def test_last_owner_cannot_be_demoted_or_removed() -> None:
    """Sem outro OWNER no tenant, o último dono não pode sair do papel."""
    with pytest.raises(ConflictError):
        ensure_tenant_keeps_an_owner(MemberRole.OWNER, other_owner_count=0)


def test_owner_can_leave_when_another_owner_exists() -> None:
    """Havendo outro OWNER, o dono pode ser rebaixado ou removido."""
    ensure_tenant_keeps_an_owner(MemberRole.OWNER, other_owner_count=1)


def test_non_owner_changes_never_hit_the_owner_rule() -> None:
    """Membros que não são OWNER podem mudar de papel mesmo sem outro dono."""
    ensure_tenant_keeps_an_owner(MemberRole.DEVELOPER, other_owner_count=0)
    ensure_tenant_keeps_an_owner(MemberRole.VIEWER, other_owner_count=0)


def test_role_update_accepts_known_roles() -> None:
    assert MemberRoleUpdate(role="DEVELOPER").role is MemberRole.DEVELOPER


def test_role_update_rejects_unknown_role() -> None:
    with pytest.raises(ValidationError):
        MemberRoleUpdate(role="ADMIN")


def test_role_update_rejects_unknown_fields() -> None:
    """Campos extras (ex.: tentativa de mudar outro tenant) são recusados."""
    with pytest.raises(ValidationError):
        MemberRoleUpdate(role="VIEWER", tenant_id=2)
