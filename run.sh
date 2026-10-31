#!/usr/bin/env bash
# Start The Last Commit. Everything it needs is local.
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8000}"
OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:11434}"
PYTHON="${PYTHON:-python3.13}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "The Last Commit needs Python 3.13 (the specimen generator and sqlite"
  echo "work fine on 3.11+, but 3.13 is what this checkout was built with)."
  echo "Set PYTHON=/path/to/python3 if it lives somewhere else."
  exit 1
fi

if [ ! -d .venv ]; then
  echo "· creating the virtualenv"
  "$PYTHON" -m venv .venv
fi
# shellcheck disable=SC1091
. .venv/bin/activate

if ! python -c "import fastapi" >/dev/null 2>&1; then
  echo "· installing Python dependencies"
  pip install --quiet --upgrade pip
  pip install --quiet -r requirements.txt
fi

if [ ! -f frontend/dist/index.html ]; then
  if command -v npm >/dev/null 2>&1; then
    echo "· building the interface (dist/ was missing)"
    (cd frontend && npm install --silent && npm run build)
  else
    echo "frontend/dist is missing and npm is not installed." >&2
    echo "Install Node 18+ and run 'cd frontend && npm install && npm run build'." >&2
    exit 1
  fi
fi

if ! curl -sf --max-time 2 "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
  echo
  echo "  Ollama is not answering at $OLLAMA_URL"
  echo "  Start it in another terminal:  ollama serve"
  echo "  Then pull a model:             ollama pull gemma3:4b"
  echo
  echo "  The archive still works without it: every question falls back to the"
  echo "  evidence itself instead of pretending to think."
  echo
fi

echo "· the archive is open at http://127.0.0.1:$PORT"
exec uvicorn backend.app:app --host 127.0.0.1 --port "$PORT"
