"""Schemas de entrada e saída para ``Review``."""

from datetime import datetime

from pydantic import Field

from app.models.enums import ReviewState
from app.schemas.base import GitHubId, InputSchema, PositiveInt, ReadSchema


class ReviewCreate(InputSchema):
    """Dados de uma revisão para ingestão. As FKs são IDs internos."""

    github_review_id: GitHubId
    pull_request_id: PositiveInt
    reviewer_id: PositiveInt
    state: ReviewState
    submitted_at: datetime
    body: str | None = Field(default=None, max_length=65535)


class ReviewRead(ReadSchema):
    """Representação de uma revisão devolvida pela API."""

    id: int
    github_review_id: int
    pull_request_id: int
    reviewer_id: int
    state: ReviewState
    submitted_at: datetime
    body: str | None
