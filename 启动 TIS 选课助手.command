#!/usr/bin/env sh
set -eu

PROJECT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
URL="http://127.0.0.1:8000/"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/launcher.log"

if /usr/bin/curl --silent --fail "$URL" >/dev/null 2>&1; then
  open "$URL"
  exit 0
fi

mkdir -p "$LOG_DIR"
echo "正在启动 TIS 选课助手。请保持此窗口打开；关闭窗口会停止本地服务。"
exec "$PROJECT_DIR/start.sh" 2>&1 | tee -a "$LOG_FILE"
