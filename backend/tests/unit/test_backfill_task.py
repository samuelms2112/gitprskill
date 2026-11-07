"""Testes unitários do status de backfill (Redis e memória) e da tarefa Celery."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

import app.workers.backfill_tasks as backfill_module
from app.core.exceptions import GitHubRateLimitError
from app.schemas.sync import SyncStatus
from app.services.sync_status import (
    KEY_PREFIX,
    STATUS_TTL_SECONDS,
    InMemorySyncStatusStore,
    RedisSyncStatusStore,
)
from app.workers.backfill_tasks import run_backfill, sync_repository_history_task

NOW = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)


def _status(task_id: str = "t-1", state: str = "running") -> SyncStatus:
    return SyncStatus(
        task_id=task_id,
        tenant_id=1,
        repository_id=2,
        state=state,  # type: ignore[arg-type]
        examined=10,
        stored=4,
        new=3,
        skipped=6,
        updated_at=NOW,
    )


class FakeRedis:
    """Dublê mínimo do cliente Redis, guardando valores e TTLs em memória."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int | None] = {}

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.values[key] = value
        self.ttls[key] = ex

    def get(self, key: str) -> str | None:
        return self.values.get(key)


def test_memory_store_roundtrip_and_missing_job() -> None:
    """O status salvo é recuperado pelo ``task_id``; job desconhecido retorna ``None``."""
    store = InMemorySyncStatusStore()
    store.save(_status())

    assert store.load("t-1") == _status()
    assert store.load("nao-existe") is None


def test_redis_store_serializes_json_with_expiration() -> None:
    """No Redis, o status é JSON com TTL, sob uma chave com prefixo previsível."""
    fake = FakeRedis()
    store = RedisSyncStatusStore(fake)  # type: ignore[arg-type]

    store.save(_status("abc"))

    assert fake.ttls[f"{KEY_PREFIX}abc"] == STATUS_TTL_SECONDS
    assert store.load("abc") == _status("abc")
    assert store.load("ausente") is None


def test_task_is_registered_with_retry_policy() -> None:
    """A tarefa tem nome estável e reenvia falhas de conexão com o banco."""
    from sqlalchemy.exc import OperationalError

    assert sync_repository_history_task.name == "sync_repository_history"
    assert sync_repository_history_task.acks_late is True
    assert OperationalError in sync_repository_history_task.autoretry_for


def test_rate_limit_reschedules_after_github_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cota esgotada reagenda o job para depois da renovação informada pelo GitHub."""
    reset = datetime.now(UTC) + timedelta(seconds=600)
    error = GitHubRateLimitError(reset_at=reset)

    async def failing(**_: Any) -> str:
        raise error

    scheduled: list[int] = []

    class _Retry(Exception):
        pass

    def fake_retry(exc: Exception, countdown: int) -> _Retry:
        scheduled.append(countdown)
        return _Retry()

    monkeypatch.setattr(backfill_module, "run_backfill", failing)
    monkeypatch.setattr(backfill_module, "build_status_store", lambda: InMemorySyncStatusStore())
    monkeypatch.setattr(sync_repository_history_task, "retry", fake_retry)

    with pytest.raises(_Retry):
        sync_repository_history_task(1, 2, None)

    assert len(scheduled) == 1
    assert 590 <= scheduled[0] <= 600


def test_rate_limit_without_reset_uses_default_wait() -> None:
    """Sem horário de renovação, a espera padrão é usada."""
    assert backfill_module._retry_countdown(GitHubRateLimitError(reset_at=None)) == 900


async def test_missing_github_app_marks_job_failed_without_touching_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sem GitHub App configurado, o job falha de forma explícita e registra o motivo."""
    from app.core.config import get_settings

    monkeypatch.delenv("GITHUB_APP_ID", raising=False)
    monkeypatch.delenv("GITHUB_APP_PRIVATE_KEY", raising=False)
    get_settings.cache_clear()
    store = InMemorySyncStatusStore()

    outcome = await run_backfill(task_id="t-x", tenant_id=1, repository_id=2, days_back=None, store=store)

    assert outcome == "failed"
    final = store.load("t-x")
    assert final is not None
    assert final.state == "failed"
    assert final.error is not None
