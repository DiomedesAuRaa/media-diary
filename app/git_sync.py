from __future__ import annotations

import logging
import os
import subprocess
import threading

from app.config import REPO_ROOT, csv_path

logger = logging.getLogger(__name__)

_last_sync_error: str | None = None
_last_sync_ok: bool | None = None


def git_sync_enabled() -> bool:
    return os.environ.get("GIT_SYNC_ENABLED", "false").lower() in {"1", "true", "yes"}


def get_sync_status() -> dict[str, str | bool | None]:
    return {
        "enabled": git_sync_enabled(),
        "last_ok": _last_sync_ok,
        "last_error": _last_sync_error,
    }


def _run_git(args: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _push_env() -> dict[str, str]:
    return os.environ.copy()


def _push_url(remote: str) -> str | None:
    result = _run_git(["remote", "get-url", remote])
    if result.returncode != 0:
        return None
    url = result.stdout.strip()
    token = os.environ.get("GIT_PUSH_TOKEN", "").strip()
    if not token or url.startswith("git@"):
        return url
    if url.startswith("https://") and "@" not in url.removeprefix("https://"):
        return "https://x-access-token:" + token + "@" + url.removeprefix("https://")
    return url


def sync_csv(media_type: str, message: str) -> None:
    global _last_sync_error, _last_sync_ok

    if not git_sync_enabled():
        _last_sync_ok = None
        _last_sync_error = None
        return

    relative = csv_path(media_type).relative_to(REPO_ROOT)
    add_result = _run_git(["add", str(relative)])
    if add_result.returncode != 0:
        _last_sync_ok = False
        _last_sync_error = add_result.stderr.strip() or add_result.stdout.strip()
        logger.error("git add failed: %s", _last_sync_error)
        return

    diff_result = _run_git(["diff", "--cached", "--quiet"])
    if diff_result.returncode == 0:
        _last_sync_ok = True
        _last_sync_error = None
        return

    commit_result = _run_git(["commit", "-m", message])
    if commit_result.returncode != 0:
        _last_sync_ok = False
        _last_sync_error = commit_result.stderr.strip() or commit_result.stdout.strip()
        logger.error("git commit failed: %s", _last_sync_error)
        return

    remote = os.environ.get("GIT_REMOTE", "origin")
    branch = os.environ.get("GIT_BRANCH", "main")
    push_args = ["push", remote, branch]
    push_url = _push_url(remote)
    if push_url and push_url.startswith("https://") and "x-access-token:" in push_url:
        push_args = ["push", push_url, f"HEAD:{branch}"]

    push_result = _run_git(push_args, env=_push_env())
    if push_result.returncode != 0:
        _last_sync_ok = False
        _last_sync_error = push_result.stderr.strip() or push_result.stdout.strip()
        logger.error("git push failed: %s", _last_sync_error)
        return

    _last_sync_ok = True
    _last_sync_error = None


def sync_csv_async(media_type: str, message: str) -> None:
    thread = threading.Thread(target=sync_csv, args=(media_type, message), daemon=True)
    thread.start()
