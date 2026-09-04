"""sql_fence_check —— SQL 围栏的 pipe 侧 CLI 入口（闸门单点在 pipe，docs/specs/opt/05 §二）。

对 ts_v2.change 的每条 placed_rule：baseline SQL（etl_baseline/）vs 新 SQL（etl/，
read_select 兼容 {code}.sql 与 {code}_描述_模式.sql 命名）跑 sql_fence.check_sql_fence。
exit 0 = 全过；exit 1 = 有越界/漏改（报错带 [SQL围栏] 导航回对应 coder）。
"""
import argparse
import sys
from pathlib import Path

# shared 公共库自洽引用：相对路径推算 design-dev-shared（skill 脚本标准 bootstrap）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "design-dev-shared" / "scripts"))
from typing import Optional

from run_ut import read_select
from sql_fence import check_sql_fence, rule_declaration


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="SQL 围栏：pipe 独立跑（审计独立于被审计者）")
    ap.add_argument("--ts-v2", required=True)
    ap.add_argument("--etl-dir", required=True)
    ap.add_argument("--baseline-dir", required=True)
    args = ap.parse_args(argv)

    import json
    ts_v2 = json.loads(Path(args.ts_v2).read_text(encoding="utf-8"))
    change = ts_v2.get("change") or {}
    if not change.get("fields"):
        print("SQL_FENCE_ERROR: ts_v2 无 change 段", file=sys.stderr)
        return 2

    etl_dir, baseline_dir = Path(args.etl_dir), Path(args.baseline_dir)
    all_violations = []
    touched = sorted({r for f in change.get("fields", []) for r in f.get("placed_rules", [])})
    for rc in touched:
        old_sql = read_select(baseline_dir, rc)
        new_sql = read_select(etl_dir, rc)
        if not old_sql or not new_sql:
            all_violations.append({"type": "missing",
                                   "message": f"[SQL围栏][{rc}] 缺 {'baseline' if not old_sql else '新'} SQL 文件——漏改"})
            continue
        all_violations.extend(check_sql_fence(old_sql, new_sql, rule_declaration(change, rc)))

    # 结果落盘（ut_opt 开跑校验围栏时效——"产物变→围栏重跑→才进 UT"从剧本纪律变机器闸门）
    result_path = etl_dir.parent / "_internal" / "sql_fence_result.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    result_path.write_text(json.dumps({
        "passed": not all_violations,
        "rules": touched,
        "violations": all_violations,
        "checked_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    if all_violations:
        over = sum(1 for v in all_violations if v["type"] != "missing")
        miss = sum(1 for v in all_violations if v["type"] == "missing")
        print(f"SQL_FENCE_BLOCKED：越界 {over} 项 / 漏改 {miss} 项", file=sys.stderr)
        for v in all_violations:
            print(f"  {v['message']}", file=sys.stderr)
        return 1
    print(f"SQL_FENCE_PASS（{len(touched)} 规则）→ {result_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
