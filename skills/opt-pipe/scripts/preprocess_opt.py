"""preprocess_opt —— 优化输入预处理 v2（真实输入格式：全量 mapping + RS，2026-08-21 确认）。

输入（契约参数直传，不猜文件——分拣器已退役 2026-08-31）：
  --mapping     全量 mapping xlsx 路径（调用方/人指定，内网命名无关键词约定）
  --rs          RS md 路径（变更记录在 RS，opt 场景必有）
  --ts-baseline 档案 ts（archive/ts.json，只读）
  --version     可选覆盖（默认 = RS 变更记录最新"优化"行日期归一 YYYYMM）

真实格式约定（mapping-format.md 备注版本标记规范）：
  - mapping 备注列写 "{YYYYMM}版本{动词}"（如"202608版本新增"），多次优化多个标记
  - RS 3.3 变更记录表（日期/版本/修改人/修改内容），修改内容含"优化"的行 = 优化版本
  - RS 正文以"{YYYYMM}版本"为锚描述该版本完整需求（变更记录里是简述）

提取：本次版本 + "新增"标记的行 → 变更清单（属性级 = add_field 候选，实体级 = 新来源）；
其他动词（修改/下线…）→ 归类 change_type 并报告"待扩展"（识别是一回事，支持是另一回事）。
校验：冲突/别名配对/资产一致（F/I 镜像归一：mapping 写 I 视图、baseline 记 F 表是同一资产）
      + 版本锚定与正文对账。
产出：change_request.json（含 source_files/version/变更记录摘要——闸口①'把简述与提取字段并排）。
exit 0/1/2 对齐 precheck 分级。编排者不读输入原文——解析校验全在本脚本。
"""
import argparse
import json
import re
import sys
from pathlib import Path

# shared 公共库自洽引用：相对路径推算 design-dev-shared（skill 脚本标准 bootstrap）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "design-dev-shared" / "scripts"))
from typing import Dict, List, Optional, Tuple

import pandas as pd

from preprocess import ExcelMappingParser

# 备注版本标记：{YYYYMM}版本{动词}（多个标记可并存——多次优化）
REMARK_RE = re.compile(r"(20\d{4})\s*版本\s*(新增|修改|调整|变更|下线|删除|停用)")
# 动词 → change_type（属性级/实体级语义在提取层区分）
VERB_TO_CHANGE = {"新增": "add", "修改": "modify", "调整": "modify", "变更": "modify",
                  "下线": "drop", "删除": "drop", "停用": "drop"}
SUPPORTED_CHANGE_TYPES = {"add"}   # 第一刀全流程仅 add；其余识别+报告待扩展


def norm_asset(name: str) -> str:
    """资产名镜像归一：剥 schema 前缀 + 去 _i/_f 尾（资产铆定 I，mapping 写 I 视图、
    baseline 记 F 表是同一资产的两面——I 视图是 F 表的固定镜像）。"""
    n = (name or "").strip()
    if "." in n:
        n = n.rsplit(".", 1)[-1]
    return re.sub(r"_[if]$", "", n.lower())


# ---------------------------------------------------------------------------
# 2. RS 解析：变更记录表 + 版本锚定
# ---------------------------------------------------------------------------

def _md_tables_after(lines: List[str], start: int) -> List[List[List[str]]]:
    """收集 start 之后连续的 markdown 表格块（| 分隔行）。"""
    tables, cur = [], []
    for ln in lines[start:]:
        s = ln.strip()
        if s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if not all(re.fullmatch(r"[-: ]+", c or "-") for c in cells):  # 跳过分隔行
                cur.append(cells)
        else:
            if cur:
                tables.append(cur)
                cur = []
    if cur:
        tables.append(cur)
    return tables


def parse_change_log(rs_text: str) -> List[dict]:
    """解析变更记录表（定位含"变更记录"的标题，取其后第一个表格）。"""
    lines = rs_text.splitlines()
    for i, ln in enumerate(lines):
        if ln.strip().startswith("#") and "变更记录" in ln:
            tables = _md_tables_after(lines, i + 1)
            if not tables:
                break
            header, *rows = tables[0]
            idx = {k: next((j for j, h in enumerate(header) if k in h), None)
                   for k in ("日期", "版本", "修改人", "修改内容")}
            out = []
            for r in rows:
                get = lambda k: (r[idx[k]] if idx[k] is not None and idx[k] < len(r) else "")
                out.append({"date": get("日期"), "ver": get("版本"),
                            "author": get("修改人"), "desc": get("修改内容")})
            return out
    return []


def normalize_yyyymm(s: str) -> str:
    m = re.search(r"(20\d{2})[-/年.](\d{1,2})", s or "")
    if m:
        return f"{m.group(1)}{int(m.group(2)):02d}"
    m = re.fullmatch(r"(20\d{4})", (s or "").strip())
    if m:
        return m.group(1)
    raise ValueError(f"日期无法归一成 YYYYMM：{s!r}")


def pick_current_version(change_log: List[dict]) -> Tuple[str, dict]:
    """最新"优化"行（修改内容含'优化'）→ (YYYYMM, 该行)。无优化行则报错。"""
    opt_rows = [r for r in change_log if "优化" in r["desc"]]
    if not opt_rows:
        raise ValueError("变更记录表中没有'优化'行——无法定位本次版本（可用 --version 显式指定）")
    row = opt_rows[-1]
    return normalize_yyyymm(row["date"]), row


def extract_version_section(rs_text: str, version: str) -> str:
    """正文按 "{YYYYMM}版本" 锚定提取本次需求段（到下一个版本锚点/空行分隔为止）。"""
    anchor = re.compile(rf"{version}\s*版本")
    next_anchor = re.compile(r"20\d{4}\s*版本")
    lines = rs_text.splitlines()
    out, capturing = [], False
    for ln in lines:
        if anchor.search(ln):
            capturing = True
            out.append(ln)
            continue
        if capturing:
            if next_anchor.search(ln) and not anchor.search(ln):
                break
            if ln.strip().startswith("#") and not anchor.search(ln):
                break
            out.append(ln)
    return "\n".join(out).strip()


# ---------------------------------------------------------------------------
# 3. 全量 mapping 读取 + 备注标记分类
# ---------------------------------------------------------------------------

def read_full_mapping(xlsx_path: Path) -> Dict[str, List[dict]]:
    """读全量 mapping 两 sheet（复用 preprocess 列名映射）→ 规范化行（含 remark 原文）。"""
    xlsx = pd.ExcelFile(xlsx_path)
    entity_df = attr_df = None
    for sheet in xlsx.sheet_names:
        s = sheet.lower()
        if any(k in s for k in ("实体级", "entity")):
            entity_df = pd.read_excel(xlsx, sheet_name=sheet, keep_default_na=False)
        elif any(k in s for k in ("属性级", "attribute")):
            attr_df = pd.read_excel(xlsx, sheet_name=sheet, keep_default_na=False)

    def normalize(df, col_map):
        rows = []
        if df is None:
            return rows
        for _, raw in df.iterrows():
            row = {}
            for col, val in raw.items():
                name = col_map.get(str(col).strip())
                if name:
                    row[name] = str(val).strip() if val is not None else ""
            rows.append(row)
        return rows

    return {"entity": normalize(entity_df, ExcelMappingParser.ENTITY_COLUMN_MAP),
            "attr": normalize(attr_df, ExcelMappingParser.ATTRIBUTE_COLUMN_MAP)}


def remark_markers(remark: str) -> List[Tuple[str, str]]:
    """备注文本 → [(YYYYMM, 动词)]（多次优化多个标记全解析）。"""
    return [(m.group(1), m.group(2)) for m in REMARK_RE.finditer(remark or "")]


def baseline_facts(ts_baseline: dict) -> dict:
    f_table = ts_baseline["meta"]["target"]["f_table"]
    target_short = f_table["table"]
    fields = {f["target_field"]
              for f in ts_baseline.get("tables", {}).get(target_short, {}).get("fields", [])}
    sources = {s.get("table", "") for s in ts_baseline["meta"].get("source_tables", [])}
    return {"asset": f"{f_table['schema']}.{target_short}",
            "target_short": target_short, "target_fields": fields, "source_tables": sources}


# ---------------------------------------------------------------------------
# 4. 提取 + 校验
# ---------------------------------------------------------------------------

def extract_and_check(mapping: Dict[str, List[dict]], facts: dict, version: str,
                      rs_section: str) -> Tuple[List[dict], List[dict], List[dict]]:
    """返回 (add_fields, unsupported, diagnostics)。

    add_fields = 本次版本"新增"标记的属性级行（change_request.fields 条目）；
    unsupported = 识别为其他 change_type 的行（识别+报告，不拒收为非法）。
    """
    diags: List[dict] = []
    unsupported: List[dict] = []
    entity_rows, attr_rows = mapping["entity"], mapping["attr"]

    # 实体级分类：本次版本标记行 = 新来源声明；其余 = 存量
    def row_change(row: dict) -> Optional[Tuple[str, str]]:
        for ver, verb in remark_markers(row.get("remark", "")):
            if ver == version:
                return ver, verb
        return None

    alias_index: Dict[str, dict] = {}
    new_sources: Dict[str, dict] = {}
    for row in entity_rows:
        if row.get("source_alias"):
            alias_index[row["source_alias"]] = row
        ch = row_change(row)
        if ch:
            verb = ch[1]
            ctype = VERB_TO_CHANGE[verb]
            if ctype != "add":
                unsupported.append({"level": "entity", "change_type": ctype,
                                    "name": row.get("source_table", "?"), "verb": verb})
            else:
                new_sources[row["source_table"]] = row

    # 属性级分类
    add_fields: List[dict] = []
    for i, row in enumerate(attr_rows, start=2):
        tcol = row.get("target_column", "")
        ch = row_change(row)
        if ch:
            ctype = VERB_TO_CHANGE[ch[1]]
            if ctype != "add":
                unsupported.append({"level": "attr", "change_type": ctype,
                                    "name": tcol or "?", "verb": ch[1]})
                continue
            # add_field 候选：走原有校验链
            if tcol in facts["target_fields"]:
                diags.append({"level": "error", "code": "add_field_conflict",
                              "message": f"属性级第{i}行：{tcol!r} 标本次新增但 baseline 已存在"})
                continue
            alias = row.get("source_alias", "")
            ent = alias_index.get(alias)
            if ent is None:
                diags.append({"level": "error", "code": "source_alias_dangling",
                              "message": f"属性级第{i}行：源表别名 {alias!r} 在实体级找不到"})
                continue
            add_fields.append({
                "field": tcol, "cn": row.get("target_column_cn", ""),
                "type": row.get("target_type", ""), "scene_group": row.get("scene_group", ""),
                "source": {"schema": ent.get("source_schema", ""),
                           "table": ent.get("source_table", ""), "alias": alias,
                           "field": row.get("source_column", ""),
                           "rule": row.get("mapping_rule", ""),
                           "expr": row.get("mapping_expression", ""),
                           "join_condition": ent.get("join_condition", "")},
                "new_source_table": ent.get("source_table", "") not in facts["source_tables"],
            })
        else:
            if tcol and tcol not in facts["target_fields"]:
                diags.append({"level": "warn", "code": "unmarked_new_field",
                              "message": f"属性级第{i}行：{tcol!r} 不在 baseline 存量且无本次"
                                         f"版本标记（旧版本漏入档 or 漏标）——请业务确认"})

    # 资产定位一致性（F/I 镜像归一：mapping 目标表写 I 视图、baseline 记 F 表是常态）
    for t in sorted({r.get("target_table", "") for r in entity_rows if r.get("target_table")}):
        if norm_asset(t) != norm_asset(facts["target_short"]):
            diags.append({"level": "error", "code": "asset_table_mismatch",
                          "message": f"实体级目标表 {t!r} 与本次资产 {facts['target_short']!r} 不一致"
                                     f"（已按 I/F 镜像归一比较）"})

    # RS 对账：新增字段应出现在版本锚定段
    if rs_section:
        for f in add_fields:
            if f["field"] not in rs_section:
                diags.append({"level": "warn", "code": "rs_field_not_mentioned",
                              "message": f"新增字段 {f['field']!r} 未在 RS {version}版本 需求段提及"})
    else:
        diags.append({"level": "warn", "code": "rs_section_not_found",
                      "message": f"RS 正文未找到 {version}版本 锚定段——口径请人确认"})
    return add_fields, unsupported, diags


# ---------------------------------------------------------------------------
# 5. 组装与 main
# ---------------------------------------------------------------------------

def build_change_request(facts: dict, version: str, add_fields: List[dict],
                         unsupported: List[dict], change_log_row: dict,
                         rs_section: str, files: dict) -> dict:
    return {
        "change_type": "add_field",
        "version": version,
        "asset": facts["asset"],
        "change_log_summary": change_log_row,   # 闸口素材：简述 ↔ 提取字段并排（delta 已取消，漏标靠人扫这一眼）
        "unsupported_changes": unsupported,     # 识别+归类但流程待扩展（modify/drop/add_source…）
        "source_files": files,
        "fields": add_fields,
        "backfill": "pending",
        "rs_opt_section": rs_section,
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="优化输入预处理 v2：全量 mapping + RS（契约参数直传）")
    ap.add_argument("--mapping", required=True, help="全量 mapping xlsx 路径（调用方指定）")
    ap.add_argument("--rs", required=True, help="RS md 路径（变更记录所在，opt 场景必有）")
    ap.add_argument("--ts-baseline", required=True, help="档案 ts（archive/ts.json，只读）")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--version", default="", help="覆盖版本号（默认 RS 变更记录最新优化行 YYYYMM）")
    args = ap.parse_args(argv)

    mapping_path, rs_path = Path(args.mapping), Path(args.rs)
    for p, label in ((mapping_path, "mapping"), (rs_path, "RS")):
        if not p.exists():
            print(f"OPT_PRECHECK_ERROR: {label} 文件不存在: {p}", file=sys.stderr)
            return 2

    rs_text = rs_path.read_text(encoding="utf-8")
    try:
        change_log = parse_change_log(rs_text)
        version = args.version or pick_current_version(change_log)[0]
        if args.version:
            row = next((r for r in reversed(change_log) if "优化" in r["desc"]),
                       {"date": args.version, "desc": "（显式指定版本）"})
        else:
            row = pick_current_version(change_log)[1]
    except ValueError as e:
        print(f"OPT_PRECHECK_ERROR: {e}", file=sys.stderr)
        return 2
    rs_section = extract_version_section(rs_text, version)

    ts_baseline = json.loads(Path(args.ts_baseline).read_text(encoding="utf-8"))
    facts = baseline_facts(ts_baseline)
    mapping = read_full_mapping(mapping_path)
    add_fields, unsupported, diags = extract_and_check(mapping, facts, version, rs_section)

    errors = [d for d in diags if d["level"] == "error"]
    warns = [d for d in diags if d["level"] == "warn"]
    for d in diags:
        print(f"[{d['level'].upper()}][{d['code']}] {d['message']}", file=sys.stderr)
    for u in unsupported:
        print(f"[INFO] 识别到 {u['change_type']} 变更（{u['level']} {u['name']}，"
              f"备注动词'{u['verb']}'）——本刀流程未支持，待扩展", file=sys.stderr)

    if errors:
        out = Path(args.outdir)
        out.mkdir(parents=True, exist_ok=True)
        print(f"OPT_PRECHECK_BLOCKED：{len(errors)} 项阻断，{len(warns)} 项 warn。", file=sys.stderr)
        return 2

    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    cr = build_change_request(facts, version, add_fields, unsupported, row, rs_section,
                              {"mapping": str(mapping_path), "rs": str(rs_path),
                               "ts_baseline": str(args.ts_baseline)})
    (out / "change_request.json").write_text(
        json.dumps(cr, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"change_request: {out / 'change_request.json'}")
    print(f"version: {version}, add_fields: {len(add_fields)}, "
          f"unsupported: {len(unsupported)}, warns: {len(warns)}")
    return 1 if warns else 0


if __name__ == "__main__":
    sys.exit(main())
