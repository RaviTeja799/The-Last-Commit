"""SQLite persistence: one database for every ghost, plus an FTS5 index.

FTS5 is deliberate. The alternative is an embedding model, which is another
download, another runtime and another thing that can fail during a demo. A
3B model reading a few precisely retrieved commits produces better grounded
answers than the same model drowning in a fuzzy neighbourhood of them.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator

from .config import DB_PATH

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS repos (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    source      TEXT NOT NULL,
    head_sha    TEXT,
    analyzed_at TEXT NOT NULL,
    profile     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    repo_id    TEXT NOT NULL,
    id         TEXT NOT NULL,
    ord        INTEGER NOT NULL,
    kind       TEXT NOT NULL,
    title      TEXT NOT NULL,
    text       TEXT NOT NULL,
    commit_sha TEXT,
    path       TEXT,
    date       TEXT,
    author     TEXT,
    meta       TEXT,
    PRIMARY KEY (repo_id, id)
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
    repo_id UNINDEXED,
    chunk_id UNINDEXED,
    title,
    text,
    tokenize = 'porter unicode61'
);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


@contextmanager
def session() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def save_repo(repo_id: str, name: str, source: str, head_sha: str,
              analyzed_at: str, profile: dict[str, Any]) -> None:
    with session() as conn:
        conn.execute(
            "INSERT INTO repos (id, name, source, head_sha, analyzed_at, profile) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
            "name=excluded.name, source=excluded.source, head_sha=excluded.head_sha, "
            "analyzed_at=excluded.analyzed_at, profile=excluded.profile",
            (repo_id, name, source, head_sha, analyzed_at, json.dumps(profile)),
        )


def get_repo(repo_id: str) -> dict[str, Any] | None:
    with session() as conn:
        row = conn.execute("SELECT * FROM repos WHERE id = ?", (repo_id,)).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "source": row["source"],
        "head_sha": row["head_sha"],
        "analyzed_at": row["analyzed_at"],
        "profile": json.loads(row["profile"]),
    }


def list_repos() -> list[dict[str, Any]]:
    with session() as conn:
        rows = conn.execute(
            "SELECT id, name, source, head_sha, analyzed_at, profile FROM repos "
            "ORDER BY analyzed_at DESC"
        ).fetchall()
    out = []
    for row in rows:
        profile = json.loads(row["profile"])
        out.append({
            "id": row["id"],
            "name": row["name"],
            "source": row["source"],
            "head_sha": row["head_sha"],
            "analyzed_at": row["analyzed_at"],
            "commit_count": profile.get("commit_count"),
            "last_commit": profile.get("last_commit"),
            "silence_days": profile.get("silence_days"),
        })
    return out


def save_chunks(repo_id: str, chunks: list[dict[str, Any]]) -> None:
    with session() as conn:
        conn.execute("DELETE FROM chunks WHERE repo_id = ?", (repo_id,))
        conn.execute("DELETE FROM chunk_fts WHERE repo_id = ?", (repo_id,))
        for index, chunk in enumerate(chunks):
            conn.execute(
                "INSERT INTO chunks (repo_id, id, ord, kind, title, text, commit_sha, "
                "path, date, author, meta) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (repo_id, chunk["id"], index, chunk["kind"], chunk["title"],
                 chunk["text"], chunk.get("commit_sha"), chunk.get("path"),
                 chunk.get("date"), chunk.get("author"),
                 json.dumps(chunk.get("meta", {}))),
            )
            conn.execute(
                "INSERT INTO chunk_fts (repo_id, chunk_id, title, text) VALUES (?, ?, ?, ?)",
                (repo_id, chunk["id"], chunk["title"], chunk["text"]),
            )


def get_chunk(repo_id: str, chunk_id: str) -> dict[str, Any] | None:
    with session() as conn:
        row = conn.execute(
            "SELECT * FROM chunks WHERE repo_id = ? AND id = ?", (repo_id, chunk_id)
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"], "kind": row["kind"], "title": row["title"],
        "text": row["text"], "commit_sha": row["commit_sha"], "path": row["path"],
        "date": row["date"], "author": row["author"],
        "meta": json.loads(row["meta"] or "{}"),
    }


def count_chunks(repo_id: str) -> int:
    with session() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM chunks WHERE repo_id = ?", (repo_id,)
        ).fetchone()
    return int(row["n"])
