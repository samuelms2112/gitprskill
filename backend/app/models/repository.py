"""Modelo ORM de repositórios rastreados, isolados por tenant."""

from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.pull_request import PullRequest
    from app.models.tenant import Tenant


class Repository(TimestampMixin, Base):
    """Repositório do GitHub monitorado por um tenant.

    O mesmo repositório pode existir em tenants diferentes; por isso a unicidade
    é ``(tenant_id, github_id)`` e ``(tenant_id, full_name)``.
    """

    __tablename__ = "repositories"
    __table_args__ = (
        UniqueConstraint("tenant_id", "github_id", name="uq_repositories_tenant_id_github_id"),
        UniqueConstraint("tenant_id", "full_name", name="uq_repositories_tenant_id_full_name"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    github_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_login: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    html_url: Mapped[str] = mapped_column(Text, nullable=False)
    default_branch: Mapped[str] = mapped_column(
        String(100), nullable=False, server_default="main"
    )
    is_private: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())

    tenant: Mapped["Tenant"] = relationship(back_populates="repositories")
    pull_requests: Mapped[list["PullRequest"]] = relationship(
        back_populates="repository",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        """Representação curta para depuração."""
        return f"<Repository id={self.id} full_name={self.full_name!r}>"
