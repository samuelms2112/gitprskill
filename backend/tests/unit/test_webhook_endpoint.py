"""Testes unitários do endpoint de webhook: assinatura, roteamento e despacho ao Celery.

Não há banco nem broker: ``process_github_event.delay`` é substituído por um fake.
"""

import hashlib
import hmac
import json
from typing import Any

import httpx
import pytest
from kombu.exceptions import OperationalError as BrokerOperationalError

from app.core.config import get_settings
from app.main import app
from app.tasks.github_events import process_github_event
from tests.factories.github import build_pull_request_event

ENDPOINT = "/api/v1/webhooks/github"


class FakeDelay:
    """Registra as chamadas de ``delay`` e, opcionalmente, simula falha do broker."""

    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._error = error

    def __call__(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error


@pytest.fixture
def delay(monkeypatch: pytest.MonkeyPatch) -> FakeDelay:
    fake = FakeDelay()
    monkeypatch.setattr(process_github_event, "delay", fake)
    return fake


def _signed_headers(body: bytes, event: str = "pull_request", delivery: str = "d-1") -> dict[str, str]:
    secret = get_settings().github_webhook_secret
    assert secret is not None
    digest = hmac.new(secret.get_secret_value().encode(), body, hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-GitHub-Event": event,
        "X-GitHub-Delivery": delivery,
        "X-Hub-Signature-256": f"sha256={digest}",
    }


async def _post(body: bytes, headers: dict[str, str]) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.post(ENDPOINT, content=body, headers=headers)


async def test_signed_pull_request_is_accepted_and_dispatched(delay: FakeDelay) -> None:
    """Entrega válida responde 202 e enfileira o payload com evento e entrega."""
    payload = build_pull_request_event(installation_id=111)
    body = json.dumps(payload).encode()

    response = await _post(body, _signed_headers(body, delivery="entrega-42"))

    assert response.status_code == 202
    assert response.json() == {"status": "accepted", "reason": None}
    assert len(delay.calls) == 1
    call = delay.calls[0]
    assert call["event_name"] == "pull_request"
    assert call["delivery_id"] == "entrega-42"
    assert call["payload"] == payload


async def test_invalid_signature_is_rejected_and_not_dispatched(delay: FakeDelay) -> None:
    """Assinatura inválida responde 401 e nada é enfileirado."""
    body = json.dumps(build_pull_request_event()).encode()
    headers = _signed_headers(body)
    headers["X-Hub-Signature-256"] = "sha256=" + "0" * 64

    response = await _post(body, headers)

    assert response.status_code == 401
    assert delay.calls == []


async def test_missing_signature_is_rejected(delay: FakeDelay) -> None:
    """Sem ``X-Hub-Signature-256``, a entrega é recusada."""
    body = json.dumps(build_pull_request_event()).encode()
    headers = {k: v for k, v in _signed_headers(body).items() if k != "X-Hub-Signature-256"}

    response = await _post(body, headers)

    assert response.status_code == 401
    assert delay.calls == []


async def test_ping_is_answered_without_dispatch(delay: FakeDelay) -> None:
    """O ``ping`` do GitHub é respondido sem enfileirar nada."""
    body = b'{"zen":"Keep it logically awesome."}'

    response = await _post(body, _signed_headers(body, event="ping"))

    assert response.status_code == 202
    assert response.json()["status"] == "pong"
    assert delay.calls == []


async def test_unsupported_event_is_ignored_without_dispatch(delay: FakeDelay) -> None:
    """Eventos fora da lista suportada são confirmados e não consomem a fila."""
    body = b'{"ref":"refs/heads/main"}'

    response = await _post(body, _signed_headers(body, event="push"))

    assert response.json() == {"status": "ignored", "reason": "unsupported_event"}
    assert delay.calls == []


@pytest.mark.parametrize("body", [b"{nao-e-json", b'["lista", "nao-objeto"]'])
async def test_signed_body_that_is_not_a_json_object_is_rejected(delay: FakeDelay, body: bytes) -> None:
    """Corpo assinado, mas que não é um objeto JSON, responde 400."""
    response = await _post(body, _signed_headers(body))

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_payload"
    assert delay.calls == []


async def test_broker_outage_returns_503_so_github_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Se o Redis estiver fora, a entrega não é perdida: responde 503 para o GitHub reenviar."""
    monkeypatch.setattr(
        process_github_event,
        "delay",
        FakeDelay(error=BrokerOperationalError("redis indisponível")),
    )
    body = json.dumps(build_pull_request_event()).encode()

    response = await _post(body, _signed_headers(body))

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "task_queue_unavailable"
