"""Testes unitários da listagem histórica do GitHub: paginação, cota e dados do repositório."""

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from app.core.exceptions import GitHubRateLimitError
from app.services.github_client import GitHubClient
from tests.factories.github import build_pull_request, build_repository

BASE = "https://api.github.com"
NOW = 1_767_000_000.0


class FakeClock:
    def __init__(self) -> None:
        self.now = NOW
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _client(handler: Any, clock: FakeClock) -> GitHubClient:
    return GitHubClient(
        http_client=httpx.AsyncClient(base_url=BASE, transport=httpx.MockTransport(handler)),
        token="jwt-de-teste",
        sleep=clock.sleep,
        clock=clock,
    )


async def test_closed_listing_follows_link_pages_and_keeps_unmerged_prs() -> None:
    """Todas as páginas são percorridas e PRs fechados sem merge também são devolvidos (quem filtra é o backfill)."""
    second_page = f"{BASE}/repos/org/api/pulls?page=2"
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.params.get("page") == "2":
            return httpx.Response(200, json=[build_pull_request(pr_id=3, number=3, merged=False)])
        return httpx.Response(
            200,
            json=[
                build_pull_request(pr_id=1, number=1, merged=True),
                build_pull_request(pr_id=2, number=2, base_ref="develop", merged=True),
            ],
            headers={"Link": f'<{second_page}>; rel="next"'},
        )

    clock = FakeClock()
    async with _client(handler, clock) as client:
        numbers = [pr.number async for pr in client.iter_pull_requests("org", "api", updated_since=None)]

    assert numbers == [1, 2, 3]
    assert requests[0].url.params["state"] == "all"  # abertos e fechados: a captura começa na abertura
    assert "base" not in requests[0].url.params  # sem filtro de branch: a decisão é do backfill


async def test_listing_stops_at_updated_since_boundary() -> None:
    """Como a ordenação é por atualização decrescente, a paginação para no primeiro PR antigo demais."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json=[
                build_pull_request(pr_id=1, number=1, updated_at="2026-03-01T00:00:00Z"),
                build_pull_request(pr_id=2, number=2, updated_at="2025-01-01T00:00:00Z"),
            ],
            headers={"Link": f'<{BASE}/next>; rel="next"'},
        )

    clock = FakeClock()
    since = datetime(2026, 1, 1, tzinfo=UTC)
    async with _client(handler, clock) as client:
        numbers = [pr.number async for pr in client.iter_pull_requests("org", "api", updated_since=since)]

    assert numbers == [1]
    assert calls == 1


async def test_rate_limit_mid_pagination_waits_for_reset_and_keeps_collecting() -> None:
    """Cota zerada no meio da paginação: espera até o ``X-RateLimit-Reset`` e continua do mesmo ponto."""
    second_page = f"{BASE}/repos/org/api/pulls?page=2"
    responses = iter(
        [
            httpx.Response(
                200,
                json=[build_pull_request(pr_id=1, number=1)],
                headers={"Link": f'<{second_page}>; rel="next"', "X-RateLimit-Remaining": "4000"},
            ),
            httpx.Response(
                403,
                json={"message": "API rate limit exceeded"},
                headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(int(NOW) + 60)},
            ),
            httpx.Response(200, json=[build_pull_request(pr_id=2, number=2)]),
        ]
    )

    clock = FakeClock()
    async with _client(lambda request: next(responses), clock) as client:
        numbers = [pr.number async for pr in client.iter_pull_requests("org", "api", updated_since=None)]

    assert numbers == [1, 2]
    assert clock.sleeps == [pytest.approx(61.0)]  # 60s até o reset + 1s de margem


async def test_rate_limit_beyond_maximum_wait_raises_with_reset_time() -> None:
    """Se a espera passa do máximo configurado, a exceção sobe com o horário de renovação."""
    reset = int(NOW) + 7200
    clock = FakeClock()
    client = GitHubClient(
        http_client=httpx.AsyncClient(
            base_url=BASE,
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    403, json={"message": "limit"}, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(reset)}
                )
            ),
        ),
        token="jwt",
        max_rate_limit_wait=300.0,
        sleep=clock.sleep,
        clock=clock,
    )

    with pytest.raises(GitHubRateLimitError) as exc_info:
        async for _ in client.iter_pull_requests("org", "api", updated_since=None):
            pass

    assert exc_info.value.reset_at == datetime.fromtimestamp(reset, tz=UTC)
    assert clock.sleeps == []
    await client.aclose()


async def test_get_repository_parses_owner_and_default_branch() -> None:
    """Os dados do repositório (necessários para gravá-lo) são lidos corretamente."""
    clock = FakeClock()
    async with _client(lambda r: httpx.Response(200, json=build_repository(repo_id=777, owner="acme")), clock) as client:
        repository = await client.get_repository("acme", "api")

    assert repository.id == 777
    assert repository.owner.login == "acme"
    assert repository.default_branch == "main"
