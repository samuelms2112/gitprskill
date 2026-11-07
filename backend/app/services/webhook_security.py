"""Verificação de autenticidade e limites de tamanho dos webhooks do GitHub.

O GitHub assina cada entrega com HMAC SHA-256 do corpo bruto, usando o segredo do
webhook, e envia o resultado em ``X-Hub-Signature-256: sha256=<hex>``. A comparação
é feita em tempo constante (``hmac.compare_digest``) para evitar ataques de temporização.
"""

import hashlib
import hmac

from starlette.requests import Request

from app.core.exceptions import (
    InvalidSignatureError,
    PayloadTooLargeError,
    WebhookSecretNotConfiguredError,
)
from app.core.logging import get_logger

logger = get_logger(__name__)

SIGNATURE_PREFIX = "sha256="
SIGNATURE_HEX_LENGTH = 64
# Limite conservador: payloads de PR do GitHub raramente passam de alguns KB.
MAX_WEBHOOK_BODY_BYTES = 5 * 1024 * 1024


def verify_github_signature(
    payload: bytes,
    signature_header: str | None,
    secret: str | None,
) -> None:
    """Valida a assinatura HMAC SHA-256 de uma entrega de webhook.

    Falha de forma fechada: sem segredo configurado, toda entrega é rejeitada.

    Args:
        payload: Corpo bruto da requisição, exatamente como recebido.
        signature_header: Valor do cabeçalho ``X-Hub-Signature-256``.
        secret: Segredo configurado para o webhook.

    Raises:
        WebhookSecretNotConfiguredError: Quando ``secret`` está vazio.
        InvalidSignatureError: Quando o cabeçalho está ausente, malformado ou não confere.
    """
    if not secret:
        logger.error("GITHUB_WEBHOOK_SECRET não configurado; webhook rejeitado")
        raise WebhookSecretNotConfiguredError("Segredo do webhook não configurado.")

    if not signature_header:
        raise InvalidSignatureError("Cabeçalho X-Hub-Signature-256 ausente.")

    if not signature_header.startswith(SIGNATURE_PREFIX):
        raise InvalidSignatureError("Formato da assinatura inválido.")

    received = signature_header[len(SIGNATURE_PREFIX) :]
    if len(received) != SIGNATURE_HEX_LENGTH:
        raise InvalidSignatureError("Formato da assinatura inválido.")

    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    # Comparação em bytes: compare_digest rejeita str com caracteres não ASCII.
    if not hmac.compare_digest(expected.encode("ascii"), received.encode("utf-8", "replace")):
        raise InvalidSignatureError("Assinatura do webhook inválida.")


async def read_body_with_limit(request: Request, max_bytes: int = MAX_WEBHOOK_BODY_BYTES) -> bytes:
    """Lê o corpo bruto da requisição respeitando um limite de tamanho.

    Verifica ``Content-Length`` antes de ler e, como o cabeçalho pode ser omitido
    ou mentir, confere também o tamanho real do corpo.

    Raises:
        PayloadTooLargeError: Quando o corpo excede ``max_bytes``.
    """
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > max_bytes:
                raise PayloadTooLargeError("Corpo da requisição excede o limite permitido.")
        except ValueError:
            pass  # Cabeçalho malformado: a verificação pelo tamanho real continua valendo.

    body = await request.body()
    if len(body) > max_bytes:
        raise PayloadTooLargeError("Corpo da requisição excede o limite permitido.")
    return body
