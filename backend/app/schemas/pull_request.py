"""Schemas de entrada e saída para ``PullRequest``."""

from datetime import datetime

from pydantic import Field, model_validator

from app.models.enums import PRSizeCategory, PullRequestState
from app.schemas.base import GitHubId, InputSchema, PositiveInt, ReadSchema
from app.services.pr_metrics import (
    classify_pr_size,
    compute_time_to_merge_seconds,
    total_changes,
)

HTTPS_URL_PATTERN = r"^https://"


class PullRequestCreate(InputSchema):
    """Dados de um PR para ingestão. As FKs são IDs internos (``id``) das entidades.

    As validações garantem a consistência entre estado, datas e merge, para que
    métricas como o time-to-merge nunca sejam calculadas sobre dados incoerentes.
    """

    tenant_id: PositiveInt
    github_pr_id: GitHubId
    repository_id: PositiveInt
    author_id: PositiveInt
    number: PositiveInt
    title: str = Field(min_length=1, max_length=512)
    # O GitHub limita o corpo de PRs a 65536 caracteres.
    body: str | None = Field(default=None, max_length=65536)
    state: PullRequestState
    is_merged: bool = False
    head_branch: str = Field(min_length=1, max_length=255)
    base_branch: str = Field(min_length=1, max_length=255)
    additions: int = Field(default=0, ge=0)
    deletions: int = Field(default=0, ge=0)
    changed_files: int = Field(default=0, ge=0)
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None
    merged_at: datetime | None = None
    html_url: str = Field(max_length=2048, pattern=HTTPS_URL_PATTERN)
    # Derivados: calculados pela ingestão. Quando informados, são conferidos abaixo.
    pr_size_category: PRSizeCategory | None = None
    time_to_merge_seconds: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _check_consistency(self) -> "PullRequestCreate":
        """Valida a coerência entre estado, merge e as datas do ciclo de vida."""
        if self.updated_at < self.created_at:
            raise ValueError("updated_at não pode ser anterior a created_at.")
        if self.closed_at is not None and self.closed_at < self.created_at:
            raise ValueError("closed_at não pode ser anterior a created_at.")

        if self.state == PullRequestState.OPEN and self.closed_at is not None:
            raise ValueError("Um PR aberto não pode possuir closed_at.")

        if self.is_merged:
            if self.merged_at is None:
                raise ValueError("Um PR mergeado exige merged_at.")
            if self.state != PullRequestState.CLOSED:
                raise ValueError("Um PR mergeado deve estar com state='closed'.")
        elif self.merged_at is not None:
            raise ValueError("merged_at informado, mas is_merged é False.")

        if self.merged_at is not None and self.merged_at < self.created_at:
            raise ValueError("merged_at não pode ser anterior a created_at.")

        expected_time_to_merge = compute_time_to_merge_seconds(self.created_at, self.merged_at)
        if self.time_to_merge_seconds is not None and self.time_to_merge_seconds != expected_time_to_merge:
            raise ValueError("time_to_merge_seconds inconsistente com merged_at e created_at.")

        if self.pr_size_category is not None:
            expected_size = classify_pr_size(total_changes(self.additions, self.deletions))
            if self.pr_size_category != expected_size:
                raise ValueError("pr_size_category inconsistente com as linhas alteradas.")
        return self


class PullRequestRead(ReadSchema):
    """Representação de um PR devolvida pela API, incluindo métricas derivadas."""

    id: int
    tenant_id: int
    github_pr_id: int
    repository_id: int
    author_id: int
    number: int
    title: str
    body: str | None
    state: PullRequestState
    is_merged: bool
    head_branch: str
    base_branch: str
    additions: int
    deletions: int
    changed_files: int
    pr_size_category: PRSizeCategory | None
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None
    merged_at: datetime | None
    time_to_merge_seconds: int | None
    html_url: str
