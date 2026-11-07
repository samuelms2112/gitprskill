"""Dublês dos colaboradores externos (GitHub e Gemini) para os testes de integração."""

from collections.abc import Sequence
from typing import Any

from app.core.exceptions import AIError
from app.models.pull_request import PullRequest
from app.services.ai_service import PullRequestAnalysis


class FakeDiffSource:
    """Substitui o buscador de diffs por instalação. Registra cada chamada."""

    def __init__(self, diff: str = "diff --git a/x b/x\n+ok\n") -> None:
        self.diff = diff
        self.calls: list[tuple[int, str, str, int]] = []

    async def get_diff(self, installation_id: int, owner: str, repo: str, number: int) -> str:
        self.calls.append((installation_id, owner, repo, number))
        return self.diff


class FakeAnalyzer:
    """Substitui o ``AIService`` na análise de PRs. Pode simular qualquer exceção."""

    def __init__(
        self,
        analysis: PullRequestAnalysis | None = None,
        error: AIError | None = None,
    ) -> None:
        self.analysis = analysis
        self.error = error
        self.calls: list[tuple[str, str, str]] = []

    async def analyze_pull_request(
        self,
        title: str,
        description: str,
        diff_text: str,
        *,
        product_context: str | None = None,
    ) -> PullRequestAnalysis:
        self.calls.append((title, description, diff_text))
        if self.error is not None:
            raise self.error
        assert self.analysis is not None, "FakeAnalyzer sem análise configurada"
        return self.analysis


class FakeReleaseNotesAI:
    """Substitui o ``AIService`` no endpoint de release notes."""

    def __init__(self, markdown: str = "## Novas funcionalidades\n- Item (#1)", error: AIError | None = None) -> None:
        self.markdown = markdown
        self.error = error
        self.calls: list[list[int]] = []

    async def generate_release_notes(self, prs: Sequence[PullRequest]) -> str:
        self.calls.append([pr.number for pr in prs])
        if self.error is not None:
            raise self.error
        return self.markdown


class FakeTaskDispatcher:
    """Substitui ``enrich_pr_with_ai_task.delay`` e registra os PRs enfileirados."""

    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[Any] = []
        self._error = error

    def delay(self, pr_id: int) -> None:
        self.calls.append(pr_id)
        if self._error is not None:
            raise self._error
