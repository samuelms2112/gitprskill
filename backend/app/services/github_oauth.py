"""Fluxo de login OAuth 2.0 com o GitHub (authorization code).

Etapas:
    1. ``build_authorize_url`` monta a URL de autorização com um ``state`` assinado (anti-CSRF).
    2. O GitHub redireciona de volta com ``code``.
    3. ``complete_login`` troca o ``code`` pelo token de acesso e busca o perfil em ``/user``.

O token do GitHub é usado apenas nesta chamada e não é persistido.
"""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlencode

import httpx
from pydantic import SecretStr

from app.core.exceptions import OAuthError, OAuthNotConfiguredError
from app.core.logging import get_logger
from app.schemas.github import GitHubUserProfile
from app.services.github_client import GitHubClient

logger = get_logger(__name__)

AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"

ApiClientFactory = Callable[[str], GitHubClient]


class GitHubOAuthService:
    """Serviço do login OAuth. ``http_client`` fala com github.com; a API usa ``api_client_factory``."""

    def __init__(
        self,
        *,
        client_id: str | None,
        client_secret: SecretStr | None,
        redirect_uri: str | None,
        scopes: str,
        http_client: httpx.AsyncClient,
        api_client_factory: ApiClientFactory,
    ) -> None:
        """Injeta credenciais e dependências de rede."""
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._scopes = scopes
        self._http = http_client
        self._api_client_factory = api_client_factory

    def build_authorize_url(self, state: str) -> str:
        """Gera a URL para a qual o navegador do usuário deve ser redirecionado.

        Raises:
            OAuthNotConfiguredError: Se ``client_id`` ou ``redirect_uri`` não estiverem configurados.
        """
        client_id, redirect_uri = self._require_configured()
        query = urlencode(
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "scope": self._scopes,
                "state": state,
                "allow_signup": "true",
            }
        )
        return f"{AUTHORIZE_URL}?{query}"

    async def complete_login(self, code: str) -> GitHubUserProfile:
        """Troca o ``code`` por um token e devolve o perfil do usuário autenticado.

        Raises:
            OAuthError: Código rejeitado ou falha de comunicação com o GitHub.
        """
        access_token = await self.exchange_code(code)
        return await self.fetch_profile(access_token)

    async def fetch_profile(self, access_token: str) -> GitHubUserProfile:
        """Perfil do dono do token (``GET /user``)."""
        async with self._api_client_factory(access_token) as api:
            return await api.get_authenticated_user()

    async def list_organizations(self, access_token: str) -> list[str]:
        """Logins das organizações do dono do token. Requer o escopo ``read:org``.

        Raises:
            GitHubError: Falha ao consultar o GitHub (o chamador decide se segue sem a lista).
        """
        async with self._api_client_factory(access_token) as api:
            return await api.list_organization_logins()

    async def exchange_code(self, code: str) -> str:
        """Troca o ``code`` do callback pelo token de acesso do usuário.

        Raises:
            OAuthError: Código rejeitado ou falha de comunicação com o GitHub.
        """
        return await self._exchange_code(code)

    async def _exchange_code(self, code: str) -> str:
        client_id, redirect_uri = self._require_configured()
        if self._client_secret is None:
            raise OAuthNotConfiguredError("Segredo do GitHub OAuth não configurado.")

        form = {
            "client_id": client_id,
            "client_secret": self._client_secret.get_secret_value(),
            "code": code,
            "redirect_uri": redirect_uri,
        }
        try:
            response = await self._http.post(
                TOKEN_URL, data=form, headers={"Accept": "application/json"}
            )
        except httpx.TransportError as exc:
            logger.error("Falha de rede na troca de código OAuth")
            raise OAuthError("Não foi possível contatar o GitHub para concluir o login.") from exc

        if not response.is_success:
            raise OAuthError(f"GitHub retornou HTTP {response.status_code} na troca de código.")

        try:
            body = response.json()
        except ValueError as exc:
            raise OAuthError("Resposta inválida do GitHub na troca de código.") from exc

        token = body.get("access_token") if isinstance(body, dict) else None
        if not isinstance(token, str) or not token:
            reason = body.get("error", "desconhecido") if isinstance(body, dict) else "desconhecido"
            raise OAuthError(f"Código OAuth rejeitado pelo GitHub ({reason}).")
        return token

    def _require_configured(self) -> tuple[str, str]:
        if not self._client_id or not self._redirect_uri:
            raise OAuthNotConfiguredError("Login com GitHub não configurado no servidor.")
        return self._client_id, self._redirect_uri
