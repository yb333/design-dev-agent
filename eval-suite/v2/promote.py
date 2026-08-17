#!/usr/bin/env python3
"""手工沉淀 golden：把人认可的产出拷进案例 golden/{方案名}/。

纪律（红线：语义判断不自主）：
- 本命令只是拷贝工具——"这个产出是否认可"由人决定，评测系统绝不自动推
- 典型用法：实际调测中产出你认可的版本 → promote 沉淀 → 之后评测以它为标准答案之一

用法:
    python eval-suite/v2/promote.py --case dwb_x [--name 方案A]
    python eval-suite/v2/promote.py --case dwb_x --from 10_project_deliver/app/dwb/dwb_x/ddlc_design_dev --name 方案B
    # --cases-dir 可指定案例根（默认 eval-suite/cases_real/，支持 {分类}/{资产} 两级）

拷贝范围（golden 只留断言/比对要用的核心产出，不含 export 大文件）：
ts.json、ts.md/{资产}_ts.md、etl/、ddl/、ddl_rollback/、dq/、_internal/design_decisions.yaml
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

_V2_DIR = Path(__file__).resolve().parent
_EVAL_SUITE = _V2_DIR.parent
_ROOT = _EVAL_SUITE.parent
for p in (str(_V2_DIR), str(_EVAL_SUITE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from _paths import find_deliver
import golden

CASES_REAL_DIR = _EVAL_SUITE / "cases_real"
DELIVER_BASE = _ROOT / "10_project_deliver"
UNCATEGORIZED = "未分类"

# 拷贝清单：文件名 / 目录名（存在才拷）
_COPY_ITEMS = [
    "ts.json",
    "etl",
    "ddl",
    "ddl_rollback",
    "dq",
    "_internal/design_decisions.yaml",
]


def _find_case_dir(case_name: str, cases_root: Path) -> Path | None:
    """在案例根下找 {资产} 目录（兼容一级 cases/ 和两级 cases_real/{分类}/{资产}）。"""
    one = cases_root / case_name
    if one.is_dir():
        return one
    if cases_root.exists():
        for cat in sorted(cases_root.iterdir()):
            cand = cat / case_name
            if cand.is_dir():
                return cand
    return None


def promote(case: str, name: str, deliver_from: Path, case_dir: Path) -> Path:
    """执行拷贝，返回 golden 目标目录。"""
    target = case_dir / "golden" / name
    if target.exists():
        raise SystemExit(f"❌ golden 已存在: {target}（换 --name 或先手工删除旧方案）")
    target.mkdir(parents=True)

    copied = []
    for item in _COPY_ITEMS:
        src = deliver_from / item
        dst = target / item
        if not src.exists():
            continue
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        copied.append(item)
    # ts.md 兼容两种命名（ts.md / {资产}_ts.md）
    for f in deliver_from.iterdir():
        if f.is_file() and (f.name == "ts.md" or f.name.endswith("_ts.md")):
            shutil.copy2(f, target / f.name)
            copied.append(f.name)
            break
    if (deliver_from / "ts.json") not in [deliver_from / c for c in copied]:
        raise SystemExit(f"❌ 源产出缺 ts.json，不成其为 golden: {deliver_from}")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="手工沉淀 golden（纯拷贝，认可决定在人）")
    parser.add_argument("--case", required=True, help="资产名（如 dwb_x）")
    parser.add_argument("--name", default="", help="golden 方案名（默认自动取 方案A/B/C...）")
    parser.add_argument("--from", dest="deliver_from", default="",
                        help="产出目录（默认按资产名扫 10_project_deliver，平铺/三层兼容）")
    parser.add_argument("--cases-dir", default="",
                        help="案例根目录（默认 eval-suite/cases_real/）")
    args = parser.parse_args()

    cases_root = Path(args.cases_dir) if args.cases_dir else CASES_REAL_DIR

    # 定位产出
    if args.deliver_from:
        deliver = Path(args.deliver_from)
        if not deliver.exists():
            print(f"❌ 产出目录不存在: {deliver}", file=sys.stderr)
            return 1
    else:
        deliver = find_deliver(DELIVER_BASE, args.case)
        if not deliver:
            print(f"❌ 三层产出未找到: 10_project_deliver/{{appid}}/{{schema}}/{args.case}"
                  f"/ddlc_design_dev（用 --from 显式指定产出路径）", file=sys.stderr)
            return 1

    # 定位案例目录（没有则建 未分类/{case} 占位）
    case_dir = _find_case_dir(args.case, cases_root)
    if not case_dir:
        case_dir = cases_root / UNCATEGORIZED / args.case
        case_dir.mkdir(parents=True, exist_ok=True)
        print(f"ℹ️ 案例目录不存在，已建占位: {case_dir}")

    # golden 方案名：默认按已有方案数顺延 方案A/B/C...
    if not args.name:
        golden_dir = case_dir / "golden"
        existing = sorted(d.name for d in golden_dir.iterdir()) if golden_dir.exists() else []
        idx = len(existing)
        name = f"方案{chr(ord('A') + idx)}" if idx < 26 else f"方案{idx + 1}"
    else:
        name = args.name

    target = promote(args.case, name, deliver, case_dir)

    # 指纹摘要（给人确认沉淀的内容概况）
    fp = golden.fingerprint(target)
    print(f"✅ golden 已沉淀: {target}")
    print(f"   方案名: {name}")
    print(f"   business_key: {fp['business_key']}")
    print(f"   规则: {fp['rules']}  load_mode: {fp['load_modes']}")
    print(f"   字段数: {len(fp['field_targets'])}")
    print("   ⚠️ golden 只能人手工沉淀（本命令不自动触发）；后续评测命中任一 golden 即通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
