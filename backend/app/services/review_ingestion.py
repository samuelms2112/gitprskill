"""Ingestão de revisões (``pull_request_review``) para o banco, isolada por tenant.

Um review pode chegar antes do merge do PR. Por isso, quando o PR ainda não existe
no tenant, ele é gravado no estado em que está (desde que a branch seja rastreada),
e será atualizado pelo evento de merge posteriormente.
"""

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InvalidPayloadError
from app.core.logging import get_logger
from app.models.enums import ReviewState
from app.models.review import Review
from app.schemas.github import PullRequestReviewEventPayload
from app.schemas.review import ReviewCreate
from app.services.outcomes import IngestionOutcome
from app.services.pull_request_ingestion import PullRequestIngestionService
from app.services.validation import validate_domain

logger = get_logger(__name__)

SUBMITTED_ACTION = "submitted"


def map_review_state(raw_state: str) -> ReviewState | None:
    """Converte o estado do webhook (minúsculas) para o domínio.

    Estados fora do domínio, como ``dismissed``, devolvem ``None`` e são ignorados.
    """
    try:
        return ReviewState(raw_state.upper())
    except ValueError:
        return None


class ReviewIngestionService:
    """Persiste revisões submetidas em PRs de branches rastreadas."""

    def __init__(self, session: AsyncSession, tracked_branches: frozenset[str]) -> None:
        """Associa o serviço a uma sessão e às branches rastreadas."""
        self._session = session
        self._tracked_branches = tracked_branches
        self._pull_requests = PullRequestIngestionService(session, tracked_branches)

    async def process(
        self, event: PullRequestReviewEventPayload, tenant_id: int
    ) -> IngestionOutcome:
        """Processa um evento ``pull_request_review`` para o tenant informado.

        Raises:
            InvalidPayloadError: Quando a revisão não tem data de envio ou viola regras de domínio.
        """
        if event.action != SUBMITTED_ACTION:
            return IngestionOutcome.IGNORED_ACTION

        state = map_review_state(event.review.state)
        if state is None:
            return IngestionOutcome.IGNORED_REVIEW_STATE

        pull_request = event.pull_request
        if pull_request.base.ref not in self._tracked_branches:
            return IngestionOutcome.IGNORED_BRANCH

        if event.review.submitted_at is None:
            raise InvalidPayloadError("A revisão não informa submitted_at.")

        pull_request_id = await self._pull_requests.store(
            pull_request, event.repository, tenant_id
        )
        reviewer_id = await self._pull_requests.contributor_id(event.review.user, tenant_id)

        data = validate_domain(
            ReviewCreate,
            github_review_id=event.review.id,
            pull_request_id=pull_request_id,
            reviewer_id=reviewer_id,
            state=state,
            submitted_at=event.review.submitted_at,
            body=event.review.body,
        )
        values = data.model_dump()
        statement = pg_insert(Review).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[Review.github_review_id],
            set_={
                "state": statement.excluded.state,
                "submitted_at": statement.excluded.submitted_at,
                "body": statement.excluded.body,
                "reviewer_id": statement.excluded.reviewer_id,
            },
        )
        await self._session.execute(statement)
        logger.info(
            "Revisão persistida",
            extra={"review_id": event.review.id, "state": state.value},
        )
        return IngestionOutcome.STORED_REVIEW
