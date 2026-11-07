"""Modelo ORM de Pull Requests e suas métricas derivadas."""

from datetime import datetime
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, str_enum
from app.models.enums import AICategory, AIRiskLevel, PRSizeCategory, PullRequestState

# Dimensão do vetor de embedding (nomic-embed-text produz 768 dimensões).
EMBEDDING_DIMENSIONS = 768

if TYPE_CHECKING:
    from app.models.contributor import Contributor
    from app.models.repository import Repository
    from app.models.review import Review


class PullRequest(Base):
    """Pull Request espelhado do GitHub, com métricas de tamanho e tempo de merge.

    As datas ``created_at``/``updated_at``/``closed_at``/``merged_at`` são as do
    próprio GitHub. ``pr_size_category`` e ``time_to_merge_seconds`` são derivados
    e preenchidos pelo motor de métricas.
    """

    __tablename__ = "pull_requests"
    __table_args__ = (
        UniqueConstraint("tenant_id", "github_pr_id", name="uq_pull_requests_tenant_id_github_pr_id"),
        UniqueConstraint("repository_id", "number", name="uq_pull_requests_repository_id_number"),
        # Índice parcial: acelera relatórios de merges, que filtram apenas PRs mergeados.
        Index(
            "ix_pull_requests_merged_at",
            "merged_at",
            postgresql_where=text("is_merged = true"),
        ),
        # Busca por similaridade de cosseno (memória semântica): índice HNSW no pgvector.
        Index(
            "ix_pull_requests_ai_embedding",
            "ai_embedding",
            postgresql_using="hnsw",
            postgresql_ops={"ai_embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    github_pr_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    repository_id: Mapped[int] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    author_id: Mapped[int] = mapped_column(
        ForeignKey("contributors.id"), nullable=False, index=True
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    state: Mapped[PullRequestState] = mapped_column(
        str_enum(PullRequestState, name="pull_request_state", length=20), nullable=False
    )
    is_merged: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    head_branch: Mapped[str] = mapped_column(String(255), nullable=False)
    base_branch: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    additions: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    deletions: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    changed_files: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    pr_size_category: Mapped[PRSizeCategory | None] = mapped_column(
        str_enum(PRSizeCategory, name="pr_size_category", length=2)
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    time_to_merge_seconds: Mapped[int | None] = mapped_column(BigInteger)
    html_url: Mapped[str] = mapped_column(Text, nullable=False)
    # Enriquecimento por IA (preenchido em background; nulo até a análise ser concluída).
    ai_summary: Mapped[str | None] = mapped_column(Text)
    ai_category: Mapped[AICategory | None] = mapped_column(
        str_enum(AICategory, name="ai_category", length=20)
    )
    # Parecer de produto (PM/PO) usado como contexto do conselho técnico.
    ai_product_opinion: Mapped[str | None] = mapped_column(Text)
    # Vetor do resumo para a memória semântica (dimensão do nomic-embed-text).
    ai_embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    ai_risk_level: Mapped[AIRiskLevel | None] = mapped_column(
        str_enum(AIRiskLevel, name="ai_risk_level", length=10)
    )

    repository: Mapped["Repository"] = relationship(back_populates="pull_requests")
    author: Mapped["Contributor"] = relationship(back_populates="pull_requests")
    reviews: Mapped[list["Review"]] = relationship(
        back_populates="pull_request",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        """Representação curta para depuração."""
        return f"<PullRequest id={self.id} number={self.number} state={self.state!r}>"
