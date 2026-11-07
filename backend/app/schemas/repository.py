"""Schemas de entrada e saída para ``Repository``."""

from datetime import datetime

from pydantic import Field, model_validator

from app.schemas.base import GitHubId, InputSchema, PositiveInt, ReadSchema

# Formato "owner/repo" aceito pelo GitHub.
FULL_NAME_PATTERN = r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"
HTTPS_URL_PATTERN = r"^https://"


class RepositoryCreate(InputSchema):
    """Dados para cadastrar um repositório rastreado."""

    tenant_id: PositiveInt
    github_id: GitHubId
    name: str = Field(min_length=1, max_length=255)
    full_name: str = Field(min_length=3, max_length=255, pattern=FULL_NAME_PATTERN)
    owner_login: str = Field(min_length=1, max_length=150)
    html_url: str = Field(max_length=2048, pattern=HTTPS_URL_PATTERN)
    default_branch: str = Field(default="main", min_length=1, max_length=100)
    is_private: bool = False

    @model_validator(mode="after")
    def _check_full_name_consistency(self) -> "RepositoryCreate":
        """Garante que ``owner_login`` e ``name`` sejam coerentes com ``full_name``."""
        owner, _, repo = self.full_name.partition("/")
        if owner != self.owner_login:
            raise ValueError("owner_login deve corresponder ao proprietário de full_name.")
        if repo != self.name:
            raise ValueError("name deve corresponder ao nome do repositório em full_name.")
        return self


class RepositoryRead(ReadSchema):
    """Representação de um repositório devolvida pela API."""

    id: int
    tenant_id: int
    github_id: int
    name: str
    full_name: str
    owner_login: str
    html_url: str
    default_branch: str
    is_private: bool
    created_at: datetime
    updated_at: datetime
