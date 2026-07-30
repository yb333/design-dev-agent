#!/usr/bin/env bash
# 设计开发 Agent 安装器 (macOS/Linux)
# 用法: ./install.sh [--local | --check]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

PYTHON=""
for cmd in python3 python; do
  if command -v "$cmd" &>/dev/null; then
    if "$cmd" -c "import sys; exit(0 if sys.version_info >= (3,10) else 1)" 2>/dev/null; then
      PYTHON="$cmd"
      break
    fi
  fi
done

if [ -z "$PYTHON" ]; then
  echo "未找到 Python 3.10+"
  echo "  macOS:  brew install python3"
  echo "  Ubuntu: sudo apt install python3 python3-venv"
  exit 1
fi

exec "$PYTHON" "$SCRIPT_DIR/install.py" "$@"
