"""Fábricas de payloads no formato real da API do GitHub, para testes."""

import copy
from typing import Any

DEFAULT_INSTALLATION_ID = 111
BASE_TIME = "2026-01-10T10:00:00Z"
MERGE_TIME = "2026-01-10T12:00:00Z"


def build_user(*, user_id: int = 7001, login: str = "dev-ana") -> dict[str, Any]:
    """Usuário do GitHub."""
    return {
        "id": user_id,
        "login": login,
        "avatar_url": f"https://avatars.githubusercontent.com/u/{user_id}?v=4",
        "html_url": f"https://github.com/{login}",
    }


def build_repository(
    *, repo_id: int = 555, owner: str = "org", name: str = "api", default_branch: str = "main"
) -> dict[str, Any]:
    """Repositório do GitHub."""
    return {
        "id": repo_id,
        "name": name,
        "full_name": f"{owner}/{name}",
        "owner": build_user(user_id=9001, login=owner),
        "html_url": f"https://github.com/{owner}/{name}",
        "default_branch": default_branch,
        "private": False,
    }


def build_pull_request(
    *,
    pr_id: int = 1001,
    number: int = 42,
    base_ref: str = "main",
    merged: bool = True,
    state: str = "closed",
    include_stats: bool = True,
    updated_at: str = MERGE_TIME,
) -> dict[str, Any]:
    """Objeto ``pull_request`` do GitHub, como vem em eventos e listagens."""
    pull_request: dict[str, Any] = {
        "id": pr_id,
        "number": number,
        "title": f"feat: alteração {number}",
        "body": "Descrição do PR",
        "state": state,
        "merged": merged,
        "merged_at": MERGE_TIME if merged else None,
        "created_at": BASE_TIME,
        "updated_at": updated_at,
        "closed_at": MERGE_TIME if state == "closed" else None,
        "html_url": f"https://github.com/org/api/pull/{number}",
        "user": build_user(),
        "head": {"ref": "feature/login"},
        "base": {"ref": base_ref},
    }
    if include_stats:
        pull_request.update({"additions": 10, "deletions": 2, "changed_files": 3})
    return pull_request


def build_pull_request_event(
    *,
    action: str = "closed",
    merged: bool = True,
    base_ref: str = "main",
    number: int = 42,
    pr_id: int = 1001,
    installation_id: int = DEFAULT_INSTALLATION_ID,
    repo_id: int = 555,
) -> dict[str, Any]:
    """Payload completo do evento ``pull_request`` do GitHub App."""
    return {
        "action": action,
        "number": number,
        "pull_request": build_pull_request(
            pr_id=pr_id, number=number, base_ref=base_ref, merged=merged
        ),
        "repository": build_repository(repo_id=repo_id),
        "installation": {"id": installation_id},
    }


def build_review_event(
    *,
    action: str = "submitted",
    review_state: str = "approved",
    base_ref: str = "main",
    review_id: int = 88001,
    installation_id: int = DEFAULT_INSTALLATION_ID,
    pr_merged: bool = False,
) -> dict[str, Any]:
    """Payload do evento ``pull_request_review``. ``review_state`` segue o webhook (minúsculas)."""
    return {
        "action": action,
        "review": {
            "id": review_id,
            "state": review_state,
            "body": "LGTM",
            "submitted_at": "2026-01-10T11:00:00Z",
            "user": build_user(user_id=7002, login="dev-bruno"),
        },
        "pull_request": build_pull_request(
            base_ref=base_ref, merged=pr_merged, state="closed" if pr_merged else "open"
        ),
        "repository": build_repository(),
        "installation": {"id": installation_id},
    }


def build_installation_repository(*, repo_id: int = 900, full_name: str = "acme/web", private: bool = True) -> dict[str, Any]:
    """Repositório como vem nos eventos de instalação (dados reduzidos)."""
    name = full_name.split("/", 1)[1]
    return {"id": repo_id, "name": name, "full_name": full_name, "private": private}


def build_installation_event(
    *,
    action: str = "created",
    installation_id: int = 5001,
    account_login: str = "acme",
    sender_id: int = 7001,
    sender_login: str = "dev-ana",
    repositories: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Payload do evento ``installation`` (instalação do GitHub App em uma conta)."""
    return {
        "action": action,
        "installation": {
            "id": installation_id,
            "account": build_user(user_id=9100, login=account_login),
        },
        "sender": build_user(user_id=sender_id, login=sender_login),
        "repositories": repositories or [],
    }


def build_installation_repositories_event(
    *,
    action: str = "added",
    installation_id: int = 5001,
    added: list[dict[str, Any]] | None = None,
    removed: list[dict[str, Any]] | None = None,
    sender_id: int = 7001,
    sender_login: str = "dev-ana",
) -> dict[str, Any]:
    """Payload do evento ``installation_repositories`` (repositórios incluídos ou removidos)."""
    return {
        "action": action,
        "installation": {
            "id": installation_id,
            "account": build_user(user_id=9100, login="acme"),
        },
        "sender": build_user(user_id=sender_id, login=sender_login),
        "repositories_added": added or [],
        "repositories_removed": removed or [],
    }


def with_changes(payload: dict[str, Any], **changes: Any) -> dict[str, Any]:
    """Cópia profunda do payload com alterações de primeiro nível, sem mutar o original."""
    clone = copy.deepcopy(payload)
    clone.update(changes)
    return clone
