"""Dependências do FastAPI: autenticação, contexto de tenant e autorização por papel.

Uso típico em uma rota::

    @router.get("/tenants/{tenant_slug}/repositories")
    async def list_repos(ctx: Annotated[TenantContext, Depends(require_role(MemberRole.VIEWER))]):
        ...

Para não revelar a existência de tenants a terceiros, quem não é membro recebe 404,
e não 403.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache
from typing import Annotated

import httpx
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db_session
from app.core.exceptions import (
    AINotConfiguredError,
    AuthenticationError,
    AuthorizationError,
    NotFoundError,
)
from app.core.security import TokenService, TokenValidationError
from app.models.enums import MemberRole
from app.models.tenant import Tenant
from app.models.tenant_member import TenantMember
from app.models.user import User
from app.services.ai.base import AIProvider
from app.services.ai.factory import open_ai_services
from app.services.github_app_auth import GitHubAppAuth
from app.services.github_client import GitHubClient
from app.services.github_oauth import GitHubOAuthService
from app.services.installation_repositories import (
    GitHubInstallationRepositories,
    InstallationRepositorySource,
)

OAUTH_HTTP_TIMEOUT = 10.0
_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class TenantContext:
    """Tenant solicitado e o papel do usuário autenticado nele."""

    tenant: Tenant
    role: MemberRole


@lru_cache
def get_token_service() -> TokenService:
    """Serviço de tokens configurado com as settings da aplicação (uma instância)."""
    settings = get_settings()
    return TokenService(
        secret=settings.jwt_secret_key.get_secret_value(),
        access_token_ttl=timedelta(minutes=settings.jwt_access_token_ttl_minutes),
        oauth_state_ttl=timedelta(minutes=settings.oauth_state_ttl_minutes),
    )


async def get_github_oauth_service() -> AsyncIterator[GitHubOAuthService]:
    """Serviço OAuth com um cliente HTTP por requisição, fechado ao final."""
    settings = get_settings()
    secret = settings.github_oauth_client_secret

    def api_client_factory(token: str) -> GitHubClient:
        return GitHubClient(
            base_url=settings.github_api_base_url,
            token=token,
            timeout=OAUTH_HTTP_TIMEOUT,
        )

    async with httpx.AsyncClient(timeout=OAUTH_HTTP_TIMEOUT) as http:
        yield GitHubOAuthService(
            client_id=settings.github_oauth_client_id,
            client_secret=secret,
            redirect_uri=settings.github_oauth_redirect_uri,
            scopes=settings.github_oauth_scopes,
            http_client=http,
            api_client_factory=api_client_factory,
        )


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    tokens: Annotated[TokenService, Depends(get_token_service)],
) -> User:
    """Autentica a requisição pelo token ``Bearer`` e devolve o usuário.

    Raises:
        AuthenticationError: Token ausente, inválido, expirado ou de usuário inexistente.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError("Token de acesso ausente.")
    try:
        claims = tokens.decode_access_token(credentials.credentials)
    except TokenValidationError as exc:
        raise AuthenticationError("Token de acesso inválido ou expirado.") from exc

    user = await session.get(User, claims.user_id)
    if user is None:
        raise AuthenticationError("Usuário não encontrado.")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def resolve_tenant_context(
    session: AsyncSession, user: User, tenant_slug: str
) -> TenantContext:
    """Resolve um tenant pelo slug, exigindo que ``user`` seja membro.

    Raises:
        NotFoundError: Tenant inexistente ou o usuário não é membro (sem distinção).
    """
    row = (
        await session.execute(
            select(Tenant, TenantMember.role)
            .join(TenantMember, TenantMember.tenant_id == Tenant.id)
            .where(Tenant.slug == tenant_slug, TenantMember.user_id == user.id)
        )
    ).one_or_none()
    if row is None:
        raise NotFoundError("Tenant não encontrado.")
    tenant, role = row
    return TenantContext(tenant=tenant, role=role)


async def get_current_tenant(
    tenant_slug: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TenantContext:
    """Resolve o tenant informado no caminho da rota (``/tenants/{tenant_slug}/...``)."""
    return await resolve_tenant_context(session, user, tenant_slug)


@lru_cache
def get_github_app_auth() -> GitHubAppAuth:
    """Autenticação do GitHub App, criada uma única vez: o cache de tokens precisa persistir.

    Raises:
        GitHubAppNotConfiguredError: Quando ``GITHUB_APP_ID`` ou a chave privada faltam.
    """
    settings = get_settings()
    private_key = settings.github_app_private_key
    return GitHubAppAuth(
        app_id=settings.github_app_id,
        private_key_pem=private_key.get_secret_value() if private_key else None,
        client_factory=lambda token: GitHubClient(
            base_url=settings.github_api_base_url,
            token=token,
            timeout=settings.github_request_timeout_seconds,
        ),
    )


def get_installation_repository_source() -> InstallationRepositorySource:
    """Fonte da lista de repositórios de uma instalação (substituível nos testes)."""
    settings = get_settings()
    return GitHubInstallationRepositories(
        get_github_app_auth(),
        lambda token: GitHubClient(
            base_url=settings.github_api_base_url,
            token=token,
            timeout=settings.github_request_timeout_seconds,
        ),
    )


async def get_ai_service() -> AsyncIterator[AIProvider | None]:
    """Provedor de IA configurado (Gemini ou conselho local), ou ``None`` se não houver IA.

    Não lança exceção aqui de propósito: o FastAPI resolve dependências antes de validar
    o corpo, e um erro de configuração mascararia erros de validação do pedido. Quem usa
    a IA deve tratar ``None`` depois da validação (ver ``require_ai``).
    """
    settings = get_settings()
    if not settings.ai_configured:
        yield None
        return
    async with open_ai_services(settings) as services:
        yield services.provider


def require_ai(ai: AIProvider | None) -> AIProvider:
    """Garante que a IA está disponível para o uso corrente.

    Raises:
        AINotConfiguredError: Quando ``GEMINI_API_KEY`` não está configurada.
    """
    if ai is None:
        raise AINotConfiguredError("Integração com IA não configurada no servidor.")
    return ai


def require_role(minimum: MemberRole) -> Callable[..., Awaitable[TenantContext]]:
    """Fábrica de dependências que exige um papel mínimo no tenant da rota.

    Raises:
        AuthorizationError: Quando o papel do usuário é inferior ao mínimo.
    """

    async def _dependency(
        context: Annotated[TenantContext, Depends(get_current_tenant)],
    ) -> TenantContext:
        if not context.role.includes(minimum):
            raise AuthorizationError("Permissão insuficiente para esta operação.")
        return context

    return _dependency
