#!/usr/bin/env bash
# 设计开发 Agent 评测系统 - 交互式菜单入口
# 用法: ./eval.sh 或 bash eval.sh

cd "$(dirname "$0")" || exit 1

PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" >/dev/null 2>&1; then
        PYTHON="$cmd"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "未找到 Python，请先安装 python3。"
    exit 1
fi

exec "$PYTHON" eval-suite/v2/menu.py "$@"
