"""Testes de integração do cadastro automático de repositórios pelos eventos de instalação.

Ponto central: a listagem de repositórios do tenant não depende de existir nenhum PR mergeado.
"""

from typing import Any

import httpx
import pytest
from sqlalchemy import select, update

from app.core.database import get_session_factory
from app.models.repository import Repository
from app.models.tenant import Tenant
from app.models.user import User
from app.tasks.github_events import handle_event
from tests.factories.github import (
    build_installation_event,
    build_installation_repositories_event,
    build_installation_repository,
)
from tests.integration.helpers import count_rows, session_token

pytestmark = pytest.mark.integration

TRACKED = frozenset({"main", "master", "master-tip"})
WEB = build_installation_repository(repo_id=900, full_name="acme/web")
API = build_installation_repository(repo_id=901, full_name="acme/api", private=False)


async def _event(name: str, payload: dict[str, Any]) -> str:
    return await handle_event(
        get_session_factory(),
        tracked_branches=TRACKED,
        event_name=name,
        delivery_id="d",
        payload=payload,
    )


async def _owner_token() -> str:
    async with get_session_factory()() as session:
        user_id = await session.scalar(select(User.id).where(User.github_id == 7001))
    assert user_id is not None
    return session_token(user_id)


async def test_installation_registers_repositories_without_any_pull_request(client: httpx.AsyncClient) -> None:
    """Instalar o App já cadastra os repositórios: aparecem na listagem sem nenhum PR no banco."""
    await _event("installation", build_installation_event(repositories=[WEB, API]))

    assert await count_rows(Repository) == 2

    response = await client.get(
        "/api/v1/tenants/acme/repositories", headers={"Authorization": f"Bearer {await _owner_token()}"}
    )
    assert response.status_code == 200
    assert [repo["full_name"] for repo in response.json()] == ["acme/api", "acme/web"]


async def test_repository_fields_are_derived_from_the_installation_payload(client: httpx.AsyncClient) -> None:
    """Dono, URL e visibilidade vêm do ``full_name``; a branch padrão é o valor inicial ``main``."""
    await _event("installation", build_installation_event(repositories=[WEB]))

    async with get_session_factory()() as session:
        repo = (await session.execute(select(Repository))).scalar_one()
    assert repo.owner_login == "acme"
    assert repo.html_url == "https://github.com/acme/web"
    assert repo.is_private is True
    assert repo.default_branch == "main"


async def test_repeated_installation_delivery_does_not_duplicate_repositories() -> None:
    """A mesma entrega reenviada não duplica repositórios nem tenant."""
    payload = build_installation_event(repositories=[WEB, API])

    await _event("installation", payload)
    await _event("installation", payload)

    assert await count_rows(Repository) == 2
    assert await count_rows(Tenant) == 1


async def test_added_repositories_are_registered(client: httpx.AsyncClient) -> None:
    """Incluir repositórios depois da instalação os cadastra, sem depender de PR."""
    await _event("installation", build_installation_event(repositories=[WEB]))

    outcome = await _event("installation_repositories", build_installation_repositories_event(added=[API]))

    assert outcome == "registered_repositories"
    assert await count_rows(Repository) == 2


async def test_removed_repositories_keep_their_history() -> None:
    """Remover um repositório da instalação não apaga o que já foi importado."""
    await _event("installation", build_installation_event(repositories=[WEB, API]))

    outcome = await _event(
        "installation_repositories",
        build_installation_repositories_event(action="removed", removed=[WEB]),
    )

    assert outcome == "ignored_action"
    assert await count_rows(Repository) == 2


async def test_update_preserves_default_branch_learned_elsewhere() -> None:
    """A branch padrão só vem de fontes completas. Um evento reduzido não a sobrescreve."""
    await _event("installation", build_installation_event(repositories=[WEB]))
    async with get_session_factory()() as session, session.begin():
        await session.execute(update(Repository).values(default_branch="develop"))

    await _event("installation_repositories", build_installation_repositories_event(added=[WEB]))

    async with get_session_factory()() as session:
        branch = await session.scalar(select(Repository.default_branch))
    assert branch == "develop"


async def test_repositories_for_unknown_installation_are_ignored() -> None:
    """Sem tenant para a instalação, nada é cadastrado."""
    outcome = await _event(
        "installation_repositories",
        build_installation_repositories_event(installation_id=99999, added=[WEB]),
    )

    assert outcome == "ignored_unknown_installation"
    assert await count_rows(Repository) == 0
