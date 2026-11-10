"""Schemas da revisão automática de PRs (skills) e das regras editáveis da empresa.

Não confundir com ``app.schemas.review``, que trata das reviews humanas vindas do GitHub.
"""

from datetime import datetime
from typing import Annotated

from pydantic import Field

from app.models.ai_review import AIReviewStatus
from app.schemas.base import InputSchema, ReadSchema
from app.services.pr_review import ReviewFinding

MAX_RULE_CONTENT_CHARS = 20_000


class AIReviewRead(ReadSchema):
    """Revisão de um PR, com o status atual e os apontamentos quando já estiverem prontos."""

    id: int
    pull_request_id: int
    pr_number: int
    pr_title: str
    repository: str
    pr_url: str
    status: AIReviewStatus
    findings: list[ReviewFinding] | None
    findings_count: int
    error_message: str | None
    publish_error: str | None
    github_review_url: str | None
    created_at: datetime
    finished_at: datetime | None


class AIReviewRequested(ReadSchema):
    """Revisão pedida. O status inicial é PENDING; o card acompanha até COMPLETED ou FAILED."""

    id: int
    pull_request_id: int
    status: AIReviewStatus


class SkillRuleRead(ReadSchema):
    filename: str
    content: str
    updated_at: datetime


class ReviewSkillRead(ReadSchema):
    slug: str
    name: str
    rules: list[SkillRuleRead]


class SkillRuleUpdate(InputSchema):
    """Novo conteúdo de uma regra. Nome do arquivo vem da URL; campos extras são recusados."""

    content: Annotated[str, Field(min_length=1, max_length=MAX_RULE_CONTENT_CHARS)]
