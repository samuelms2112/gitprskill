"""Schemas de entrada e saída para ``Contributor``."""

from datetime import datetime

from pydantic import EmailStr, Field

from app.schemas.base import GitHubId, InputSchema, PositiveInt, ReadSchema

HTTPS_URL_PATTERN = r"^https://"


class ContributorCreate(InputSchema):
    """Dados para cadastrar ou atualizar um contribuidor."""

    tenant_id: PositiveInt
    github_id: GitHubId
    login: str = Field(min_length=1, max_length=150)
    avatar_url: str | None = Field(default=None, max_length=2048, pattern=HTTPS_URL_PATTERN)
    html_url: str | None = Field(default=None, max_length=2048, pattern=HTTPS_URL_PATTERN)
    name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = None


class ContributorRead(ReadSchema):
    """Representação de um contribuidor devolvida pela API."""

    id: int
    tenant_id: int
    github_id: int
    login: str
    avatar_url: str | None
    html_url: str | None
    name: str | None
    email: str | None
    created_at: datetime
    updated_at: datetime
