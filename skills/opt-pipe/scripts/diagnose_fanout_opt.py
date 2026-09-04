"""diagnose_fanout_opt —— opt 场景关联发散定位（对比 FAIL / 新列全 NULL 人定根因时的证据工具）。

轻量版（对齐 new-pipe diagnose_fanout 的主判据，opt 语境裁剪——2026-09-04）：
- **主判据 = 逐表键唯一性**：对规则每张 join 表，COUNT(*) vs COUNT(DISTINCT ON键)
  （声明了 join_filter 的按声明条件过滤）——条件下唯一 ⇒ 任何数据不膨胀。
- **join_safety 断言对照**：designer 声明 join_key_unique=true 但实测不唯一 = 证伪
  （新 JOIN 是 designer 声明的，无需 new-pipe 版的"声明对照"——那是对照 mapping 用的）。
- 证据：重复键样例 TOP + 重复行数（膨胀量级参考）。
不做（裁掉）：join-count 试算 / 重复组解剖——需要时人跑 explore（dws-design 工具）。

用法：
  python diagnose_fanout_opt.py --ts-v2 {opt}/ts_v2.json [--rule R0002]
输出：stdout 结论 + {opt}/_internal/diagnose/fanout_{rule}.md（证据可回溯）。
连不上库 → 报告降级提示（不猜）。
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "design-dev-shared" / "scripts"))
from sql_parse import parse_join_pairs

SAMPLE_LIMIT = 5
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")


def _keys_and_filter(rule: dict, alias: str) -> tuple[list[str], str]:
    """该别名在规则全部 JOIN 条件中的键列 + 其 join_safety 声明的过滤条件。"""
    keys = []
    for j in rule.get("joins") or []:
        for (a1, c1), (a2, c2) in parse_join_pairs(j.get("condition", "")):
            if a1 == alias and c1 not in keys:
                keys.append(c1)
            if a2 == alias and c2 not in keys:
                keys.append(c2)
    filt = ""
    for js in rule.get("join_safety") or []:
        if js.get("join_filter"):
            filt = js["join_filter"]
            break
    return keys, filt


def check_rule(executor, rule_code: str, rule: dict) -> list[dict]:
    """逐表键唯一性 + 断言对照。返回证据条目列表。"""
    out = []
    alias_map = {str(s.get("alias", "")).lower(): (s.get("schema", ""), s.get("table", ""))
                 for s in rule.get("source_tables") or []}
    declared_unique = {js.get("table"): bool(js.get("join_key_unique"))
                       for js in rule.get("join_safety") or []}
    seen = set()
    for j in rule.get("joins") or []:
        alias = str(j.get("alias", "")).lower()
        st = alias_map.get(alias)
        if not st or st[1] in seen or not st[0]:
            continue
        seen.add(st[1])
        keys, filt = _keys_and_filter(rule, alias)
        if not keys:
            continue
        for k in keys:
            if not IDENT_RE.match(k):
                continue
        key_expr = ", ".join(keys)
        where = f" WHERE {filt}" if filt else ""
        try:
            rows = executor.fetch_all(
                f"SELECT COUNT(*) AS total, COUNT(DISTINCT {key_expr}) AS dist "
                f"FROM {st[0]}.{st[1]}{where}") or [{}]
            total, dist = int(rows[0].get("total") or 0), int(rows[0].get("dist") or 0)
        except Exception as e:
            out.append({"table": f"{st[0]}.{st[1]}", "alias": alias, "keys": key_expr,
                        "status": "ERROR", "detail": str(e)[:150]})
            continue
        dup = max(total - dist, 0)
        entry = {"table": f"{st[0]}.{st[1]}", "alias": alias, "keys": key_expr,
                 "total": total, "distinct": dist, "dup": dup, "filter": filt}
        if dup == 0:
            entry["status"] = "UNIQUE"
            entry["detail"] = f"✓ 关联键 {key_expr} 唯一（{total} 行）——此表不发散"
        else:
            entry["status"] = "DUP"
            entry["detail"] = (f"✗ 关联键 {key_expr} 不唯一：{total} 行 / 去重 {dist}"
                               f"（重复 {dup} 行——JOIN 此表膨胀）")
            try:
                samples = executor.fetch_all(
                    f"SELECT {key_expr}, COUNT(*) AS n FROM {st[0]}.{st[1]}{where} "
                    f"GROUP BY {key_expr} HAVING COUNT(*) > 1 "
                    f"ORDER BY n DESC LIMIT {SAMPLE_LIMIT}") or []
                entry["samples"] = [", ".join(str(v) for v in s.values()) for s in samples]
            except Exception:
                entry["samples"] = []
            if declared_unique.get(st[1]):
                entry["detail"] += " ★证伪 join_safety 声明（designer 标唯一，实测不唯一）"
        out.append(entry)
    return out


def render(rule_code: str, entries: list[dict]) -> str:
    lines = [f"# 关联发散定位（opt 轻量版）· 规则 {rule_code}", ""]
    for e in entries:
        lines.append(f"- [{e['status']}] {e['table']}（{e['alias']}）: {e['detail']}"
                     + (f"｜filter: {e['filter']}" if e.get("filter") else ""))
        for s in (e.get("samples") or [])[:SAMPLE_LIMIT]:
            lines.append(f"    - 重复键: {s}")
    if not entries:
        lines.append("（该规则无 JOIN / 无可测表）")
    lines.append("")
    lines.append("> 判据：关联键条件下唯一 ⇒ 任何数据不膨胀。不唯一的表是发散根因候选——"
                 "改法归人定（换键/收敛条件/退源端），不自动改。")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="opt 关联发散定位（逐表键唯一性主判据）")
    ap.add_argument("--ts-v2", required=True)
    ap.add_argument("--rule", default="", help="规则码（默认全部有 JOIN 的规则）")
    args = ap.parse_args(argv)

    ts = json.loads(Path(args.ts_v2).read_text(encoding="utf-8"))
    rules = ts.get("rules") or {}
    targets = {args.rule} if args.rule else set(rules)
    schema = ts.get("meta", {}).get("target", {}).get("f_table", {}).get("schema", "")

    try:
        from dws_db import create_executor_for_schema
        executor = create_executor_for_schema(schema, role="etl")
    except Exception as e:
        print(f"FANOUT_NO_DB: 连不上库——证据工具降级（{e}）。人定根因可用 explore 逐表试算",
              file=sys.stderr)
        return 3

    ts_path = Path(args.ts_v2)
    diag_dir = ts_path.parent / "_internal" / "diagnose"
    diag_dir.mkdir(parents=True, exist_ok=True)
    try:
        bad = 0
        for code in sorted(targets):
            rule = rules.get(code) or {}
            if not (rule.get("joins") or []):
                continue
            entries = check_rule(executor, code, rule)
            text = render(code, entries)
            out_path = diag_dir / f"fanout_{code}.md"
            out_path.write_text(text, encoding="utf-8")
            print(text)
            print(f"→ {out_path}")
            bad += sum(1 for e in entries if e["status"] == "DUP")
        print(f"\n汇总: {'❌ ' + str(bad) + ' 张表键不唯一（发散根因候选）' if bad else '✅ 全部关联键唯一——发散另有根因（过滤条件/数据本身）'}")
        return 0
    finally:
        try:
            executor.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
