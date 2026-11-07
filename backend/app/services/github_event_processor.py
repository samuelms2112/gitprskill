"""Orquestrador do processamento de eventos do GitHub.

Recebe o nome do evento e o payload já autenticados, roteia para o serviço adequado
e garante que todos os dados gravados pertençam ao tenant resolvido pela instalação
do GitHub App. Eventos sem instalação conhecida são descartados: nenhum dado é
gravado sem tenant.
"""

from collections.abc import Mapping
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InvalidPayloadError
from app.models.tenant import Tenant
from app.schemas.github import (
    GitHubInstallationRef,
    InstallationEventPayload,
    InstallationRepositoriesEventPayload,
    PullRequestEventPayload,
    PullRequestReviewEventPayload,
)
from app.services.outcomes import IngestionOutcome, IngestionResult
from app.services.pull_request_ingestion import PullRequestIngestionService
from app.services.review_ingestion import ReviewIngestionService
from app.services.tenant_provisioning import TenantProvisioningService
from app.services.validation import safe_error_details

PULL_REQUEST_EVENT = "pull_request"
PULL_REQUEST_REVIEW_EVENT = "pull_request_review"
INSTALLATION_EVENT = "installation"
INSTALLATION_REPOSITORIES_EVENT = "installation_repositories"

_M = TypeVar("_M", bound=BaseModel)


class GitHubEventProcessor:
    """Processa um evento dentro de uma transação já aberta pelo chamador."""

    def __init__(self, session: AsyncSession, tracked_branches: frozenset[str]) -> None:
        """Associa o processador a uma sessão e às branches rastreadas."""
        self._session = session
        self._tracked_branches = tracked_branches

    async def process(self, event_name: str, payload: Mapping[str, Any]) -> IngestionResult:
        """Roteia o evento pelo nome e devolve o desfecho.

        Raises:
            InvalidPayloadError: Quando o payload não corresponde ao schema do evento.
        """
        if event_name == PULL_REQUEST_EVENT:
            return await self._pull_request(payload)
        if event_name == PULL_REQUEST_REVIEW_EVENT:
            return await self._review(payload)
        if event_name == INSTALLATION_EVENT:
            event = _parse(InstallationEventPayload, payload)
            outcome = await TenantProvisioningService(self._session).handle(event)
            return IngestionResult(outcome=outcome)
        if event_name == INSTALLATION_REPOSITORIES_EVENT:
            repositories_event = _parse(InstallationRepositoriesEventPayload, payload)
            outcome = await TenantProvisioningService(self._session).handle_repositories(repositories_event)
            return IngestionResult(outcome=outcome)
        return IngestionResult(outcome=IngestionOutcome.IGNORED_UNSUPPORTED_EVENT)

    async def _pull_request(self, payload: Mapping[str, Any]) -> IngestionResult:
        event = _parse(PullRequestEventPayload, payload)
        tenant_id, rejection = await self._resolve_tenant(event.installation)
        if tenant_id is None:
            return IngestionResult(outcome=rejection)
        service = PullRequestIngestionService(self._session, self._tracked_branches)
        return await service.process(event, tenant_id)

    async def _review(self, payload: Mapping[str, Any]) -> IngestionResult:
        event = _parse(PullRequestReviewEventPayload, payload)
        tenant_id, rejection = await self._resolve_tenant(event.installation)
        if tenant_id is None:
            return IngestionResult(outcome=rejection)
        service = ReviewIngestionService(self._session, self._tracked_branches)
        outcome = await service.process(event, tenant_id)
        return IngestionResult(outcome=outcome)

    async def _resolve_tenant(
        self, installation: GitHubInstallationRef | None
    ) -> tuple[int | None, IngestionOutcome]:
        """Devolve ``(tenant_id, _)``, ou ``(None, motivo)`` quando a instalação não é resolvível."""
        if installation is None:
            return None, IngestionOutcome.IGNORED_MISSING_INSTALLATION
        tenant_id = await self._session.scalar(
            select(Tenant.id).where(Tenant.github_installation_id == installation.id)
        )
        if tenant_id is None:
            return None, IngestionOutcome.IGNORED_UNKNOWN_INSTALLATION
        return int(tenant_id), IngestionOutcome.PROCESSED


def _parse(model: type[_M], payload: Mapping[str, Any]) -> _M:
    """Valida o payload e converte falhas em erro de aplicação sem ecoar os valores."""
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise InvalidPayloadError(
            f"Payload inválido para {model.__name__}.",
            details={"errors": safe_error_details(exc)},
        ) from exc
