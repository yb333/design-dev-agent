#!/usr/bin/env python3
"""
数据库连接检查：确认 db-sources.json 是否存在 + 能否连接。

command 调本脚本决定要不要跑 UT，不给 AI 判断。
AI 只看脚本输出（有/无数据源），不自己找配置文件。

按 target schema 选数据源（和 precheck/UT 完全一致）：
从 ts.json 的 meta.target.f_table.schema 取 schema，按 schema_mapping 选源。
不兜底默认数据源——必须命中目标 schema 对应的源。

用法:
  python check_db.py --ts {deliver}/ts.json

退出码: 0=有数据源且能连接, 1=无数据源或连不上
"""

import sys
import os
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "design-dev-shared" / "scripts"))
from config_paths import db_sources_path


def main():
    parser = argparse.ArgumentParser(description="数据库连接检查（按 target schema 选源）")
    parser.add_argument("--ts", required=True, help="ts.json 路径（用来取 target schema）")
    args = parser.parse_args()

    # 从 ts.json 取 target schema
    ts_path = Path(args.ts)
    if not ts_path.exists():
        print("NO_DB_SOURCE")
        print(f"  原因: ts.json 不存在 ({ts_path})")
        sys.exit(1)

    import json
    try:
        ts = json.loads(ts_path.read_text(encoding="utf-8"))
    except Exception as e:
        print("NO_DB_SOURCE")
        print(f"  原因: ts.json 解析失败: {e}")
        sys.exit(1)

    target_schema = ts.get("meta", {}).get("target", {}).get("f_table", {}).get("schema", "")
    if not target_schema:
        print("NO_DB_SOURCE")
        print(f"  原因: ts.json 缺 target.f_table.schema（无法按 schema 选源）")
        sys.exit(1)

    # 定位 db-sources.json（和 dws_db.py 同样的查找逻辑）
    config_path = os.environ.get(
        "DB_CONFIG",
        str(db_sources_path()),
    )

    if not Path(config_path).exists():
        print("NO_DB_SOURCE")
        print(f"  原因: 配置文件不存在 ({config_path})")
        print(f"  处理: 跳过 UT 执行验证，只做静态检查")
        sys.exit(1)

    # 配置结构自检（不连库，提前发现配置错误）
    try:
        raw = json.loads(Path(config_path).read_text(encoding="utf-8"))
        sources = raw.get("sources", {})
        if not sources:
            print("NO_DB_SOURCE")
            print(f"  原因: sources 为空（没配数据源）")
            sys.exit(1)
        # 检查每个 source 是否配了 roles（新结构）
        bad = []
        for name, cfg in sources.items():
            roles = cfg.get("roles", {})
            if not roles:
                bad.append(f"{name}: 缺 roles（旧结构 user/password 已废弃，需配 roles.admin/roles.etl）")
            else:
                for rn in ("admin", "etl"):
                    if rn not in roles:
                        bad.append(f"{name}: roles 里缺 {rn}")
                    elif not roles[rn].get("user"):
                        bad.append(f"{name}: roles.{rn}.user 为空")
        if bad:
            print("NO_DB_SOURCE")
            print(f"  原因: 配置结构错误")
            for b in bad:
                print(f"    - {b}")
            print(f"  参考: skills/dws-coding/assets/db-sources.example.json")
            sys.exit(1)
    except json.JSONDecodeError as e:
        print("NO_DB_SOURCE")
        print(f"  原因: 配置文件 JSON 格式错误: {e}")
        sys.exit(1)

    # 按 target schema 选源，测 admin + etl 两个账号（与 precheck/UT 选源逻辑一致）
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "design-dev-shared" / "scripts"))
        from dws_db import create_executor_for_schema

        failures = []
        source_name = ""
        for role in ("admin", "etl"):
            executor = create_executor_for_schema(target_schema, role=role)
            if not source_name:
                source_name = executor.get_current_source()
            r = executor.execute("SELECT 1")
            executor.close()
            if not r.success:
                failures.append(f"{role}: {r.error}")

        if not failures:
            print("DB_OK")
            print(f"  数据源: {source_name}（schema={target_schema}）")
            print(f"  账号: admin + etl 均通")
            sys.exit(0)
        else:
            print("NO_DB_SOURCE")
            print(f"  数据源: {source_name}（schema={target_schema}）")
            for f in failures:
                print(f"  原因: {f}")
            sys.exit(1)
    except ImportError as e:
        print("NO_DB_SOURCE")
        print(f"  原因: 依赖缺失 ({e})")
        sys.exit(1)
    except Exception as e:
        print("NO_DB_SOURCE")
        print(f"  原因: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

