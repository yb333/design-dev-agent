#!/usr/bin/env bash
# sync_to_team.sh — 薄入口（开发环境测试用；内网实际运行用 sync_to_team.bat）
# 核心逻辑在 sync_to_team.py，参数原样透传。
exec python3 "$(cd "$(dirname "$0")" && pwd)/sync_to_team.py" "$@"
