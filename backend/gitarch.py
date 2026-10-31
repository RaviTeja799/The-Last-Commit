"""Read a git repository like an excavation site.

No checkout, no execution, no network. Every function here shells out to
`git` with an explicit argument list and reads objects that already exist in
the repository. The output is a plain dictionary of *facts*, which is the
only thing the language model is ever allowed to reason from.
"""

from __future__ import annotations

import re
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import MAX_COMMITS

GIT_ENV = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_PAGER": "cat",
    "LC_ALL": "C.UTF-8",
    "HOME": "/tmp",
}

SOURCE_EXT = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".rb", ".java", ".c",
    ".h", ".cpp", ".cc", ".cs", ".php", ".sh", ".lua", ".swift", ".kt", ".ex",
    ".exs", ".clj", ".hs", ".ml", ".scala", ".sql", ".vue", ".svelte",
}

TODO_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b[:\s-]*(.*)", re.IGNORECASE)
SKIP_RE = re.compile(r"\b(skip|skipif|xfail)\b", re.IGNORECASE)


class GitError(RuntimeError):
    pass


def _git(repo: Path, *args: str, timeout: int = 90) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, timeout=timeout, env=GIT_ENV,
            errors="replace",
        )
    except subprocess.TimeoutExpired as exc:  # pragma: no cover - defensive
        raise GitError(f"git {args[0]} timed out") from exc
    if proc.returncode != 0:
        if "does not have any commits" in proc.stderr or "unknown revision" in proc.stderr:
            raise GitError("this repository has no commits yet")
        raise GitError(proc.stderr.strip() or f"git {args[0]} failed")
    return proc.stdout


def _parse_date(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _short(text: str, limit: int = 160) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def read_commits(repo: Path) -> list[dict[str, Any]]:
    """One `git log -p` call. Returns commits with a small patch excerpt."""
    out = _git(
        repo, "log", "-p", "-U0", "--no-merges", "--no-color",
        f"-n{MAX_COMMITS}", "--date=iso-strict",
        "--pretty=format:%x1e%H%x1f%an%x1f%ae%x1f%aI%x1f%s%x1f%b",
    )
    commits: list[dict[str, Any]] = []
    for record in out.split("\x1e"):
        if not record.strip():
            continue
        split = record.find("\ndiff --git ")
        head = record if split == -1 else record[:split]
        patch = "" if split == -1 else record[split + 1:]
        fields = head.split("\x1f")
        if len(fields) < 5:
            continue
        sha, author, email, date, subject = fields[:5]
        body = fields[5].strip() if len(fields) > 5 else ""

        files: list[str] = []
        added: list[str] = []
        removed: list[str] = []
        additions = deletions = 0
        for line in patch.splitlines():
            if line.startswith("diff --git "):
                match = re.search(r" b/(.+)$", line)
                if match:
                    files.append(match.group(1))
            elif line.startswith("+") and not line.startswith("+++"):
                additions += 1
                if len(added) < 14:
                    added.append(line[1:])
            elif line.startswith("-") and not line.startswith("---"):
                deletions += 1
                if len(removed) < 14:
                    removed.append(line[1:])

        excerpt_lines = [f"+{line}" for line in added] + [f"-{line}" for line in removed]
        excerpt = "\n".join(excerpt_lines)[:900]

        commits.append({
            "sha": sha,
            "short": sha[:7],
            "author": author,
            "email": email,
            "date": date,
            "ts": int(_parse_date(date).timestamp()) if _parse_date(date) else 0,
            "subject": subject,
            "body": body,
            "files": files[:24],
            "files_changed": len(files),
            "insertions": additions,
            "deletions": deletions,
            "patch_excerpt": excerpt,
        })
    commits.reverse()  # oldest first
    return commits


def read_todos(repo: Path) -> list[dict[str, Any]]:
    try:
        out = _git(repo, "grep", "-n", "-I", "-E", "-e", r"\b(TODO|FIXME|HACK|XXX)\b", "HEAD", "--", ".")
    except GitError:
        return []
    todos = []
    for line in out.splitlines():
        parts = line.split(":", 3)
        if len(parts) < 4:
            continue
        path, lineno, text = parts[1], parts[2], parts[3].strip()
        match = TODO_RE.search(text)
        if not match:
            continue
        note = match.group(2).strip(" -:")
        todos.append({
            "path": path,
            "line": int(lineno) if lineno.isdigit() else 0,
            "keyword": match.group(1).upper(),
            "text": _short(note, 220),
            "raw": text,
        })
    return todos


def read_skipped_tests(repo: Path) -> list[dict[str, Any]]:
    try:
        out = _git(repo, "grep", "-n", "-I", "-E", "-e", r"\.skip|skipif|xfail|pytest\.mark\.skip", "HEAD", "--", ".")
    except GitError:
        return []
    found = []
    for line in out.splitlines():
        parts = line.split(":", 3)
        if len(parts) < 4:
            continue
        path, lineno, text = parts[1], parts[2], parts[3].strip()
        if not (path.startswith("test") or "/test" in path or path.endswith("_test.py")):
            continue
        found.append({"path": path, "line": int(lineno) if lineno.isdigit() else 0,
                      "text": _short(text, 200)})
    return found[:12]


def read_files(repo: Path) -> list[dict[str, Any]]:
    out = _git(repo, "ls-tree", "-r", "-l", "HEAD")
    files = []
    for line in out.splitlines():
        meta, _, path = line.partition("\t")
        parts = meta.split()
        if len(parts) < 4:
            continue
        try:
            size = int(parts[3])
        except ValueError:
            size = 0
        files.append({"path": path, "size": size})
    return files


def read_readme(repo: Path, files: list[dict[str, Any]]) -> tuple[str, str]:
    candidates = [f["path"] for f in files
                  if f["path"].lower().startswith("readme")]
    if not candidates:
        return "", ""
    path = candidates[0]
    try:
        return _git(repo, "show", f"HEAD:{path}"), path
    except GitError:
        return "", path


def read_branches(repo: Path, current: str) -> list[dict[str, Any]]:
    out = _git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads")
    branches = []
    for name in out.split():
        if name == current:
            continue
        try:
            ahead = int(_git(repo, "rev-list", "--count", f"HEAD..{name}").strip())
        except (GitError, ValueError):
            continue
        if ahead == 0:
            continue
        log = _git(repo, "log", "--no-merges", "--date=iso-strict",
                   "--pretty=format:%h%x1f%aI%x1f%s", f"-n{min(ahead, 6)}",
                   f"HEAD..{name}")
        commits = []
        for line in log.splitlines():
            parts = line.split("\x1f")
            if len(parts) == 3:
                commits.append({"short": parts[0], "date": parts[1], "subject": parts[2]})
        branches.append({"name": name, "ahead": ahead, "commits": commits})
    return branches


def read_tags(repo: Path, commits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    try:
        out = _git(repo, "tag", "--sort=creatordate",
                   "--format=%(refname:short)%x1f%(creatordate:iso-strict)")
    except GitError:
        return []
    shas = {c["sha"] for c in commits}
    tags = []
    for line in out.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 2:
            continue
        name, date = parts
        try:
            target = _git(repo, "rev-list", "-n1", name).strip()
        except GitError:
            target = ""
        tags.append({"name": name, "date": date, "sha": target,
                     "reachable": target in shas})
    return tags


def _humanise_days(days: int) -> str:
    if days < 60:
        return f"{days} days"
    if days < 730:
        return f"{days / 30:.1f} months"
    return f"{days / 365:.1f} years"


def _signals(commits: list[dict[str, Any]], todos, branches, skipped, readme,
             silence_days: int) -> list[dict[str, str]]:
    signals: list[dict[str, str]] = []
    if silence_days > 365:
        signals.append({
            "label": "long silence",
            "detail": f"No commit in {_humanise_days(silence_days)}.",
            "tone": "cold",
        })
    if commits:
        last = commits[-1]
        signals.append({
            "label": "last commit",
            "detail": f'{last["short"]} · "{_short(last["subject"], 70)}"',
            "tone": "cold",
        })
    if todos:
        signals.append({
            "label": "unfinished work",
            "detail": f"{len(todos)} TODO/FIXME markers still in the tree.",
            "tone": "warm",
        })
    if skipped:
        signals.append({
            "label": "skipped test",
            "detail": f"{skipped[0]['path']}:{skipped[0]['line']} is still marked skip.",
            "tone": "warm",
        })
    if branches:
        branch = branches[0]
        signals.append({
            "label": "unmerged branch",
            "detail": f'{branch["name"]} is {branch["ahead"]} commits ahead and never merged.',
            "tone": "haunt",
        })
    if readme and re.search(r"coming soon|not finished|unreleased|wip", readme, re.I):
        signals.append({
            "label": "promise in the README",
            "detail": "The documentation still advertises something that never shipped.",
            "tone": "haunt",
        })
    return signals


def analyze(path: str | Path) -> dict[str, Any]:
    repo = Path(path).expanduser().resolve()
    if not (repo / ".git").exists():
        raise GitError("not a git repository")

    current = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    head = _git(repo, "rev-parse", "HEAD").strip()
    commits = read_commits(repo)
    if not commits:
        raise GitError("this repository has no commits yet")

    files = read_files(repo)
    readme, readme_path = read_readme(repo, files)
    todos = read_todos(repo)
    skipped = read_skipped_tests(repo)
    branches = read_branches(repo, current)
    tags = read_tags(repo, commits)

    authors = Counter(c["author"] for c in commits)
    first, last = commits[0], commits[-1]
    now = datetime.now(timezone.utc)
    last_dt = _parse_date(last["date"]) or now
    silence_days = max(0, (now - last_dt).days)

    months = Counter(c["date"][:7] for c in commits)
    month_histogram = [{"month": m, "count": n} for m, n in sorted(months.items())]

    gaps = []
    for older, newer in zip(commits, commits[1:]):
        gap = (newer["ts"] - older["ts"]) / 86400
        gaps.append({"from": older["short"], "to": newer["short"],
                     "days": round(gap, 1),
                     "from_date": older["date"], "to_date": newer["date"]})
    biggest_gap = max(gaps, key=lambda g: g["days"]) if gaps else None

    active_days = sum(1 for _, n in months.items() if n)
    languages = Counter(
        Path(f["path"]).suffix.lower() for f in files
        if Path(f["path"]).suffix.lower() in SOURCE_EXT
    )
    total_added = sum(c["insertions"] for c in commits)

    profile: dict[str, Any] = {
        "name": repo.name,
        "path": str(repo),
        "head_sha": head,
        "branch": current,
        "commit_count": len(commits),
        "first_commit": first,
        "last_commit": last,
        "silence_days": silence_days,
        "silence_label": _humanise_days(silence_days),
        "authors": [{"name": n, "commits": c} for n, c in authors.most_common()],
        "month_histogram": month_histogram,
        "active_months": active_days,
        "biggest_gap": biggest_gap,
        "todos": todos,
        "branches": branches,
        "tags": tags,
        "skipped_tests": skipped,
        "files": files[:400],
        "file_count": len(files),
        "languages": dict(languages.most_common(6)),
        "readme": readme[:8000],
        "readme_path": readme_path,
        "added_lines": total_added,
        "signals": _signals(commits, todos, branches, skipped, readme, silence_days),
        "commits": commits,
    }
    return profile
