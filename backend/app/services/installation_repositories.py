"""Sincronização da lista de repositórios direto da API da instalação do GitHub App.

Resolve instalações antigas: quando o App foi instalado antes do cadastro automático existir,
os eventos de instalação nunca trouxeram os repositórios. Esta rota pergunta ao próprio GitHub
quais repositórios a instalação pode acessar e cadastra todos (com o mesmo cadastro idempotente
dos eventos).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.github import GitHubInstallationRepository
from app.services.github_app_auth import GitHubAppAuth
from app.services.github_client import GitHubClient
from app.services.repository_catalog import register_repositories


class InstallationRepositorySource(Protocol):
    """Fonte da lista de repositórios de uma instalação (implementada pela API do GitHub)."""

    def iter_for_installation(self, installation_id: int) -> AsyncIterator[GitHubInstallationRepository]: ...


class GitHubInstallationRepositories:
    """Busca a lista usando o token de instalação do tenant, nunca um token global."""

    def __init__(self, auth: GitHubAppAuth, client_factory: Callable[[str], GitHubClient]) -> None:
        self._auth = auth
        self._client_factory = client_factory

    async def iter_for_installation(self, installation_id: int) -> AsyncIterator[GitHubInstallationRepository]:
        token = await self._auth.get_installation_access_token(installation_id)
        async with self._client_factory(token.token) as client:
            async for repository in client.iter_installation_repositories():
                yield repository


async def sync_installation_repositories(
    session: AsyncSession,
    *,
    tenant_id: int,
    installation_id: int,
    source: InstallationRepositorySource,
) -> int:
    """Cadastra/atualiza todos os repositórios da instalação. Devolve quantos foram processados.

    Repositórios que deixaram de ser acessíveis não são apagados: o histórico é preservado.

    Raises:
        GitHubError: Falha ao consultar o GitHub (token, instalação removida, rede).
        InvalidPayloadError: Algum repositório retornado não é um ``owner/repo`` válido.
    """
    repositories = [repository async for repository in source.iter_for_installation(installation_id)]
    return await register_repositories(session, tenant_id, repositories)
