"""Testes unitários das validações dos schemas Pydantic."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from app.models.enums import ReviewState
from app.schemas.pull_request import PullRequestCreate
from app.schemas.repository import RepositoryCreate
from app.schemas.review import ReviewCreate

NOW = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)


def _pr_payload(**overrides: Any) -> dict[str, Any]:
    """Payload válido de PR mergeado, com sobrescritas por teste."""
    payload: dict[str, Any] = {
        "tenant_id": 1,
        "github_pr_id": 1001,
        "repository_id": 1,
        "author_id": 1,
        "number": 42,
        "title": "feat: nova tela de login",
        "state": "closed",
        "is_merged": True,
        "head_branch": "feature/login",
        "base_branch": "main",
        "additions": 10,
        "deletions": 2,
        "changed_files": 3,
        "created_at": NOW,
        "updated_at": NOW + timedelta(hours=2),
        "closed_at": NOW + timedelta(hours=2),
        "merged_at": NOW + timedelta(hours=2),
        "html_url": "https://github.com/org/repo/pull/42",
    }
    payload.update(overrides)
    return payload


def _repo_payload(**overrides: Any) -> dict[str, Any]:
    """Payload válido de repositório, com sobrescritas por teste."""
    payload: dict[str, Any] = {
        "tenant_id": 1,
        "github_id": 555,
        "name": "api",
        "full_name": "org/api",
        "owner_login": "org",
        "html_url": "https://github.com/org/api",
    }
    payload.update(overrides)
    return payload


class TestRepositoryCreate:
    """Validações de ``RepositoryCreate``."""

    def test_accepts_consistent_payload(self) -> None:
        """Payload coerente é aceito e recebe o branch padrão."""
        repo = RepositoryCreate(**_repo_payload())
        assert repo.default_branch == "main"
        assert repo.is_private is False

    def test_rejects_owner_mismatch(self) -> None:
        """``owner_login`` divergente de ``full_name`` é rejeitado."""
        with pytest.raises(ValidationError, match="owner_login"):
            RepositoryCreate(**_repo_payload(owner_login="outra-org"))

    def test_rejects_name_mismatch(self) -> None:
        """``name`` divergente de ``full_name`` é rejeitado."""
        with pytest.raises(ValidationError, match="name"):
            RepositoryCreate(**_repo_payload(name="outro"))

    @pytest.mark.parametrize("full_name", ["semibarra", "a/b/c", "org/ repo"])
    def test_rejects_invalid_full_name(self, full_name: str) -> None:
        """Formatos fora de ``owner/repo`` são rejeitados."""
        with pytest.raises(ValidationError):
            RepositoryCreate(**_repo_payload(full_name=full_name))

    def test_rejects_non_https_url(self) -> None:
        """URLs que não usam HTTPS são rejeitadas."""
        with pytest.raises(ValidationError):
            RepositoryCreate(**_repo_payload(html_url="http://github.com/org/api"))

    def test_rejects_unknown_fields(self) -> None:
        """Campos não mapeados são rejeitados (``extra="forbid"``)."""
        with pytest.raises(ValidationError):
            RepositoryCreate(**_repo_payload(campo_inesperado=True))


class TestPullRequestCreate:
    """Validações de consistência de ``PullRequestCreate``."""

    def test_accepts_merged_pr(self) -> None:
        """PR mergeado coerente é aceito."""
        pr = PullRequestCreate(**_pr_payload())
        assert pr.is_merged is True

    def test_merged_without_merged_at_is_rejected(self) -> None:
        """PR marcado como mergeado exige ``merged_at``."""
        with pytest.raises(ValidationError, match="merged_at"):
            PullRequestCreate(**_pr_payload(merged_at=None))

    def test_merged_at_without_merge_flag_is_rejected(self) -> None:
        """``merged_at`` informado sem ``is_merged`` é inconsistente."""
        with pytest.raises(ValidationError, match="is_merged"):
            PullRequestCreate(**_pr_payload(is_merged=False, state="closed"))

    def test_open_pr_cannot_have_closed_at(self) -> None:
        """PR aberto não pode ter data de fechamento."""
        with pytest.raises(ValidationError, match="aberto"):
            PullRequestCreate(
                **_pr_payload(state="open", is_merged=False, merged_at=None, closed_at=NOW)
            )

    def test_updated_before_created_is_rejected(self) -> None:
        """``updated_at`` anterior a ``created_at`` é rejeitado."""
        with pytest.raises(ValidationError, match="updated_at"):
            PullRequestCreate(**_pr_payload(updated_at=NOW - timedelta(days=1)))

    def test_rejects_negative_line_counts(self) -> None:
        """Contagens de linhas negativas são rejeitadas."""
        with pytest.raises(ValidationError):
            PullRequestCreate(**_pr_payload(additions=-1))

    def test_rejects_unknown_fields(self) -> None:
        """Campos desconhecidos, como um tamanho calculado enviado pelo cliente, são rejeitados."""
        with pytest.raises(ValidationError):
            PullRequestCreate(**_pr_payload(pr_size_category="XS"))


class TestReviewCreate:
    """Validações de ``ReviewCreate``."""

    def test_accepts_known_state(self) -> None:
        """Estados conhecidos do GitHub são aceitos."""
        review = ReviewCreate(
            github_review_id=9001,
            pull_request_id=1,
            reviewer_id=2,
            state="APPROVED",
            submitted_at=NOW,
        )
        assert review.state == ReviewState.APPROVED

    def test_rejects_unknown_state(self) -> None:
        """Estados fora do domínio são rejeitados."""
        with pytest.raises(ValidationError):
            ReviewCreate(
                github_review_id=9001,
                pull_request_id=1,
                reviewer_id=2,
                state="DISMISSED_ALGUM_DIA",
                submitted_at=NOW,
            )
