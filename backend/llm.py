"""A thin client for a local Ollama server.

No SDK, no hidden retries, no telemetry. If Ollama is not running the ghost
degrades to an evidence-only reply instead of pretending to think.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

import httpx

from .config import DEFAULT_MODEL, OLLAMA_URL


class LLMError(RuntimeError):
    """Raised when the local model server cannot answer."""


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=OLLAMA_URL,
        timeout=httpx.Timeout(600.0, connect=4.0),
        headers={"Content-Type": "application/json"},
    )


async def list_models() -> list[dict[str, Any]]:
    try:
        async with _client() as client:
            response = await client.get("/api/tags")
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as exc:
        raise LLMError(
            f"Ollama is not reachable at {OLLAMA_URL}. Start it with `ollama serve`."
        ) from exc
    models = []
    for model in payload.get("models", []):
        size = model.get("size") or 0
        models.append({
            "name": model.get("name"),
            "size_gb": round(size / 1e9, 2) if size else None,
            "family": (model.get("details") or {}).get("family"),
            "parameters": (model.get("details") or {}).get("parameter_size"),
        })
    return models


async def ensure_model(model: str) -> None:
    available = {m["name"] for m in await list_models()}
    if model in available:
        return
    short = {name.split(":")[0] for name in available}
    if model.split(":")[0] in short:
        return
    raise LLMError(
        f"Model '{model}' is not installed. Run `ollama pull {model}`, "
        f"or pick one of: {', '.join(sorted(available)) or '(none)'}."
    )


async def stream_chat(model: str, messages: list[dict[str, str]],
                      options: dict[str, Any] | None = None) -> AsyncIterator[str]:
    payload = {
        "model": model,
        "messages": messages,
        "keep_alive": "30m",
        "stream": True,
        "options": {
            "temperature": 0.5,
            "top_p": 0.9,
            "repeat_penalty": 1.08,
            "num_ctx": 4096,
            "num_predict": 220,
            **(options or {}),
        },
    }
    try:
        async with _client() as client:
            async with client.stream("POST", "/api/chat", json=payload) as response:
                if response.status_code == 404:
                    raise LLMError(f"Model '{model}' is not installed locally.")
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    import json
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if event.get("error"):
                        raise LLMError(str(event["error"]))
                    message = event.get("message") or {}
                    content = message.get("content")
                    if content:
                        yield content
    except httpx.HTTPError as exc:
        raise LLMError(
            f"Lost the connection to Ollama at {OLLAMA_URL}: {exc.__class__.__name__}."
        ) from exc


async def complete(model: str, messages: list[dict[str, str]],
                   options: dict[str, Any] | None = None) -> str:
    chunks: list[str] = []
    async for token in stream_chat(model, messages, options):
        chunks.append(token)
    return "".join(chunks)
