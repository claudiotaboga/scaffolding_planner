#!/usr/bin/env bash
# Start the API + frontend on http://localhost:${PORT:-8000}. Sample project B12 is seeded on first start.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -d .venv ] && . .venv/bin/activate
export PYTHONPATH=backend
exec uvicorn vsr.api.app:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8000}"
