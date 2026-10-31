"""Turn a profile into citable memories.

Every chunk is a small, self-contained piece of evidence with an id the model
can cite. Chunks are deliberately *verbatim*: the ghost is allowed to
interpret, but the evidence it points at is the repository talking.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .gitarch import GIT_ENV, GitError, _git

MAX_DOC_CHARS = 1500
HEADER_FILES = 10


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _commit_chunk(commit: dict[str, Any]) -> dict[str, Any]:
    files = ", ".join(commit["files"][:8]) or "(no files)"
    body = f"\n{commit['body']}" if commit["body"] else ""
    text = (
        f"commit {commit['short']} · {commit['date'][:10]} · {commit['author']}\n"
        f"message: {commit['subject']}{body}\n"
        f"files: {files}\n"
        f"churn: +{commit['insertions']} / -{commit['deletions']}\n"
    )
    if commit["patch_excerpt"]:
        text += f"diff excerpt:\n{commit['patch_excerpt']}"
    return {
        "id": f"commit:{commit['sha'][:10]}",
        "kind": "commit",
        "title": f"{commit['short']} · {commit['subject']}",
        "text": text,
        "commit_sha": commit["sha"],
        "path": commit["files"][0] if commit["files"] else None,
        "date": commit["date"],
        "author": commit["author"],
        "meta": {"short": commit["short"], "subject": commit["subject"],
                 "files": commit["files"][:8], "insertions": commit["insertions"],
                 "deletions": commit["deletions"], "body": commit["body"]},
    }


def _todo_chunk(todo: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"todo:{todo['path']}:{todo['line']}",
        "kind": "todo",
        "title": f"{todo['keyword']} · {todo['path']}:{todo['line']}",
        "text": (f"{todo['keyword']} in {todo['path']} at line {todo['line']}:\n"
                 f"{todo['raw']}"),
        "path": todo["path"],
        "meta": {"line": todo["line"], "keyword": todo["keyword"]},
    }


def _skip_chunk(skip: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"test:{skip['path']}:{skip['line']}",
        "kind": "test",
        "title": f"skipped test · {skip['path']}:{skip['line']}",
        "text": f"in {skip['path']} at line {skip['line']}:\n{skip['text']}",
        "path": skip["path"],
        "meta": {"line": skip["line"]},
    }


def _branch_chunk(branch: dict[str, Any]) -> dict[str, Any]:
    lines = [f"{c['short']} · {c['date'][:10]} · {c['subject']}" for c in branch["commits"]]
    return {
        "id": f"branch:{branch['name']}",
        "kind": "branch",
        "title": f"unmerged branch · {branch['name']} ({branch['ahead']} ahead)",
        "text": (f"branch {branch['name']} is {branch['ahead']} commits ahead of the "
                 f"default branch and was never merged:\n" + "\n".join(lines)),
        "meta": {"branch": branch["name"], "ahead": branch["ahead"]},
    }


def _doc_chunks(repo: Path, path: str) -> list[dict[str, Any]]:
    try:
        text = _git(repo, "show", f"HEAD:{path}")
    except GitError:
        return []
    parts = re.split(r"\n(?=#{1,3} )", text)
    chunks = []
    for index, part in enumerate(parts):
        part = part.strip()
        if len(part) < 40:
            continue
        heading = part.splitlines()[0].lstrip("# ").strip() or path
        chunks.append({
            "id": f"doc:{path}:{index}",
            "kind": "doc",
            "title": f"{path} · {_clip(heading, 70)}",
            "text": _clip(part, MAX_DOC_CHARS),
            "path": path,
            "meta": {"heading": heading},
        })
    return chunks


def _file_chunk(repo: Path, path: str, churn: int) -> dict[str, Any] | None:
    try:
        text = _git(repo, "show", f"HEAD:{path}")
    except GitError:
        return None
    lines = text.splitlines()
    head = "\n".join(lines[:45])
    return {
        "id": f"file:{path}",
        "kind": "file",
        "title": f"source · {path} ({len(lines)} lines)",
        "text": f"{path} as it exists at HEAD:\n{_clip(head, 1600)}",
        "path": path,
        "meta": {"churn": churn, "lines": len(lines)},
    }


def _profile_chunk(profile: dict[str, Any]) -> dict[str, Any]:
    authors = ", ".join(f"{a['name']} ({a['commits']} commits)" for a in profile["authors"][:6])
    tags = ", ".join(f"{t['name']} on {t['date'][:10]}" for t in profile["tags"][-2:])
    gap = profile.get("biggest_gap") or {}
    return {
        "id": "profile:summary",
        "kind": "profile",
        "title": f"repository profile · {profile['name']}",
        "text": (
            f"{profile['name']}: {profile['commit_count']} commits between "
            f"{profile['first_commit']['date'][:10]} and {profile['last_commit']['date'][:10]}, "
            f"across {profile['active_months']} active months.\n"
            f"authors: {authors}\n"
            f"last commit: {profile['last_commit']['subject']} "
            f"({profile['last_commit']['date'][:10]})\n"
            f"silence since then: {profile['silence_label']}\n"
            f"longest gap: {gap.get('days', 'n/a')} days "
            f"({str(gap.get('from_date', ''))[:10]} to {str(gap.get('to_date', ''))[:10]})\n"
            f"unmerged branches: "
            + (", ".join(b["name"] for b in profile["branches"]) or "none") + "\n"
            f"tags: {tags or 'none'}"
        ),
        "meta": {},
    }


def build_chunks(profile: dict[str, Any], repo: Path) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = [_profile_chunk(profile)]

    # Documentation first: it is where a project explains its own intentions.
    doc_paths = [f["path"] for f in profile["files"]
                 if f["path"].lower().endswith((".md", ".rst", ".txt"))
                 and f["size"] < 60_000][:6]
    if profile.get("readme_path") and profile["readme_path"] not in doc_paths:
        doc_paths.insert(0, profile["readme_path"])
    for path in doc_paths:
        chunks.extend(_doc_chunks(repo, path))

    for todo in profile["todos"]:
        chunks.append(_todo_chunk(todo))
    for skip in profile["skipped_tests"]:
        chunks.append(_skip_chunk(skip))
    for branch in profile["branches"]:
        chunks.append(_branch_chunk(branch))

    # Source headers, weighted by how often the file was touched.
    churn: dict[str, int] = {}
    for commit in profile["commits"]:
        for path in commit["files"]:
            churn[path] = churn.get(path, 0) + 1
    source = [f["path"] for f in profile["files"]
              if Path(f["path"]).suffix.lower() in (".py", ".js", ".ts", ".go", ".rs")
              and f["size"] < 40_000
              and "test" not in Path(f["path"]).name.lower()]
    source.sort(key=lambda p: churn.get(p, 0), reverse=True)
    for path in source[:HEADER_FILES]:
        chunk = _file_chunk(repo, path, churn.get(path, 0))
        if chunk:
            chunks.append(chunk)

    for commit in profile["commits"]:
        chunks.append(_commit_chunk(commit))

    return chunks
