#!/usr/bin/env python3
"""执行计划生成器：读 ts.json 输出编码段的任务清单（给 pipe 统一并行发起）。

pipe 不再手工解析 ts.json 判断"要不要 DQ / 有没有 init / 哪些规则要编码"——
本工具一次算清，pipe 读计划按清单发起（4a DDL + 4b 规则coder + 4c DQ 同消息并行，
4d init 等 4b），避免逐个判断把 DQ/init 拖成串行。

输出字段：
- ddl: true（assemble_ddl 总要跑）
- dq: ts.dq_rules 非空（DQ 完全跟随 RS）+ dq_count 条数
- etl_rules: ts.rules 中非视图步骤的规则（按 exec_sequence 排序；视图由 DDL 覆盖，不调 coder）
- init_rules: ts.init.rules 的规则清单（derive/explicit 均需 coder 编码）
- groups: data_flow.schedule_groups（4b 组内并行的依据）
- summary: 人读摘要

用法:
  python dispatch_plan.py --ts ts.json
输出: JSON 到 stdout（exit 0；ts.json 不存在 exit 2）
"""

import sys
import json
import argparse
from pathlib import Path


def build_dispatch_plan(ts: dict) -> dict:
    """从 ts.json 算执行计划（纯函数，不碰文件）。"""
    rules = ts.get("rules", {}) or {}
    # 全部规则都由 coder 编码（视图是 F 表配套镜像，由 assemble_ddl 生成，不是规则）
    etl_rules = sorted(rules.keys(),
                       key=lambda c: ((rules[c] or {}).get("exec_sequence") or 0, c))
    init_rules = list(((ts.get("init") or {}).get("rules")) or {})
    dq_rules = ts.get("dq_rules") or []
    groups = ((ts.get("data_flow") or {}).get("schedule_groups")) or []

    plan = {
        "ddl": True,
        "dq": bool(dq_rules),
        "dq_count": len(dq_rules),
        "etl_rules": etl_rules,
        "init_rules": init_rules,
        "groups": groups,
    }
    plan["summary"] = (
        f"{len(etl_rules)} 条 ETL 规则 + {len(init_rules)} 条 init"
        + (f" + DQ {len(dq_rules)} 条" if dq_rules else "，无 DQ")
        + f"，{len(groups)} 个规则组（组内并行、组间串行）"
    )
    return plan


def main():
    parser = argparse.ArgumentParser(
        description="编码段执行计划生成器（pipe 统一并行发起用，不自己解析 ts.json 猜）")
    parser.add_argument("--ts", required=True, help="ts.json 路径")
    args = parser.parse_args()

    ts_path = Path(args.ts)
    if not ts_path.exists():
        print(f"错误: ts.json 不存在: {ts_path}", file=sys.stderr)
        sys.exit(2)
    try:
        ts = json.loads(ts_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"错误: ts.json 解析失败: {e}", file=sys.stderr)
        sys.exit(2)

    print(json.dumps(build_dispatch_plan(ts), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
