"""Testes unitários: quais eventos o webhook aceita e enfileira."""

import hashlib
import hmac
import json
from typing import Any

import httpx
import pytest

from app.core.config import get_settings
from app.main import app
from app.tasks.github_events import process_github_event
from tests.factories.github import build_installation_repositories_event

ENDPOINT = "/api/v1/webhooks/github"


class RecordingDelay:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


@pytest.fixture
def delay(monkeypatch: pytest.MonkeyPatch) -> RecordingDelay:
    fake = RecordingDelay()
    monkeypatch.setattr(process_github_event, "delay", fake)
    return fake


def _signed(body: bytes, event: str) -> dict[str, str]:
    secret = get_settings().github_webhook_secret
    assert secret is not None
    digest = hmac.new(secret.get_secret_value().encode(), body, hashlib.sha256).hexdigest()
    return {"Content-Type": "application/json", "X-GitHub-Event": event, "X-GitHub-Delivery": "d-1", "X-Hub-Signature-256": f"sha256={digest}"}


async def test_installation_repositories_event_is_accepted_and_dispatched(delay: RecordingDelay) -> None:
    """O evento de repositórios incluídos é aceito e enviado ao worker para cadastro."""
    body = json.dumps(build_installation_repositories_event(added=[{"id": 1, "name": "x", "full_name": "acme/x", "private": True}])).encode()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(ENDPOINT, content=body, headers=_signed(body, "installation_repositories"))

    assert response.status_code == 202
    assert response.json()["status"] == "accepted"
    assert delay.calls[0]["event_name"] == "installation_repositories"
