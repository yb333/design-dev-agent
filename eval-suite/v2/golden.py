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
import re
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
        "tables": {},
        "rule_flow": {},
        "ddl": {},
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

    # 表结构事实：类型/分布键/build_mode（中间表几个、每个的分布键——设计结构全貌）
    fp["tables"] = {
        name: {
            "type": t.get("type", ""),
            "distribution_key": sorted(t.get("distribution_key", []) or []),
            "build_mode": t.get("build_mode", ""),
        }
        for name, t in (ts.get("tables") or {}).items()
    }
    # 规则数据流：每规则的目标表 + 来源表集合（去重）
    fp["rule_flow"] = {
        code: {
            "target": r.get("target_table", ""),
            "sources": sorted({st.get("table", "") for st in (r.get("source_tables") or [])}),
        }
        for code, r in rules.items()
    }
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

    # DDL 维度：每表 {列: [基类型, 精度]}——基类型相等才算同口径，精度差异只扣分不拦及格
    ddl: dict[str, dict] = {}
    ddl_dir = deliver / "ddl"
    for tname in (ts.get("tables") or {}):
        ddl_file = ddl_dir / f"create_table_{tname}.sql"
        parsed = parse_ddl_columns(ddl_file)
        if parsed:
            ddl[tname] = {c: _split_type(t) for c, t in parsed.items()}
    fp["ddl"] = ddl

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
                # 字段级口径签名（refs/aggs/consts）——L3 映射忠实度比对载体
                "field_sigs": assert_sql._extract_field_signatures(sql),
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
    if fp_a.get("tables") != fp_b.get("tables"):
        diffs.append("表结构(类型/分布键/build_mode)")
    if fp_a.get("rule_flow") != fp_b.get("rule_flow"):
        diffs.append("规则数据流(源表/目标表)")
    ddl_diffs = _ddl_diffs(fp_a.get("ddl"), fp_b.get("ddl"))
    diffs.extend(ddl_diffs)
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
        sig_a, sig_b = sa.get("field_sigs", {}), sb.get("field_sigs", {})
        logic_f, const_f = [], []
        for f in sorted(set(sig_a) | set(sig_b)):
            ga, gb = sig_a.get(f) or {}, sig_b.get(f) or {}
            if ga.get("refs") != gb.get("refs") or ga.get("aggs") != gb.get("aggs"):
                logic_f.append(f)  # 引用源列/聚合口径变了 = 加工逻辑错（致命）
            elif ga.get("consts") != gb.get("consts"):
                const_f.append(f)  # 仅常量不同（写法差异，非致命，人裁决）
        if logic_f:
            diffs.append(f"{code}:口径逻辑({','.join(logic_f[:4])})")
        if const_f:
            diffs.append(f"{code}:口径常量({','.join(const_f[:4])})")
    return (not diffs, diffs)


def parse_ddl_columns(ddl_path: Path) -> dict[str, str]:
    """解析 CREATE TABLE 的列定义：{列名: 原始类型}（自洽断言与 golden 指纹共用）。

    行式解析 assemble_ddl 生成的标准 DDL：列行在 CREATE TABLE ( 与 ) 之间，
    形如 `  col_name varchar(50) COMMENT '..'`。解析不了的行跳过（容错）。
    """
    cols: dict[str, str] = {}
    if not ddl_path.exists():
        return cols
    try:
        in_cols = False
        for line in ddl_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not in_cols:
                if "create table" in stripped.lower() and "(" in stripped:
                    in_cols = True
                continue
            if stripped.startswith(")"):
                break
            m = re.match(r'^"?\s*([A-Za-z_][\w]*)"?\s+([A-Za-z_][\w]*(?:\s*\([^)]*\))?)',
                         stripped, re.IGNORECASE)
            if m:
                cols[m.group(1).lower()] = m.group(2).strip().lower()
        return cols
    except Exception:
        return {}


def _split_type(t: str) -> list[str]:
    """类型拆 [基类型, 精度]：decimal(18,2) → ['decimal', '18,2']；varchar → ['varchar', '']。"""
    t = (t or "").strip().lower().replace(" ", "")
    base, _, prec = t.partition("(")
    return [base, prec.rstrip(")") if prec else ""]


def _ddl_diffs(a: dict | None, b: dict | None) -> list[str]:
    """DDL 三层差异：列集合（致命）/ 基类型（致命）/ 精度（非致命，只扣分）。"""
    a, b = a or {}, b or {}
    diffs: list[str] = []
    cols_missing, base_bad, prec_bad = [], [], []
    for t in sorted(set(a) | set(b)):
        if t not in a or t not in b:
            cols_missing.append(t)
            continue
        for c in sorted(set(a[t]) | set(b[t])):
            if c not in a[t] or c not in b[t]:
                cols_missing.append(f"{t}.{c}")
            elif a[t][c][0] != b[t][c][0]:
                base_bad.append(f"{t}.{c}")
            elif a[t][c][1] != b[t][c][1]:
                prec_bad.append(f"{t}.{c}")
    if cols_missing:
        diffs.append(f"DDL(列): {','.join(cols_missing[:4])}")
    if base_bad:
        diffs.append(f"DDL(基类型): {','.join(base_bad[:4])}")
    if prec_bad:
        diffs.append(f"DDL(类型精度): {','.join(prec_bad[:4])}")
    return diffs


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
    # 越界：找差异点最少的 golden 给参照，差异给自解释证据（golden vs 实际并排）
    best_name, best_diffs = min(
        ((n, compare(fp, g)[1]) for n, g in goldens.items()), key=lambda x: len(x[1])
    )
    evidence = _diff_evidence(fp, goldens[best_name])
    return [
        CheckResult(
            check_type="golden",
            status=CheckStatus.FAIL,
            detail=(
                f"未命中任何 golden（越界，待人工裁决）— 与 {best_name} 的差异证据:\n"
                + "\n".join(evidence[:10])
                + (f"\n（其余 {max(0, len(evidence) - 10)} 项略，全文见 scoring 明细）" if len(evidence) > 10 else "")
            ),
        )
    ]


def _diff_evidence(fp: dict, gfp: dict) -> list[str]:
    """逐维度生成自解释差异证据：维度名: golden=[...] vs 实际=[...]。"""
    import json as _json

    def _short(v, n=90):
        return _json.dumps(v, ensure_ascii=False, sort_keys=True)[:n]

    lines: list[str] = []
    for dim in ("business_key", "rules", "load_modes", "field_targets", "tables",
                "rule_flow", "ddl"):
        a, b = fp.get(dim), gfp.get(dim)
        if a != b:
            lines.append(f"  {dim}: golden={_short(b)} | 实际={_short(a)}")
    codes = sorted(set(fp.get("selects", {})) | set(gfp.get("selects", {})))
    for code in codes:
        sa, sb = fp.get("selects", {}).get(code), gfp.get("selects", {}).get(code)
        if sa is None or sb is None:
            lines.append(f"  {code}.SELECT: golden={'有' if sb else '无'} | 实际={'有' if sa else '无'}")
            continue
        for k in ("fields", "joins", "group_by"):
            if sa.get(k) != sb.get(k):
                lines.append(f"  {code}.{k}: golden={_short(sb.get(k))} | 实际={_short(sa.get(k))}")
        fa, fb = sa.get("field_sigs", {}), sb.get("field_sigs", {})
        for f in sorted(set(fa) | set(fb)):
            if fa.get(f) != fb.get(f):
                lines.append(f"  {code}.口径[{f}]: golden={_short(fb.get(f), 70)} | 实际={_short(fa.get(f), 70)}")
    return lines
