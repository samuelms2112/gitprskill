"""Modelo ORM de contribuidores (autores de PR e revisores), isolados por tenant."""

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.pull_request import PullRequest
    from app.models.review import Review


class Contributor(TimestampMixin, Base):
    """Usuário do GitHub que abre PRs ou revisa, visto por um tenant.

    ``login`` não é único (o GitHub permite renomear usuários); a identidade é
    ``(tenant_id, github_id)``.
    """

    __tablename__ = "contributors"
    __table_args__ = (
        UniqueConstraint("tenant_id", "github_id", name="uq_contributors_tenant_id_github_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    github_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    login: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    avatar_url: Mapped[str | None] = mapped_column(Text)
    html_url: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255))

    pull_requests: Mapped[list["PullRequest"]] = relationship(back_populates="author")
    reviews: Mapped[list["Review"]] = relationship(back_populates="reviewer")

    def __repr__(self) -> str:
        """Representação curta para depuração."""
        return f"<Contributor id={self.id} login={self.login!r}>"
