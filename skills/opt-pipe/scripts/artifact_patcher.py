"""artifact_patcher —— 制品 patch 引擎（docs/specs/opt/07：编辑原语 × 变更声明，严格 patch）。

交付副本模式：读原始制品目录（--source=目录唯一形态，一般 {arc}/export/）→ 产出
**更新后的完整文件副本**进 patched/ + patch 说明。不就地改原件、不碰仓（推生产
不自主）。存量声明漂移不碰（严格 patch）。

--source 目录形态（2026-11-04 实报 #8 收敛唯一形态）：扫目录内 xlsx 逐个尝试，
含 RULE/TargetFields sheet 的即术加制品包（patch 之），lts/dq 等非术加 excel 跳过
披露；一个都 patch 不了=fail loud。yml 代码仓通道已退役（v2 档 provenance 只携
execution_tasks/lts/dq excel——一波换彻底不留双通道）。

定位一律稳定标识（rule_code / 目标字段名），不做行号假设；未知列/未知 sheet 不动。
"""
import argparse
import json
import shutil
import sys
from copy import copy
from pathlib import Path

# shared 公共库自洽引用：相对路径推算 design-dev-shared（skill 脚本标准 bootstrap）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "design-dev-shared" / "scripts"))
from typing import Dict, List, Optional, Tuple

from run_ut import read_select
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

# 术加 xlsx 约定列名（与 analyzer/assemble_export 同源的平台约定）
RULE_SHEET_CANDIDATES = ("RULE", "Rule", "rule")
TF_SHEET_CANDIDATES = ("TargetFields", "target_fields", "targetfields")
COL_RULE_CODE = "规则编码"
# xlsx 的 SQL 列头是「(生成的）查询语句1..N」（全角右括号+数字后缀）——按正则定位（见 patch_xlsx 内注释）

TF_COLS = {"规则编码": "rule_code", "目标字段名称": "target_field", "来源字段名称": "source_field",
           "加密方式": "encryption", "别名": "alias", "字段类型": "field_type", "备注": "remark"}


def _change_index(ts_v2: dict) -> List[Tuple[str, str, dict]]:
    """[(rule_code, field, 该规则下该字段的定义)] —— TargetFields 行的展开源。"""
    out = []
    for f in (ts_v2.get("change") or {}).get("fields", []):
        for r in f.get("placed_rules", []):
            t = f.get("target_table", "")
            fd = next((x for x in ts_v2.get("tables", {}).get(t, {}).get("fields", [])
                       if x.get("target_field") == f["field"]), {})
            src = f.get("source") or {}
            out.append((r, f["field"], {
                "target_field": f["field"],
                "source_field": f"{src.get('alias', '')}.{src.get('field', f['field'])}".lstrip("."),
                "encryption": "0", "alias": "",
                "field_type": fd.get("field_type", ""),
                "remark": fd.get("field_comment", ""),
            }))
    return out


def _sql_rules(ts_v2: dict) -> List[str]:
    """SQL 单元格需要替换的规则（= 有声明落位的规则 ∪ 口径修改字段的落位规则——
    口径修改：口径变了 SQL 必然变）。"""
    _mod_rules = {rc for m in ((ts_v2.get("change") or {}).get("modify_logics") or [])
                  for rc in (m.get("rules") or [])}
    return sorted({r for r, _, _ in _change_index(ts_v2)} | _mod_rules)


# ---------------------------------------------------------------------------
# xlsx patch
# ---------------------------------------------------------------------------

def patch_xlsx(src: Path, dst: Path, ts_v2: dict, etl_dir: Path, notes: List[str]) -> None:
    wb = load_workbook(src)
    rule_ws = next((wb[s] for s in wb.sheetnames if s in RULE_SHEET_CANDIDATES), None)
    tf_ws = next((wb[s] for s in wb.sheetnames if s in TF_SHEET_CANDIDATES), None)
    if rule_ws is None or tf_ws is None:
        raise ValueError(f"xlsx 缺 RULE/TargetFields sheet（现有: {wb.sheetnames}）——"
                         f"provenance 指到的可能不是术加制品包")

    def header_map(ws) -> Dict[str, int]:
        return {str(c.value).strip(): c.column for c in ws[1] if c.value is not None}

    # --- RULE 表：SQL 单元格替换（按 rule_code 定位行） ---
    # 真实导出列头是「(生成的）查询语句1..N」（全角右括号+数字后缀，超长 SQL 按列切块存储），
    # 与 analyzer 读取规则（按 N 序拼接非空列）镜像：写回 = 清空全部查询语句N、新 SQL 整体
    # 写列 1 —— 拼接语义恒等（读取时 1..N 非空拼接 = 只有列 1 非空 = 新 SQL）。
    import re as _re
    rh = header_map(rule_ws)
    sql_cols = sorted((int(m.group(1)), col) for name, col in rh.items()
                      for m in [_re.match(r".*查询语句\s*(\d+)", name)] if m)
    if not sql_cols:
        raise ValueError(f"RULE 表无「查询语句N」列（现有列头样例: {list(rh)[:8]}）——"
                         f"provenance 指到的可能不是术加制品包")
    col1 = sql_cols[0][1]
    for rc in _sql_rules(ts_v2):
        sql_text = read_select(etl_dir, rc)   # {code}.sql 或 {code}_描述_模式.sql
        if not sql_text:
            notes.append(f"[跳过] {rc} 无新 SQL 文件，RULE 表未替换")
            continue
        hit = False
        for row in rule_ws.iter_rows(min_row=2):
            if str(row[rh[COL_RULE_CODE] - 1].value).strip().lower() == rc.lower():
                for _, c in sql_cols:
                    row[c - 1].value = None
                row[col1 - 1].value = sql_text
                hit = True
                notes.append(f"[替换单元格] RULE.查询语句1..{sql_cols[-1][0]} → 列1 @ rule={rc}")
                break
        if not hit:
            notes.append(f"[缺失] RULE 表找不到 rule_code={rc}——定位失败，人工核查")

    # --- TargetFields：行追加（样式从末行复制） ---
    th = header_map(tf_ws)
    for rc, field, vals in _change_index(ts_v2):
        # 已存在（声明漂移/重复执行）→ 不动不覆盖（严格 patch：只落变更清单，不修存量）
        dup = any(str(r[th[COL_RULE_CODE] - 1].value).strip().lower() == rc.lower() and
                  str(r[th["目标字段名称"] - 1].value).strip().lower() == str(field).lower()
                  for r in tf_ws.iter_rows(min_row=2) if r[th[COL_RULE_CODE] - 1].value)
        if dup:
            notes.append(f"[跳过] TargetFields 已有 ({rc}, {field})——不覆盖（严格 patch）")
            continue
        new_row = tf_ws.max_row + 1
        src_row = tf_ws.max_row
        for cn, val in ((COL_RULE_CODE, rc), ("目标字段名称", vals["target_field"]),
                        ("来源字段名称", vals["source_field"]), ("加密方式", vals["encryption"]),
                        ("别名", vals["alias"]), ("字段类型", vals["field_type"]),
                        ("备注", vals["remark"])):
            cell = tf_ws.cell(row=new_row, column=th[cn])
            cell.value = val
            src_cell = tf_ws.cell(row=src_row, column=th[cn])
            cell.font = copy(src_cell.font)
            cell.border = copy(src_cell.border)
            cell.alignment = copy(src_cell.alignment)
        notes.append(f"[追加行] TargetFields ({rc}, {field})")

    # --- TargetFields：类型修改列的「字段类型」单元格更新（场景 B·2026-10-22——
    #     modify 字段已有行，只更新类型单元格；存量其他列不动） ---
    for m in (ts_v2.get("change") or {}).get("modify_types", []):
        field, new_type = m.get("field", ""), m.get("new_type", "")
        hit = 0
        for r in tf_ws.iter_rows(min_row=2):
            if r[th["目标字段名称"] - 1].value is None:
                continue
            if str(r[th["目标字段名称"] - 1].value).strip().lower() == field.lower():
                tf_ws.cell(row=r[0].row, column=th["字段类型"]).value = new_type
                hit += 1
        if hit:
            notes.append(f"[类型更新] TargetFields.字段类型 {field} → {new_type}（{hit} 行）")
        else:
            notes.append(f"[缺失] TargetFields 找不到类型修改字段 {field}——定位失败，人工核查")
    dst.parent.mkdir(parents=True, exist_ok=True)
    wb.save(dst)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="制品 patch：交付副本 + patch 说明（严格 patch）")
    ap.add_argument("--ts-v2", required=True)
    ap.add_argument("--etl-dir", required=True, help="新 SELECT 目录")
    ap.add_argument("--source", required=True,
                    help="原始制品目录（一般 {arc}/export/——目录唯一形态：扫内 xlsx，"
                         "术加包 patch、非术加跳过披露）")
    ap.add_argument("--outdir", required=True, help="patched/ 输出目录")
    args = ap.parse_args(argv)

    ts_v2 = json.loads(Path(args.ts_v2).read_text(encoding="utf-8"))
    if not (ts_v2.get("change") or {}).get("fields"):
        print("PATCH_ERROR: ts 无 change 段", file=sys.stderr)
        return 2
    src = Path(args.source)
    etl_dir = Path(args.etl_dir)
    out = Path(args.outdir)
    if not src.is_dir():
        print(f"PATCH_ERROR: --source 应为制品目录（一般 {{arc}}/export/），收到: {src}",
              file=sys.stderr)
        return 2
    notes: List[str] = []
    patched = 0
    # 目录唯一形态（2026-11-04）：扫 xlsx 逐个尝试——含 RULE/TargetFields sheet 即术加
    # 制品包；lts/dq 等非术加 excel 跳过披露（不误伤不漏patch）
    for f in sorted(list(src.glob("*.xlsx")) + list(src.glob("*.xls"))):
        try:
            patch_xlsx(f, out / "patched" / f.name, ts_v2, etl_dir, notes)
            patched += 1
        except Exception as e:   # 非术加（缺 sheet）/打不开——跳过披露不炸整轮
            notes.append(f"[跳过] {f.name}：{str(e)[:120]}")
    if not patched:
        print(f"PATCH_ERROR: {src} 内无术加制品包（含 RULE/TargetFields sheet 的 xlsx）——"
              f"确认 --source 指向 export/ 目录且制品已随档", file=sys.stderr)
        return 2
    (out / "patch_notes.md").write_text(
        "# patch 说明（严格 patch：只落变更清单）\n\n" + "\n".join(f"- {n}" for n in notes)
        + "\n", encoding="utf-8")
    print(f"patched: {out / 'patched'}")
    print(f"patch_notes: {out / 'patch_notes.md'}（{len(notes)} 条）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
