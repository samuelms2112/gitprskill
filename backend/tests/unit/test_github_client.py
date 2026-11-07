"""Testes unitários do cliente GitHub com ``httpx.MockTransport`` (sem rede real)."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from app.core.exceptions import (
    GitHubApiError,
    GitHubAuthenticationError,
    GitHubNotFoundError,
    GitHubRateLimitError,
    GitHubRequestError,
    GitHubResponseError,
)
from app.services.github_client import GitHubClient
from tests.factories.github import build_pull_request

BASE_URL = "https://api.github.com"
NOW = 1_767_000_000.0  # instante fixo para o relógio injetado
TOKEN = "ghp_token_super_secreto"

Handler = Callable[[httpx.Request], httpx.Response]


class FakeClock:
    """Relógio controlável; ``sleep`` apenas registra as esperas, sem bloquear."""

    def __init__(self) -> None:
        self.now = NOW
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _client(handler: Handler, clock: FakeClock, **kwargs: Any) -> GitHubClient:
    """Cliente apontando para um transporte falso."""
    http = httpx.AsyncClient(
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
    )
    return GitHubClient(
        http_client=http,
        token=kwargs.pop("token", TOKEN),
        sleep=clock.sleep,
        clock=clock.clock,
        **kwargs,
    )


def _json(data: Any, status: int = 200, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, json=data, headers=headers)


async def test_get_pull_request_parses_payload_and_sends_auth_headers() -> None:
    """Obtém um PR, envia token e cabeçalhos de versão e valida o schema."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _json(build_pull_request(number=42))

    clock = FakeClock()
    async with _client(handler, clock) as client:
        pr = await client.get_pull_request("org", "api", 42)

    assert pr.number == 42
    assert pr.is_merged is True
    assert pr.additions == 10
    request = seen[0]
    assert request.url.path == "/repos/org/api/pulls/42"
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert request.headers["X-GitHub-Api-Version"] == "2022-11-28"


async def test_list_merged_follows_link_pagination_and_filters_branch() -> None:
    """Percorre todas as páginas, envia o filtro ``base`` e devolve apenas PRs mergeados."""
    page_two_url = f"{BASE_URL}/repos/org/api/pulls?page=2"
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.params.get("page") == "2":
            return _json([build_pull_request(pr_id=2, number=2, merged=True)])
        return httpx.Response(
            200,
            json=[
                build_pull_request(pr_id=1, number=1, merged=True),
                build_pull_request(pr_id=9, number=9, merged=False, state="closed"),
            ],
            headers={"Link": f'<{page_two_url}>; rel="next"'},
        )

    clock = FakeClock()
    async with _client(handler, clock) as client:
        numbers = [
            pr.number
            async for pr in client.list_merged_pull_requests("org", "api", "master-tip")
        ]

    assert numbers == [1, 2]
    assert requests[0].url.params["base"] == "master-tip"
    assert requests[0].url.params["state"] == "closed"
    assert len(requests) == 2


async def test_list_stops_early_when_older_than_updated_since() -> None:
    """Como a listagem é ordenada por atualização decrescente, a paginação para cedo."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json=[
                build_pull_request(pr_id=1, number=1, updated_at="2026-01-10T12:00:00Z"),
                build_pull_request(pr_id=2, number=2, updated_at="2025-01-01T00:00:00Z"),
            ],
            headers={"Link": f'<{BASE_URL}/next>; rel="next"'},
        )

    since = datetime(2026, 1, 1, tzinfo=UTC)
    clock = FakeClock()
    async with _client(handler, clock) as client:
        numbers = [
            pr.number
            async for pr in client.list_merged_pull_requests(
                "org", "api", "main", updated_since=since
            )
        ]

    assert numbers == [1]
    assert calls == 1  # não buscou a próxima página


async def test_waits_for_primary_rate_limit_reset_then_succeeds() -> None:
    """HTTP 403 com cota zerada: aguarda até ``X-RateLimit-Reset`` e tenta de novo."""
    responses = iter(
        [
            httpx.Response(
                403,
                json={"message": "API rate limit exceeded"},
                headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(int(NOW) + 30)},
            ),
            _json(build_pull_request()),
        ]
    )

    clock = FakeClock()
    async with _client(lambda request: next(responses), clock) as client:
        pr = await client.get_pull_request("org", "api", 42)

    assert pr.number == 42
    assert len(clock.sleeps) == 1
    assert clock.sleeps[0] == pytest.approx(31.0)  # 30s até o reset + 1s de margem


async def test_honors_retry_after_for_secondary_limit() -> None:
    """HTTP 429 com ``Retry-After``: aguarda o tempo informado."""
    responses = iter([httpx.Response(429, headers={"Retry-After": "2"}), _json(build_pull_request())])

    clock = FakeClock()
    async with _client(lambda request: next(responses), clock) as client:
        await client.get_pull_request("org", "api", 42)

    assert clock.sleeps == [pytest.approx(2.0)]


async def test_raises_rate_limit_error_when_wait_exceeds_maximum() -> None:
    """Se a espera exceder o máximo configurado, falha imediatamente sem dormir."""
    reset = int(NOW) + 3600
    response = httpx.Response(
        403,
        json={"message": "limit"},
        headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(reset)},
    )

    clock = FakeClock()
    async with _client(lambda request: response, clock, max_rate_limit_wait=60.0) as client:
        with pytest.raises(GitHubRateLimitError) as exc_info:
            await client.get_pull_request("org", "api", 42)

    assert clock.sleeps == []
    assert exc_info.value.reset_at == datetime.fromtimestamp(reset, tz=UTC)


async def test_pauses_preemptively_when_quota_is_low() -> None:
    """Com cota baixa na resposta anterior, a próxima chamada aguarda a renovação."""
    reset = int(NOW) + 10
    responses = iter(
        [
            _json(build_pull_request(number=1), headers={
                "X-RateLimit-Remaining": "5",
                "X-RateLimit-Reset": str(reset),
            }),
            _json(build_pull_request(number=2)),
        ]
    )

    clock = FakeClock()
    async with _client(lambda request: next(responses), clock) as client:
        await client.get_pull_request("org", "api", 1)
        await client.get_pull_request("org", "api", 2)

    assert clock.sleeps == [pytest.approx(10.0)]


async def test_authentication_error_does_not_leak_token() -> None:
    """HTTP 401 vira ``GitHubAuthenticationError`` sem expor o token na mensagem."""
    clock = FakeClock()
    async with _client(lambda r: _json({"message": "Bad credentials"}, 401), clock) as client:
        with pytest.raises(GitHubAuthenticationError) as exc_info:
            await client.get_pull_request("org", "api", 42)

    assert TOKEN not in exc_info.value.message
    assert TOKEN not in str(exc_info.value.details)


async def test_not_found_maps_to_domain_error() -> None:
    """HTTP 404 vira ``GitHubNotFoundError``."""
    clock = FakeClock()
    async with _client(lambda r: _json({"message": "Not Found"}, 404), clock) as client:
        with pytest.raises(GitHubNotFoundError):
            await client.get_pull_request("org", "api", 999)


async def test_server_errors_are_retried_then_reported() -> None:
    """HTTP 500 é repetido até ``max_retries`` e depois vira ``GitHubApiError``."""
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return _json({"message": "Server Error"}, 500)

    clock = FakeClock()
    async with _client(handler, clock, max_retries=2) as client:
        with pytest.raises(GitHubApiError) as exc_info:
            await client.get_pull_request("org", "api", 42)

    assert attempts == 3  # 1 tentativa original + 2 retentativas
    assert exc_info.value.upstream_status == 500
    assert len(clock.sleeps) == 2


async def test_transport_errors_are_retried_then_raised() -> None:
    """Falhas de rede são repetidas e, persistindo, viram ``GitHubRequestError``."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("conexão recusada", request=request)

    clock = FakeClock()
    async with _client(handler, clock, max_retries=1) as client:
        with pytest.raises(GitHubRequestError):
            await client.get_pull_request("org", "api", 42)

    assert len(clock.sleeps) == 1


async def test_malformed_response_is_reported_as_invalid_response() -> None:
    """Resposta fora do schema vira ``GitHubResponseError``."""
    clock = FakeClock()
    async with _client(lambda r: _json({"inesperado": True}), clock) as client:
        with pytest.raises(GitHubResponseError):
            await client.get_pull_request("org", "api", 42)


async def test_rejects_path_traversal_in_owner_or_branch() -> None:
    """Segmentos com ``..`` ou caracteres de controle são recusados antes de qualquer chamada."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _json([])

    clock = FakeClock()
    async with _client(handler, clock) as client:
        with pytest.raises(ValueError):
            await client.get_pull_request("../admin", "api", 1)
        with pytest.raises(ValueError):
            async for _ in client.list_merged_pull_requests("org", "api", "main?x=1"):
                pass

    assert calls == 0
