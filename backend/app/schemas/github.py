"""Schemas que modelam os payloads do GitHub usados pela plataforma.

Campos ausentes em algumas respostas (ex.: ``additions`` na listagem de PRs) são
opcionais. Campos extras são ignorados, pois o GitHub adiciona atributos com frequência.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import PullRequestState


class _GitHubPayload(BaseModel):
    """Base dos payloads do GitHub: ignora campos desconhecidos."""

    model_config = ConfigDict(extra="ignore")


class GitHubUser(_GitHubPayload):
    """Usuário ou conta de organização do GitHub."""

    id: int
    login: str
    avatar_url: str | None = None
    html_url: str | None = None


class GitHubRepository(_GitHubPayload):
    """Repositório do GitHub."""

    id: int
    name: str
    full_name: str
    owner: GitHubUser
    html_url: str
    default_branch: str = "main"
    private: bool = False


class GitHubBranchRef(_GitHubPayload):
    """Referência de branch (``head`` ou ``base``) de um PR."""

    ref: str


class GitHubPullRequest(_GitHubPayload):
    """Pull Request do GitHub, tanto na listagem quanto nos eventos de webhook."""

    id: int
    number: int
    title: str
    body: str | None = None
    state: PullRequestState
    merged: bool = False
    merged_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None
    html_url: str
    user: GitHubUser
    head: GitHubBranchRef
    base: GitHubBranchRef
    # Estatísticas aparecem nos eventos e no GET individual, mas não na listagem.
    additions: int | None = None
    deletions: int | None = None
    changed_files: int | None = None

    @property
    def is_merged(self) -> bool:
        """Um PR está mergeado quando o flag ``merged`` ou ``merged_at`` indica isso."""
        return self.merged or self.merged_at is not None


class GitHubInstallationRef(_GitHubPayload):
    """Referência à instalação do GitHub App que originou o evento."""

    id: int


class GitHubInstallation(_GitHubPayload):
    """Instalação do GitHub App, com a conta (organização ou usuário) que a recebeu."""

    id: int
    account: GitHubUser


class GitHubReview(_GitHubPayload):
    """Revisão de um PR. No webhook, ``state`` vem em minúsculas (ex.: ``approved``)."""

    id: int
    state: str
    body: str | None = None
    submitted_at: datetime | None = None
    user: GitHubUser


class InstallationAccessToken(_GitHubPayload):
    """Token temporário (1 hora) escopado a uma instalação do GitHub App."""

    token: str = Field(min_length=1)
    expires_at: datetime


class GitHubUserProfile(_GitHubPayload):
    """Perfil do usuário autenticado (``GET /user``)."""

    id: int
    login: str
    email: str | None = None
    avatar_url: str | None = None


class PullRequestEventPayload(_GitHubPayload):
    """Payload do evento de webhook ``pull_request``."""

    action: str
    number: int
    pull_request: GitHubPullRequest
    repository: GitHubRepository
    installation: GitHubInstallationRef | None = None


class PullRequestReviewEventPayload(_GitHubPayload):
    """Payload do evento de webhook ``pull_request_review``."""

    action: str
    review: GitHubReview
    pull_request: GitHubPullRequest
    repository: GitHubRepository
    installation: GitHubInstallationRef | None = None


class GitHubInstallationRepository(_GitHubPayload):
    """Repositório como vem nos eventos de instalação: dados reduzidos (sem dono nem branch padrão)."""

    id: int
    name: str
    full_name: str
    private: bool = False


class InstallationEventPayload(_GitHubPayload):
    """Payload do evento de webhook ``installation`` (criação, remoção, suspensão)."""

    action: str
    installation: GitHubInstallation
    sender: GitHubUser
    repositories: list[GitHubInstallationRepository] = Field(default_factory=list)


class InstallationRepositoriesEventPayload(_GitHubPayload):
    """Payload do evento ``installation_repositories``: repositórios adicionados ou removidos."""

    action: str
    installation: GitHubInstallation
    sender: GitHubUser
    repositories_added: list[GitHubInstallationRepository] = Field(default_factory=list)
    repositories_removed: list[GitHubInstallationRepository] = Field(default_factory=list)
