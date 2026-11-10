"""Testes unitários do diff no GitHub e do reagendamento da tarefa de enriquecimento."""

import asyncio
from typing import Any

import httpx
import pytest

import app.workers.tasks as workers_module
from app.core.celery_app import celery_app
from app.core.config import get_settings
from app.core.exceptions import AIRateLimitError
from app.services.github_client import DIFF_ACCEPT_HEADER, GitHubClient
from app.workers.tasks import enrich_pr_with_ai_backfill_task, enrich_pr_with_ai_task
from tests.fake_redis import FakeRedis

DIFF = "diff --git a/app.py b/app.py\n+print('ok')\n"


@pytest.fixture(autouse=True)
def _fake_state_redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    """Estado da sessão em memória: estes testes não dependem de Redis."""
    fake = FakeRedis()
    monkeypatch.setattr(workers_module, "_state_redis", lambda: fake)
    return fake


async def test_get_pull_request_diff_requests_diff_media_type() -> None:
    """O diff é pedido com o media type de diff e devolvido como texto puro."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text=DIFF)

    async with GitHubClient(
        http_client=httpx.AsyncClient(base_url="https://api.github.com", transport=httpx.MockTransport(handler)),
        token="ghp_x",
    ) as client:
        diff = await client.get_pull_request_diff("org", "api", 42)

    assert diff == DIFF
    assert seen[0].url.path == "/repos/org/api/pulls/42"
    assert seen[0].headers["Accept"] == DIFF_ACCEPT_HEADER


def test_task_is_registered_with_expected_policy() -> None:
    """A tarefa tem o nome esperado, confirma após execução e reenvia falhas de conexão com o banco."""
    assert enrich_pr_with_ai_task.name == "enrich_pr_with_ai"
    assert enrich_pr_with_ai_task.acks_late is True
    assert "app.workers.tasks" in celery_app.conf.include


def test_backfill_task_is_registered_separately() -> None:
    """O backfill tem nome próprio, para não compartilhar a fila de PRs novos nem o analisador."""
    assert enrich_pr_with_ai_backfill_task.name == "enrich_pr_with_ai_backfill"
    assert enrich_pr_with_ai_backfill_task.acks_late is True


def test_backfill_task_runs_in_single_model_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """A tarefa de backfill chama o enriquecimento com ``single_model=True``; a de PRs novos, com False."""
    modes: list[bool] = []

    async def recording_run(pr_id: int, *, single_model: bool = False) -> str:
        modes.append(single_model)
        return "enriched"

    monkeypatch.setattr(workers_module, "run_enrichment", recording_run)

    assert enrich_pr_with_ai_backfill_task(3) == "enriched"
    assert enrich_pr_with_ai_task(4) == "enriched"
    assert modes == [True, False]


def test_rate_limit_reschedules_task_after_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    """Limite da IA reagenda a tarefa com ``countdown`` igual ao ``Retry-After`` recebido."""
    error = AIRateLimitError(retry_after=45)

    async def failing_run(pr_id: int, **_: Any) -> str:
        raise error

    scheduled: list[dict[str, Any]] = []

    class _Retry(Exception):
        pass

    def fake_retry(exc: Exception, countdown: int) -> _Retry:
        scheduled.append({"exc": exc, "countdown": countdown})
        return _Retry()

    monkeypatch.setattr(workers_module, "run_enrichment", failing_run)
    monkeypatch.setattr(enrich_pr_with_ai_task, "retry", fake_retry)

    with pytest.raises(_Retry):
        enrich_pr_with_ai_task(7)

    assert scheduled == [{"exc": error, "countdown": 45}]


def test_skipped_when_ai_key_is_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sem ``GEMINI_API_KEY`` (provedor Gemini), o enriquecimento é ignorado sem tocar em nenhum serviço externo."""
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    get_settings.cache_clear()

    assert asyncio.run(workers_module.run_enrichment(1)) == workers_module.SKIPPED_NO_AI_KEY


class _Retry(Exception):
    pass


def test_expired_session_pauses_queue_without_dropping_the_pr(
    monkeypatch: pytest.MonkeyPatch, _fake_state_redis: FakeRedis
) -> None:
    """Sessão do Claude expirada marca ``AUTH_REQUIRED``, reagenda a tarefa sem limite e não descarta o PR."""
    from app.core.exceptions import AISessionExpiredError
    from app.services.claude_session import AUTH_REQUIRED, AUTH_STATE_KEY

    async def expired_run(pr_id: int, **_: Any) -> str:
        raise AISessionExpiredError("sessão expirada")

    scheduled: list[dict[str, Any]] = []

    def fake_retry(**kwargs: Any) -> _Retry:
        scheduled.append(kwargs)
        return _Retry()

    monkeypatch.setattr(workers_module, "run_enrichment", expired_run)
    monkeypatch.setattr(enrich_pr_with_ai_task, "retry", fake_retry)

    with pytest.raises(_Retry):
        enrich_pr_with_ai_task(9)

    assert _fake_state_redis.get(AUTH_STATE_KEY) == AUTH_REQUIRED
    assert scheduled[0]["countdown"] == workers_module.AUTH_PAUSE_SECONDS
    assert scheduled[0]["max_retries"] is None


def test_paused_queue_does_not_call_the_model(
    monkeypatch: pytest.MonkeyPatch, _fake_state_redis: FakeRedis
) -> None:
    """Com a fila pausada e a sessão ainda inválida, a tarefa reagenda sem chamar a IA."""
    from app.services.claude_session import AUTH_REQUIRED, AUTH_STATE_KEY

    _fake_state_redis.set(AUTH_STATE_KEY, AUTH_REQUIRED)

    async def must_not_run(pr_id: int, **_: Any) -> str:
        raise AssertionError("a IA não deveria ser chamada com a fila pausada")

    async def still_expired(_service: Any) -> Any:
        from datetime import UTC, datetime

        from app.services.claude_session import SessionStatus

        return SessionStatus(False, datetime.now(UTC), "sessão expirada")

    scheduled: list[dict[str, Any]] = []

    def fake_retry(**kwargs: Any) -> _Retry:
        scheduled.append(kwargs)
        return _Retry()

    monkeypatch.setattr(workers_module, "run_enrichment", must_not_run)
    monkeypatch.setattr(workers_module, "check_session", still_expired)
    monkeypatch.setattr(enrich_pr_with_ai_task, "retry", fake_retry)

    with pytest.raises(_Retry):
        enrich_pr_with_ai_task(10)

    assert scheduled == [{"countdown": workers_module.AUTH_PAUSE_SECONDS, "max_retries": None}]
