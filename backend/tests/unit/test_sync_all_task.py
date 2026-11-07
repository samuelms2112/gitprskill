"""Testes unitários da tarefa de sincronização em massa de um tenant."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.exc import OperationalError

import app.workers.backfill_tasks as backfill_module
from app.core.exceptions import GitHubRateLimitError
from app.services.backfill_service import BackfillCounters
from app.services.sync_status import InMemorySyncStatusStore
from app.workers.backfill_tasks import (
    ALL_REPOSITORIES,
    _add,
    sync_all_tenant_repositories_task,
)


def test_task_is_registered_with_retry_and_ack_policy() -> None:
    """A tarefa tem nome estável, confirma após execução e reenvia falhas de conexão com o banco."""
    assert sync_all_tenant_repositories_task.name == "sync_all_tenant_repositories"
    assert sync_all_tenant_repositories_task.acks_late is True
    assert OperationalError in sync_all_tenant_repositories_task.autoretry_for


def test_task_delegates_to_the_runner_with_tenant_and_status_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """A tarefa repassa o tenant ao núcleo e devolve o desfecho."""
    calls: list[dict[str, Any]] = []

    async def runner(**kwargs: Any) -> str:
        calls.append(kwargs)
        return "completed"

    store = InMemorySyncStatusStore()
    monkeypatch.setattr(backfill_module, "run_sync_all", runner)
    monkeypatch.setattr(backfill_module, "build_status_store", lambda: store)

    result = sync_all_tenant_repositories_task(7)

    assert result == "completed"
    assert calls[0]["tenant_id"] == 7
    assert calls[0]["store"] is store


def test_rate_limit_reschedules_the_whole_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cota esgotada no meio do sync reagenda a tarefa para depois da renovação."""
    reset = datetime.now(UTC) + timedelta(seconds=300)

    async def failing(**_: Any) -> str:
        raise GitHubRateLimitError(reset_at=reset)

    scheduled: list[int] = []

    class _Retry(Exception):
        pass

    def fake_retry(exc: Exception, countdown: int) -> _Retry:
        scheduled.append(countdown)
        return _Retry()

    monkeypatch.setattr(backfill_module, "run_sync_all", failing)
    monkeypatch.setattr(backfill_module, "build_status_store", lambda: InMemorySyncStatusStore())
    monkeypatch.setattr(sync_all_tenant_repositories_task, "retry", fake_retry)

    with pytest.raises(_Retry):
        sync_all_tenant_repositories_task(7)

    assert 290 <= scheduled[0] <= 300


def test_aggregated_progress_is_the_sum_of_repositories() -> None:
    """O progresso agregado é a soma dos repositórios: nenhuma contagem se perde ao trocar de repositório."""
    first = BackfillCounters(examined=10, stored=8, new=5, skipped=2)
    second = BackfillCounters(examined=4, stored=3, new=1, skipped=1)

    total = _add(first, second)

    assert total == BackfillCounters(examined=14, stored=11, new=6, skipped=3)


def test_aggregated_status_uses_a_reserved_repository_id() -> None:
    """O status do sync em massa usa um ``repository_id`` reservado, distinto de qualquer repositório real."""
    assert ALL_REPOSITORIES == 0
