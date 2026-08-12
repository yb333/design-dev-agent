#!/usr/bin/env python3
"""按 schema 查 appid（schema_apps.json 标准源）。

编排 command 调：构造 deliver 目录 `10_project_deliver/{appid}/{schema}/{资产}/...` 时，
先用本脚本按 schema 查 appid。appid 是 schema↔appid 的唯一来源（platform_config 已不带 appid）。

用法:
  python resolve_appid.py --schema slprd
  → 打印 appid（如 SLPRD_APP_001）；找不到打印空串 + stderr 警告
"""
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config_paths import resolve_appid, schema_apps_path


def main():
    ap = argparse.ArgumentParser(description="按 schema 查 appid（schema_apps.json 标准源）")
    ap.add_argument("--schema", required=True, help="目标 schema（从 ts/rs_input 的 meta.target.f_table.schema 取）")
    ap.add_argument("--config", default="", help="schema_apps.json 路径（默认 config_paths.schema_apps_path）")
    args = ap.parse_args()

    appid = resolve_appid(args.schema, args.config)
    if not appid:
        print(f"⚠️  schema '{args.schema}' 在 schema_apps.json 没找到 appid（{schema_apps_path()}）", file=sys.stderr)
        print("   deliver 目录的 appid 层将为空——建议先填 schema_apps.json", file=sys.stderr)
    print(appid)


if __name__ == "__main__":
    main()
