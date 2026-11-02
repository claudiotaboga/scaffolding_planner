#!/usr/bin/env bash
# Azure App Service (Linux, Python) startup command:  bash startup.sh
# Data lives under /home, which App Service keeps across restarts and redeploys.
set -e
cd "$(dirname "$0")"
mkdir -p /home/data/files 2>/dev/null || mkdir -p var/files
export PYTHONPATH="$(pwd)/backend${PYTHONPATH:+:$PYTHONPATH}"
if [ -d /home/data ]; then
  export VSR_DB="${VSR_DB:-/home/data/vsr.sqlite}"
  export VSR_FILES="${VSR_FILES:-/home/data/files}"
fi
exec python -m uvicorn vsr.api.app:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips="*"
