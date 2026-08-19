"""preprocess_opt —— 优化输入预处理（docs/specs/opt/03 §一/二 + 02 §三）。

输入：已标注 mapping.xlsx（模板 + "变更标识"列，业务侧交付）+ ts_baseline.json（组装备件）
     [+ RS.md 可选：优化章节原文附挂]
产出：change_request.json（**业务级**变更清单：业务说了什么——字段/含义/源意图；
     **不含落位**——挂哪条规则/怎么改是 designer 的事，见 03 §二两级声明）
     诊断分级对齐 precheck：exit 0 通过 / 1 有 warn（问人）/ 2 阻断。

范围（阶段一）：
- 机械校验全量：标识枚举 / 冲突（标"新增"但 baseline 已有）/ 漏标提示 /
  实体-属性级配对（源表别名悬空）/ 资产定位一致性 / 存量表重复声明新来源；
- 新来源信号（源表不在 baseline 源表清单）是**事实标记**，供 designer 落位用；
- RS 解析最小化：优化章节原文附挂 + 新增字段名出现性对账（warn）——口径/回刷意向
  由 designer 读原文，不做模糊结构化（RS 优化章节格式未定，00 挂账）；
- 回刷 × load_mode 一致性在闸口①'人选拿时检查（本模块不预判）。

列名定义单源：复用 preprocess.ExcelMappingParser 的列名映射（mapping-format.md 权威）。
"""
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from preprocess import ExcelMappingParser
from baseline_contract import validate_baseline_v1  # noqa: F401  （保留导入关系备扩展）

# 优化场景新增列（mapping-format.md 扩展，v2.3 兼容性检查：new-pipe 静默忽略该列）
CHANGE_FLAG_COL = "变更标识"
SUPPORTED_FLAGS = {"", "新增"}   # 第一刀只认"新增"；空串 = 存量行

# 诊断码（阶段一；阶段二接 assemble_ts 报错风格时保持同名）
D_UNSUPPORTED_FLAG = "unsupported_change_flag"
D_FIELD_CONFLICT = "add_field_conflict"
D_ENTITY_CONFLICT = "entity_add_conflict"
D_UNMARKED_NEW_FIELD = "unmarked_new_field"
D_ALIAS_DANGLING = "source_alias_dangling"
D_ASSET_MISMATCH = "asset_table_mismatch"
D_RS_FIELD_ABSENT = "rs_field_not_mentioned"


# ---------------------------------------------------------------------------
# 读取已标注 mapping（复用 preprocess 的 sheet 发现与列名映射）
# ---------------------------------------------------------------------------

def read_marked_mapping(xlsx_path: Path) -> Dict[str, List[dict]]:
    """读实体级/属性级 sheet → 规范化行列表（键=列名映射后的英文名，值=字符串）。"""
    xlsx = pd.ExcelFile(xlsx_path)
    entity_df = attr_df = None
    for sheet in xlsx.sheet_names:
        s = sheet.lower()
        if any(k in s for k in ("实体级", "entity")):
            entity_df = pd.read_excel(xlsx, sheet_name=sheet, keep_default_na=False)
        elif any(k in s for k in ("属性级", "attribute")):
            attr_df = pd.read_excel(xlsx, sheet_name=sheet, keep_default_na=False)

    def normalize(df: Optional[pd.DataFrame], col_map: dict, label: str) -> List[dict]:
        if df is None:
            return []
        rows = []
        for _, raw in df.iterrows():
            row: Dict[str, str] = {}
            for col, val in raw.items():
                name = col_map.get(str(col).strip(), None)
                val_s = str(val).strip() if val is not None else ""
                if name:
                    row[name] = val_s
                elif str(col).strip() == CHANGE_FLAG_COL:
                    row["change_flag"] = val_s
            rows.append(row)
        return rows

    return {
        "entity": normalize(entity_df, ExcelMappingParser.ENTITY_COLUMN_MAP, "实体级"),
        "attr": normalize(attr_df, ExcelMappingParser.ATTRIBUTE_COLUMN_MAP, "属性级"),
    }


# ---------------------------------------------------------------------------
# baseline 消费视角（ts_baseline 的最小读取面）
# ---------------------------------------------------------------------------

def baseline_facts(ts_baseline: dict) -> dict:
    """从 ts_baseline 提取校验所需事实：资产表 / 目标表字段集 / 源表集。"""
    f_table = ts_baseline["meta"]["target"]["f_table"]
    target_short = f_table["table"]
    fields = {f["target_field"]
              for f in ts_baseline.get("tables", {}).get(target_short, {}).get("fields", [])}
    sources = {s.get("table", "") for s in ts_baseline["meta"].get("source_tables", [])}
    return {"asset": f"{f_table['schema']}.{target_short}",
            "target_short": target_short, "target_fields": fields, "source_tables": sources}


# ---------------------------------------------------------------------------
# 校验 + 变更提取
# ---------------------------------------------------------------------------

def extract_and_check(mapping: Dict[str, List[dict]], facts: dict,
                      rs_text: Optional[str]) -> Tuple[List[dict], List[dict], List[dict]]:
    """返回 (add_fields, diagnostics, unsupported_flags)。

    add_fields 元素即 change_request.fields 条目（业务说了什么 + 事实标记）。
    """
    diags: List[dict] = []
    unsupported: List[str] = []
    entity_rows, attr_rows = mapping["entity"], mapping["attr"]

    # 0. 标识枚举（实体级 + 属性级都查）
    for label, rows in (("实体级", entity_rows), ("属性级", attr_rows)):
        for i, row in enumerate(rows, start=2):   # start=2：xlsx 行号（含表头）
            flag = row.get("change_flag", "")
            if flag not in SUPPORTED_FLAGS:
                unsupported.append(flag)
                diags.append({"level": "error", "code": D_UNSUPPORTED_FLAG,
                              "message": f"{label}第{i}行：变更标识 {flag!r} 不支持"
                                         f"（本刀仅支持：新增 / 留空=存量）"})

    # 1. 资产定位一致性：实体级声明的目标表必须就是本次资产
    target_tables = {r.get("target_table", "") for r in entity_rows if r.get("target_table")}
    for t in sorted(target_tables):
        if t != facts["target_short"]:
            diags.append({"level": "error", "code": D_ASSET_MISMATCH,
                          "message": f"实体级目标表 {t!r} 与本次资产 "
                                     f"{facts['target_short']!r} 不一致（载体用错/标注错资产）"})

    # 2. 实体级新增行：存量表重复声明 → 冲突
    for i, row in enumerate(entity_rows, start=2):
        if row.get("change_flag") == "新增" and row.get("source_table") in facts["source_tables"]:
            diags.append({"level": "error", "code": D_ENTITY_CONFLICT,
                          "message": f"实体级第{i}行：源表 {row.get('source_table')!r} 已是 "
                                     f"baseline 存量来源，不能标'新增'（同源直挂不需要新实体行）"})

    # 3. 别名索引（实体级全部行——存量行与新增行都可被属性级引用）
    alias_index: Dict[str, dict] = {}
    for row in entity_rows:
        if row.get("source_alias"):
            alias_index[row["source_alias"]] = row

    # 4. 属性级逐行：新增提取 / 冲突 / 漏标 / 配对
    add_fields: List[dict] = []
    for i, row in enumerate(attr_rows, start=2):
        flag = row.get("change_flag", "")
        tcol = row.get("target_column", "")
        if not tcol:
            continue
        if flag == "新增":
            if tcol in facts["target_fields"]:
                diags.append({"level": "error", "code": D_FIELD_CONFLICT,
                              "message": f"属性级第{i}行：目标字段 {tcol!r} 标'新增'但 "
                                         f"baseline 已存在（存量字段——请核对标注或需求）"})
                continue
            alias = row.get("source_alias", "")
            ent = alias_index.get(alias)
            if ent is None:
                diags.append({"level": "error", "code": D_ALIAS_DANGLING,
                              "message": f"属性级第{i}行：源表别名 {alias!r} 在实体级找不到"
                                         f"（新表来源需在实体级加行并标'新增'）"})
                continue
            src_table = ent.get("source_table", "")
            add_fields.append({
                "field": tcol,
                "cn": row.get("target_column_cn", ""),
                "type": row.get("target_type", ""),
                "scene_group": row.get("scene_group", ""),
                "source": {
                    "schema": ent.get("source_schema", ""),
                    "table": src_table,
                    "alias": alias,
                    "field": row.get("source_column", ""),
                    "rule": row.get("mapping_rule", ""),
                    "expr": row.get("mapping_expression", ""),
                    "join_condition": ent.get("join_condition", ""),
                },
                # 事实标记：源表不在 baseline 源表清单 → 新来源（落位归 designer）
                "new_source_table": src_table not in facts["source_tables"],
            })
        else:
            if tcol not in facts["target_fields"]:
                diags.append({"level": "warn", "code": D_UNMARKED_NEW_FIELD,
                              "message": f"属性级第{i}行：目标字段 {tcol!r} 不在 baseline "
                                         f"存量字段中且未标'新增'——漏标？（请业务确认）"})

    # 5. RS 对账（可选）：新增字段名应出现在 RS 优化章节
    if rs_text:
        for f in add_fields:
            if f["field"] not in rs_text:
                diags.append({"level": "warn", "code": D_RS_FIELD_ABSENT,
                              "message": f"新增字段 {f['field']!r} 未在 RS 优化章节提及"
                                         f"（双源对账——请业务确认口径来源）"})
    return add_fields, diags, unsupported


# ---------------------------------------------------------------------------
# RS 优化章节提取（最小化：定位含"优化"的标题，取其后的原文；找不到取全文）
# ---------------------------------------------------------------------------

def extract_rs_opt_section(rs_text: str) -> str:
    lines = rs_text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.strip().startswith("#") and "优化" in ln:
            start = i
            break
    if start is None:
        return rs_text.strip()
    out = lines[start:]
    for j in range(1, len(out)):
        if out[j].strip().startswith("#") and "优化" not in out[j]:
            return "\n".join(out[:j]).strip()
    return "\n".join(out).strip()


# ---------------------------------------------------------------------------
# change_request 组装与 main
# ---------------------------------------------------------------------------

def build_change_request(facts: dict, add_fields: List[dict],
                         rs_section: str, files: dict) -> dict:
    return {
        "change_type": "add_field",          # 原则6：枚举第一值
        "asset": facts["asset"],
        "source_files": files,
        "fields": add_fields,
        "backfill": "pending",               # 回刷意向：RS 无结构化来源时 pending 到闸口①'
        "rs_opt_section": rs_section or "",  # 原文附挂，designer 读口径（不做模糊结构化）
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="优化输入预处理：标注 mapping → change_request")
    ap.add_argument("--mapping", required=True, help="已标注 mapping.xlsx")
    ap.add_argument("--ts-baseline", required=True, help="ts_baseline.json（组装备件）")
    ap.add_argument("--outdir", required=True, help="输出目录（{deliver}/_internal）")
    ap.add_argument("--rs", default="", help="RS.md（可选，优化章节原文附挂+对账）")
    args = ap.parse_args(argv)

    ts_baseline = json.loads(Path(args.ts_baseline).read_text(encoding="utf-8"))
    facts = baseline_facts(ts_baseline)
    mapping = read_marked_mapping(Path(args.mapping))
    rs_text = Path(args.rs).read_text(encoding="utf-8") if args.rs else ""
    rs_section = extract_rs_opt_section(rs_text) if rs_text else ""

    add_fields, diags, _ = extract_and_check(mapping, facts, rs_section)
    errors = [d for d in diags if d["level"] == "error"]
    warns = [d for d in diags if d["level"] == "warn"]

    for d in diags:
        print(f"[{d['level'].upper()}][{d['code']}] {d['message']}", file=sys.stderr)

    if errors:
        print(f"OPT_PRECHECK_BLOCKED：{len(errors)} 项阻断（错误需处理输入后重跑），"
              f"{len(warns)} 项 warn。", file=sys.stderr)
        return 2

    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    cr = build_change_request(facts, add_fields, rs_section,
                              {"mapping": str(args.mapping), "rs": args.rs or None,
                               "ts_baseline": str(args.ts_baseline)})
    (out / "change_request.json").write_text(
        json.dumps(cr, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"change_request: {out / 'change_request.json'}")
    print(f"add_fields: {len(add_fields)}, warns: {len(warns)}")
    return 1 if warns else 0


if __name__ == "__main__":
    sys.exit(main())
