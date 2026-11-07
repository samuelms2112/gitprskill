"""Testes unitários da regra de decisão e do parsing do evento ``pull_request``."""

import pytest

from app.schemas.github import PullRequestEventPayload
from app.services.pull_request_ingestion import IngestionOutcome, decide
from tests.factories.github import build_pull_request_event, with_changes

TRACKED = frozenset({"main", "master", "master-tip"})


def _event(**kwargs: object) -> PullRequestEventPayload:
    return PullRequestEventPayload.model_validate(build_pull_request_event(**kwargs))


def test_merged_pr_into_tracked_branch_is_processed() -> None:
    """PR mergeado em branch rastreada deve ser persistido."""
    assert decide(_event(base_ref="main"), TRACKED) is IngestionOutcome.PROCESSED


@pytest.mark.parametrize("branch", ["master", "master-tip"])
def test_all_default_tracked_branches_are_accepted(branch: str) -> None:
    """``master`` e ``master-tip`` também são destinos válidos."""
    assert decide(_event(base_ref=branch), TRACKED) is IngestionOutcome.PROCESSED


def test_untracked_branch_is_ignored() -> None:
    """Merges em feature branches não são registrados."""
    assert decide(_event(base_ref="develop"), TRACKED) is IngestionOutcome.IGNORED_BRANCH


def test_closed_without_merge_is_recorded_as_closed() -> None:
    """PR fechado sem merge também é gravado: o histórico de abertos e fechados é preservado."""
    assert decide(_event(merged=False), TRACKED) is IngestionOutcome.PROCESSED


@pytest.mark.parametrize("action", ["opened", "synchronize", "reopened"])
def test_lifecycle_actions_are_captured_from_opening(action: str) -> None:
    """A captura começa na abertura: abertura, novos commits e reabertura entram no sistema."""
    assert decide(_event(action=action, merged=False), TRACKED) is IngestionOutcome.PROCESSED


@pytest.mark.parametrize("action", ["edited", "labeled", "assigned"])
def test_metadata_only_actions_are_ignored(action: str) -> None:
    """Edições que não mudam o estado do PR não geram gravação."""
    assert decide(_event(action=action), TRACKED) is IngestionOutcome.IGNORED_ACTION


def test_parses_event_and_detects_merge_by_merged_at_only() -> None:
    """A listagem/evento pode trazer apenas ``merged_at``; ele basta para considerar mergeado."""
    payload = build_pull_request_event()
    payload["pull_request"].pop("merged")
    event = PullRequestEventPayload.model_validate(payload)
    assert event.pull_request.is_merged is True


def test_missing_stats_are_accepted_as_none() -> None:
    """Estatísticas ausentes (ex.: listagem) não invalidam o evento."""
    payload = build_pull_request_event()
    for key in ("additions", "deletions", "changed_files"):
        payload["pull_request"].pop(key)
    event = PullRequestEventPayload.model_validate(payload)
    assert event.pull_request.additions is None


def test_with_changes_does_not_mutate_original() -> None:
    """A fábrica de testes gera cópias independentes."""
    original = build_pull_request_event()
    changed = with_changes(original, action="opened")
    assert original["action"] == "closed"
    assert changed["action"] == "opened"
