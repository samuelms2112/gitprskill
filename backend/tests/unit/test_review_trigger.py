"""Testes das regras de reavaliação: anti-loop, menção ao bot, resposta a thread e debounce."""

from typing import Any

import pytest

from app.services.review_trigger import (
    ISSUE_COMMENT_EVENT,
    PULL_REQUEST_EVENT,
    REVIEW_COMMENT_EVENT,
    ReanalysisTrigger,
    acquire_debounce,
    decide,
    is_own_bot,
    mentions_bot,
)

APP = "pr-insights-samuel"
BOT = {"login": "pr-insights-samuel[bot]", "type": "Bot"}
DEV = {"login": "devtip", "type": "User"}
REPO = {"full_name": "TIP-BRASIL/MVNO_ISPS_BRASIL"}


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> bool | None:
        if nx and key in self.data:
            return None
        self.data[key] = value
        return True


def _pull_request_event(action: str, sender: dict[str, Any] = DEV, **pr: Any) -> dict[str, Any]:
    pull_request = {"number": 889, "state": "open", "merged": False, **pr}
    return {"action": action, "sender": sender, "number": 889, "pull_request": pull_request, "repository": REPO}


def _issue_comment(body: str, sender: dict[str, Any] = DEV, *, is_pr: bool = True) -> dict[str, Any]:
    issue: dict[str, Any] = {"number": 889}
    if is_pr:
        issue["pull_request"] = {"url": "https://api.github.com/x"}
    return {"action": "created", "sender": sender, "issue": issue, "comment": {"id": 5, "body": body}, "repository": REPO}


def _review_comment(body: str, *, parent: int | None = None, sender: dict[str, Any] = DEV) -> dict[str, Any]:
    comment: dict[str, Any] = {"id": 9, "body": body, "in_reply_to_id": parent}
    return {"action": "created", "sender": sender, "comment": comment, "pull_request": {"number": 889}, "repository": REPO}


# --- Anti-loop -----------------------------------------------------------------------------


def test_own_bot_is_detected_by_login_and_type() -> None:
    assert is_own_bot(BOT, APP) is True
    assert is_own_bot({"login": "PR-INSIGHTS-SAMUEL[bot]", "type": "Bot"}, APP) is True


def test_other_bots_and_users_are_not_the_own_bot() -> None:
    assert is_own_bot({"login": "dependabot[bot]", "type": "Bot"}, APP) is False
    assert is_own_bot({"login": "pr-insights-samuel", "type": "User"}, APP) is False
    assert is_own_bot(None, APP) is False


def test_own_bot_push_is_ignored() -> None:
    assert decide(PULL_REQUEST_EVENT, _pull_request_event("synchronize", sender=BOT), APP) is None


def test_own_bot_mention_is_ignored_even_with_handle() -> None:
    assert decide(ISSUE_COMMENT_EVENT, _issue_comment("oi @pr-insights", sender=BOT), APP) is None


def test_own_bot_reply_is_ignored() -> None:
    payload = _review_comment("ok", parent=5, sender=BOT)
    assert decide(REVIEW_COMMENT_EVENT, payload, APP, frozenset({5})) is None


# --- Menção ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        "@pr-insights-samuel pode reavaliar?",
        "@pr-insights, olha isso",
        "fala com @PR-INSIGHTS",
        "(@pr-insights)",
    ],
)
def test_mention_of_the_bot_is_detected(body: str) -> None:
    assert mentions_bot(body, APP) is True


@pytest.mark.parametrize(
    "body",
    [
        "pr-insights sem arroba",
        "@pr-insights-samuel-antigo",
        "@pr-insightsx",
        "email@pr-insights.com",
        "",
        None,
    ],
)
def test_text_that_only_resembles_a_mention_is_not_a_mention(body: str | None) -> None:
    assert mentions_bot(body, APP) is False


def test_comment_with_mention_triggers_mention() -> None:
    decision = decide(ISSUE_COMMENT_EVENT, _issue_comment("@pr-insights-samuel corrigi o retry"), APP)

    assert decision is not None
    assert decision.trigger is ReanalysisTrigger.MENTION
    assert decision.pr_number == 889
    assert decision.repository == "TIP-BRASIL/MVNO_ISPS_BRASIL"


def test_comment_without_mention_does_not_trigger() -> None:
    assert decide(ISSUE_COMMENT_EVENT, _issue_comment("LGTM, valeu"), APP) is None


def test_issue_comment_on_a_plain_issue_does_not_trigger() -> None:
    assert decide(ISSUE_COMMENT_EVENT, _issue_comment("@pr-insights-samuel oi", is_pr=False), APP) is None


def test_edited_or_deleted_comments_do_not_trigger() -> None:
    payload = _issue_comment("@pr-insights-samuel oi")
    payload["action"] = "edited"
    assert decide(ISSUE_COMMENT_EVENT, payload, APP) is None


# --- Resposta a thread do bot -------------------------------------------------------------


def test_reply_to_a_bot_thread_triggers_without_mention() -> None:
    decision = decide(REVIEW_COMMENT_EVENT, _review_comment("feito, era isso", parent=77), APP, frozenset({77}))

    assert decision is not None
    assert decision.trigger is ReanalysisTrigger.THREAD_REPLY


def test_reply_to_a_developer_thread_does_not_trigger() -> None:
    assert decide(REVIEW_COMMENT_EVENT, _review_comment("concordo", parent=12), APP, frozenset({77})) is None


def test_reply_to_bot_thread_only_applies_to_review_comments() -> None:
    payload = _issue_comment("feito")
    payload["comment"]["in_reply_to_id"] = 77
    assert decide(ISSUE_COMMENT_EVENT, payload, APP, frozenset({77})) is None


# --- Push ------------------------------------------------------------------------------------


def test_synchronize_on_open_pr_triggers() -> None:
    decision = decide(PULL_REQUEST_EVENT, _pull_request_event("synchronize"), APP)

    assert decision is not None
    assert decision.trigger is ReanalysisTrigger.SYNCHRONIZE


@pytest.mark.parametrize("action", ["opened", "closed", "reopened", "edited"])
def test_other_pull_request_actions_do_not_trigger(action: str) -> None:
    assert decide(PULL_REQUEST_EVENT, _pull_request_event(action), APP) is None


def test_synchronize_on_merged_or_closed_pr_does_not_trigger() -> None:
    assert decide(PULL_REQUEST_EVENT, _pull_request_event("synchronize", merged=True), APP) is None
    assert decide(PULL_REQUEST_EVENT, _pull_request_event("synchronize", state="closed"), APP) is None


def test_unknown_event_never_triggers() -> None:
    assert decide("push", {"action": "created", "sender": DEV}, APP) is None


# --- Debounce ----------------------------------------------------------------------------------


def test_debounce_allows_one_review_per_window_per_pr() -> None:
    redis = FakeRedis()

    assert acquire_debounce(redis, tenant_id=1, pull_request_id=9, ttl_seconds=180) is True
    assert acquire_debounce(redis, tenant_id=1, pull_request_id=9, ttl_seconds=180) is False


def test_debounce_is_scoped_by_tenant_and_pr() -> None:
    redis = FakeRedis()

    assert acquire_debounce(redis, tenant_id=1, pull_request_id=9, ttl_seconds=180) is True
    assert acquire_debounce(redis, tenant_id=1, pull_request_id=10, ttl_seconds=180) is True
    assert acquire_debounce(redis, tenant_id=2, pull_request_id=9, ttl_seconds=180) is True
