"""Testes unitários da configuração do Celery e do delegado da tarefa ``process_github_event``."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import OperationalError

import app.tasks.github_events as tasks_module
from app.core.celery_app import celery_app
from app.core.config import get_settings
from app.tasks.github_events import process_github_event


def test_task_is_registered_with_retry_and_ack_policy() -> None:
    """A tarefa tem nome estável, confirma após execução e reenvia apenas falhas de conexão."""
    assert process_github_event.name == "process_github_event"
    assert process_github_event.acks_late is True
    assert OperationalError in process_github_event.autoretry_for
    assert process_github_event.max_retries == 5


def test_celery_uses_redis_broker_and_json_only() -> None:
    """Broker é o Redis configurado, e apenas JSON é aceito (evita desserialização insegura)."""
    assert celery_app.conf.broker_url == get_settings().redis_url
    assert celery_app.conf.accept_content == ["json"]
    assert celery_app.conf.task_serializer == "json"
    assert celery_app.conf.task_reject_on_worker_lost is True


def test_task_delegates_to_runner_with_keyword_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    """Executar a tarefa repassa exatamente os argumentos ao runner e devolve o desfecho."""
    runner = AsyncMock(return_value="processed")
    monkeypatch.setattr(tasks_module, "run_github_event", runner)

    result = process_github_event("pull_request", "entrega-9", {"action": "closed"})

    assert result == "processed"
    runner.assert_awaited_once_with(
        event_name="pull_request",
        delivery_id="entrega-9",
        payload={"action": "closed"},
    )
