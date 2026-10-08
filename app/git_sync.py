from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import subprocess
import tempfile
import threading
from datetime import datetime, timezone

from app.config import REPO_ROOT, SYNC_STATE_PATH, get_enabled_types
from app.csv_store import storage_lock
from app.backups import create_backup

logger = logging.getLogger(__name__)
_status_lock = threading.RLock()
_wake = threading.Event()
_stop = threading.Event()
_worker: threading.Thread | None = None
_status = {"last_ok": None, "last_error": None, "last_success_at": None, "pending": True}
_message = "Update media diary data"
_generation = 0


class SyncError(RuntimeError):
    pass


def git_sync_enabled() -> bool:
    return os.environ.get("GIT_SYNC_ENABLED", "false").lower() in {"1", "true", "yes"}


def get_sync_status() -> dict:
    with _status_lock:
        return {"enabled": git_sync_enabled(), **_status}


def _save_status(**values) -> None:
    with _status_lock:
        _status.update(values)
        payload = dict(_status)
        SYNC_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".sync-", dir=SYNC_STATE_PATH.parent)
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(payload, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, SYNC_STATE_PATH)
        finally:
            if os.path.exists(name):
                os.unlink(name)


def _run_git(args: list[str], allowed: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            ["git", "-c", f"safe.directory={REPO_ROOT}", *args],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=45,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SyncError("Git operation unavailable or timed out; publication will retry") from exc
    if result.returncode not in allowed:
        # Never return/log stderr: remotes, provider URLs and credential helpers may contain secrets.
        raise SyncError("Git publication failed; check credentials or remote divergence; retry scheduled")
    return result


def sync_csv(media_type: str = "", message: str = "Update media diary data") -> None:
    if not git_sync_enabled():
        return
    with _status_lock:
        generation = _generation
    paths = sorted({config[key] for config in get_enabled_types().values() for key in ("csv", "watchlist_csv")})
    try:
        # This is also the lock used by application writes. The network push runs outside it.
        with storage_lock:
            current_branch = _run_git(["branch", "--show-current"]).stdout.strip()
            branch = os.environ.get("GIT_BRANCH", "main")
            if current_branch != branch:
                raise SyncError("Runtime checkout is on the wrong branch; publication paused")
            staged = _run_git(["diff", "--cached", "--name-only", "-z"]).stdout.split("\0")
            if any(path and path not in paths for path in staged):
                raise SyncError("Unexpected staged files; publication paused for review")
            _run_git(["add", "-A", "--", *paths])
            changed = _run_git(["diff", "--cached", "--quiet", "--", *paths], (0, 1))
            if changed.returncode == 1:
                _run_git(["commit", "-m", message, "--", *paths])
        # Always push, even if the CSV diff is empty: an earlier failed push may have committed locally.
        _run_git(["push", os.environ.get("GIT_REMOTE", "origin"), f"HEAD:refs/heads/{branch}"])
        with _status_lock:
            pending = _generation != generation
            _save_status(last_ok=True, last_error=None, pending=pending,
                         last_success_at=datetime.now(timezone.utc).isoformat())
    except SyncError as exc:
        _save_status(last_ok=False, last_error=str(exc), pending=True)
        logger.warning("%s", exc)


def sync_csv_async(media_type: str, message: str) -> None:
    global _message, _generation
    if not git_sync_enabled():
        return
    with _status_lock:
        _message = message
        _generation += 1
    try:
        _save_status(pending=True)
    except OSError:
        logger.error("Publication status storage unavailable; data remains saved locally")
    _wake.set()


def _loop() -> None:
    while not _stop.is_set():
        _wake.wait(timeout=60)
        _wake.clear()
        if _stop.is_set():
            break
        with _status_lock:
            message = _message
        try:
            sync_csv(message=message)
        except OSError:
            logger.error("Publication status storage unavailable")
        try:
            backup_time = create_backup()
            if backup_time:
                _save_status(backup_last_success_at=backup_time, backup_last_error=None)
        except (OSError, ValueError):
            _save_status(backup_last_error="Local backup failed; operator review needed")
            logger.error("Local recovery snapshot failed")


def start_sync_worker() -> None:
    global _worker
    if (not git_sync_enabled() and not os.environ.get("BACKUP_ROOT")) or (_worker and _worker.is_alive()):
        return
    try:
        saved = json.loads(SYNC_STATE_PATH.read_text())
        with _status_lock:
            for key in _status:
                if key in saved:
                    _status[key] = saved[key]
    except (OSError, ValueError):
        pass
    _stop.clear()
    _wake.set()
    _worker = threading.Thread(target=_loop, name="diary-publication", daemon=True)
    _worker.start()


def stop_sync_worker() -> None:
    _stop.set()
    _wake.set()
    if _worker:
        _worker.join(timeout=5)
