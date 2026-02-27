#!/usr/bin/env bash
# 백엔드만 실행 (포트 6005)
set -e
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

BACKEND_DIR="$REPO_ROOT/backend"
# 프로젝트 루트 venv(pymodbus 설치됨) 우선, 없으면 backend/venv
ROOT_VENV_PYTHON="$REPO_ROOT/venv/bin/python3"
BACKEND_VENV_PYTHON="$BACKEND_DIR/venv/bin/python"

# 포트 6005 사용 중이면 종료
if command -v lsof &>/dev/null; then
  pids=$(lsof -ti ":6005" 2>/dev/null) || true
  if [ -n "$pids" ]; then
    echo "기존 프로세스 종료 중 (포트 6005)..."
    echo "$pids" | xargs -r kill 2>/dev/null || true
    sleep 1
  fi
fi

# 루트 venv에 pymodbus 있으면 사용(Modbus 폴링용), 없으면 backend/venv 또는 시스템 python3
if [ -x "$ROOT_VENV_PYTHON" ] && "$ROOT_VENV_PYTHON" -c "import pymodbus" 2>/dev/null; then
  exec "$ROOT_VENV_PYTHON" "$BACKEND_DIR/app.py"
elif [ -x "$BACKEND_VENV_PYTHON" ] && "$BACKEND_VENV_PYTHON" -c "import sys" 2>/dev/null; then
  exec "$BACKEND_VENV_PYTHON" "$BACKEND_DIR/app.py"
else
  exec python3 "$BACKEND_DIR/app.py"
fi
