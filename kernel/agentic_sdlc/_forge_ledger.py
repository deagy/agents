"""Internal shared ledger/lock durable-write primitives.

Extracted from `gate_issues.py` (which originally defined these inline) so
`gate_status.py` (`publish-gate-status` / `list-gate-status`) can reuse the
same discipline without copy-pasting ~80 lines. No public CLI surface of its
own -- both call sites keep their own forge-qualified filenames, ledger
schemas, and module-specific "blocked" exception types; this module only
supplies the filesystem mechanics:

- `write_ledger_file`: full-file rewrite, same-filesystem tmp file, fsync
  data, atomic rename, fsync the containing directory.
- `acquire_lock_file`/`release_lock_file`: `O_CREAT|O_EXCL` advisory lock,
  never auto-broken on timeout -- callers pass `break_lock=True` (an
  explicit `--break-lock` flag) to remove a stale lock file first.

This is a pure extraction: behavior, file paths, and permissions are
unchanged from `gate_issues.py`'s original inline implementation.
"""

from __future__ import annotations

import json
import os
import socket
import tempfile
from pathlib import Path
from typing import Any

from . import confined_path, now


class LedgerLockHeld(RuntimeError):
    """Raised by `acquire_lock_file` when the lock file already exists and
    `break_lock` was not requested. Callers catch this and re-raise their
    own module-specific "needs human resolution" exception (e.g.
    `GateIssuesBlocked`, `GateStatusBlocked`) with the same message, so each
    call site keeps its own exit-code mapping."""


def ledger_path(root: Path, overlay: str, task_id: str, filename: str) -> Path:
    return confined_path(root, overlay, "runs", task_id, filename)


def lock_path(root: Path, overlay: str, task_id: str, filename: str) -> Path:
    return confined_path(root, overlay, "runs", task_id, filename)


def write_ledger_file(path: Path, ledger: dict[str, Any], *, tmp_prefix: str) -> None:
    """Same durable-write sequence for every ledger sidecar in this
    repository: full-file rewrite, same-filesystem tmp file, fsync data,
    atomic rename, fsync the containing directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(ledger, indent=2, sort_keys=True) + "\n").encode("utf-8")

    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=tmp_prefix, suffix=".tmp")
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.chmod(tmp_name, 0o600)
    os.replace(tmp_name, path)

    dir_fd = os.open(str(path.parent), os.O_DIRECTORY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def acquire_lock_file(path: Path, *, break_lock: bool) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)

    if break_lock and path.is_file():
        path.unlink(missing_ok=True)

    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        holder = "(unreadable)"
        try:
            holder = path.read_text(encoding="utf-8")
        except OSError:
            pass
        raise LedgerLockHeld(
            f"{path.name} is already held -- pass --break-lock to override "
            f"(never auto-broken on timeout). Holder:\n{holder}"
        ) from None

    payload = json.dumps({"pid": os.getpid(), "host": socket.gethostname(), "started_at": now()}, indent=2)
    os.write(fd, payload.encode("utf-8"))
    os.close(fd)
    return path


def release_lock_file(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
