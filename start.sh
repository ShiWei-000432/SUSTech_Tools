#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")"

if ! python3 -c 'import fastapi, jinja2, multipart, requests, uvicorn' >/dev/null 2>&1; then
  echo "正在安装 Web UI 所需依赖..."
  python3 -m pip install -r requirements.txt
fi

exec python3 app.py
