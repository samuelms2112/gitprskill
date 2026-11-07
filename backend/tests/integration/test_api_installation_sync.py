"""Testes de integração da rota que sincroniza a lista de repositórios pela instalação do App."""

from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

import httpx
import pytest
from sqlalchemy import select, update

from app.api.deps import get_installation_repository_source
from app.core.database import get_session_factory
from app.main import app
from app.models.enums import MemberRole
from app.models.repository import Repository
from app.models.tenant import Tenant
from app.schemas.github import GitHubInstallationRepository
from tests.integration.helpers import (
    add_member,
    create_tenant,
    create_user,
    session_token,
)

pytestmark = pytest.mark.integration

ROUTE = "/api/v1/tenants/acme/repositories/sync-from-github-app"


class FakeInstallationSource:
    """Substitui a consulta à API do GitHub: devolve a lista de repositórios da instalação."""

    def __init__(self, repositories: list[dict[str, Any]]) -> None:
        self._repositories = [GitHubInstallationRepository.model_validate(item) for item in repositories]
        self.installation_ids: list[int] = []

    async def iter_for_installation(self, installation_id: int) -> AsyncIterator[GitHubInstallationRepository]:
        self.installation_ids.append(installation_id)
        for repository in self._repositories:
            yield repository


@pytest.fixture
def source_override() -> Iterator[Callable[[FakeInstallationSource], None]]:
    """Instala a fonte simulada e a remove ao final."""

    def install(fake: FakeInstallationSource) -> None:
        app.dependency_overrides[get_installation_repository_source] = lambda: fake

    yield install
    app.dependency_overrides.pop(get_installation_repository_source, None)


@pytest.fixture
async def members() -> dict[str, Any]:
    tenant_id = await create_tenant(slug="acme", installation_id=111)
    owner = await create_user(github_id=7001, login="ana")
    viewer = await create_user(github_id=7002, login="bruno")
    await add_member(tenant_id=tenant_id, user_id=owner, role=MemberRole.OWNER)
    await add_member(tenant_id=tenant_id, user_id=viewer, role=MemberRole.VIEWER)
    return {"tenant_id": tenant_id, "owner": owner, "viewer": viewer}


def _auth(user_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {session_token(user_id)}"}


REPOSITORIES = [
    {"id": 1001, "name": "web", "full_name": "acme/web", "private": True},
    {"id": 1002, "name": "api", "full_name": "acme/api", "private": False},
]


async def test_registers_all_repositories_the_installation_can_access(
    client: httpx.AsyncClient, members: dict[str, Any], source_override: Callable[[FakeInstallationSource], None]
) -> None:
    """Instalações antigas ganham a lista completa: todos os repositórios cadastrados, sem PR nenhum."""
    source = FakeInstallationSource(REPOSITORIES)
    source_override(source)

    response = await client.post(ROUTE, headers=_auth(members["owner"]))

    assert response.status_code == 200
    assert response.json() == {"synced": 2}
    assert source.installation_ids == [111]  # consultado com a instalação do tenant
    async with get_session_factory()() as session:
        names = (await session.scalars(select(Repository.full_name).order_by(Repository.full_name))).all()
    assert list(names) == ["acme/api", "acme/web"]


async def test_repeated_sync_is_idempotent(
    client: httpx.AsyncClient, members: dict[str, Any], source_override: Callable[[FakeInstallationSource], None]
) -> None:
    """Rodar a sincronização de novo não duplica repositórios."""
    source_override(FakeInstallationSource(REPOSITORIES))

    await client.post(ROUTE, headers=_auth(members["owner"]))
    await client.post(ROUTE, headers=_auth(members["owner"]))

    async with get_session_factory()() as session:
        count = len((await session.scalars(select(Repository))).all())
    assert count == 2


async def test_sync_keeps_a_default_branch_already_known(
    client: httpx.AsyncClient, members: dict[str, Any], source_override: Callable[[FakeInstallationSource], None]
) -> None:
    """Sincronizar não sobrescreve a branch padrão que já foi aprendida de um PR."""
    source_override(FakeInstallationSource(REPOSITORIES))
    await client.post(ROUTE, headers=_auth(members["owner"]))
    async with get_session_factory()() as session, session.begin():
        await session.execute(update(Repository).where(Repository.name == "web").values(default_branch="develop"))

    await client.post(ROUTE, headers=_auth(members["owner"]))

    async with get_session_factory()() as session:
        branch = await session.scalar(select(Repository.default_branch).where(Repository.name == "web"))
    assert branch == "develop"


async def test_viewer_cannot_trigger_the_sync(
    client: httpx.AsyncClient, members: dict[str, Any], source_override: Callable[[FakeInstallationSource], None]
) -> None:
    """Leitor não consulta a API do GitHub nem altera o cadastro."""
    source = FakeInstallationSource(REPOSITORIES)
    source_override(source)

    response = await client.post(ROUTE, headers=_auth(members["viewer"]))

    assert response.status_code == 403
    assert source.installation_ids == []


async def test_tenant_without_installation_is_a_conflict(
    client: httpx.AsyncClient, members: dict[str, Any], source_override: Callable[[FakeInstallationSource], None]
) -> None:
    """Sem instalação ativa não há o que consultar."""
    source = FakeInstallationSource(REPOSITORIES)
    source_override(source)
    async with get_session_factory()() as session, session.begin():
        await session.execute(update(Tenant).where(Tenant.id == members["tenant_id"]).values(github_installation_id=None))

    response = await client.post(ROUTE, headers=_auth(members["owner"]))

    assert response.status_code == 409
    assert source.installation_ids == []
