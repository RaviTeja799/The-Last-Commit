"""FastAPI surface for The Last Commit.

Three verbs matter here: import a repository, ask its ghost a question, and
propose a resurrection. The last one never writes to disk.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import chunks as chunker
from . import db, ghost, llm, retrieval, revive
from .config import DEFAULT_MODEL, FRONTEND_DIST, REPOS_DIR
from .gitarch import GIT_ENV, GitError, analyze

app = FastAPI(title="The Last Commit", version="1.0.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


class ImportRequest(BaseModel):
    path: str | None = None
    url: str | None = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[dict[str, str]] = Field(default_factory=list)
    model: str | None = None


class ModelRequest(BaseModel):
    model: str | None = None


class PatchRequest(BaseModel):
    chunk_id: str
    model: str | None = None


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:40] or "repository"


def _public(profile: dict[str, Any]) -> dict[str, Any]:
    """Trim the profile for the browser: no full diffs, no huge blobs."""
    keep = ("name", "branch", "head_sha", "commit_count", "first_commit",
            "last_commit", "silence_days", "silence_label", "authors",
            "month_histogram", "active_months", "biggest_gap", "todos",
            "branches", "tags", "skipped_tests", "file_count", "languages",
            "readme_path", "added_lines", "signals")
    public = {key: profile.get(key) for key in keep}
    public["commits"] = [{
        "sha": c["sha"], "short": c["short"], "author": c["author"],
        "date": c["date"], "subject": c["subject"],
        "files_changed": c["files_changed"], "insertions": c["insertions"],
        "deletions": c["deletions"],
    } for c in profile["commits"]]
    public["readme_excerpt"] = profile.get("readme", "")[:1500]
    public["welcome"] = ghost.seed_line(profile)
    public["path"] = profile.get("path")
    return public


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _clone(url: str) -> Path:
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise HTTPException(400, "Only https:// repository URLs can be imported.")
    host = parsed.hostname.lower()
    if host in {"localhost", "127.0.0.1", "::1"} or host.startswith(
            ("10.", "192.168.", "169.254.", "172.16.", "172.17.", "172.18.")):
        raise HTTPException(400, "Refusing to clone from a private address.")
    name = _slug(Path(parsed.path.rstrip("/")).stem or "repository")
    dest = REPOS_DIR / name
    if (dest / ".git").exists():
        return dest
    try:
        subprocess.run(
            ["git", "clone", "--quiet", "--", url, str(dest)],
            capture_output=True, text=True, timeout=300, env=GIT_ENV,
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(504, "The clone took longer than five minutes.") from exc
    if not (dest / ".git").exists():
        raise HTTPException(400, "Could not clone that repository. Is it public?")
    return dest


@app.get("/api/health")
async def health() -> dict[str, Any]:
    db.init()
    try:
        models = await llm.list_models()
        ollama = {"ok": True, "models": models}
    except llm.LLMError as exc:
        ollama = {"ok": False, "error": str(exc), "models": []}
    return {
        "ok": True,
        "default_model": DEFAULT_MODEL,
        "ollama": ollama,
        "repos": len(db.list_repos()),
    }


@app.get("/api/models")
async def models() -> dict[str, Any]:
    try:
        return {"models": await llm.list_models(), "default": DEFAULT_MODEL}
    except llm.LLMError as exc:
        return JSONResponse({"models": [], "default": DEFAULT_MODEL,
                             "error": str(exc)}, status_code=200)


@app.get("/api/repos")
async def repos() -> dict[str, Any]:
    return {"repos": db.list_repos()}


@app.post("/api/repos")
async def import_repo(request: ImportRequest) -> dict[str, Any]:
    if not request.path and not request.url:
        raise HTTPException(400, "Give a local path or a repository URL.")

    source = request.url or request.path or ""
    if request.url:
        target = _clone(request.url)
    else:
        target = Path(request.path or "").expanduser()
        if not target.exists():
            raise HTTPException(400, f"No directory at {target}.")
        if not (target / ".git").exists():
            raise HTTPException(400, "That directory is not a git repository.")

    try:
        profile = analyze(target)
    except GitError as exc:
        raise HTTPException(400, str(exc)) from exc

    repo_id = f"{_slug(profile['name'])}-{hashlib.sha1(source.encode()).hexdigest()[:6]}"
    if db.get_repo(repo_id) is None:
        memories = chunker.build_chunks(profile, target)
        db.save_chunks(repo_id, memories)
    db.save_repo(repo_id, profile["name"], source, profile["head_sha"],
                 datetime.now(timezone.utc).isoformat(timespec="seconds"), profile)

    public = _public(profile)
    public["id"] = repo_id
    public["memory_count"] = db.count_chunks(repo_id)
    return public


@app.post("/api/specimen")
async def specimen() -> dict[str, Any]:
    """Import the bundled demonstration repository, building it if needed."""
    from .config import ROOT
    target = REPOS_DIR / "sundial"
    if not (target / ".git").exists():
        # A fresh clone has no specimen. The generator is bundled and offline;
        # replays a fixed, dated history, so the demo is reproducible anywhere.
        if target.exists():
            import shutil
            shutil.rmtree(target)
        script = ROOT / "samples" / "make_sample_repo.py"
        if not script.exists():
            raise HTTPException(500, "The specimen generator is missing.")
        built = subprocess.run([sys.executable, str(script)], capture_output=True,
                               text=True, timeout=180, check=False)
        if built.returncode != 0 or not (target / ".git").exists():
            detail = (built.stderr or built.stdout or "").strip()[-400:]
            raise HTTPException(500, f"The specimen could not be built. {detail}")
    return await import_repo(ImportRequest(path=str(target)))


@app.get("/api/repos/{repo_id}")
async def get_repo(repo_id: str) -> dict[str, Any]:
    stored = db.get_repo(repo_id)
    if stored is None:
        raise HTTPException(404, "No such ghost.")
    public = _public(stored["profile"])
    public["id"] = repo_id
    public["source"] = stored["source"]
    public["analyzed_at"] = stored["analyzed_at"]
    public["memory_count"] = db.count_chunks(repo_id)
    return public


@app.get("/api/repos/{repo_id}/chunk")
async def get_chunk(repo_id: str, id: str) -> dict[str, Any]:
    chunk = db.get_chunk(repo_id, id)
    if chunk is None:
        raise HTTPException(404, "That memory is not in the archive.")
    return chunk


@app.post("/api/repos/{repo_id}/chat")
async def chat(repo_id: str, request: ChatRequest) -> StreamingResponse:
    stored = db.get_repo(repo_id)
    if stored is None:
        raise HTTPException(404, "No such ghost.")
    profile = stored["profile"]
    model = request.model or DEFAULT_MODEL

    evidence = retrieval.select_evidence(profile, repo_id, request.message)
    if not evidence:
        raise HTTPException(409, "This repository left no readable memories.")

    async def stream() -> AsyncIterator[str]:
        yield _sse({
            "type": "meta",
            "model": model,
            "evidence": retrieval.to_refs(evidence),
        })
        try:
            async for kind, payload in ghost.stream_answer(
                    profile, evidence, request.history, request.message, model):
                if kind == "token":
                    yield _sse({"type": "token", "text": payload})
                elif kind == "notice":
                    yield _sse({"type": "notice", "text": payload})
                elif kind == "done":
                    yield _sse({"type": "done", **payload})
        except Exception as exc:  # the ghost must never take the page down
            yield _sse({"type": "error", "text": f"{exc.__class__.__name__}: {exc}"})

    return StreamingResponse(stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    })


@app.post("/api/repos/{repo_id}/revive")
async def revive_repo(repo_id: str, request: ModelRequest) -> StreamingResponse:
    stored = db.get_repo(repo_id)
    if stored is None:
        raise HTTPException(404, "No such ghost.")
    profile = stored["profile"]
    model = request.model or DEFAULT_MODEL

    async def stream() -> AsyncIterator[str]:
        yield _sse({"type": "stage", "text": "reading what was left unfinished"})
        try:
            plan = await revive.generate_roadmap(profile, repo_id, model)
            yield _sse({"type": "roadmap", "plan": plan})
        except llm.LLMError as exc:
            refs = retrieval.to_refs(revive.roadmap_evidence(profile, repo_id))
            yield _sse({
                "type": "roadmap",
                "plan": {**revive.fallback_roadmap(profile, refs),
                         "note": f"No model, so this plan is heuristic. {exc}"},
            })
        except Exception as exc:
            yield _sse({"type": "error", "text": f"{exc.__class__.__name__}: {exc}"})

    return StreamingResponse(stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
    })


@app.post("/api/repos/{repo_id}/patch")
async def propose_patch(repo_id: str, request: PatchRequest) -> dict[str, Any]:
    stored = db.get_repo(repo_id)
    if stored is None:
        raise HTTPException(404, "No such ghost.")
    try:
        return await revive.propose_patch(
            stored["profile"], repo_id, request.chunk_id,
            request.model or DEFAULT_MODEL)
    except KeyError:
        raise HTTPException(404, "That memory is not in the archive.")
    except llm.LLMError as exc:
        return {"ok": False, "reason": str(exc)}


@app.on_event("startup")
async def startup() -> None:
    db.init()


if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="ui")
