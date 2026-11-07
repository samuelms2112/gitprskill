"""Endpoint de recepção de webhooks do GitHub (GitHub App).

Fluxo síncrono, sem acesso ao banco:
    corpo bruto -> limite de tamanho -> assinatura HMAC -> evento suportado
    -> JSON objeto -> ``process_github_event.delay(...)`` -> HTTP 202.

O processamento (resolução do tenant, validação de domínio e gravação) acontece no
worker Celery. Assim o GitHub recebe a confirmação rapidamente e não reenvia a entrega
por timeout.
"""

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request, status
from kombu.exceptions import OperationalError as BrokerOperationalError
from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.core.exceptions import CeleryDispatchError, InvalidPayloadError
from app.core.logging import get_logger
from app.services.webhook_security import read_body_with_limit, verify_github_signature
from app.tasks.github_events import process_github_event

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])
logger = get_logger(__name__)

PING_EVENT = "ping"
SUPPORTED_EVENTS = frozenset(
    {"pull_request", "pull_request_review", "installation", "installation_repositories"}
)


class WebhookResponse(BaseModel):
    """Resposta padronizada às entregas de webhook."""

    status: str
    reason: str | None = None


@router.post(
    "/github",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=WebhookResponse,
    summary="Recebe eventos de webhook do GitHub App",
)
async def receive_github_webhook(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    x_github_event: Annotated[str | None, Header()] = None,
    x_github_delivery: Annotated[str | None, Header()] = None,
    x_hub_signature_256: Annotated[str | None, Header()] = None,
) -> WebhookResponse:
    """Valida a entrega e a enfileira para processamento assíncrono.

    Raises:
        InvalidSignatureError: Assinatura ausente ou inválida (HTTP 401).
        InvalidPayloadError: Corpo que não é um objeto JSON (HTTP 400).
        CeleryDispatchError: Broker indisponível (HTTP 503). O GitHub pode reenviar.
    """
    body = await read_body_with_limit(request)

    secret = settings.github_webhook_secret
    verify_github_signature(
        body,
        x_hub_signature_256,
        secret.get_secret_value() if secret else None,
    )

    event_name = x_github_event or ""
    if event_name == PING_EVENT:
        return WebhookResponse(status="pong")
    if event_name not in SUPPORTED_EVENTS:
        return WebhookResponse(status="ignored", reason="unsupported_event")

    payload = _parse_json_object(body)
    dispatch_github_event(event_name=event_name, delivery_id=x_github_delivery, payload=payload)
    logger.info(
        "Evento do GitHub enfileirado",
        extra={"event": event_name, "delivery_id": x_github_delivery},
    )
    return WebhookResponse(status="accepted")


def dispatch_github_event(
    *, event_name: str, delivery_id: str | None, payload: dict[str, Any]
) -> None:
    """Envia o evento para a fila do Celery.

    Raises:
        CeleryDispatchError: Se o broker (Redis) não estiver acessível.
    """
    try:
        process_github_event.delay(
            event_name=event_name,
            delivery_id=delivery_id,
            payload=payload,
        )
    except BrokerOperationalError as exc:
        logger.error("Broker indisponível ao enfileirar evento", extra={"event": event_name})
        raise CeleryDispatchError("Fila de processamento indisponível no momento.") from exc


def _parse_json_object(body: bytes) -> dict[str, Any]:
    """Garante que o corpo é um objeto JSON, sem validar o schema (isso é feito no worker).

    Raises:
        InvalidPayloadError: Se o corpo não for JSON ou não for um objeto.
    """
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise InvalidPayloadError("Corpo da requisição não é JSON válido.") from exc
    if not isinstance(data, dict):
        raise InvalidPayloadError("O corpo do webhook deve ser um objeto JSON.")
    return data
