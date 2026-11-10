"""Testes unitários de ``GET /api/v1/system/claude/status``.

Não há banco nem CLI real: o autorizador, o Redis e o Claude Code são substituídos por dublês.
"""

import json
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

import httpx
import pytest

from app.api.v1.system import get_claude_service, get_redis_client, require_owner
from app.core.exceptions import AIUnavailableError
from app.main import app
from app.services.ai.claude_cli_service import ClaudeCliService, CliOutput
from app.services.claude_session import AUTH_REQUIRED, AUTH_STATE_KEY
from tests.fake_redis import FakeRedis

ENDPOINT = "/api/v1/system/claude/status"
EXPECTED_KEYS = {"authenticated", "last_checked", "error_message"}


Runner = Callable[[list[str], str, float], Awaitable[CliOutput]]


def _runner(output: CliOutput | Exception) -> Runner:
    async def run(argv: list[str], prompt: str, timeout: float) -> CliOutput:
        if isinstance(output, Exception):
            raise output
        return output

    return run


def _ok(result: str = "ok") -> CliOutput:
    return CliOutput(0, json.dumps({"type": "result", "is_error": False, "result": result}), "")


def _service(runner: Runner) -> ClaudeCliService:
    return ClaudeCliService(command="claude", model="claude-sonnet-5-5", timeout=5, max_diff_chars=1000, runner=runner)


@pytest.fixture
def redis_fake() -> FakeRedis:
    return FakeRedis()


@pytest.fixture(autouse=True)
def _restore_overrides() -> Any:
    yield
    app.dependency_overrides.clear()


def _install(runner: Runner, redis_client: FakeRedis) -> None:
    app.dependency_overrides[require_owner] = lambda: object()
    app.dependency_overrides[get_claude_service] = lambda: _service(runner)
    app.dependency_overrides[get_redis_client] = lambda: redis_client


async def _get() -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(ENDPOINT)


async def test_valid_session_reports_authenticated(redis_fake: FakeRedis) -> None:
    _install(_runner(_ok()), redis_fake)

    response = await _get()

    assert response.status_code == 200
    body = response.json()
    assert set(body) == EXPECTED_KEYS
    assert body["authenticated"] is True
    assert body["error_message"] is None
    datetime.fromisoformat(body["last_checked"])  # timestamp ISO 8601 válido


async def test_expired_session_reports_error_and_pauses_queue(redis_fake: FakeRedis) -> None:
    expired = CliOutput(
        1,
        json.dumps({"type": "result", "is_error": True, "result": "Please run /login · API Error: 401"}),
        "",
    )
    _install(_runner(expired), redis_fake)

    body = (await _get()).json()

    assert body["authenticated"] is False
    assert body["error_message"] is not None
    assert "login" in body["error_message"].lower()
    assert redis_fake.get(AUTH_STATE_KEY) == AUTH_REQUIRED


async def test_restored_session_resumes_queue(redis_fake: FakeRedis) -> None:
    redis_fake.set(AUTH_STATE_KEY, AUTH_REQUIRED)
    _install(_runner(_ok()), redis_fake)

    body = (await _get()).json()

    assert body["authenticated"] is True
    assert redis_fake.get(AUTH_STATE_KEY) is None


async def test_timeout_is_reported_as_unavailable_not_as_500(redis_fake: FakeRedis) -> None:
    _install(_runner(AIUnavailableError("O Claude Code CLI excedeu o tempo limite.")), redis_fake)

    response = await _get()

    assert response.status_code == 200
    body = response.json()
    assert body["authenticated"] is False
    assert "tempo limite" in body["error_message"]


async def test_usage_limit_keeps_session_authenticated(redis_fake: FakeRedis) -> None:
    reset_at = int(time.time()) + 3600
    limited = CliOutput(
        1,
        json.dumps({"type": "result", "is_error": True, "result": f"Claude AI usage limit reached|{reset_at}"}),
        "",
    )
    _install(_runner(limited), redis_fake)

    body = (await _get()).json()

    assert body["authenticated"] is True
    assert "limite" in body["error_message"]
    assert redis_fake.get(AUTH_STATE_KEY) is None
