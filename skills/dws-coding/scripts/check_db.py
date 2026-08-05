#!/usr/bin/env python3
"""
数据库连接检查：确认 db-sources.json 是否存在 + 能否连接。

command 调本脚本决定要不要跑 UT，不给 AI 判断。
AI 只看脚本输出（有/无数据源），不自己找配置文件。

用法:
  python check_db.py
  python check_db.py --source dws-dev

退出码: 0=有数据源且能连接, 1=无数据源或连不上
"""

import sys
import os
from pathlib import Path


def main():
    # 定位 db-sources.json（和 dws_db.py 同样的查找逻辑）
    config_path = os.environ.get(
        "DB_CONFIG",
        str(Path.home() / ".config" / "opencode" / "db-sources.json"),
    )

    if not Path(config_path).exists():
        print("NO_DB_SOURCE")
        print(f"  原因: 配置文件不存在 ({config_path})")
        print(f"  处理: 跳过 UT 执行验证，只做静态检查")
        sys.exit(1)

    # 配置结构自检（不连库，提前发现配置错误）
    import json
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

    # 尝试连接
    try:
        # dws_db 在 design-dev-shared 公共库（与本 skill 平级）
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "design-dev-shared" / "scripts"))
        from dws_db import create_executor
        source = ""
        for i, arg in enumerate(sys.argv):
            if arg == "--source" and i + 1 < len(sys.argv):
                source = sys.argv[i + 1]
        executor = create_executor(config_path, source, role="etl")
        # 直接 execute('SELECT 1')，拿真实报错（test_connection 会吞异常）
        r = executor.execute("SELECT 1")
        if r.success:
            print("DB_OK")
            print(f"  数据源: {executor.get_current_source()}")
            print(f"  账号: etl")
            sys.exit(0)
        else:
            print("NO_DB_SOURCE")
            print(f"  数据源: {executor.get_current_source()}")
            print(f"  账号: etl")
            print(f"  原因: {r.error}")
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
