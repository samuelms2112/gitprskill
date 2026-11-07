"""Cliente assíncrono para a REST API do GitHub, baseado em ``httpx``.

Responsabilidades:
    * Autenticação por token e cabeçalhos da versão da API.
    * Paginação via cabeçalho ``Link`` (``rel="next"``).
    * Tratamento de rate limit primário (``X-RateLimit-Reset``) e secundário
      (``Retry-After``), com espera automática dentro de um limite configurável.
    * Pausa preventiva quando a cota restante está baixa.
    * Retentativas com backoff exponencial para erros de rede e HTTP 5xx.

``sleep`` e ``clock`` são injetáveis, o que permite testar as esperas sem atrasar
a suíte e simular cabeçalhos de cota com instantes controlados.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import aclosing
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, Literal, Self

import httpx
from pydantic import ValidationError

from app.core.exceptions import (
    GitHubApiError,
    GitHubAuthenticationError,
    GitHubNotFoundError,
    GitHubRateLimitError,
    GitHubRequestError,
    GitHubResponseError,
)
from app.core.logging import get_logger
from app.schemas.github import (
    GitHubInstallationRepository,
    GitHubPullRequest,
    GitHubRepository,
    GitHubUserProfile,
    InstallationAccessToken,
)

logger = get_logger(__name__)

GITHUB_API_VERSION = "2022-11-28"
ACCEPT_HEADER = "application/vnd.github+json"
DIFF_ACCEPT_HEADER = "application/vnd.github.diff"
USER_AGENT = "github-management-platform/0.1"
PAGE_SIZE = 100
# Espera padrão quando o GitHub limita sem informar quanto tempo aguardar.
DEFAULT_SECONDARY_BACKOFF_SECONDS = 60.0
MAX_BACKOFF_SECONDS = 30.0
# Quantidade de requisições restantes abaixo da qual a pausa preventiva é ativada.
LOW_QUOTA_THRESHOLD = 10

# Nomes de owner/repo/branch usados em caminhos de URL: evita path traversal.
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9_.\-/]+$")

SleepFn = Callable[[float], Awaitable[None]]
ClockFn = Callable[[], float]


class GitHubClient:
    """Cliente da REST API do GitHub. Use como context manager para fechar a conexão."""

    def __init__(
        self,
        *,
        base_url: str = "https://api.github.com",
        token: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 10.0,
        max_retries: int = 3,
        max_rate_limit_wait: float = 900.0,
        sleep: SleepFn = asyncio.sleep,
        clock: ClockFn = time.time,
    ) -> None:
        """Configura o cliente.

        Args:
            base_url: URL base da API. Ignorada se ``http_client`` for informado.
            token: Token de acesso pessoal ou de instalação. Nunca é registrado em log.
            http_client: Cliente httpx externo (usado nos testes com ``MockTransport``).
            timeout: Timeout em segundos de cada requisição.
            max_retries: Número máximo de novas tentativas por requisição.
            max_rate_limit_wait: Espera máxima aceitável por limite de cota, em segundos.
            sleep: Função de espera assíncrona.
            clock: Função que retorna o instante atual em epoch segundos.
        """
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(base_url=base_url, timeout=timeout)
        self._token = token
        self._max_retries = max_retries
        self._max_rate_limit_wait = max_rate_limit_wait
        self._sleep = sleep
        self._clock = clock
        self._quota_remaining: int | None = None
        self._quota_reset: float | None = None

    async def __aenter__(self) -> Self:
        """Permite uso em ``async with``."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Fecha o cliente HTTP somente se ele foi criado por esta instância."""
        await self.aclose()

    async def aclose(self) -> None:
        """Libera as conexões do cliente HTTP interno."""
        if self._owns_client:
            await self._http.aclose()

    # --- Endpoints públicos ---------------------------------------------------------

    async def get_pull_request(self, owner: str, repo: str, number: int) -> GitHubPullRequest:
        """Busca um PR específico, incluindo estatísticas de linhas alteradas.

        Raises:
            GitHubNotFoundError: Quando o PR não existe ou não é visível.
            GitHubResponseError: Quando a resposta não corresponde ao schema esperado.
        """
        path = f"/repos/{_segment(owner)}/{_segment(repo)}/pulls/{number}"
        response = await self._request("GET", path)
        return _parse_pull_request(response.json())

    async def create_installation_access_token(self, installation_id: int) -> InstallationAccessToken:
        """Troca o JWT do GitHub App por um token de instalação.

        Deve ser chamado com um cliente autenticado pelo JWT do App (não por um token de usuário).

        Raises:
            GitHubNotFoundError: Quando a instalação não existe ou foi removida.
            GitHubAuthenticationError: Quando o JWT do App é rejeitado.
            GitHubResponseError: Quando a resposta não corresponde ao schema esperado.
        """
        if installation_id <= 0:
            raise ValueError("installation_id deve ser positivo.")
        response = await self._request("POST", f"/app/installations/{installation_id}/access_tokens")
        try:
            return InstallationAccessToken.model_validate(response.json())
        except ValidationError as exc:
            raise GitHubResponseError("Token de instalação fora do formato esperado.") from exc

    async def get_pull_request_diff(self, owner: str, repo: str, number: int) -> str:
        """Retorna o diff unificado do PR (``Accept: application/vnd.github.diff``).

        Raises:
            GitHubNotFoundError: Quando o PR não existe ou não é visível.
            GitHubApiError: Para outros erros da API (ex.: diff grande demais).
        """
        path = f"/repos/{_segment(owner)}/{_segment(repo)}/pulls/{number}"
        response = await self._request("GET", path, accept=DIFF_ACCEPT_HEADER)
        return response.text

    async def get_authenticated_user(self) -> GitHubUserProfile:
        """Retorna o perfil do usuário dono do token (``GET /user``).

        Raises:
            GitHubAuthenticationError: Quando o token é inválido.
            GitHubResponseError: Quando a resposta não corresponde ao schema esperado.
        """
        response = await self._request("GET", "/user")
        try:
            return GitHubUserProfile.model_validate(response.json())
        except ValidationError as exc:
            raise GitHubResponseError("Perfil do GitHub fora do formato esperado.") from exc

    async def iter_installation_repositories(self) -> AsyncIterator[GitHubInstallationRepository]:
        """Todos os repositórios que a instalação do App pode acessar (``GET /installation/repositories``).

        Requer um cliente autenticado com o token de instalação (não com o JWT do App).
        A resposta é um objeto ``{"total_count", "repositories": [...]}``, paginado via ``Link``.
        """
        response = await self._request(
            "GET", "/installation/repositories", params={"per_page": PAGE_SIZE}
        )
        while True:
            page = response.json()
            repositories = page.get("repositories") if isinstance(page, dict) else None
            if not isinstance(repositories, list):
                raise GitHubResponseError("Lista de repositórios da instalação fora do formato esperado.")
            for item in repositories:
                try:
                    yield GitHubInstallationRepository.model_validate(item)
                except ValidationError as exc:
                    raise GitHubResponseError("Repositório da instalação fora do formato esperado.") from exc
            next_url = response.links.get("next", {}).get("url")
            if not next_url:
                return
            response = await self._request("GET", next_url)

    async def get_repository(self, owner: str, repo: str) -> GitHubRepository:
        """Dados do repositório (usados pelo backfill para gravar o repositório).

        Raises:
            GitHubNotFoundError: Repositório inexistente ou sem acesso para a instalação.
            GitHubResponseError: Resposta fora do schema esperado.
        """
        response = await self._request("GET", f"/repos/{_segment(owner)}/{_segment(repo)}")
        try:
            return GitHubRepository.model_validate(response.json())
        except ValidationError as exc:
            raise GitHubResponseError("Repositório do GitHub fora do formato esperado.") from exc

    async def iter_pull_requests(
        self,
        owner: str,
        repo: str,
        *,
        state: Literal["open", "closed", "all"] = "all",
        updated_since: datetime | None = None,
    ) -> AsyncIterator[GitHubPullRequest]:
        """Itera sobre os PRs do repositório (abertos, fechados ou todos), do mais recente ao mais antigo.

        Não filtra por branch nem por merge: o chamador decide. A paginação para quando
        um PR é mais antigo que ``updated_since``.
        """
        path = f"/repos/{_segment(owner)}/{_segment(repo)}/pulls"
        params: dict[str, Any] = {
            "state": state,
            "sort": "updated",
            "direction": "desc",
            "per_page": PAGE_SIZE,
        }
        async with aclosing(self._iter_pages(path, params)) as pages:
            async for page in pages:
                for item in page:
                    pull_request = _parse_pull_request(item)
                    if updated_since is not None and pull_request.updated_at < updated_since:
                        return
                    yield pull_request

    async def list_merged_pull_requests(
        self,
        owner: str,
        repo: str,
        base_branch: str,
        *,
        updated_since: datetime | None = None,
    ) -> AsyncIterator[GitHubPullRequest]:
        """Itera sobre os PRs mergeados em ``base_branch``, do mais recente para o mais antigo.

        A listagem da API não inclui estatísticas (``additions`` etc.). Para isso, use
        ``get_pull_request``. A paginação para assim que um PR é mais antigo que
        ``updated_since``, pois a ordenação é por data de atualização decrescente.

        Args:
            owner: Proprietário do repositório.
            repo: Nome do repositório.
            base_branch: Branch de destino, por exemplo ``main``.
            updated_since: Instante mínimo de atualização (timezone-aware) a considerar.

        Yields:
            PRs cujo ``merged_at`` está preenchido.
        """
        path = f"/repos/{_segment(owner)}/{_segment(repo)}/pulls"
        params: dict[str, Any] = {
            "state": "closed",
            "base": _segment(base_branch),
            "sort": "updated",
            "direction": "desc",
            "per_page": PAGE_SIZE,
        }
        async with aclosing(self._iter_pages(path, params)) as pages:
            async for page in pages:
                for item in page:
                    pull_request = _parse_pull_request(item)
                    if updated_since is not None and pull_request.updated_at < updated_since:
                        return
                    if pull_request.is_merged:
                        yield pull_request

    # --- Infraestrutura interna -----------------------------------------------------

    async def _iter_pages(
        self, path: str, params: dict[str, Any]
    ) -> AsyncIterator[list[dict[str, Any]]]:
        """Percorre todas as páginas seguindo o link ``rel="next"`` do cabeçalho ``Link``."""
        response = await self._request("GET", path, params=params)
        while True:
            page = response.json()
            if not isinstance(page, list):
                raise GitHubResponseError("A listagem do GitHub não retornou uma lista.")
            yield page

            next_url = response.links.get("next", {}).get("url")
            if not next_url:
                return
            response = await self._request("GET", next_url)

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        accept: str = ACCEPT_HEADER,
    ) -> httpx.Response:
        """Executa uma requisição com retentativas, controle de cota e mapeamento de erros.

        Raises:
            GitHubRequestError: Falha de rede persistente.
            GitHubRateLimitError: Cota esgotada com espera acima do limite configurado.
            GitHubAuthenticationError: Credenciais inválidas (HTTP 401).
            GitHubNotFoundError: Recurso inexistente (HTTP 404).
            GitHubApiError: Outros erros HTTP persistentes.
        """
        attempt = 0
        while True:
            attempt += 1
            await self._respect_low_quota()

            try:
                response = await self._http.request(
                    method, url, params=params, headers=self._build_headers(accept)
                )
            except httpx.TransportError as exc:
                if attempt > self._max_retries:
                    logger.error("Falha de rede ao acessar o GitHub", extra={"attempt": attempt})
                    raise GitHubRequestError(
                        f"Falha de rede ao acessar o GitHub ({exc.__class__.__name__})."
                    ) from exc
                await self._sleep(_backoff_seconds(attempt))
                continue

            self._record_quota(response)
            if response.is_success:
                return response

            if _is_rate_limited(response):
                wait = self._rate_limit_wait(response)
                if attempt > self._max_retries or wait > self._max_rate_limit_wait:
                    logger.warning("Limite de requisições do GitHub atingido", extra={"wait": wait})
                    raise GitHubRateLimitError(reset_at=self._reset_at(response))
                logger.info("Aguardando renovação da cota do GitHub", extra={"wait": wait})
                await self._sleep(wait)
                continue

            if response.status_code == 401:
                raise GitHubAuthenticationError("Credenciais do GitHub inválidas ou expiradas.")
            if response.status_code == 404:
                raise GitHubNotFoundError("Recurso do GitHub não encontrado ou sem acesso.")
            if response.status_code >= 500 and attempt <= self._max_retries:
                await self._sleep(_backoff_seconds(attempt))
                continue

            raise GitHubApiError(response.status_code, _summarize_error(response))

    def _build_headers(self, accept: str = ACCEPT_HEADER) -> dict[str, str]:
        """Cabeçalhos padrão. O token é adicionado somente quando configurado."""
        headers = {
            "Accept": accept,
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
            "User-Agent": USER_AGENT,
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _record_quota(self, response: httpx.Response) -> None:
        """Guarda a cota restante e o instante de renovação para pausas preventivas."""
        remaining = response.headers.get("X-RateLimit-Remaining")
        reset = response.headers.get("X-RateLimit-Reset")
        if remaining is not None and reset is not None:
            try:
                self._quota_remaining = int(remaining)
                self._quota_reset = float(reset)
            except ValueError:
                self._quota_remaining = None
                self._quota_reset = None

    async def _respect_low_quota(self) -> None:
        """Pausa até a renovação da cota quando ela está perto de esgotar."""
        if self._quota_remaining is None or self._quota_reset is None:
            return
        if self._quota_remaining > LOW_QUOTA_THRESHOLD:
            return
        wait = min(max(self._quota_reset - self._clock(), 0.0), self._max_rate_limit_wait)
        if wait > 0:
            logger.info("Cota do GitHub baixa; pausa preventiva", extra={"wait": wait})
            await self._sleep(wait)
        self._quota_remaining = None
        self._quota_reset = None

    def _rate_limit_wait(self, response: httpx.Response) -> float:
        """Calcula quantos segundos aguardar antes de tentar novamente."""
        if response.headers.get("X-RateLimit-Remaining") == "0":
            reset = response.headers.get("X-RateLimit-Reset")
            if reset is not None:
                try:
                    return max(float(reset) - self._clock(), 0.0) + 1.0
                except ValueError:
                    pass
        retry_after = response.headers.get("Retry-After")
        if retry_after is not None:
            try:
                return max(float(retry_after), 0.0)
            except ValueError:
                pass
        return DEFAULT_SECONDARY_BACKOFF_SECONDS

    def _reset_at(self, response: httpx.Response) -> datetime | None:
        """Converte ``X-RateLimit-Reset`` em datetime UTC, se o cabeçalho existir."""
        reset = response.headers.get("X-RateLimit-Reset")
        if reset is None:
            return None
        try:
            return datetime.fromtimestamp(float(reset), tz=UTC)
        except ValueError:
            return None


# --- Funções auxiliares puras ---------------------------------------------------------


def _segment(value: str) -> str:
    """Valida um segmento de caminho (owner, repo ou branch) antes de montar a URL.

    Raises:
        ValueError: Se o valor contiver caracteres inseguros ou estiver vazio.
    """
    if not value or not _SAFE_SEGMENT.fullmatch(value) or ".." in value.split("/"):
        raise ValueError(f"Segmento de URL inválido: {value!r}")
    return value


def _is_rate_limited(response: httpx.Response) -> bool:
    """Identifica limites primários (HTTP 403 com cota zerada) e secundários (429 ou Retry-After)."""
    if response.status_code == 429:
        return True
    if response.status_code == 403:
        return (
            response.headers.get("X-RateLimit-Remaining") == "0"
            or "Retry-After" in response.headers
        )
    return False


def _backoff_seconds(attempt: int) -> float:
    """Backoff exponencial limitado: 0,5s, 1s, 2s, ... até ``MAX_BACKOFF_SECONDS``."""
    return min(0.5 * (2 ** (attempt - 1)), MAX_BACKOFF_SECONDS)


def _summarize_error(response: httpx.Response) -> str:
    """Extrai apenas a mensagem do corpo de erro, sem cabeçalhos nem credenciais."""
    try:
        message = response.json().get("message")
    except (ValueError, AttributeError):
        message = None
    if isinstance(message, str) and message:
        return f"GitHub retornou HTTP {response.status_code}: {message[:200]}"
    return f"GitHub retornou HTTP {response.status_code}."


def _parse_pull_request(data: Any) -> GitHubPullRequest:
    """Converte um item JSON do GitHub em ``GitHubPullRequest`` validado.

    Raises:
        GitHubResponseError: Se o item não corresponde ao schema esperado.
    """
    try:
        return GitHubPullRequest.model_validate(data)
    except ValidationError as exc:
        logger.error("Payload de PR do GitHub fora do schema esperado")
        raise GitHubResponseError("Resposta do GitHub fora do formato esperado.") from exc
