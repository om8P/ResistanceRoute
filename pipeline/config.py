"""Shared paths and settings for AMR-Navigator.

Every module imports paths and connection settings from here instead of
hard-coding them. Owned by the orchestrator (task T00); see docs/CONTRACTS.md.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT: Path = Path(__file__).resolve().parent.parent

DATA_DIR: Path = ROOT / "data"
DATA_RAW: Path = DATA_DIR / "raw"
DATA_PROCESSED: Path = DATA_DIR / "processed"
DATA_CURATED: Path = DATA_DIR / "curated"
SCHEMA_DIR: Path = ROOT / "schema"
EVAL_DIR: Path = ROOT / "eval"


def _load_dotenv(path: Path) -> None:
    """Load KEY=VALUE lines from a .env file without overriding real env vars."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")

NEO4J_URI: str = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER: str = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD: str = os.environ.get("NEO4J_PASSWORD", "amrnavigator")

# Sent with every outbound HTTP request. Never add a name or email address.
USER_AGENT: str = "amr-navigator/0.1"
HTTP_TIMEOUT_SECONDS: int = 60
