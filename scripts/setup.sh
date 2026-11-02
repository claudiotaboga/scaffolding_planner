#!/usr/bin/env bash
# Create a virtualenv, install dependencies, (re)generate the sample project and run the validation tests.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip >/dev/null
pip install -r requirements.txt
python samples/generate_sample_block.py
python -m pytest -q
echo "Setup complete. Start with: ./scripts/run.sh"
