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

    # 尝试连接
    try:
        # dws_db 在 design-dev-shared 公共库（与本 skill 平级）
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "design-dev-shared" / "references"))
        from dws_db import create_executor
        source = ""
        for i, arg in enumerate(sys.argv):
            if arg == "--source" and i + 1 < len(sys.argv):
                source = sys.argv[i + 1]
        executor = create_executor(config_path, source)
        ok = executor.test_connection()
        if ok:
            print("DB_OK")
            print(f"  数据源: {executor.get_current_source()}")
            sys.exit(0)
        else:
            print("NO_DB_SOURCE")
            print(f"  数据源: {executor.get_current_source()}")
            print(f"  原因: 连接测试失败")
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
