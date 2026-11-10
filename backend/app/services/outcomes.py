"""Desfechos do processamento de eventos do GitHub.

Valores são estáveis porque são devolvidos ao cliente do webhook e registrados em log.
"""

from dataclasses import dataclass
from enum import StrEnum


class IngestionOutcome(StrEnum):
    """Resultado do processamento de um evento."""

    PROCESSED = "processed"
    STORED_REVIEW = "stored_review"
    PROVISIONED = "provisioned"
    DETACHED = "detached"
    REGISTERED_REPOSITORIES = "registered_repositories"
    IGNORED_ACTION = "ignored_action"
    IGNORED_BRANCH = "ignored_branch"
    IGNORED_REVIEW_STATE = "ignored_review_state"
    IGNORED_UNKNOWN_INSTALLATION = "ignored_unknown_installation"
    IGNORED_MISSING_INSTALLATION = "ignored_missing_installation"
    IGNORED_UNSUPPORTED_EVENT = "ignored_unsupported_event"


@dataclass(frozen=True, slots=True)
class IngestionResult:
    """Desfecho de um evento e, quando houve gravação de PR, o ``id`` interno dele."""

    outcome: IngestionOutcome
    pull_request_id: int | None = None
    # True só quando o PR foi mergeado: somente então a análise de IA é disparada.
    enrich: bool = False
    # True na abertura de um PR ainda não mergeado: pede a revisão automática pelas skills.
    review: bool = False
