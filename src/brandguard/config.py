"""Runtime configuration: one place that knows where the repo root is and how
secrets reach the process.

Every module that needs a key (the LLM adjudicators, the Serper client, the
registry) used to read ``.env`` relative to the current working directory,
which silently broke when the program was started from another folder (an API
server, a scheduled task, a Docker entrypoint). This module resolves the repo
root from its own location, so ``.env`` is found wherever the process starts.

Real environment variables always win; ``.env`` only fills gaps. That mirrors
how CI and production inject secrets, so a developer laptop and a deployed
run never diverge in behaviour.
"""

from __future__ import annotations

import os
from pathlib import Path

# src/brandguard/config.py -> src/brandguard -> src -> repo root
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

_loaded: set[Path] = set()


def env_file() -> Path:
    """The .env file consulted for secrets. Overridable for tests and deployments."""
    override = os.environ.get("BRANDGUARD_ENV_FILE")
    return Path(override) if override else REPO_ROOT / ".env"


def load_dotenv(path: Path | None = None) -> None:
    """Fill gaps in os.environ from the .env file (idempotent, never overrides).

    Accepts a BOM (Windows editors add one), quotes around values, comments and
    blank lines. Called by every credential-using entry point, so the order in
    which modules are imported does not matter.
    """
    target = (path or env_file()).resolve()
    if target in _loaded:
        return
    _loaded.add(target)
    if not target.exists():
        return
    for line in target.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def setting(name: str, default: str | None = None) -> str | None:
    """Read one setting after making sure .env has been consulted."""
    load_dotenv()
    return os.environ.get(name, default)


def data_dir() -> Path:
    return Path(setting("BRANDGUARD_DATA_DIR", str(REPO_ROOT / "data")))


def database_url() -> str:
    """SQLAlchemy URL for the product database. SQLite under data/ by default."""
    return setting("BRANDGUARD_DATABASE_URL", f"sqlite:///{data_dir() / 'brandguard.db'}")
