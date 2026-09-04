"""Detect when the database is sitting on storage that will not survive a restart.

Silent data loss is the worst kind. A SQLite file on a container's ephemeral
filesystem looks completely healthy until the service restarts, at which point
every engagement, artifact and approval is gone — and the only visible symptom
is stale ids in the browser producing "not found" on pages that worked minutes
earlier.

This module makes that condition explicit at startup and through the API.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

#: Mount points that platforms use for attached persistent disks.
KNOWN_PERSISTENT_MOUNTS = ("/var/data", "/data", "/mnt/data", "/persistent")


def _on_persistent_mount(path: Path) -> bool:
    """True when `path` sits under a directory that is genuinely a mount point.

    A declared mount path that was never attached is an ordinary directory, so
    checking `ismount` is what separates a real disk from a hopeful config.
    """
    resolved = path.resolve()
    for parent in [resolved, *resolved.parents]:
        try:
            if os.path.ismount(parent):
                # "/" is always a mount and is not a persistent volume.
                return str(parent) != "/"
        except OSError:
            continue
    return False


def assess(db_path: str | None = None, database_url: str | None = None) -> Dict[str, Any]:
    """Report whether persisted data will survive a restart."""
    url = (database_url if database_url is not None else os.getenv("DATABASE_URL", "")).strip()
    if url and not url.startswith("sqlite"):
        return {
            "durable": True,
            "backend": "external-database",
            "detail": "Data is stored in an external database and survives restarts.",
            "action": "",
        }

    raw = db_path if db_path is not None else os.getenv("CINVENT_DB_PATH", "data/cinvent.db")
    path = Path(raw)
    declared_persistent = any(str(path).startswith(m) for m in KNOWN_PERSISTENT_MOUNTS)
    attached = _on_persistent_mount(path)

    if declared_persistent and not attached:
        return {
            "durable": False,
            "backend": "sqlite",
            "path": str(path),
            "detail": (
                f"The database is configured at {path}, which looks like a persistent "
                f"disk mount but is not actually mounted. On most hosts this means the "
                f"path is ordinary container storage: every engagement, artifact and "
                f"approval is lost when the service restarts or redeploys."
            ),
            "action": (
                "Attach a persistent disk at that mount path (this requires a paid "
                "instance on Render), or point DATABASE_URL at a managed PostgreSQL "
                "database."
            ),
        }

    if not attached:
        return {
            "durable": False,
            "backend": "sqlite",
            "path": str(path),
            "detail": (
                f"The database is a SQLite file at {path} on non-persistent storage. "
                f"Data is lost when the container restarts."
            ),
            "action": "Attach a persistent disk, or set DATABASE_URL to a managed database.",
        }

    return {
        "durable": True,
        "backend": "sqlite",
        "path": str(path),
        "detail": f"SQLite at {path}, on an attached persistent disk.",
        "action": "",
    }


def warn_at_startup() -> Dict[str, Any]:
    """Print a visible banner when storage is not durable. Returns the assessment."""
    report = assess()
    if not report["durable"]:
        line = "!" * 72
        print(f"\n{line}")
        print("  DATA DURABILITY WARNING")
        print(f"  {report['detail']}")
        print(f"  {report['action']}")
        print(f"{line}\n")
    return report
