from __future__ import annotations

import subprocess
from pathlib import Path


def get_git_commit(project_root: Path) -> str | None:
    """Best-effort current commit hash. Never raises; returns None if unavailable."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=10,
            check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    commit = result.stdout.strip()
    return commit or None
