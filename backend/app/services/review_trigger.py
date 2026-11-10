"""Decisão de quando reavaliar um PR: novo push, menção ao bot ou resposta a uma thread do bot.

Funções puras, sem I/O, para que as regras de segurança sejam testáveis:
    * Anti-loop: eventos enviados pelo próprio bot da plataforma nunca disparam nada.
    * Comentários só disparam com menção ao bot ou resposta a um comentário que o bot publicou.
    * Debounce: no máximo uma reavaliação por PR a cada janela, via chave no Redis.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Protocol

PULL_REQUEST_EVENT: Final = "pull_request"
REVIEW_COMMENT_EVENT: Final = "pull_request_review_comment"
ISSUE_COMMENT_EVENT: Final = "issue_comment"
TRIGGER_EVENTS: Final = frozenset({PULL_REQUEST_EVENT, REVIEW_COMMENT_EVENT, ISSUE_COMMENT_EVENT})

# Handles aceitos na menção. O App se chama ``pr-insights-samuel``; ``pr-insights`` é o nome curto.
BOT_HANDLES: Final = ("pr-insights-samuel", "pr-insights")
DEBOUNCE_KEY: Final = "pr_review_lock:{tenant_id}:{pr_id}"


class ReanalysisTrigger(StrEnum):
    """Motivo da reavaliação. Fica registrado na revisão."""

    SYNCHRONIZE = "synchronize"
    MENTION = "mention"
    THREAD_REPLY = "thread_reply"
    COMMAND = "command"
    BOT_THREAD = "bot_thread"


# Comando explícito no início de uma linha: "/revisar" ou "/reavaliar".
COMMAND_PATTERN: Final = re.compile(r"^\s*/(revisar|reavaliar)\b", re.IGNORECASE | re.MULTILINE)


@dataclass(frozen=True, slots=True)
class TriggerDecision:
    """Reavaliação a disparar, com o PR identificado por repositório e número."""

    repository: str
    pr_number: int
    trigger: ReanalysisTrigger


def is_own_bot(sender: Mapping[str, Any] | None, app_slug: str) -> bool:
    """Verdadeiro quando o evento foi causado pelo próprio bot. Esses eventos são descartados."""
    if not sender:
        return False
    return sender.get("type") == "Bot" and str(sender.get("login", "")).lower() == f"{app_slug.lower()}[bot]"


def mentions_bot(body: str | None, app_slug: str) -> bool:
    """Procura ``@pr-insights-samuel`` ou ``@pr-insights`` como menção, sem casar com outros nomes."""
    if not body:
        return False
    handles = {app_slug.lower(), *BOT_HANDLES}
    pattern = re.compile(r"(?<![\w-])@(" + "|".join(re.escape(h) for h in sorted(handles, key=len, reverse=True)) + r")(?![\w-])", re.IGNORECASE)
    return pattern.search(body) is not None


def decide_pull_request(payload: Mapping[str, Any], app_slug: str) -> TriggerDecision | None:
    """Novo push em um PR aberto dispara reavaliação. Outras ações não disparam."""
    if is_own_bot(payload.get("sender"), app_slug):
        return None
    if payload.get("action") != "synchronize":
        return None
    pull_request = payload.get("pull_request") or {}
    if pull_request.get("merged") or pull_request.get("state") != "open":
        return None
    return _decision(payload, ReanalysisTrigger.SYNCHRONIZE)


def has_command(body: str | None) -> bool:
    """Verdadeiro quando o comentário traz o comando ``/revisar`` ou ``/reavaliar`` no início de uma linha."""
    return bool(body) and COMMAND_PATTERN.search(body or "") is not None


def decide_comment(
    event_name: str,
    payload: Mapping[str, Any],
    app_slug: str,
    bot_comment_ids: frozenset[int],
    bot_recently_active: bool = False,
) -> TriggerDecision | None:
    """Comentário criado dispara reavaliação por uma de quatro vias, nesta ordem:

    1. comando ``/revisar`` ou ``/reavaliar``;
    2. menção ao bot (``@pr-insights-samuel`` ou ``@pr-insights``);
    3. resposta a um comentário que a plataforma publicou (review comment);
    4. comentário geral num PR em que a plataforma falou nas últimas horas (``bot_recently_active``).

    ``bot_comment_ids`` são os ids dos comentários que a plataforma já publicou neste PR.
    """
    if is_own_bot(payload.get("sender"), app_slug):
        return None
    if payload.get("action") != "created":
        return None
    # Comentário em issue comum não é de PR: ``issue_comment`` só vale quando o issue é um PR.
    if event_name == ISSUE_COMMENT_EVENT and not (payload.get("issue") or {}).get("pull_request"):
        return None
    comment = payload.get("comment") or {}
    body = comment.get("body")
    if has_command(body):
        return _decision(payload, ReanalysisTrigger.COMMAND)
    if mentions_bot(body, app_slug):
        return _decision(payload, ReanalysisTrigger.MENTION)
    parent = comment.get("in_reply_to_id")
    if event_name == REVIEW_COMMENT_EVENT and isinstance(parent, int) and parent in bot_comment_ids:
        return _decision(payload, ReanalysisTrigger.THREAD_REPLY)
    if event_name == ISSUE_COMMENT_EVENT and bot_recently_active:
        return _decision(payload, ReanalysisTrigger.BOT_THREAD)
    return None


def decide(
    event_name: str,
    payload: Mapping[str, Any],
    app_slug: str,
    bot_comment_ids: frozenset[int] = frozenset(),
    bot_recently_active: bool = False,
) -> TriggerDecision | None:
    """Ponto de entrada: escolhe a regra de acordo com o evento."""
    if event_name == PULL_REQUEST_EVENT:
        return decide_pull_request(payload, app_slug)
    if event_name in (REVIEW_COMMENT_EVENT, ISSUE_COMMENT_EVENT):
        return decide_comment(event_name, payload, app_slug, bot_comment_ids, bot_recently_active)
    return None


def acquire_debounce(client: DebounceClient, *, tenant_id: int, pull_request_id: int, ttl_seconds: int) -> bool:
    """Tenta a trava do PR. ``True`` quando ela foi obtida; ``False`` se outra reavaliação está na janela."""
    key = DEBOUNCE_KEY.format(tenant_id=tenant_id, pr_id=pull_request_id)
    return bool(client.set(key, "1", nx=True, ex=ttl_seconds))


class DebounceClient(Protocol):
    def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> Any: ...


def _decision(payload: Mapping[str, Any], trigger: ReanalysisTrigger) -> TriggerDecision | None:
    repository = (payload.get("repository") or {}).get("full_name")
    number = (
        payload.get("number")
        or (payload.get("pull_request") or {}).get("number")
        or (payload.get("issue") or {}).get("number")
    )
    if not isinstance(repository, str) or not isinstance(number, int):
        return None
    return TriggerDecision(repository=repository, pr_number=number, trigger=trigger)


def pr_reference(event_name: str, payload: Mapping[str, Any]) -> tuple[str, int] | None:
    """Repositório e número do PR a que o evento se refere, ou ``None`` para evento que não é de PR."""
    if event_name == ISSUE_COMMENT_EVENT and not (payload.get("issue") or {}).get("pull_request"):
        return None
    decision = _decision(payload, ReanalysisTrigger.MENTION)
    if decision is None:
        return None
    return decision.repository, decision.pr_number
