"""assemble_ts_opt —— 优化模式 ts 组装器（docs/specs/opt/04 §二）。

ts_baseline + 增量 decisions → ts_v2（完整结构 + change 段）。
★ 独立脚本，不改 assemble_ts.py（零存量接触）；ts 结构消费与 fence_check 对齐。

增量 decisions（designer 产出，YAML——模板见 dws-design-opt/assets/opt-decisions-template.yaml）：
只写增量，不写存量（重写存量 = 重写存量设计，红线禁止）。每个新增字段一条：
挂哪条规则 / 血缘 / 新 JOIN 及其 safety（新 JOIN 必须声明——04 §一第3步）/ 回刷意向。

应用是确定性的：decisions 说的才落，ts_baseline 的存量一个字节不动。
产出 ts_v2 后由 pipe 跑 fence_check 审计（本脚本不自审——被审计者不当审计员）。

用法：
  python assemble_ts_opt.py --ts-baseline {ts_baseline.json} \
      --decisions {design_decisions_opt.yaml} --output {ts_v2.json}
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

# decisions 必填键（缺 = fail loud，防 designer 漏声明）
FIELD_REQUIRED_KEYS = ("field", "target_table", "placed_rules", "field_type",
                       "field_comment", "design_logic")
JOIN_REQUIRED_KEYS = ("rule", "table", "alias", "join_type", "on", "join_safety")

TS_RESERVED_RULE_KEYS = {"field_targets", "field_logics", "joins", "join_safety",
                         "source_tables"}


def _fail(msg: str) -> None:
    print(f"[ASSEMBLE_OPT_ERROR] {msg}", file=sys.stderr)
    sys.exit(1)


def load_decisions(path: Path) -> dict:
    d = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if d.get("change_type") != "add_field":
        _fail(f"decisions.change_type = {d.get('change_type')!r}，本刀仅支持 add_field")
    if not d.get("fields"):
        _fail("decisions.fields 为空——没有要落的字段")
    return d


def validate_decisions(decisions: dict, ts_baseline: dict) -> None:
    """decisions 自身合法性（与 ts_baseline 的对接面），fail loud。"""
    fields = ts_baseline.get("tables", {})
    rules = ts_baseline.get("rules", {})
    target_asset = ts_baseline["meta"]["target"]["f_table"]["table"]

    for i, f in enumerate(decisions["fields"], start=1):
        for k in FIELD_REQUIRED_KEYS:
            if not f.get(k):
                _fail(f"fields[{i}] 缺必填项 {k!r}（模板见 dws-design-opt/assets/opt-decisions-template.yaml）")
        if f["target_table"] not in fields:
            _fail(f"fields[{i}].target_table {f['target_table']!r} 不在 baseline 表集")
        if f["field"] in {x["target_field"] for x in fields[f["target_table"]]["fields"]}:
            _fail(f"fields[{i}].field {f['field']!r} 已存在于 {f['target_table']}——存量字段")
        if f["target_table"] == target_asset and "placed_rules" not in f:
            pass
        for t in f.get("intermediate_tables", []):
            if t not in fields:
                _fail(f"fields[{i}].intermediate_tables 含未知表 {t!r}")
        for r in f["placed_rules"]:
            if r not in rules:
                _fail(f"fields[{i}].placed_rules 含未知规则 {r!r}")
        for j in f.get("new_joins", []):
            for k in JOIN_REQUIRED_KEYS:
                if k not in j or (k != "join_safety" and not j.get(k)):
                    _fail(f"fields[{i}].new_joins 缺必填项 {k!r}——新 JOIN 必须完整声明"
                          f"（含 join_safety，04 §一第3步）")
            if j["rule"] not in f["placed_rules"]:
                _fail(f"fields[{i}].new_joins.rule {j['rule']!r} 不在 placed_rules——"
                      f"新 JOIN 只能挂落位规则")
            js = j.get("join_safety") or {}
            if not js.get("strategy"):
                _fail(f"fields[{i}].new_joins[{j['alias']}].join_safety.strategy 为空")


def apply_decisions(ts_baseline: dict, decisions: dict) -> dict:
    """确定性应用：decisions 说的才落，存量不动。返回 ts_v2（含 change 段）。"""
    from ts_compat import normalize_ts
    v2 = normalize_ts(json.loads(json.dumps(ts_baseline)))  # 深拷贝 + 升级两视图（幂等）
    v2["generated_by"] = "assemble_ts_opt"
    change_fields = []

    for f in decisions["fields"]:
        fname = f["field"]
        # 1. 目标表 + 中间表字段定义
        # 新字段按两视图落：tables 三键元数据 + 规则桶（designer 写了口径 → processed）
        def make_field(ttype_comment=True):
            return {
                "target_field": fname,
                "field_type": f["field_type"] if ttype_comment else "",
                "field_comment": f["field_comment"] if ttype_comment else "",
            }
        v2["tables"][f["target_table"]]["fields"].append(make_field())
        for t in f.get("intermediate_tables", []):
            v2["tables"][t]["fields"].append(make_field(ttype_comment=False))

        # 2. 落位规则：field_targets 投影 + fields 桶（design_logic → processed）
        for r in f["placed_rules"]:
            rule = v2["rules"][r]
            rule["field_targets"] = sorted(set(rule.get("field_targets") or []) | {fname})
            _src = f.get("source") or {}
            _ref = f"{_src.get('alias','')}.{_src.get('field', fname)}".strip(".")
            rule.setdefault("fields", {"processed": [], "assign": [], "direct": []})["processed"].append(
                {"target": fname, "logic": f["design_logic"], "refs": [_ref] if _ref else []})

        # 3. 新 JOIN：joins / source_tables / join_safety / meta 源表 / data_flow 节点
        for j in f.get("new_joins", []):
            rule = v2["rules"][j["rule"]]
            rule["joins"].append({"alias": j["alias"], "type": j["join_type"],
                                  "condition": j["on"], "filter": ""})
            rule["source_tables"].append({"schema": j.get("schema", ""),
                                          "table": j["table"], "alias": j["alias"]})
            js = j["join_safety"]
            rule["join_safety"].append({
                "table": j["table"], "join_filter": js.get("join_filter", ""),
                "join_key_unique": bool(js.get("join_key_unique", False)),
                "strategy": js.get("strategy", ""), "reason": js.get("reason", ""),
            })
            if not any(s.get("table") == j["table"]
                       for s in v2["meta"]["source_tables"]):
                v2["meta"]["source_tables"].append({
                    "schema": j.get("schema", ""), "table": j["table"],
                    "table_cn": "", "alias": j["alias"]})
            if not any(n.get("name") == j["table"]
                       for n in v2["data_flow"]["tables"]):
                v2["data_flow"]["tables"].append({
                    "schema": j.get("schema", ""), "name": j["table"],
                    "role": "source", "layer": "", "is_view": False})

        # 4. 派生计数
        tgt = f["target_table"]
        v2["meta"]["field_count"]["business"] += 1
        v2["meta"]["field_count"]["total"] += 1

        change_fields.append({
            "field": fname, "target_table": tgt,
            "placed_rules": list(f["placed_rules"]),
            "intermediate_tables": list(f.get("intermediate_tables", [])),
            "new_joins": [{k: j[k] for k in ("rule", "table", "alias", "on")}
                          for j in f.get("new_joins", [])],
            "source": f.get("source") or {},   # 血缘（alias.field）——patcher 写 TargetFields 用
            "backfill": decisions.get("backfill", f.get("backfill", "pending")),
        })

    # 5. change 段（fence_check 的消费形状；结构见 fence_check 模块头注释）
    v2["change"] = {"change_type": "add_field", "fields": change_fields}
    return v2


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="优化模式组装：ts_baseline + 增量decisions → ts_v2")
    ap.add_argument("--ts-baseline", required=True)
    ap.add_argument("--decisions", required=True, help="design_decisions_opt.yaml")
    ap.add_argument("--output", required=True, help="ts_v2.json 输出路径")
    args = ap.parse_args(argv)

    ts_baseline = json.loads(Path(args.ts_baseline).read_text(encoding="utf-8"))
    decisions = load_decisions(Path(args.decisions))
    validate_decisions(decisions, ts_baseline)
    v2 = apply_decisions(ts_baseline, decisions)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(v2, ensure_ascii=False, indent=2), encoding="utf-8")
    n_joins = sum(len(f.get("new_joins", [])) for f in decisions["fields"])
    print(f"ts_v2: {out}")
    print(f"fields: {len(decisions['fields'])}, new_joins: {n_joins}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
