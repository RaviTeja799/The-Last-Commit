"""Runtime configuration. Everything is local; nothing here reads the network
unless you explicitly import a repository by URL."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("GHOST_DATA_DIR", ROOT / "data"))
REPOS_DIR = DATA_DIR / "repos"
DB_PATH = DATA_DIR / "ghosts.db"
FRONTEND_DIST = ROOT / "frontend" / "dist"

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
DEFAULT_MODEL = os.environ.get("GHOST_MODEL", "gemma3:4b")

# How much history we are willing to read. A repository with 20k commits is
# archaeology at a different scale; the first 220 commits are the readable part.
MAX_COMMITS = int(os.environ.get("GHOST_MAX_COMMITS", "220"))

for path in (DATA_DIR, REPOS_DIR):
    path.mkdir(parents=True, exist_ok=True)
