"""Testes unitários do vínculo automático de membros de organizações (sem banco).

O ``MembershipStore`` é substituído por um dublê que segue o mesmo contrato do SQL: só enxerga
tenants com instalação ativa e cria o vínculo apenas quando ele não existe.
"""

from dataclasses import dataclass, field

from app.core.exceptions import GitHubRequestError
from app.models.enums import MemberRole
from app.services.org_membership import (
    DEFAULT_ORG_MEMBER_ROLE,
    TenantRef,
    link_organization_tenants,
)


@dataclass
class _Tenant:
    id: int
    slug: str
    name: str
    attached: bool = True


@dataclass
class FakeStore:
    tenants: list[_Tenant]
    members: dict[tuple[int, int], MemberRole] = field(default_factory=dict)

    async def find_attached_tenants(self, lowercase_names: list[str]) -> list[TenantRef]:
        return [
            TenantRef(id=t.id, slug=t.slug)
            for t in sorted(self.tenants, key=lambda t: t.id)
            if t.attached and t.name.lower() in lowercase_names
        ]

    async def ensure_member(self, tenant_id: int, user_id: int, role: MemberRole) -> bool:
        key = (tenant_id, user_id)
        if key in self.members:
            return False
        self.members[key] = role
        return True


def _orgs(*logins: str):
    async def list_organizations() -> list[str]:
        return list(logins)

    return list_organizations


async def test_member_of_installed_organization_gets_developer_membership() -> None:
    """Quem pertence à organização dona da instalação entra como DEVELOPER no tenant dela."""
    store = FakeStore([_Tenant(id=1, slug="acme", name="Acme")])

    linked = await link_organization_tenants(store, user_id=42, list_organizations=_orgs("Acme"))

    assert store.members == {(1, 42): MemberRole.DEVELOPER}
    assert DEFAULT_ORG_MEMBER_ROLE is MemberRole.DEVELOPER
    assert [(item.slug, item.created) for item in linked] == [("acme", True)]


async def test_user_outside_the_organization_is_not_linked() -> None:
    """Sem pertencer à organização da instalação, nenhum vínculo é criado."""
    store = FakeStore([_Tenant(id=1, slug="acme", name="Acme")])

    linked = await link_organization_tenants(store, user_id=42, list_organizations=_orgs("outra-org"))

    assert store.members == {}
    assert linked == []


async def test_organization_match_ignores_letter_case() -> None:
    """O login da organização e o nome do tenant são comparados sem diferenciar maiúsculas."""
    store = FakeStore([_Tenant(id=1, slug="acme", name="ACME")])

    linked = await link_organization_tenants(store, user_id=7, list_organizations=_orgs("acme"))

    assert [item.slug for item in linked] == ["acme"]
    assert store.members == {(1, 7): MemberRole.DEVELOPER}


async def test_existing_membership_keeps_its_role_and_is_reported_as_not_created() -> None:
    """Um vínculo que já existe nunca é rebaixado nem recriado: o papel atual é preservado."""
    store = FakeStore(
        [_Tenant(id=1, slug="acme", name="Acme")],
        members={(1, 42): MemberRole.OWNER},
    )

    linked = await link_organization_tenants(store, user_id=42, list_organizations=_orgs("Acme"))

    assert store.members == {(1, 42): MemberRole.OWNER}
    assert [(item.slug, item.created) for item in linked] == [("acme", False)]


async def test_detached_tenant_is_not_linked() -> None:
    """Tenant cuja instalação foi removida (sem ``github_installation_id``) não recebe vínculos."""
    store = FakeStore([_Tenant(id=1, slug="acme", name="Acme", attached=False)])

    linked = await link_organization_tenants(store, user_id=42, list_organizations=_orgs("Acme"))

    assert linked == []
    assert store.members == {}


async def test_github_failure_does_not_block_login() -> None:
    """Se o GitHub não devolver as organizações, o login segue sem vínculo e sem exceção."""
    store = FakeStore([_Tenant(id=1, slug="acme", name="Acme")])

    async def failing() -> list[str]:
        raise GitHubRequestError("sem conexão")

    linked = await link_organization_tenants(store, user_id=42, list_organizations=failing)

    assert linked == []
    assert store.members == {}


async def test_user_in_several_organizations_is_linked_to_each_tenant_in_id_order() -> None:
    """Com vários tenants correspondentes, todos são vinculados; o primeiro (menor id) vira o padrão."""
    store = FakeStore(
        [
            _Tenant(id=9, slug="beta", name="Beta"),
            _Tenant(id=3, slug="acme", name="Acme"),
        ]
    )

    linked = await link_organization_tenants(store, user_id=42, list_organizations=_orgs("Beta", "Acme"))

    assert [item.slug for item in linked] == ["acme", "beta"]
    assert len(store.members) == 2
