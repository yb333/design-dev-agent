"""golden 指纹比对：人审认可的产出（golden）vs 新跑产出。

golden 纪律（对齐红线"语义判断不自主"）：
- golden 只能由人手工沉淀（promote.py 是纯拷贝工具，评测运行绝不自动推）
- 评测零交互：命中/越界只落报告，不做任何确认/暂停
- 比对的是"指纹"（提取后的结构事实），不是文本——同一 golden 允许多种 SQL 写法
  （多解兼容：命中集合中任一 golden 即通过；多 golden 并存 = 多个合理方案）

指纹内容（全部从产出现提，不维护第二份真相）：
- business_key / 规则集 / 每规则 load_mode / field_targets 并集
- 每规则 SELECT 的输出字段 / JOIN 表 / GROUP BY 粒度
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_V2_DIR = Path(__file__).resolve().parent
_EVAL_SUITE = _V2_DIR.parent
for p in (str(_V2_DIR), str(_EVAL_SUITE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from validators.base import CheckResult, CheckStatus  # type: ignore

import assert_sql
from _paths import find_select_file


def fingerprint(deliver: Path) -> dict:
    """从产出目录提取指纹（结构事实）。产出不全时尽量提取，不抛异常。"""
    fp: dict = {
        "business_key": [],
        "rules": [],
        "load_modes": {},
        "field_targets": [],
        "selects": {},
    }
    ts_path = deliver / "ts.json"
    if not ts_path.exists():
        return fp
    try:
        ts = json.loads(ts_path.read_text(encoding="utf-8"))
    except Exception:
        return fp

    fp["business_key"] = sorted(ts.get("design", {}).get("business_key", []))
    rules = ts.get("rules", {})
    fp["rules"] = sorted(rules)
    fp["load_modes"] = {c: r.get("load_mode", "") for c, r in rules.items()}

    # field_targets 在 design_decisions.yaml（ts 不含）
    dec_path = deliver / "_internal" / "design_decisions.yaml"
    if dec_path.exists():
        try:
            import yaml

            data = yaml.safe_load(dec_path.read_text(encoding="utf-8")) or {}
            targets: set = set()
            for r in data.get("rules", []):
                targets.update(r.get("field_targets", []))
            fp["field_targets"] = sorted(targets)
        except Exception:
            pass

    for code in rules:
        sql_file = find_select_file(deliver, code)
        if not sql_file:
            continue
        try:
            sql = sql_file.read_text(encoding="utf-8")
            fp["selects"][code] = {
                "fields": sorted(assert_sql._extract_select_columns(sql)),
                "joins": sorted(str(t) for t in assert_sql._extract_join_tables(sql)),
                "group_by": sorted(assert_sql._extract_groupby_columns(sql)),
            }
        except Exception:
            continue
    return fp


def compare(fp_a: dict, fp_b: dict) -> tuple[bool, list[str]]:
    """比对两份指纹。返回 (是否一致, 差异点列表)。"""
    diffs: list[str] = []
    if fp_a.get("business_key") != fp_b.get("business_key"):
        diffs.append("business_key")
    if fp_a.get("rules") != fp_b.get("rules"):
        diffs.append("规则集")
    if fp_a.get("load_modes") != fp_b.get("load_modes"):
        diffs.append("load_mode")
    if fp_a.get("field_targets") != fp_b.get("field_targets"):
        diffs.append("field_targets")
    codes = sorted(set(fp_a.get("selects", {})) | set(fp_b.get("selects", {})))
    for code in codes:
        sa, sb = fp_a.get("selects", {}).get(code), fp_b.get("selects", {}).get(code)
        if sa is None or sb is None:
            diffs.append(f"{code}:SELECT缺失")
            continue
        if sa.get("fields") != sb.get("fields"):
            diffs.append(f"{code}:输出字段")
        if sa.get("joins") != sb.get("joins"):
            diffs.append(f"{code}:JOIN表")
        if sa.get("group_by") != sb.get("group_by"):
            diffs.append(f"{code}:GROUP_BY")
    return (not diffs, diffs)


def load_goldens(case_dir: Path) -> dict[str, dict]:
    """加载案例的 golden 集合：{方案名: 指纹}。

    golden 目录约定：cases_real/{分类}/{资产}/golden/{方案名}/（每个子目录一份
    完整认可产出，含 ts.json）。无 golden 目录或子目录缺 ts.json 的跳过。
    """
    goldens: dict[str, dict] = {}
    golden_dir = case_dir / "golden"
    if not golden_dir.exists():
        return goldens
    for d in sorted(golden_dir.iterdir()):
        if d.is_dir() and (d / "ts.json").exists():
            try:
                goldens[d.name] = fingerprint(d)
            except Exception as e:
                print(f"  ⚠️ golden {d.name} 指纹提取失败，跳过: {e}", file=sys.stderr)
    return goldens


def golden_check(deliver: Path, case_dir: Path) -> list[CheckResult]:
    """golden 命中检查（作为独立断言层）。

    - 无 golden → SKIP（还没沉淀标准答案，不判对错）
    - 命中任一 → PASS（多解兼容）
    - 全不中 → FAIL（越界，待人工裁决：可能新合理方案，可能回归）
    """
    goldens = load_goldens(case_dir)
    if not goldens:
        return [
            CheckResult(
                check_type="golden",
                status=CheckStatus.SKIP,
                detail="无 golden（未沉淀标准答案，跳过比对；用 promote.py 手工沉淀）",
            )
        ]
    fp = fingerprint(deliver)
    for name, gfp in goldens.items():
        hit, _ = compare(fp, gfp)
        if hit:
            return [
                CheckResult(
                    check_type="golden", status=CheckStatus.PASS, detail=f"命中 golden: {name}"
                )
            ]
    # 越界：找差异点最少的 golden 给参照
    best_name, best_diffs = min(
        ((n, compare(fp, g)[1]) for n, g in goldens.items()), key=lambda x: len(x[1])
    )
    return [
        CheckResult(
            check_type="golden",
            status=CheckStatus.FAIL,
            detail=(
                f"未命中任何 golden（越界，待人工裁决）— "
                f"与最接近的 {best_name} 差异: {best_diffs[:6]}"
            ),
        )
    ]
