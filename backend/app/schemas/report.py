"""Schemas de entrada e saída dos relatórios de Pull Requests."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import AICategory, AIRiskLevel, PRSizeCategory

PRStateFilter = Literal["all", "open", "merged"]
MAX_RELEASE_NOTES_RANGE_DAYS = 366
TRACKED_RELEASE_BRANCHES = Literal["main", "master", "master-tip"]


class PullRequestReportItem(BaseModel):
    """Linha do relatório de PRs, já com os dados de enriquecimento por IA."""

    id: int
    number: int
    title: str
    repository: str
    author: str
    base_branch: str
    # "open" enquanto o PR está aberto; "closed" depois (mergeado ou não). ``is_merged`` distingue.
    state: Literal["open", "closed"]
    is_merged: bool
    created_at: datetime
    merged_at: datetime | None
    additions: int
    deletions: int
    changed_files: int
    pr_size_category: PRSizeCategory | None
    time_to_merge_seconds: int | None
    ai_category: AICategory | None
    ai_risk_level: AIRiskLevel | None
    ai_summary: str | None
    html_url: str


class SizeDistribution(BaseModel):
    """Quantidade de PRs mergeados por faixa de tamanho."""

    XS: int = 0
    S: int = 0
    M: int = 0
    L: int = 0
    XL: int = 0


class ReportSummary(BaseModel):
    """Indicadores agregados do período filtrado, com as opções dos seletores do frontend."""

    total: int
    average_time_to_merge_seconds: int | None
    size_distribution: SizeDistribution
    available_authors: list[str]
    available_repositories: list[str]


class PullRequestReportPage(BaseModel):
    """Página de resultados do relatório, com o total para paginação."""

    items: list[PullRequestReportItem]
    total: int
    limit: int
    offset: int


class ReleaseNotesRequest(BaseModel):
    """Pedido de release notes para um período e, opcionalmente, uma branch."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    tenant_slug: str = Field(min_length=1, max_length=100)
    start_date: date
    end_date: date
    base_branch: TRACKED_RELEASE_BRANCHES | None = None
    limit: int = Field(default=100, ge=1, le=200)

    @model_validator(mode="after")
    def _check_period(self) -> "ReleaseNotesRequest":
        """O período deve ser coerente e limitado, para bound do tamanho do prompt."""
        if self.end_date < self.start_date:
            raise ValueError("end_date não pode ser anterior a start_date.")
        if (self.end_date - self.start_date).days > MAX_RELEASE_NOTES_RANGE_DAYS:
            raise ValueError(f"O período máximo é de {MAX_RELEASE_NOTES_RANGE_DAYS} dias.")
        return self


class ReleaseNotesResponse(BaseModel):
    """Release notes geradas, com o escopo utilizado."""

    tenant_slug: str
    start_date: date
    end_date: date
    base_branch: str | None
    pr_count: int
    markdown: str
