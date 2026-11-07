"""Testes unitários da verificação HMAC e dos limites de tamanho do webhook."""

import hashlib
import hmac

import pytest
from starlette.requests import Request

from app.core.exceptions import (
    InvalidSignatureError,
    PayloadTooLargeError,
    WebhookSecretNotConfiguredError,
)
from app.services.webhook_security import read_body_with_limit, verify_github_signature

SECRET = "segredo-de-teste"
BODY = b'{"action":"closed"}'


def _sign(body: bytes, secret: str = SECRET) -> str:
    """Gera o cabeçalho ``X-Hub-Signature-256`` como o GitHub faria."""
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_accepts_valid_signature() -> None:
    """Assinatura correta sobre o corpo exato é aceita sem exceção."""
    verify_github_signature(BODY, _sign(BODY), SECRET)


def test_rejects_signature_made_with_another_secret() -> None:
    """Assinatura gerada com outro segredo é rejeitada."""
    with pytest.raises(InvalidSignatureError):
        verify_github_signature(BODY, _sign(BODY, secret="outro-segredo"), SECRET)


def test_rejects_when_body_was_tampered() -> None:
    """Qualquer alteração no corpo invalida a assinatura."""
    with pytest.raises(InvalidSignatureError):
        verify_github_signature(BODY + b" ", _sign(BODY), SECRET)


def test_rejects_missing_header() -> None:
    """Ausência do cabeçalho é rejeitada."""
    with pytest.raises(InvalidSignatureError, match="ausente"):
        verify_github_signature(BODY, None, SECRET)


@pytest.mark.parametrize(
    "malformed",
    [
        "",
        "sha1=" + "a" * 40,  # algoritmo errado
        "sha256=",  # sem digest
        "sha256=" + "a" * 63,  # tamanho incorreto
        "sha256=" + "a" * 65,
        "a" * 71,  # sem prefixo
    ],
)
def test_rejects_malformed_header(malformed: str) -> None:
    """Formatos fora do padrão ``sha256=<64 hex>`` são rejeitados."""
    with pytest.raises(InvalidSignatureError):
        verify_github_signature(BODY, malformed, SECRET)


def test_non_ascii_signature_is_rejected_without_crashing() -> None:
    """Caracteres não ASCII não devem gerar TypeError no compare_digest."""
    with pytest.raises(InvalidSignatureError):
        verify_github_signature(BODY, "sha256=" + "ç" * 64, SECRET)


@pytest.mark.parametrize("secret", [None, ""])
def test_fails_closed_when_secret_not_configured(secret: str | None) -> None:
    """Sem segredo configurado, nenhuma entrega é aceita, mesmo com assinatura 'válida'."""
    with pytest.raises(WebhookSecretNotConfiguredError):
        verify_github_signature(BODY, _sign(BODY, secret=""), secret)


def _request(body: bytes, content_length: str | None = None) -> Request:
    """Cria uma requisição Starlette mínima com corpo e cabeçalho opcionais."""
    headers = []
    if content_length is not None:
        headers.append((b"content-length", content_length.encode()))
    scope = {"type": "http", "method": "POST", "path": "/", "headers": headers}
    sent = False

    async def receive() -> dict:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


async def test_reads_body_within_limit() -> None:
    """Corpo dentro do limite é devolvido byte a byte."""
    request = _request(BODY, content_length=str(len(BODY)))
    assert await read_body_with_limit(request, max_bytes=1024) == BODY


async def test_rejects_declared_content_length_above_limit() -> None:
    """``Content-Length`` acima do limite é recusado antes de ler o corpo."""
    request = _request(BODY, content_length="999999")
    with pytest.raises(PayloadTooLargeError):
        await read_body_with_limit(request, max_bytes=100)


async def test_rejects_real_body_above_limit_even_without_header() -> None:
    """Sem ``Content-Length``, o tamanho real do corpo ainda é verificado."""
    request = _request(b"x" * 200)
    with pytest.raises(PayloadTooLargeError):
        await read_body_with_limit(request, max_bytes=100)
