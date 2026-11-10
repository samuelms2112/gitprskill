"""Gatilhos de reavaliação: comando /revisar, conversa com o bot e os casos que continuam bloqueados."""

from typing import Any

import pytest

from app.services.review_trigger import (
    ISSUE_COMMENT_EVENT,
    PULL_REQUEST_EVENT,
    REVIEW_COMMENT_EVENT,
    ReanalysisTrigger,
    decide,
    has_command,
)

APP = "pr-insights-samuel"
BOT = {"login": "pr-insights-samuel[bot]", "type": "Bot"}
DEV = {"login": "devtip", "type": "User"}
REPO = {"full_name": "TIP-BRASIL/MVNO_ISPS_BRASIL"}


def _issue_comment(body: str, sender: dict[str, Any] = DEV) -> dict[str, Any]:
    return {
        "action": "created",
        "sender": sender,
        "issue": {"number": 890, "pull_request": {"url": "https://api.github.com/x"}},
        "comment": {"id": 5, "body": body},
        "repository": REPO,
    }


def _review_comment(body: str, parent: int | None = None, sender: dict[str, Any] = DEV) -> dict[str, Any]:
    return {
        "action": "created",
        "sender": sender,
        "comment": {"id": 9, "body": body, "in_reply_to_id": parent},
        "pull_request": {"number": 890},
        "repository": REPO,
    }


@pytest.mark.parametrize("body", ["/revisar", "/reavaliar agora", "texto\n  /REVISAR", "/Reavaliar\nobrigado"])
def test_command_at_start_of_line_is_detected(body: str) -> None:
    assert has_command(body) is True


@pytest.mark.parametrize("body", ["revisar isso", "/revisarx", "oi /revisar no meio", "", None])
def test_text_that_is_not_a_command_is_ignored(body: str | None) -> None:
    assert has_command(body) is False


def test_command_triggers_on_general_comment() -> None:
    decision = decide(ISSUE_COMMENT_EVENT, _issue_comment("/revisar"), APP)
    assert decision is not None
    assert decision.trigger is ReanalysisTrigger.COMMAND


def test_command_triggers_on_review_comment() -> None:
    decision = decide(REVIEW_COMMENT_EVENT, _review_comment("/reavaliar"), APP)
    assert decision is not None
    assert decision.trigger is ReanalysisTrigger.COMMAND


def test_command_takes_precedence_over_mention() -> None:
    decision = decide(ISSUE_COMMENT_EVENT, _issue_comment("@pr-insights-samuel\n/revisar"), APP)
    assert decision is not None
    assert decision.trigger is ReanalysisTrigger.COMMAND


def test_own_bot_cannot_trigger_with_a_command() -> None:
    assert decide(ISSUE_COMMENT_EVENT, _issue_comment("/revisar", sender=BOT), APP) is None


def test_general_comment_triggers_when_bot_was_recently_active() -> None:
    decision = decide(ISSUE_COMMENT_EVENT, _issue_comment("com isso podemos aprovar?"), APP, bot_recently_active=True)
    assert decision is not None
    assert decision.trigger is ReanalysisTrigger.BOT_THREAD


def test_general_comment_is_ignored_when_bot_is_not_active() -> None:
    assert decide(ISSUE_COMMENT_EVENT, _issue_comment("com isso podemos aprovar?"), APP, bot_recently_active=False) is None


def test_review_comment_without_parent_does_not_use_bot_thread_rule() -> None:
    assert decide(REVIEW_COMMENT_EVENT, _review_comment("concordo"), APP, bot_recently_active=True) is None


def test_bot_thread_rule_never_fires_for_own_bot() -> None:
    assert decide(ISSUE_COMMENT_EVENT, _issue_comment("oi", sender=BOT), APP, bot_recently_active=True) is None


def test_plain_pull_request_opened_ignores_bot_activity() -> None:
    payload = {"action": "opened", "sender": DEV, "number": 890, "pull_request": {"number": 890, "state": "open"}, "repository": REPO}
    assert decide(PULL_REQUEST_EVENT, payload, APP, bot_recently_active=True) is None
