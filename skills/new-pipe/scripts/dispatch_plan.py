#!/usr/bin/env python3
"""执行计划生成器：读 ts.json 输出编码段的任务清单（给 pipe 统一并行发起）。

pipe 不再手工解析 ts.json 判断"有没有 init / 哪些规则要编码"——
本工具一次算清，pipe 读计划按清单发起（4a DDL + 4b 规则 coder + 4c DQ producer
同消息并行，4d init 等 4b），避免逐个判断把 init 拖成串行。
DQ 内容随 2026-09-14 拆分不在 ts 里（dq.json 独立），但"RS 有没有 DQ 需求"这个
事实由装配带进 ts.meta.dq_required——计划据此出 dq 行（2026-09-22：此前计划无 dq 行，
按清单发起的 pipe 会漏掉 4c，到 6a DQ 兜底才炸，回滚成本高）。

输出字段：
- ddl: true（assemble_ddl 总要跑）
- etl_rules: ts.rules 中非视图步骤的规则（按 exec_sequence 排序；视图由 DDL 覆盖，不调 coder）
- init_rules: ts.init.rules 的规则清单（derive/explicit 均需 coder 编码）
- groups: data_flow.schedule_groups（4b 组内并行的依据）
- dq: {required, requirements}（required=true → 4c 起 dws-dq-producer；
  false 显式跳过——计划里明示"跳过"比"没有"强，人扫一眼知道不是漏了）
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
    groups = ((ts.get("data_flow") or {}).get("schedule_groups")) or []
    # DQ 行：meta.dq_required（装配时从 rs_input.dq_requirements 判定）；旧档无键按
    # ts.dq_rules 兜底（DQ 拆分前形态）；两者都无 = 显式 required=false（跳过要明示）
    dq_n = ((ts.get("meta") or {}).get("dq_required"))
    if dq_n is None:
        dq_n = len(ts.get("dq_rules") or [])
    dq = {"required": bool(dq_n), "requirements": int(dq_n)}

    plan = {
        "ddl": True,
        "etl_rules": etl_rules,
        "init_rules": init_rules,
        "groups": groups,
        "dq": dq,
    }
    dq_txt = f"DQ {dq['requirements']} 条（4c 起 producer，与 coder 同消息并行）" \
        if dq["required"] else "无 DQ 需求（4c 跳过）"
    plan["summary"] = (
        f"{len(etl_rules)} 条 ETL 规则 + {len(init_rules)} 条 init"
        + f"，{len(groups)} 个规则组（组内并行、组间串行），{dq_txt}"
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
