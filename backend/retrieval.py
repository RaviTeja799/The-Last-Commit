"""Retrieval over repository memories.

Lexical first, with intent-aware anchors. A question about abandonment should
retrieve the last commit, the branch that never merged and the skipped test
even if the word "abandon" appears nowhere in the repository — which it
never does.
"""

from __future__ import annotations

import re
from typing import Any

from . import db

STOPWORDS = set("""
a about above after again against all also am an and any are as at be because
been before being below between both but by can cannot could did do does doing
down during each few for from further had has have having he her here hers him
his how i if in into is it its itself just me more most my no nor not now of off
on once only or other our out over own same she should so some such than that
the their them then there these they this those through to too under until up
very was we were what when where which while who whom why will with would you
your tell show give please something anything much many really does
""".split())

INTENTS = {
    "abandon": re.compile(
        r"abandon|why .*(stop|left|leave|end)|gave? up|give up|silence|quiet|"
        r"dead|died|last commit|disappear|forgot|forgotten|ghost|haunt|nobody",
        re.I),
    "repair": re.compile(
        r"fix|bug|broken|next|roadmap|revive|resurrect|finish|implement|todo|"
        r"blocked|stuck|improve|continue|bring .* back|take", re.I),
    "origin": re.compile(
        r"when|first|begin|start|created|oldest|history|timeline|year|early|origin",
        re.I),
}

CAPS = {"profile": 1, "commit": 4, "todo": 3, "doc": 2, "file": 2, "test": 1, "branch": 1}


def _terms(query: str) -> list[str]:
    words = re.findall(r"[A-Za-z0-9_]{2,}", query.lower())
    seen: list[str] = []
    for word in words:
        if word in STOPWORDS or word in seen:
            continue
        seen.append(word)
    return seen[:12]


def _match_query(query: str) -> str | None:
    terms = _terms(query)
    if not terms:
        return None
    return " OR ".join(f"{term}*" for term in terms)


def _fts(repo_id: str, query: str, limit: int = 30) -> list[dict[str, Any]]:
    match = _match_query(query)
    if not match:
        return []
    with db.session() as conn:
        rows = conn.execute(
            "SELECT c.id, c.kind, c.title, c.text, c.commit_sha, c.path, c.date, "
            "c.author, c.meta, -bm25(chunk_fts) AS score "
            "FROM chunk_fts JOIN chunks c "
            "  ON c.repo_id = chunk_fts.repo_id AND c.id = chunk_fts.chunk_id "
            "WHERE chunk_fts MATCH ? AND chunk_fts.repo_id = ? "
            "ORDER BY bm25(chunk_fts) LIMIT ?",
            (match, repo_id, limit),
        ).fetchall()
    import json
    return [{
        "id": row["id"], "kind": row["kind"], "title": row["title"],
        "text": row["text"], "commit_sha": row["commit_sha"], "path": row["path"],
        "date": row["date"], "author": row["author"],
        "meta": json.loads(row["meta"] or "{}"), "score": round(row["score"], 3),
    } for row in rows]


def _keyword_docs(repo_id: str, phrases: list[str], limit: int = 2) -> list[dict[str, Any]]:
    """Documentation that says the quiet part out loud ("never merged", "gave
    up", "coming soon") is often the best answer to "what happened?"."""
    import json
    clauses = " OR ".join("c.text LIKE ?" for _ in phrases)
    params = [repo_id] + [f"%{phrase}%" for phrase in phrases] + [limit]
    with db.session() as conn:
        rows = conn.execute(
            "SELECT c.id, c.kind, c.title, c.text, c.commit_sha, c.path, c.date, "
            "c.author, c.meta FROM chunks c WHERE c.repo_id = ? AND c.kind = 'doc' "
            f"AND ({clauses}) LIMIT ?", params,
        ).fetchall()
    return [{
        "id": row["id"], "kind": row["kind"], "title": row["title"],
        "text": row["text"], "commit_sha": row["commit_sha"], "path": row["path"],
        "date": row["date"], "author": row["author"],
        "meta": json.loads(row["meta"] or "{}"), "score": 0,
    } for row in rows]


def _path_chunks(repo_id: str, query: str) -> list[str]:
    """If the question names a file ("storage", "daemon"), retrieve that file."""
    terms = _terms(query)
    if not terms:
        return []
    with db.session() as conn:
        rows = conn.execute(
            "SELECT id, path FROM chunks WHERE repo_id = ? AND kind = 'file'", (repo_id,)
        ).fetchall()
    hits = []
    for row in rows:
        stem = row["path"].rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()
        if stem and any(term == stem or term in stem for term in terms):
            hits.append(row["id"])
    return hits[:2]


def _load(repo_id: str, chunk_id: str) -> dict[str, Any] | None:
    chunk = db.get_chunk(repo_id, chunk_id)
    if chunk:
        chunk["score"] = 0
    return chunk


def _anchor_ids(profile: dict[str, Any], repo_id: str, query: str) -> list[str]:
    ids: list[str] = ["profile:summary"]
    commits = profile["commits"]

    if INTENTS["abandon"].search(query):
        if commits:
            ids.append(f"commit:{commits[-1]['sha'][:10]}")
        for branch in profile["branches"][:1]:
            ids.append(f"branch:{branch['name']}")
        for skip in profile["skipped_tests"][:1]:
            ids.append(f"test:{skip['path']}:{skip['line']}")
        gap = profile.get("biggest_gap")
        if gap:
            for commit in commits:
                if commit["sha"][:7] == gap["from"] or commit["sha"][:7] == gap["to"]:
                    ids.append(f"commit:{commit['sha'][:10]}")
                    break
        for todo in profile["todos"][:1]:
            ids.append(f"todo:{todo['path']}:{todo['line']}")
        for chunk in _keyword_docs(repo_id, ["not merged", "gave up", "give up",
                                             "unfinished", "coming soon"], 2):
            ids.append(chunk["id"])

    if INTENTS["repair"].search(query):
        ordered = sorted(
            profile["todos"],
            key=lambda t: (t["keyword"] != "FIXME", t["keyword"] != "TODO"),
        )
        for todo in ordered[:3]:
            ids.append(f"todo:{todo['path']}:{todo['line']}")
        for branch in profile["branches"][:1]:
            ids.append(f"branch:{branch['name']}")

    ids.extend(_path_chunks(repo_id, query))

    if INTENTS["origin"].search(query) and commits:
        ids.append(f"commit:{commits[0]['sha'][:10]}")
        gap = profile.get("biggest_gap")
        if gap:
            for commit in commits:
                if commit["sha"][:7] == gap["to"]:
                    ids.append(f"commit:{commit['sha'][:10]}")
                    break

    return ids


def select_evidence(profile: dict[str, Any], repo_id: str, query: str,
                    limit: int = 8) -> list[dict[str, Any]]:
    """Intent anchors first, then lexical hits, deduped and capped by kind."""
    hits = _fts(repo_id, query, 40)
    by_id = {hit["id"]: hit for hit in hits}

    ordered: list[dict[str, Any]] = []
    for chunk_id in _anchor_ids(profile, repo_id, query):
        chunk = by_id.get(chunk_id) or _load(repo_id, chunk_id)
        if chunk:
            chunk["anchored"] = True
            ordered.append(chunk)

    for hit in hits:
        ordered.append(hit)

    # A last-commit memory is always worth one slot.
    if profile["commits"]:
        last_id = f"commit:{profile['commits'][-1]['sha'][:10]}"
        if last_id not in {c["id"] for c in ordered}:
            chunk = _load(repo_id, last_id)
            if chunk:
                ordered.append(chunk)

    selected: list[dict[str, Any]] = []
    per_kind: dict[str, int] = {}
    seen: set[str] = set()
    for chunk in ordered:
        if chunk["id"] in seen:
            continue
        cap = CAPS.get(chunk["kind"], 2)
        if per_kind.get(chunk["kind"], 0) >= cap:
            continue
        per_kind[chunk["kind"]] = per_kind.get(chunk["kind"], 0) + 1
        seen.add(chunk["id"])
        selected.append(chunk)
        if len(selected) >= limit:
            break
    return selected


def to_refs(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Number the evidence the way the prompt and the answer will refer to it."""
    refs = []
    for index, chunk in enumerate(evidence, start=1):
        refs.append({
            "ref": f"C{index}",
            "id": chunk["id"],
            "kind": chunk["kind"],
            "title": chunk["title"],
            "path": chunk.get("path"),
            "date": chunk.get("date"),
            "author": chunk.get("author"),
            "commit_sha": chunk.get("commit_sha"),
            "preview": " ".join(chunk["text"].split())[:240],
            "anchored": bool(chunk.get("anchored")),
            "meta": chunk.get("meta", {}),
        })
    return refs
