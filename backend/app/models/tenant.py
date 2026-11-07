"""Modelo ORM de tenants (organizações atendidas pela plataforma)."""

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.repository import Repository
    from app.models.tenant_member import TenantMember


class Tenant(TimestampMixin, Base):
    """Organização cliente da plataforma.

    ``github_installation_id`` liga o tenant à instalação do GitHub App. É nulo quando
    a instalação foi removida, preservando os dados históricos.
    """

    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    github_installation_id: Mapped[int | None] = mapped_column(
        BigInteger, unique=True, nullable=True
    )

    members: Mapped[list["TenantMember"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan", passive_deletes=True
    )
    repositories: Mapped[list["Repository"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:
        """Representação curta para depuração."""
        return f"<Tenant id={self.id} slug={self.slug!r}>"
