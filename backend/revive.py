"""Resurrection: a plan, a patch, and a hard refusal to run either.

The patch is generated as text, checked with `git apply --check`, and then
thrown away. Nothing in this module writes to the repository it is reading.
"""

from __future__ import annotations

import difflib
import re
import subprocess
from pathlib import Path
from typing import Any

from . import db, llm
from .gitarch import GIT_ENV
from .ghost import parse_json_answer
from .retrieval import to_refs

ROADMAP_PROMPT = """You are a software archaeologist writing a revival plan for an
abandoned repository. Be concrete and unromantic. Do not invent files, issues or
maintainers.

FACTS
{facts}

EVIDENCE
{evidence}

Reply with ONE JSON object and nothing else:
{{
  "verdict": "one sentence, quiet and specific",
  "readiness": "revivable" | "needs a rewrite" | "archival only",
  "score": 0,
  "steps": [
    {{"title": "...", "why": "...", "effort": "hours|a weekend|a week",
      "evidence": ["C1"], "first_action": "the exact first command or edit"}}
  ],
  "risks": ["..."],
  "keep": ["what still works and should survive the rewrite"]
}}
3 to 5 steps, ordered by what unblocks the most. "score" is 0-100 for how
close the project is to working again. Use only citation ids that appear
above. No prose outside the JSON.
"""

PATCH_PROMPT = """You are proposing a minimal edit to one file in an abandoned
repository. You may only edit {path}. Do not invent files, do not delete files,
do not rename unrelated identifiers, do not reformat the file.

TASK (a TODO that still exists at HEAD)
{task}

CURRENT FILE {path} AT HEAD
```
{content}
```

Return ONE JSON object and nothing else. Quote the lines as an array of strings,
copied exactly from the file, without line numbers and without backticks:
{{
  "find": ["the first existing line", "the next existing line"],
  "replace": ["what should stand in their place"],
  "why": "one short sentence"
}}
If the task cannot be done safely without more context, return:
{{"skip": "the reason"}}

"find" must occur exactly once in the file. Keep the edit under 25 changed
lines. No prose outside the JSON.

Rules for the edit: implement the behaviour the task asks for. Do not mark the
task done by deleting or rewording its comment: the code itself must change.
Never glue two statements onto one line, and preserve the original indentation
of the surrounding block.
"""


def _facts(profile: dict[str, Any]) -> str:
    last = profile["last_commit"]
    todos = "\n".join(f"- {t['path']}:{t['line']} {t['keyword']}: {t['text']}"
                      for t in profile["todos"][:8]) or "- none"
    return (
        f"name: {profile['name']}\n"
        f"commits: {profile['commit_count']}, last: {last['date'][:10]} "
        f"\"{last['subject']}\"\n"
        f"silence: {profile['silence_label']}\n"
        f"unmerged branches: "
        + (", ".join(b["name"] for b in profile["branches"]) or "none") + "\n"
        f"skipped tests: {len(profile['skipped_tests'])}\n"
        f"todos at HEAD:\n{todos}"
    )


def roadmap_evidence(profile: dict[str, Any], repo_id: str) -> list[dict[str, Any]]:
    ids: list[str] = [f"todo:{t['path']}:{t['line']}" for t in profile["todos"][:4]]
    ids += [f"branch:{b['name']}" for b in profile["branches"][:1]]
    ids += [f"test:{s['path']}:{s['line']}" for s in profile["skipped_tests"][:1]]
    if profile["commits"]:
        ids.append(f"commit:{profile['commits'][-1]['sha'][:10]}")
    evidence = []
    for chunk_id in ids:
        chunk = db.get_chunk(repo_id, chunk_id)
        if chunk:
            evidence.append(chunk)
    return evidence[:7]


def _normalise(raw: dict[str, Any], refs: list[dict[str, Any]],
               profile: dict[str, Any]) -> dict[str, Any]:
    valid = {ref["ref"] for ref in refs}
    readiness = str(raw.get("readiness", "")).lower().replace("_", " ")
    if readiness not in {"revivable", "needs a rewrite", "archival only"}:
        readiness = "needs a rewrite"
    steps = []
    for step in raw.get("steps") or []:
        if not isinstance(step, dict) or not step.get("title"):
            continue
        cited = [ref for ref in (step.get("evidence") or []) if ref in valid]
        steps.append({
            "title": str(step.get("title"))[:160],
            "why": str(step.get("why", ""))[:400],
            "effort": str(step.get("effort", "unknown"))[:40],
            "first_action": str(step.get("first_action", ""))[:300],
            "evidence": cited,
        })
    if not steps:
        return fallback_roadmap(profile, refs)
    try:
        score = max(0, min(100, int(raw.get("score", 50))))
    except (TypeError, ValueError):
        score = 50
    return {
        "verdict": str(raw.get("verdict") or "The archive is readable.")[:280],
        "readiness": readiness,
        "score": score,
        "steps": steps[:5],
        "risks": [str(r)[:200] for r in (raw.get("risks") or [])][:4],
        "keep": [str(k)[:200] for k in (raw.get("keep") or [])][:4],
        "source": "model",
    }


def fallback_roadmap(profile: dict[str, Any], refs: list[dict[str, Any]]) -> dict[str, Any]:
    ref_for = {ref["id"]: ref["ref"] for ref in refs}
    steps = []
    for todo in profile["todos"][:3]:
        chunk_id = f"todo:{todo['path']}:{todo['line']}"
        steps.append({
            "title": f"Resolve the {todo['keyword']} in {todo['path']}",
            "why": todo["text"],
            "effort": "hours",
            "first_action": f"Open {todo['path']} at line {todo['line']} and write a failing test first.",
            "evidence": [ref_for[chunk_id]] if chunk_id in ref_for else [],
        })
    if profile["branches"]:
        branch = profile["branches"][0]
        steps.append({
            "title": f"Decide the fate of {branch['name']}",
            "why": f"{branch['ahead']} commits were written and never merged.",
            "effort": "a weekend",
            "first_action": f"Read `git log HEAD..{branch['name']}` before deleting anything.",
            "evidence": [ref_for.get(f"branch:{branch['name']}", "")],
        })
    return {
        "verdict": (f"Nothing here is dead, only paused. {len(profile['todos'])} unfinished "
                    f"markers are the whole map."),
        "readiness": "needs a rewrite" if profile["branches"] else "revivable",
        "score": max(20, 70 - len(profile["todos"]) * 6),
        "steps": steps[:5] or [{
            "title": "Read the last three commits",
            "why": "There is no TODO trail. Start where the author stopped.",
            "effort": "hours",
            "first_action": "git show HEAD~2..HEAD",
            "evidence": [],
        }],
        "risks": ["The toolchain from this era may no longer install."],
        "keep": [f"{profile['file_count']} files and a working test entry point."],
        "source": "heuristic",
    }


async def generate_roadmap(profile: dict[str, Any], repo_id: str, model: str) -> dict[str, Any]:
    evidence = roadmap_evidence(profile, repo_id)
    refs = to_refs(evidence)
    from .ghost import render_evidence
    messages = [{
        "role": "system",
        "content": "You are a careful software archaeologist. You output JSON only.",
    }, {
        "role": "user",
        "content": ROADMAP_PROMPT.format(
            facts=_facts(profile),
            evidence=render_evidence(evidence),
        ),
    }]
    text = await llm.complete(model, messages, {"temperature": 0.35, "num_predict": 900})
    raw = parse_json_answer(text)
    if raw is None:
        result = fallback_roadmap(profile, refs)
        result["note"] = "The model did not return valid JSON; this plan is heuristic."
        return result
    result = _normalise(raw, refs, profile)
    result["refs"] = refs
    return result


def validate_patch(repo: Path, diff: str, allowed_path: str) -> dict[str, Any]:
    """Static checks, then `git apply --check`. Never `git apply`."""
    if not diff:
        return {"applies": False, "reason": "The model did not return a diff."}
    if len(diff) > 12_000:
        return {"applies": False, "reason": "The diff was too large to review."}
    if re.search(r"^(deleted file|new file|rename from|rename to|old mode|new mode|"
                 r"GIT binary patch)", diff, re.M):
        return {"applies": False, "reason": "The diff changes more than the contents of one file."}
    targets = re.findall(r"^\+\+\+ b/(.+)$", diff, re.M)
    if targets != [allowed_path]:
        return {"applies": False,
                "reason": f"The diff targets {targets or 'nothing'}, not {allowed_path}."}
    for target in targets:
        if target.startswith("/") or ".." in Path(target).parts:
            return {"applies": False, "reason": "The diff escapes the repository."}

    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "apply", "--check", "--whitespace=nowarn", "-"],
            input=diff, text=True, capture_output=True, timeout=20, env=GIT_ENV,
        )
    except subprocess.TimeoutExpired:
        return {"applies": False, "reason": "git apply --check timed out."}
    if proc.returncode != 0:
        detail = " ".join((proc.stderr or proc.stdout).split())[:220]
        return {"applies": False, "reason": detail or "git apply --check rejected the diff."}
    return {"applies": True, "reason": "git apply --check accepts this diff against HEAD."}


def _strip_line_numbers(line: str) -> str:
    """Models sometimes echo a line-number gutter; it is not part of the file."""
    return re.sub(r"^\s*\d+\|\s?", "", line)


def _locate_lines(content: str, wanted: list[str]) -> tuple[int, int, str] | None:
    """Find one exact, contiguous run of lines.

    Returns (start, end, indent). Indentation is forgiven: a model that quotes
    `x = 1` for an indented block still means that block, so the caller
    re-indents the replacement to the block it matched.
    """
    lines = content.split("\n")
    normalised = [line.rstrip() for line in lines]
    targets = [_strip_line_numbers(line).rstrip() for line in wanted]
    if not targets or not any(target.strip() for target in targets):
        return None
    span = len(targets)
    matches = [
        index for index in range(len(normalised) - span + 1)
        if normalised[index:index + span] == targets
    ]
    indent = ""
    if not matches:
        stripped = [line.strip() for line in normalised]
        target_stripped = [target.strip() for target in targets]
        matches = [
            index for index in range(len(stripped) - span + 1)
            if stripped[index:index + span] == target_stripped
        ]
        indent = "unmatched"
    if len(matches) != 1:
        return None
    index = matches[0]
    if indent == "unmatched":
        indent = re.match(r"[ \t]*", lines[index]).group(0)
    start = sum(len(line) + 1 for line in lines[:index])
    end = start + sum(len(line) + 1 for line in lines[index:index + span]) - 1
    return start, end, indent


def _reindent(find: list[str], replace: list[str], indent: str) -> list[str]:
    """Carry the file's indentation onto an unindented proposal."""
    if not indent:
        return replace
    model_indent = min(
        (len(re.match(r"[ \t]*", line).group(0)) for line in find if line.strip()),
        default=0,
    )
    adjusted = []
    for line in replace:
        if not line.strip():
            adjusted.append("")
            continue
        lead = len(re.match(r"[ \t]*", line).group(0))
        body = line[lead:] if lead >= model_indent else line.lstrip()
        adjusted.append(indent + " " * max(0, lead - model_indent) + body)
    return adjusted



async def propose_patch(profile: dict[str, Any], repo_id: str, chunk_id: str,
                        model: str) -> dict[str, Any]:
    chunk = db.get_chunk(repo_id, chunk_id)
    if chunk is None:
        raise KeyError("unknown memory")
    path = chunk.get("path")
    if not path:
        return {"ok": False, "reason": "That memory is not tied to a file."}
    try:
        content = subprocess.run(
            ["git", "-C", profile["path"], "show", f"HEAD:{path}"],
            capture_output=True, text=True, timeout=20, env=GIT_ENV, errors="replace",
        ).stdout
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "Reading the file timed out."}
    if not content:
        return {"ok": False, "reason": "That file does not exist at HEAD."}
    lines = content.splitlines()
    if len(lines) > 400:
        return {"ok": False,
                "reason": f"{path} is {len(lines)} lines; this demo only proposes patches for files under 400 lines."}

    messages = [
        {"role": "system", "content": "You propose small, exact edits. You output JSON only."},
        {"role": "user", "content": PATCH_PROMPT.format(
            path=path, task=chunk["text"][:700], content=content[:12000])},
    ]
    text = await llm.complete(model, messages, {"temperature": 0.15, "num_predict": 700})
    raw = parse_json_answer(text)
    if raw is None:
        return {"ok": False, "reason": "The model did not return a structured edit."}
    if raw.get("skip"):
        return {"ok": False, "reason": f"The model declined: {str(raw['skip'])[:200]}"}
    find = raw.get("find")
    replace = raw.get("replace")
    if isinstance(find, str):
        find = find.splitlines()
    if isinstance(replace, str):
        replace = replace.splitlines()
    if not isinstance(find, list) or not isinstance(replace, list) or not find:
        return {"ok": False, "reason": "The model returned an edit without a find/replace pair."}
    find = [str(line) for line in find]
    replace = [str(line) for line in replace]
    if [line.strip() for line in find] == [line.strip() for line in replace]:
        return {"ok": False, "reason": "The model's edit does not change anything."}

    located = _locate_lines(content, find)
    if located is None:
        return {"ok": False,
                "reason": ("The model's quoted lines do not match this file at HEAD, so no "
                           "diff was built. A guess that does not apply is not a patch.")}
    start, end, indent = located
    replace = _reindent(find, replace, indent)
    new_content = content[:start] + "\n".join(replace) + content[end:]

    diff = "".join(difflib.unified_diff(
        content.splitlines(keepends=True),
        new_content.splitlines(keepends=True),
        fromfile=f"a/{path}", tofile=f"b/{path}", n=3,
    ))
    changed = sum(1 for line in diff.splitlines()
                  if line[:1] in "+-" and not line.startswith(("+++", "---")))
    if changed == 0:
        return {"ok": False, "reason": "The proposed edit is a no-op."}
    if changed > 40:
        return {"ok": False, "reason": f"The edit changes {changed} lines; the review cap is 40."}

    verdict = validate_patch(Path(profile["path"]), diff, path)
    return {
        "ok": True,
        "path": path,
        "diff": diff,
        "applies": verdict["applies"],
        "reason": verdict["reason"],
        "applied": False,
        "chunk_id": chunk_id,
        "instruction": f"Task from the TODO at {path}:{chunk['meta'].get('line', '?')}",
        "note": "Read-only proposal. Nothing was written to the repository.",
    }
