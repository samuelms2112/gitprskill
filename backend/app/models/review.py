"""Modelo ORM de revisões de Pull Requests."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, str_enum
from app.models.enums import ReviewState

if TYPE_CHECKING:
    from app.models.contributor import Contributor
    from app.models.pull_request import PullRequest


class Review(Base):
    """Revisão de um PR: aprovação, pedido de alterações ou comentário."""

    __tablename__ = "pr_reviews"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    github_review_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    pull_request_id: Mapped[int] = mapped_column(
        ForeignKey("pull_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("contributors.id"), nullable=False)
    state: Mapped[ReviewState] = mapped_column(
        str_enum(ReviewState, name="review_state", length=20), nullable=False
    )
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)

    pull_request: Mapped["PullRequest"] = relationship(back_populates="reviews")
    reviewer: Mapped["Contributor"] = relationship(back_populates="reviews")

    def __repr__(self) -> str:
        """Representação curta para depuração."""
        return f"<Review id={self.id} state={self.state!r}>"
