"""preprocess_opt —— 优化输入预处理 v3（变更记录页签格式，2026-10-14 与业务侧确认）。

输入（契约参数直传，不猜文件——分拣器已退役 2026-08-31）：
  --mapping     全量 mapping xlsx 路径（调用方/人指定，内网命名无关键词约定）
  --rs          RS md 路径（口径材料：DQ/调度/回刷意向 + 变更记录列区分）
  --ts-baseline 档案 ts（archive/ts.json，只读）
  --version     可选覆盖（默认 = mapping 变更记录页签最新批次时间归一 YYYYMM）

v3 输入格式（mapping-format.md「变更记录页签」规范——变更事实主源在 mapping）：
  - 实体级/属性级两页签结构不变，内容 = 当前需求下最全最新（当前态）
  - 「变更记录」页签八列：变更序号/变更时间/变更页签(实体级|属性级)/变更KEY(列名匹配大小写不敏感)
    （实体级=分组|源表别名，属性级=分组|目标字段名——锚定唯一行）/变更列/变更类型
    (MODIFY|ADD|DELETE)/变更前/变更后
  - 历史批次累积，按变更时间归一 YYYYMM 区分（默认取最新批次）
  - 特殊值「资产字段」（变更列）= 整行新增（新字段/新来源，不逐列列举）
  - 改名 = 先删后加两行（DELETE 行变更后 = ADD 行的 key），synth_renames 严格证据合成
  - RS 承载 DQ/调度等需求侧信息（职责不变），表格加"变更记录"列区分本次；口径材料角色

提取：本批次 属性级 ADD（资产字段）→ add_field 候选（详情从属性级当前态取）；
rename/MODIFY/DELETE/实体级 ADD/列级 ADD → 识别归类报告"待扩展"（不拒收）。
校验：冲突/别名配对/资产一致（F/I 镜像归一）+ 漏标扫描（当前态有而 baseline 无且无 ADD）
+ 存量字段类型对账（同名异容——mapping 改存量类型无变更记录=账面失真，warn 披露；
执行由围栏兜底）。unsupported 报告附目标存在性事实（分辨笔误 vs 真待支持）。
产出：change_request.json（含 change_entries 全量规范化行——闸口①'材料）。
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

from preprocess import (ExcelMappingParser, parse_mapping_sheets, check_mapping_static,
                        clean_excel_column)

# 变更记录页签八列（规格见 mapping-format.md；列名按真实模板——「变更KEY」KEY 为大写，
# 匹配大小写不敏感：列头 strip+lower 归一后对标准名查找，变更KEY/变更key 均命中）
CHANGE_SHEET_COLS = ["变更序号", "变更时间", "变更页签", "变更KEY", "变更列", "变更类型", "变更前", "变更后"]
_CHANGE_COL_LOOKUP = {c.lower(): c for c in CHANGE_SHEET_COLS}
# 变更列约定值：整行新增（新字段/新来源——不逐列列举）
WHOLE_ROW_MARK = "资产字段"
# 第一刀全流程仅支持属性级整行 ADD；其余识别+报告待扩展
SUPPORTED_CTYPES = {"ADD"}


def render_baseline_view_from_ts(ts: dict) -> str:
    """从档案 ts 渲染 baseline_view 简化版（档案/收档路径——无逆向契约元信息，
    规则清单/写入类型/源表/字段从 ts 全量可得；json 入料的完整版优先不覆盖）。"""
    meta = ts.get("meta", {})
    f_table = meta.get("target", {}).get("f_table", {})
    lines = [
        f"# baseline_view · {f_table.get('schema','')}.{f_table.get('table','')}",
        "",
        "> 档案基线（当前态 ts 投影）。逆向 warnings/平台代数等契约元信息仅在 json 入料路径"
        "的完整版 baseline_view 中（本文件由 preprocess_opt 从档案渲染）。",
        "",
        "## 规则清单",
        "",
        "| 规则 | 写入 | 目标表 | 源表 |",
        "|------|------|--------|------|",
    ]
    for code, r in sorted((ts.get("rules") or {}).items(), key=lambda kv: (kv[1].get("exec_sequence", 1), kv[0])):
        srcs = ", ".join(f"{s.get('schema','')}.{s.get('table','')}" for s in (r.get("source_tables") or []))
        lines.append(f"| {code} | {r.get('load_mode','')} | {r.get('target_table','')} | {srcs} |")
    lines += ["", "## 目标表字段数", ""]
    for tb, td in sorted((ts.get("tables") or {}).items()):
        lines.append(f"- {tb}: {len(td.get('fields') or [])} 字段")
    if ts.get("_baseline"):
        lines += ["", "> 语义空位（存量不补，回归由输出对比保障）：主键/粒度/关联安全"
                  "（见 _internal/exemptions.json）。"]
    return "\n".join(lines)


from baseline_contract import norm_asset  # 资产对账归一口径（唯一源）


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
    """解析 RS 3.3 变更记录表（v3 降为材料角色——版本锚定主源已移至 mapping 变更记录页签）。"""
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

# read_full_mapping 已退役（2026-10-22 收敛）：全量 mapping 两页签的读取/列名归一/
# 列完整性校验全仓唯一实现=shared preprocess.parse_mapping_sheets（与主链路同一份
# 代码——「源表Schema」大写/全角/尾部* 归一命中，缺标准列 ValueError 阻断）。
# opt 侧自有代码只剩变更记录这个真正的增量（read_change_sheet/批次/合成/匹配/对账）。


def read_change_sheet(xlsx_path: Path) -> List[dict]:
    """读「变更记录」页签 → 规范化变更条目（v3 变更事实主源）。

    行结构：{seq, time(YYYYMM), page(entity|attr), group, key, column, ctype, before, after}。
    缺页签/缺列/页签值或类型枚举外/时间无法归一 → ValueError（exit 2 阻断改输入）。
    列头匹配=clean_excel_column 归一单点（2026-10-22 收敛——此前 name.lower() 是
    半吊子归一，与全量页签的清洗链口径分裂）。
    """
    xlsx = pd.ExcelFile(xlsx_path)
    sheet = next((s for s in xlsx.sheet_names if "变更记录" in s), None)
    if sheet is None:
        raise ValueError("mapping 缺「变更记录」页签——v3 输入格式的变更事实主源（规格见 mapping-format.md）")
    df = pd.read_excel(xlsx, sheet_name=sheet, keep_default_na=False)
    col_idx = {}
    for c in df.columns:
        std = _CHANGE_COL_LOOKUP.get(clean_excel_column(str(c)))
        if std and std not in col_idx:
            col_idx[std] = c
    missing = [c for c in CHANGE_SHEET_COLS if c not in col_idx]
    if missing:
        raise ValueError(f"「变更记录」页签缺列：{missing}（八列规格见 mapping-format.md）")

    entries: List[dict] = []
    for _, raw in df.iterrows():
        get = lambda k: (str(raw[col_idx[k]]).strip()
                         if raw[col_idx[k]] is not None else "")
        if not any(get(k) for k in CHANGE_SHEET_COLS):
            continue  # 空行
        page_raw = get("变更页签")
        page = "entity" if "实体" in page_raw else ("attr" if "属性" in page_raw else "")
        group, _, key_name = get("变更KEY").partition("|")
        # 标识符归一小写（DWS=PG 内核 foldcase；变更页签 key 常为大写形态，
        # 属性级当前态字段名为小写——归一后同表对齐，大小写差异不构成不同字段）
        group, key_name = group.strip().lower(), key_name.strip().lower()
        try:
            time_ym = normalize_yyyymm(get("变更时间")) if get("变更时间") else ""
        except ValueError as e:
            raise ValueError(f"「变更记录」序号 {get('变更序号')!r} 变更时间归一失败：{e}")
        entries.append({"seq": get("变更序号"), "time": time_ym, "page": page,
                        "group": group.strip(), "key": key_name.strip(),
                        "column": get("变更列"), "ctype": get("变更类型").upper(),
                        "before": get("变更前"), "after": get("变更后")})
    bad = next((e for e in entries
                if not e["page"] or not e["time"] or e["ctype"] not in ("ADD", "MODIFY", "DELETE")), None)
    if bad:
        raise ValueError(f"「变更记录」序号 {bad['seq']!r} 行非法（变更页签须为 实体级|属性级、"
                         f"变更类型须为 MODIFY|ADD|DELETE、变更时间必填）：{bad}")
    return entries


def pick_batch_version(entries: List[dict]) -> str:
    """变更记录页签最新批次（变更时间归一 YYYYMM 取 max）——版本锚定主源。"""
    times = sorted({e["time"] for e in entries})
    if not times:
        raise ValueError("「变更记录」页签无有效批次——无法定位本次版本（可用 --version 显式指定）")
    return times[-1]


def synth_renames(batch: List[dict]) -> Tuple[List[dict], List[dict]]:
    """改名合成（严格证据链）：同批次内 attr DELETE 行的「变更后」== 某 attr ADD 行的 key。

    返回 (renames, rest)：合成对从独立清单移除（改名=存量字段级变更，第一刀待扩展）；
    证据不成立（DELETE.变更后 为空/无匹配 ADD）→ 保持独立 DELETE/ADD 各自归类。
    """
    renames: List[dict] = []
    paired_ids = set()
    for d in (e for e in batch if e["page"] == "attr" and e["ctype"] == "DELETE" and e["after"]):
        a = next((e for e in batch if e["page"] == "attr" and e["ctype"] == "ADD"
                  and e["key"] == d["after"].strip().lower() and id(e) not in paired_ids), None)
        if a is not None:
            paired_ids.update({id(d), id(a)})
            renames.append({"kind": "rename", "group": d["group"],
                            "old": d["key"], "new": a["key"],
                            "seq": f"{d['seq']}+{a['seq']}",
                            "after_raw": d["after"]})
    rest = [e for e in batch if id(e) not in paired_ids]
    return renames, rest


def baseline_facts(ts_baseline: dict) -> dict:
    f_table = ts_baseline["meta"]["target"]["f_table"]
    target_short = f_table["table"]
    field_list = ts_baseline.get("tables", {}).get(target_short, {}).get("fields", [])
    fields = {f["target_field"] for f in field_list}
    field_types = {(f.get("target_field") or "").strip().lower(): (f.get("field_type") or "").strip()
                   for f in field_list}
    sources = {s.get("table", "") for s in ts_baseline["meta"].get("source_tables", [])}
    return {"asset": f"{f_table['schema']}.{target_short}",
            "target_short": target_short, "target_fields": fields,
            "field_types": field_types, "source_tables": sources}


# types_compatible（类型归一比）已归位 shared/type_compat（2026-10-22 第二刀：
# assemble_ts_opt/fence_check 跨 pipe 不可 import 此处——类型判定唯一源在 type_compat）
from type_compat import types_compatible  # noqa: F401  re-export 保旧引用（audit_ingest/测试）


def field_type_drift(attr_rows: List[dict], baseline_types: Dict[str, str],
                     skip: set) -> List[dict]:
    """存量字段类型对账（同名异容，2026-10-21 三方一致性补位）：mapping 属性级当前态
    vs 基线字段类型。检查矩阵里漏标扫描（名字正向）/台账滞后（名字反向）之外的
    内容级——mapping 改存量字段类型而无变更记录=账面静默失真（执行由围栏锁存量
    兜底不受影响，此处是账面对账）。

    归一比（types_compatible 单点：family/base 同义/length/scale）——书写形态差异
    （NUMBER(18,2) vs numeric(18,2)）天然消除；中文名不对账（人写格式自由全是噪音）。
    skip=本批新增/改名/**已申报 MODIFY** 的字段（申报的类型变更是预期变更不是漂移——
    未申报的照报，引导走正路）；任一侧类型空=跳过不猜（宁放过）。
    返回 warn 级 diags。消费方：preprocess_opt（有档链）+ audit_ingest（入料链，同
    一文案单点）。
    """
    out: List[dict] = []
    for i, row in enumerate(attr_rows, start=2):
        tcol = (row.get("target_column") or "").strip().lower()
        declared = (row.get("target_type") or "").strip()
        if not tcol or tcol in skip or not declared:
            continue
        base_t = (baseline_types or {}).get(tcol, "")
        if not base_t:
            continue  # 不在基线（漏标扫描管）/基线类型空
        if not types_compatible(declared, base_t):
            out.append({"level": "warn", "code": "field_type_drift",
                        "message": f"属性级第{i}行：存量字段 {tcol!r} 类型与基线不一致——"
                                   f"mapping {declared!r} vs 基线 {base_t!r}（归一比较）。"
                                   f"围栏锁存量、执行不受影响；若确要改类型：撤销台账改动"
                                   f"或走变更流程（MODIFY 支持待扩展）"})
    return out


# ---------------------------------------------------------------------------
# 4. 提取 + 校验（v3：变更记录页签驱动）
# ---------------------------------------------------------------------------

def _match_attr_rows(attr_rows: List[dict], entry: dict) -> List[dict]:
    """按变更key（分组|目标字段名）在属性级当前态匹配行——分组空时按字段名宽松匹配；
    标识符两侧归一小写（key 常为大写形态，当前态字段名为小写）。"""
    hits = [r for r in attr_rows
            if (r.get("target_column") or "").strip().lower() == entry["key"]
            and (not entry["group"]
                 or (r.get("scene_group") or "").strip().lower() == entry["group"])]
    return hits


def _existence_note(key: str, attr_target_cols: set, baseline_fields: set) -> str:
    """unsupported 条目的目标存在性事实（2026-10-21）：key 在两侧登记处的命中情况——
    人看 INFO 行即可分辨"变更记录笔误"vs"真待支持"，不用回查台账。
    事实增强不是对账（对账口径随对应变更类型支持刀一起定义）。"""
    in_m = (key or "").strip().lower() in attr_target_cols
    in_b = (key or "").strip().lower() in {str(f).lower() for f in baseline_fields}
    if in_m and in_b:
        return ""
    if not in_m and not in_b:
        return "｜key 不在属性级当前态与基线（变更记录疑似笔误）"
    if not in_m:
        return "｜key 不在属性级当前态（台账滞后形态——基线有台账无）"
    return "｜key 不在基线字段集"


def extract_and_check(batch: List[dict], renames: List[dict], mapping: Dict[str, List[dict]],
                      facts: dict, version: str, rs_section: str
                      ) -> Tuple[List[dict], List[dict], List[dict], List[dict], List[dict]]:
    """返回 (add_fields, new_sources, modify_fields, unsupported, diagnostics)。

    add_fields = 本批次属性级整行 ADD（变更列=资产字段）且 key 不在 baseline → 字段详情
    从属性级当前态取（变更页签只说"哪些变了"，内容取当前态 mapping）；
    new_sources = 实体级整行 ADD（新增来源表声明，2026-10-22 第二刀场景 A——内网第
    一案例综合场景）：新表取数链路第一刀已通（新字段附属），此处升级为显式声明消费；
    modify_fields = 属性级 MODIFY 且变更列=目标字段类型（2026-10-22 第二刀场景 B：
    目标字段类型修改）——三方对账（变更前≈baseline 旧类型/变更后≈mapping 当前态新
    类型，types_compatible 归一比）；其他列的 MODIFY（口径/表达式变更）仍待扩展；
    unsupported = 识别为其他变更形态（rename/DELETE/其他列 MODIFY/列级 ADD/实体级
    其他类型）——识别+报告"待扩展"（附目标存在性事实），不拒收为非法。
    """
    diags: List[dict] = []
    unsupported: List[dict] = []
    entity_rows, attr_rows = mapping["entity"], mapping["attr"]
    alias_index: Dict[str, dict] = {}
    for row in entity_rows:
        if row.get("source_alias"):
            alias_index[row["source_alias"]] = row
    attr_target_cols = {(r.get("target_column") or "").strip().lower() for r in attr_rows}
    # 本批次声明的整行新增字段集（变更事实——与"校验通过集"add_keys 分离，2026-10-22
    # 内网反馈连带修复）：任何校验失败 continue 的条目仍是变更范围，漏标扫描豁免它
    # ——否则"在变更记录中明确写了 ADD"的字段被误报"不在本次变更记录中"，误导处置
    # 方向（error 已准确报了该条目的问题，warn 不需要再错位复述）。
    batch_declared_adds = {e["key"] for e in batch
                           if e["page"] == "attr" and e["ctype"] == "ADD"
                           and e["column"] == WHOLE_ROW_MARK}
    # 本批次声明的类型修改字段集（modify 事实集——同声明/通过分离原则 + 漂移豁免）
    batch_declared_modifies = {e["key"] for e in batch
                               if e["page"] == "attr" and e["ctype"] == "MODIFY"
                               and (e["column"] or "").strip() == "目标字段类型"}

    for rn in renames:
        unsupported.append({"level": "attr", "change_type": "rename",
                            "name": f"{rn['old']}→{rn['new']}", "detail": rn,
                            "note": _existence_note(rn["old"], attr_target_cols,
                                                    facts["target_fields"])})

    add_fields: List[dict] = []
    add_keys: Dict[str, dict] = {}
    new_sources: List[dict] = []
    declared_source_aliases: set = set()
    modify_fields: List[dict] = []
    for e in batch:
        if e["page"] == "entity":
            if e["ctype"] == "ADD" and e["column"] == WHOLE_ROW_MARK:
                # 场景 A（第二刀）：新增来源表声明——校验实体级当前态有行，进 new_sources
                hit = next((r for r in entity_rows
                            if (r.get("source_alias") or "").strip().lower() == e["key"]
                            and (not e["group"]
                                 or not (r.get("scene_group") or "").strip()
                                 or (r.get("scene_group") or "").strip().lower() == e["group"])), None)
                if hit is None:
                    diags.append({"level": "error", "code": "add_source_row_missing",
                                  "message": f"变更记录序号 {e['seq']!r}：新增来源表 "
                                             f"{e['key']!r} 在实体级当前态找不到对应行"
                                             f"（key=分组|源表别名）"})
                    continue
                if hit.get("source_table", "") in facts["source_tables"]:
                    diags.append({"level": "warn", "code": "add_source_already_in_baseline",
                                  "message": f"变更记录序号 {e['seq']!r}：声明新增来源表 "
                                             f"{hit.get('source_table')!r} 已在 baseline "
                                             f"存量来源中（确认是否重复申报）"})
                new_sources.append({
                    "alias": hit.get("source_alias", ""),
                    "schema": hit.get("source_schema", ""),
                    "table": hit.get("source_table", ""),
                    "join_condition": hit.get("join_condition", ""),
                    "change_entry": {"seq": e["seq"], "before": e["before"], "after": e["after"]},
                })
                declared_source_aliases.add((hit.get("source_alias") or "").strip().lower())
                continue
            ctype = "add_source" if e["ctype"] == "ADD" else e["ctype"].lower()
            _ent_hit = e["key"] in {a.lower() for a in alias_index} \
                or e["key"] in {(r.get("scene_group") or "").strip().lower() for r in attr_rows}
            unsupported.append({"level": "entity", "change_type": ctype,
                                "name": e["key"] or "?", "detail": e,
                                "note": "" if _ent_hit else "｜key 不在实体级当前态（别名/分组未命中）"})
            continue
        # 属性级
        if e["ctype"] == "MODIFY" and (e["column"] or "").strip() == "目标字段类型":
            # 场景 B（第二刀）：目标字段类型修改——三方对账后进 modify_fields
            hits = _match_attr_rows(attr_rows, e)
            if not hits:
                diags.append({"level": "error", "code": "modify_field_row_missing",
                              "message": f"变更记录序号 {e['seq']!r}：修改字段 {e['key']!r} "
                                         f"在属性级当前态找不到对应行（key=分组|目标字段名）"})
                continue
            if e["key"] not in facts["target_fields"]:
                diags.append({"level": "error", "code": "modify_field_not_in_baseline",
                              "message": f"变更记录序号 {e['seq']!r}：{e['key']!r} 不在 baseline "
                                         f"存量字段中——新字段直接在 ADD 行写对类型，不需要 MODIFY"})
                continue
            if e["key"] in batch_declared_adds:
                diags.append({"level": "error", "code": "modify_add_conflict",
                              "message": f"变更记录序号 {e['seq']!r}：{e['key']!r} 同批次既 ADD 又 "
                                         f"MODIFY（新增字段直接写对类型，两者矛盾）"})
                continue
            row = hits[0]
            new_type = (row.get("target_type") or "").strip()
            old_type = facts.get("field_types", {}).get(e["key"], "")
            before, after = (e["before"] or "").strip(), (e["after"] or "").strip()
            if not new_type:
                diags.append({"level": "error", "code": "modify_target_type_empty",
                              "message": f"变更记录序号 {e['seq']!r}：{e['key']!r} 属性级当前态的"
                                         f"目标字段类型为空"})
                continue
            if before and old_type and not types_compatible(before, old_type):
                diags.append({"level": "error", "code": "modify_before_mismatch",
                              "message": f"变更记录序号 {e['seq']!r}：{e['key']!r} 变更前类型 "
                                         f"{before!r} 与 baseline 类型 {old_type!r} 不一致"
                                         f"（归一比较）——变更前应填基线当前类型"})
                continue
            if after and not types_compatible(after, new_type):
                diags.append({"level": "error", "code": "modify_after_mismatch",
                              "message": f"变更记录序号 {e['seq']!r}：{e['key']!r} 变更后类型 "
                                         f"{after!r} 与属性级当前态类型 {new_type!r} 不一致"
                                         f"（归一比较）——当前态应为变更后的终态"})
                continue
            modify_fields.append({
                "field": e["key"],
                "old_type": old_type or before,
                "new_type": new_type,
                "change_entry": {"seq": e["seq"], "before": before, "after": after},
            })
            continue
        if e["ctype"] != "ADD":
            unsupported.append({"level": "attr", "change_type": e["ctype"].lower(),
                                "name": e["key"] or "?", "detail": e,
                                "note": _existence_note(e["key"], attr_target_cols,
                                                        facts["target_fields"])})
            continue
        if e["column"] != WHOLE_ROW_MARK:
            # 列级 ADD（对已有字段加某列内容）≈ modify 性质——待扩展
            unsupported.append({"level": "attr", "change_type": "add_column",
                                "name": f"{e['key']}.{e['column']}", "detail": e,
                                "note": _existence_note(e["key"], attr_target_cols,
                                                        facts["target_fields"])})
            continue
        # 整行新增（资产字段）→ add_field 候选：详情从属性级当前态取
        hits = _match_attr_rows(attr_rows, e)
        if not hits:
            diags.append({"level": "error", "code": "add_field_row_missing",
                          "message": f"变更记录序号 {e['seq']!r}：新增字段 {e['key']!r} "
                                     f"在属性级当前态页签找不到对应行（key=分组|目标字段名）"})
            continue
        if len(hits) > 1:
            diags.append({"level": "warn", "code": "add_field_multi_source",
                          "message": f"新增字段 {e['key']!r} 属性级有多行（多源映射）——"
                                     f"取第一行为主条目，多源场景待扩展"})
        if e["key"] in facts["target_fields"]:
            diags.append({"level": "error", "code": "add_field_conflict",
                          "message": f"变更记录序号 {e['seq']!r}：{e['key']!r} 标本次新增"
                                     f"但 baseline 已存在（若为改口径/加源请改用 MODIFY）"})
            continue
        # 来源配对拆解（2026-10-22 单点=split_source_pairs：位置配对 a;b × x;emp /
        # 字段格自带限定符 a.x;b.emp）：取首个别名命中实体级的对配详情；全不命中 →
        # dangling（格式错已被 check_mapping_static 输入门拦——此处防御）
        from preprocess import split_source_pairs
        row = hits[0]
        pairs, _perr = split_source_pairs(row.get("source_alias") or "",
                                          row.get("source_column") or "")
        ent = hit_alias = hit_col = None
        for _a, _c in pairs:
            _ent = alias_index.get(_a)
            if _ent is not None:
                ent, hit_alias, hit_col = _ent, _a, _c
                break
        if ent is None:
            diags.append({"level": "error", "code": "source_alias_dangling",
                          "message": f"新增字段 {e['key']!r}：来源登记 "
                                     f"{row.get('source_alias', '')!r}×{row.get('source_column', '')!r} "
                                     f"配对后无别名命中实体级"})
            continue
        add_keys[e["key"]] = e
        add_fields.append({
            "field": e["key"],
            "cn": row.get("target_column_cn", ""),
            "type": row.get("target_type", ""), "scene_group": row.get("scene_group", ""),
            "change_entry": {"seq": e["seq"], "before": e["before"], "after": e["after"]},
            "source": {"schema": ent.get("source_schema", ""),
                       "table": ent.get("source_table", ""), "alias": hit_alias,
                       "field": hit_col or row.get("source_column", ""),
                       # mapping 声明源类型（precheck_opt 连库以库为准对账修正）
                       "source_type": row.get("source_type", ""),
                       "rule": row.get("mapping_rule", ""),
                       "expr": row.get("mapping_expression", ""),
                       "join_condition": ent.get("join_condition", "")},
            "new_source_table": ent.get("source_table", "") not in facts["source_tables"],
        })

    # 场景 A 联动校验（2026-10-22 第二刀）：新来源表的声明（实体级 ADD）与引用
    # （新字段来源）两向对齐——隐式引用放行+warn 提示补申报（台账完整），无用声明提示
    _referenced_new_aliases = {(f["source"]["alias"] or "").strip().lower()
                               for f in add_fields if f.get("new_source_table")}
    for al in sorted(_referenced_new_aliases - declared_source_aliases):
        diags.append({"level": "warn", "code": "new_source_undeclared",
                      "message": f"新字段的来源表别名 {al!r} 不在 baseline 且无实体级 ADD 声明"
                                 f"（隐式放行——建议在变更记录补实体级 ADD 行，台账完整）"})
    for al in sorted(declared_source_aliases - _referenced_new_aliases):
        diags.append({"level": "warn", "code": "new_source_unreferenced",
                      "message": f"声明的新来源表 {al!r} 无任何新增字段引用"
                                 f"（无用声明？确认本次是否真需要该表）"})

    # 漏标扫描：属性级当前态字段不在 baseline、且不在本批次声明/ADD/Rename 新名清单 → 漏标
    # （豁免 batch_declared_adds 声明集——校验失败的字段仍是变更范围，见头部注释）
    rename_new = {rn["new"] for rn in renames}
    for i, row in enumerate(attr_rows, start=2):
        tcol = row.get("target_column", "")
        if tcol and tcol not in facts["target_fields"] and tcol not in batch_declared_adds \
                and tcol not in rename_new:
            diags.append({"level": "warn", "code": "unmarked_new_field",
                          "message": f"属性级第{i}行：{tcol!r} 不在 baseline 存量且不在本次"
                                     f"变更记录中（历史漏入档 or 漏标）——请业务确认"})

    # 存量字段类型对账（同名异容，2026-10-21）：与漏标扫描（名字级）互补的内容级——
    # skip=本批新增/改名/**已申报 MODIFY** 字段（申报的类型变更是预期变更不是漂移，
    # 未申报的照报引导走正路）；旧调用方无 field_types → 空跳过
    diags.extend(field_type_drift(attr_rows, facts.get("field_types") or {},
                                  set(add_keys) | rename_new | batch_declared_modifies))

    # 资产定位一致性（F/I 镜像归一：mapping 目标表写 I 视图、baseline 记 F 表是常态）
    for t in sorted({r.get("target_table", "") for r in entity_rows if r.get("target_table")}):
        if norm_asset(t) != norm_asset(facts["target_short"]):
            diags.append({"level": "error", "code": "asset_table_mismatch",
                          "message": f"实体级目标表 {t!r} 与本次资产 {facts['target_short']!r} 不一致"
                                     f"（已按 I/F 镜像归一比较）"})

    # RS 对账（材料角色——口径提示不阻断）
    if rs_section:
        for f in add_fields:
            if f["field"] not in rs_section:
                diags.append({"level": "warn", "code": "rs_field_not_mentioned",
                              "message": f"新增字段 {f['field']!r} 未在 RS 正文提及——口径请人确认"})
    return add_fields, new_sources, modify_fields, unsupported, diags


# ---------------------------------------------------------------------------
# 5. 组装与 main
# ---------------------------------------------------------------------------

def build_change_request(facts: dict, version: str, add_fields: List[dict],
                         new_sources: List[dict], modify_fields: List[dict],
                         unsupported: List[dict], change_entries: List[dict],
                         renames: List[dict], rs_section: str, files: dict) -> dict:
    return {
        # change_type 兼容保留 "add_field"（fence/slice/gate 等消费方按段取所需；
        # 多类型场景下以 new_sources/modify_type_fields 段为准）
        "change_type": "add_field",
        "version": version,
        "asset": facts["asset"],
        "change_entries": change_entries,       # 本批次变更记录页签全量规范化行（含 before/after——闸口①'并排材料）
        "renames": renames,                     # 改名合成对（待扩展形态，闸口可见）
        "unsupported_changes": unsupported,     # 识别+归类但流程待扩展（modify/drop/rename/add_column…）
        "new_sources": new_sources,             # 新增来源表声明（2026-10-22 场景 A：实体级整行 ADD）
        "modify_type_fields": modify_fields,    # 目标字段类型修改（2026-10-22 场景 B：属性级 MODIFY·目标字段类型）
        "source_files": files,
        "fields": add_fields,
        "backfill": "pending",
        "rs_opt_section": rs_section,           # RS 口径材料（DQ/调度/回刷意向——RS 职责不变）
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="优化输入预处理 v3：变更记录页签格式（契约参数直传）")
    ap.add_argument("--mapping", required=True, help="全量 mapping xlsx 路径（调用方指定）")
    ap.add_argument("--rs", required=True, help="RS md 路径（口径材料：DQ/调度/回刷意向）")
    ap.add_argument("--ts-baseline", required=True, help="档案 ts（archive/ts.json，只读）")
    ap.add_argument("--opt-root", required=True,
                    help="ddlc_design_dev 目录——现场就绪（清场重建 build/ + cp archive→archive_tmp/）")
    ap.add_argument("--version", default="", help="覆盖版本号（默认 = 变更记录页签最新批次 YYYYMM）")
    args = ap.parse_args(argv)

    mapping_path, rs_path = Path(args.mapping), Path(args.rs)
    for p, label in ((mapping_path, "mapping"), (rs_path, "RS")):
        if not p.exists():
            print(f"OPT_PRECHECK_ERROR: {label} 文件不存在: {p}", file=sys.stderr)
            return 2

    # 版本锚定：mapping 变更记录页签（主源）；RS 3.3 变更记录表降为材料（取不到不阻断）
    try:
        entries = read_change_sheet(mapping_path)
        version = args.version or pick_batch_version(entries)
    except ValueError as e:
        print(f"OPT_PRECHECK_ERROR: {e}", file=sys.stderr)
        return 2
    batch = [e for e in entries if e["time"] == version]
    if not batch:
        print(f"OPT_PRECHECK_ERROR: 版本 {version} 在变更记录页签中无对应批次行"
              f"（可用 --version 重选：现有批次 {[sorted({e['time'] for e in entries})]}）",
              file=sys.stderr)
        return 2

    rs_text = rs_path.read_text(encoding="utf-8")
    rs_section = extract_version_section(rs_text, version)  # 口径段（v3 RS 无版本锚定段则空——材料角色）

    ts_baseline = json.loads(Path(args.ts_baseline).read_text(encoding="utf-8"))
    facts = baseline_facts(ts_baseline)
    try:
        mapping = parse_mapping_sheets(mapping_path)
    except ValueError as e:
        print(f"OPT_PRECHECK_ERROR: mapping 两页签解析失败——{e}", file=sys.stderr)
        return 2
    # 全量静态检查（shared 单点，2026-10-22 接入）：与主链路 precheck 同一实现同一
    # 阻断语义（error 照拦 exit 2）——opt 相对主链路的合法差异只在连库检查范围
    # （precheck_opt 只检新增子集），静态检查零重定义。
    static_diags = [{"level": d["level"], "code": "mapping_static", "message": d["message"]}
                    for d in check_mapping_static(mapping["attr"], mapping["entity"])]
    renames, rest = synth_renames(batch)
    add_fields, new_sources, modify_fields, unsupported, diags = extract_and_check(
        rest, renames, mapping, facts, version, rs_section)
    diags = static_diags + diags

    errors = [d for d in diags if d["level"] == "error"]
    warns = [d for d in diags if d["level"] == "warn"]
    for d in diags:
        print(f"[{d['level'].upper()}][{d['code']}] {d['message']}", file=sys.stderr)
    for u in unsupported:
        print(f"[INFO] 识别到 {u['change_type']} 变更（{u['level']} {u['name']}）"
              f"——本刀流程未支持，待扩展{u.get('note', '')}", file=sys.stderr)

    # 现场就绪（目录模型 2026-09-07 终态，脚本做确定性动作）：
    #   build/ = 增量现场（清场重建只留最新——上次的过程产物/交付物残留不混入本次）
    #   archive_tmp/ = 临时档案（档案副本起步——优化过程维护进度态全量，最终整体替换上位）
    ddlc = Path(args.opt_root)
    build = ddlc / "build"
    arc_tmp = ddlc / "archive_tmp"
    import shutil
    shutil.rmtree(build, ignore_errors=True)
    shutil.rmtree(arc_tmp, ignore_errors=True)
    out = build / "_internal"
    out.mkdir(parents=True, exist_ok=True)
    for sub in ("etl", "ddl", "export"):
        (build / sub).mkdir(exist_ok=True)
    (out / "diagnose").mkdir(exist_ok=True)
    shutil.copytree(ddlc / "archive", arc_tmp)
    print(f"build: {build}（增量现场，清场重建）")
    print(f"archive_tmp: {arc_tmp}（临时档案=档案副本起步）")

    if errors:
        print(f"OPT_PRECHECK_BLOCKED：{len(errors)} 项阻断，{len(warns)} 项 warn。", file=sys.stderr)
        return 2
    # baseline_view 补产（designer 契约：三段式入口 ①档案②收档 无 json 契约——从 ts 渲染
    # 简化版；③json 入料的完整版已存在则保留）
    view_path = out / "baseline_view.md"
    if not view_path.exists():
        view_path.write_text(render_baseline_view_from_ts(ts_baseline), encoding="utf-8")
        print(f"baseline_view: {view_path}（档案 ts 简化版）")
    cr = build_change_request(facts, version, add_fields, new_sources, modify_fields,
                              unsupported, batch, renames, rs_section,
                              {"mapping": str(mapping_path), "rs": str(rs_path),
                               "ts_baseline": str(args.ts_baseline)})
    (out / "change_request.json").write_text(
        json.dumps(cr, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"change_request: {out / 'change_request.json'}")
    print(f"version: {version}, add_fields: {len(add_fields)}, new_sources: {len(new_sources)}, "
          f"modify_type: {len(modify_fields)}, unsupported: {len(unsupported)}, warns: {len(warns)}")
    return 1 if warns else 0


if __name__ == "__main__":
    sys.exit(main())
