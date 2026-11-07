"""Testes unitários da listagem de repositórios da instalação: formato e paginação."""

import httpx
import pytest

from app.core.exceptions import GitHubResponseError
from app.services.github_client import GitHubClient

BASE = "https://api.github.com"


def _repo(repo_id: int, name: str) -> dict[str, object]:
    return {"id": repo_id, "name": name, "full_name": f"acme/{name}", "private": False, "extra": "ignorado"}


async def test_follows_link_pages_and_collects_every_repository() -> None:
    """A resposta é ``{repositories: [...]}``; a paginação via ``Link`` traz todas as páginas."""
    second = f"{BASE}/installation/repositories?page=2"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page") == "2":
            return httpx.Response(200, json={"total_count": 3, "repositories": [_repo(3, "c")]})
        return httpx.Response(
            200,
            json={"total_count": 3, "repositories": [_repo(1, "a"), _repo(2, "b")]},
            headers={"Link": f'<{second}>; rel="next"'},
        )

    client = GitHubClient(http_client=httpx.AsyncClient(base_url=BASE, transport=httpx.MockTransport(handler)), token="t")
    async with client:
        names = [repo.name async for repo in client.iter_installation_repositories()]

    assert names == ["a", "b", "c"]


async def test_unexpected_shape_is_rejected() -> None:
    """Resposta sem a chave ``repositories`` é tratada como falha da integração, não como lista vazia."""
    client = GitHubClient(
        http_client=httpx.AsyncClient(
            base_url=BASE, transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[1, 2]))
        ),
        token="t",
    )
    async with client:
        with pytest.raises(GitHubResponseError):
            async for _ in client.iter_installation_repositories():
                pass


async def test_empty_installation_yields_nothing() -> None:
    """Instalação sem repositórios acessíveis retorna lista vazia sem erro."""
    client = GitHubClient(
        http_client=httpx.AsyncClient(
            base_url=BASE,
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"total_count": 0, "repositories": []})),
        ),
        token="t",
    )
    async with client:
        assert [repo async for repo in client.iter_installation_repositories()] == []
