"""Autenticação como GitHub App: JWT da aplicação e tokens de instalação por tenant.

Fluxo:
    1. Assina um JWT RS256 com a chave privada do App (``iss`` = ``GITHUB_APP_ID``).
    2. Troca o JWT por um token de instalação via ``POST /app/installations/{id}/access_tokens``.
    3. Guarda o token em cache até perto da expiração (1 hora) e o reutiliza.

Cada tenant tem sua própria instalação, então cada chamada ao GitHub usa só o token da
instalação dona do dado. O token global ``GITHUB_TOKEN`` não existe mais.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

import jwt

from app.core.exceptions import GitHubAppNotConfiguredError
from app.core.logging import get_logger
from app.schemas.github import InstallationAccessToken
from app.services.github_client import GitHubClient

logger = get_logger(__name__)

JWT_ALGORITHM = "RS256"
# Tolerância a diferença de relógio entre este servidor e o GitHub.
JWT_BACKDATE_SECONDS = 60
# O GitHub aceita no máximo 10 minutos de validade para o JWT do App.
JWT_LIFETIME_SECONDS = 540
# Renova o token de instalação alguns minutos antes de ele expirar.
REFRESH_MARGIN_SECONDS = 300

ClientFactory = Callable[[str], GitHubClient]
Clock = Callable[[], float]


class GitHubAppAuth:
    """Emite e reutiliza tokens de instalação. Thread-safe dentro de um event loop."""

    def __init__(
        self,
        *,
        app_id: str | None,
        private_key_pem: str | None,
        client_factory: ClientFactory,
        clock: Clock = time.time,
        refresh_margin_seconds: float = REFRESH_MARGIN_SECONDS,
    ) -> None:
        """Valida a configuração e prepara o cache.

        Args:
            app_id: Identificador numérico do GitHub App.
            private_key_pem: Chave privada RSA do App, em PEM.
            client_factory: Cria um ``GitHubClient`` autenticado com o token informado.
            clock: Relógio em epoch segundos (injetável nos testes).
            refresh_margin_seconds: Antecedência para renovar um token de instalação.

        Raises:
            GitHubAppNotConfiguredError: Se o ID ou a chave estiverem ausentes ou inválidos.
        """
        if not app_id or not app_id.isdigit() or not private_key_pem:
            raise GitHubAppNotConfiguredError("GitHub App não configurado (GITHUB_APP_ID/GITHUB_APP_PRIVATE_KEY).")
        self._app_id = app_id
        self._private_key = private_key_pem
        self._client_factory = client_factory
        self._clock = clock
        self._margin = refresh_margin_seconds
        self._cache: dict[int, InstallationAccessToken] = {}
        self._lock = asyncio.Lock()
        # Assinar um JWT de teste na inicialização faz uma chave inválida aparecer já no boot.
        self.create_app_jwt()

    def create_app_jwt(self) -> str:
        """Gera o JWT de aplicação assinado com a chave privada.

        Raises:
            GitHubAppNotConfiguredError: Se a chave privada não puder ser usada para assinar.
        """
        now = int(self._clock())
        claims = {
            "iat": now - JWT_BACKDATE_SECONDS,
            "exp": now + JWT_LIFETIME_SECONDS,
            "iss": self._app_id,
        }
        try:
            return jwt.encode(claims, self._private_key, algorithm=JWT_ALGORITHM)
        except (jwt.PyJWTError, ValueError, TypeError):
            # Sem ``from exc``: a mensagem da biblioteca criptográfica não deve vazar a chave.
            raise GitHubAppNotConfiguredError("Chave privada do GitHub App inválida.") from None

    async def get_installation_access_token(self, installation_id: int) -> InstallationAccessToken:
        """Devolve um token válido para a instalação, usando o cache quando possível.

        Raises:
            GitHubNotFoundError: Instalação inexistente ou removida.
            GitHubAuthenticationError: JWT do App rejeitado pelo GitHub.
        """
        cached = self._valid_cached(installation_id)
        if cached is not None:
            return cached

        async with self._lock:
            # Re-checagem: outra tarefa pode ter renovado o token enquanto esperávamos o lock.
            cached = self._valid_cached(installation_id)
            if cached is not None:
                return cached

            async with self._client_factory(self.create_app_jwt()) as client:
                token = await client.create_installation_access_token(installation_id)
            self._cache[installation_id] = token
            logger.info("Token de instalação emitido", extra={"installation_id": installation_id})
            return token

    def _valid_cached(self, installation_id: int) -> InstallationAccessToken | None:
        token = self._cache.get(installation_id)
        if token is None:
            return None
        if token.expires_at.timestamp() - self._clock() <= self._margin:
            return None
        return token


class GitHubInstallationDiffs:
    """Busca diffs de PRs usando o token da instalação do tenant dono do PR."""

    def __init__(self, auth: GitHubAppAuth, client_factory: ClientFactory) -> None:
        """Associa o buscador ao gerenciador de tokens e à fábrica de clientes."""
        self._auth = auth
        self._client_factory = client_factory

    async def get_diff(self, installation_id: int, owner: str, repo: str, number: int) -> str:
        """Retorna o diff do PR autenticado como a instalação informada.

        Raises:
            GitHubAppNotConfiguredError, GitHubAuthenticationError, GitHubNotFoundError, GitHubError
        """
        token = await self._auth.get_installation_access_token(installation_id)
        async with self._client_factory(token.token) as client:
            return await client.get_pull_request_diff(owner, repo, number)
