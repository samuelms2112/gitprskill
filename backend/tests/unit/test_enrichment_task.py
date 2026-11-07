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
from app.workers.tasks import enrich_pr_with_ai_task

DIFF = "diff --git a/app.py b/app.py\n+print('ok')\n"


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


def test_rate_limit_reschedules_task_after_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    """Limite da IA reagenda a tarefa com ``countdown`` igual ao ``Retry-After`` recebido."""
    error = AIRateLimitError(retry_after=45)

    async def failing_run(pr_id: int) -> str:
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
    """Sem ``GEMINI_API_KEY``, o enriquecimento é ignorado sem tocar em nenhum serviço externo."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    get_settings.cache_clear()

    assert asyncio.run(workers_module.run_enrichment(1)) == workers_module.SKIPPED_NO_AI_KEY
