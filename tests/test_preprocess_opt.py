"""preprocess_opt v3 测试：变更记录页签格式（2026-10-14 与业务侧确认）。

场景构造对齐 mapping-format.md「变更记录页签」规范：三页签 mapping（实体级/属性级/
变更记录）+ RS（口径材料）。批次过滤/改名合成/类型归类/conflict/dangling/漏标/e2e。
不连库。
"""
import json
from pathlib import Path

from openpyxl import Workbook

import pytest

from assemble_ts_baseline import build_ts_baseline
from preprocess_opt import (
    read_change_sheet, pick_batch_version, synth_renames, extract_and_check,
    extract_version_section, parse_change_log, norm_asset, main,
)

PKG_XLSX = "dwb_trade_order_d_全量mapping.xlsx"
PKG_RS = "RS_需求文档.md"

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "opt"

ENTITY_COLS = ["源表schema", "源表物理表名", "源表别名", "目标表逻辑schema",
               "目标表物理名称", "关联&限定条件", "备注"]
ATTR_COLS = ["分组", "源表别名", "源表物理表名", "源表字段名", "映射规则", "映射表达式",
             "目标字段名", "目标字段中文名", "目标字段类型", "备注"]
CHANGE_COLS = ["变更序号", "变更时间", "变更页签", "变更KEY", "变更列", "变更类型", "变更前", "变更后"]  # 真实模板形态（KEY 大写）

RS_MD = """# 某资产需求规格

## 4. 字段需求

202610版本新增需求：新增 channel_name（渠道名称），来源渠道维表，按订单关联取渠道名称。
"""


def ent(table="ods_trade_order_di", alias="a", target="dwb_trade_order_d"):
    return {"源表schema": "ods", "源表物理表名": table, "源表别名": alias,
            "目标表逻辑schema": "dws", "目标表物理名称": target,
            "关联&限定条件": "", "备注": ""}


def attr(tcol="channel_name", tcol_cn="渠道名称", ttype="VARCHAR(64)",
         alias="c", stable="dim_channel", scol="channel_name", group="default"):
    return {"分组": group, "源表别名": alias, "源表物理表名": stable, "源表字段名": scol,
            "映射规则": "直取", "映射表达式": "-", "目标字段名": tcol,
            "目标字段中文名": tcol_cn, "目标字段类型": ttype, "备注": ""}


def chg(seq, time_, page, key, column, ctype, before="", after=""):
    """变更记录行：page='entity'|'attr'；key='分组|名'；column='资产字段' 表示整行新增。"""
    page_cn = "实体级" if page == "entity" else "属性级"
    return {"变更序号": seq, "变更时间": time_, "变更页签": page_cn,
            "变更KEY": key, "变更列": column, "变更类型": ctype,
            "变更前": before, "变更后": after}


@pytest.fixture(scope="module")
def facts():
    demo = json.loads((FIXTURES / "baseline_v1_demo_full.json").read_text(encoding="utf-8"))
    ts, _ = build_ts_baseline(demo)
    from preprocess_opt import baseline_facts
    return baseline_facts(ts)


def make_pkg(pkg_dir: Path, entity_rows, attr_rows, change_rows, rs_md=RS_MD,
             mapping_name=PKG_XLSX, with_change_sheet=True):
    pkg_dir.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws1 = wb.active; ws1.title = "实体级mapping"; ws1.append(ENTITY_COLS)
    for r in entity_rows:
        ws1.append([r.get(c, "") for c in ENTITY_COLS])
    ws2 = wb.create_sheet("属性级mapping"); ws2.append(ATTR_COLS)
    for r in attr_rows:
        ws2.append([r.get(c, "") for c in ATTR_COLS])
    if with_change_sheet:
        ws3 = wb.create_sheet("变更记录"); ws3.append(CHANGE_COLS)
        for r in change_rows:
            ws3.append([r.get(c, "") for c in CHANGE_COLS])
    wb.save(pkg_dir / mapping_name)
    (pkg_dir / PKG_RS).write_text(rs_md, encoding="utf-8")
    return pkg_dir


ATTR_EN = {"分组": "scene_group", "源表别名": "source_alias", "源表物理表名": "source_table",
           "源表字段名": "source_column", "映射规则": "mapping_rule", "映射表达式": "mapping_expression",
           "目标字段名": "target_column", "目标字段中文名": "target_column_cn",
           "目标字段类型": "target_type", "备注": "remark"}
ENT_EN = {"源表schema": "source_schema", "源表物理表名": "source_table", "源表别名": "source_alias",
          "目标表逻辑schema": "target_schema", "目标表物理名称": "target_table",
          "关联&限定条件": "join_condition", "备注": "remark"}


def mapping_of(entity_rows, attr_rows):
    """中文列名行 → extract_and_check 消费的英文键行（与 read_full_mapping 归一后同构）。"""
    to_en = lambda rows, m: [{m.get(k, k): v for k, v in r.items()} for r in rows]
    return {"entity": to_en(entity_rows, ENT_EN), "attr": to_en(attr_rows, ATTR_EN)}


STD_CHANGES = [
    chg(1, "2026-03-10", "attr", "default|pay_type", "资产字段", "ADD"),          # 历史批次（不进本次）
    chg(2, "2026-10-14", "attr", "default|channel_name", "资产字段", "ADD"),      # 本次新增字段
]


def _to_entry(c: dict) -> dict:
    """chg 中文行 → read_change_sheet 归一后的 entry 同构形态（extract 单测直喂）——
    含标识符小写归一（与生产 read_change_sheet 同口径）。"""
    from preprocess_opt import normalize_yyyymm
    group, _, key_name = c["变更KEY"].partition("|")
    return {"seq": c["变更序号"], "time": normalize_yyyymm(c["变更时间"]),
            "page": "entity" if "实体" in c["变更页签"] else "attr",
            "group": group.strip().lower(), "key": key_name.strip().lower(),
            "column": c["变更列"],
            "ctype": c["变更类型"], "before": c["变更前"], "after": c["变更后"]}


class TestNormAsset:
    """资产名 I/F 镜像归一：资产铆定 I，mapping 写 I 视图、baseline 记 F 表是同一资产。"""

    def test_if_mirror_equal(self):
        assert norm_asset("dwb_trade_order_i") == norm_asset("dwb_trade_order_f")

    def test_schema_prefix_and_case(self):
        assert norm_asset("DWS.DWB_TRADE_ORDER_I") == norm_asset("dwb_trade_order")

    def test_bare_name(self):
        assert norm_asset("dwb_trade_order") == norm_asset("dwb_trade_order_i")

    def test_real_mismatch(self):
        assert norm_asset("dwb_cust_asset_i") != norm_asset("dwb_trade_order_f")


class TestChangeSheetParsing:
    """变更记录页签读取：八列规格/枚举校验/批次锚定/历史批次过滤。"""

    def test_read_and_batch(self, tmp_path):
        make_pkg(tmp_path, [ent(), ent(table="dim_channel", alias="c")],
                 [attr(tcol="order_id", alias="a", stable="ods_trade_order_di", scol="order_id"), attr()],
                 STD_CHANGES)
        entries = read_change_sheet(tmp_path / PKG_XLSX)
        assert len(entries) == 2
        assert pick_batch_version(entries) == "202610"
        batch = [e for e in entries if e["time"] == "202610"]
        assert [e["key"] for e in batch] == ["channel_name"]
        assert batch[0]["column"] == "资产字段" and batch[0]["ctype"] == "ADD"
        assert batch[0]["group"] == "default"

    def test_missing_sheet_rejected(self, tmp_path):
        make_pkg(tmp_path, [ent()], [attr()], STD_CHANGES, with_change_sheet=False)
        with pytest.raises(ValueError, match="变更记录"):
            read_change_sheet(tmp_path / PKG_XLSX)

    def test_bad_ctype_rejected(self, tmp_path):
        make_pkg(tmp_path, [ent()], [attr()],
                 [chg(1, "2026-10-14", "attr", "default|x", "资产字段", "新增")])
        with pytest.raises(ValueError, match="非法"):
            read_change_sheet(tmp_path / PKG_XLSX)

    def test_bad_time_rejected(self, tmp_path):
        make_pkg(tmp_path, [ent()], [attr()],
                 [chg(1, "不知道", "attr", "default|x", "资产字段", "ADD")])
        with pytest.raises(ValueError, match="归一失败"):
            read_change_sheet(tmp_path / PKG_XLSX)

    def test_column_name_case_insensitive(self, tmp_path):
        """列名大小写混合形态（变更Key）也能命中标准列（真实模板为「变更KEY」大写）。"""
        pkg = make_pkg(tmp_path, [ent(), ent(table="dim_channel", alias="c")], [attr()],
                       [chg(2, "2026-10-14", "attr", "default|channel_name", "资产字段", "ADD")])
        from openpyxl import load_workbook
        wb = load_workbook(pkg / PKG_XLSX)
        ws = wb["变更记录"]
        ws.cell(row=1, column=4).value = "变更Key"      # 标准名外的混合大小写
        wb.save(pkg / PKG_XLSX)
        entries = read_change_sheet(pkg / PKG_XLSX)
        assert entries[0]["key"] == "channel_name"

    def test_uppercase_key_normalized(self, tmp_path):
        """真实填写形态：变更 key 全大写 → read_change_sheet 归一为小写（标识符 foldcase）。"""
        make_pkg(tmp_path, [ent(), ent(table="dim_channel", alias="c")], [attr()],
                 [chg(2, "2026-10-14", "attr", "DEFAULT|CHANNEL_NAME", "资产字段", "ADD")])
        entries = read_change_sheet(tmp_path / PKG_XLSX)
        assert entries[0]["key"] == "channel_name" and entries[0]["group"] == "default"


class TestRenameSynth:
    """改名合成：严格证据链（DELETE.变更后 == ADD.key）才合成，独立行不误合。"""

    def test_paired_delete_add_synthesizes(self):
        batch = [_to_entry(chg(3, "2026-10-14", "attr", "default|order_amt", "目标字段名", "DELETE",
                               "order_amt", "order_amount")),
                 _to_entry(chg(4, "2026-10-14", "attr", "default|order_amount", "资产字段", "ADD"))]
        renames, rest = synth_renames(batch)
        assert renames == [{"kind": "rename", "group": "default",
                            "old": "order_amt", "new": "order_amount", "seq": "3+4",
                            "after_raw": "order_amount"}]
        assert rest == []

    def test_rename_with_uppercase_key_and_after(self):
        """真实填写形态：变更 key 大写、变更后人填值大写——标识符 foldcase 归一后仍配对。"""
        batch = [_to_entry(chg(3, "2026-10-14", "attr", "DEFAULT|ORDER_AMT", "目标字段名", "DELETE",
                               "ORDER_AMT", "ORDER_AMOUNT")),
                 _to_entry(chg(4, "2026-10-14", "attr", "DEFAULT|ORDER_AMOUNT", "资产字段", "ADD"))]
        renames, rest = synth_renames(batch)
        assert renames and renames[0]["old"] == "order_amt" and renames[0]["new"] == "order_amount"
        assert renames[0]["after_raw"] == "ORDER_AMOUNT"
        assert rest == []

    def test_unpaired_stays_independent(self):
        batch = [_to_entry(chg(1, "2026-10-14", "attr", "default|old_f", "目标字段名", "DELETE",
                               "old_f", "")),               # 变更后为空——无配对证据
                 _to_entry(chg(2, "2026-10-14", "attr", "default|new_f", "资产字段", "ADD"))]
        renames, rest = synth_renames(batch)
        assert renames == [] and len(rest) == 2

    def test_delete_after_points_elsewhere_no_synth(self):
        batch = [_to_entry(chg(1, "2026-10-14", "attr", "default|a", "目标字段名", "DELETE", "a", "zzz")),
                 _to_entry(chg(2, "2026-10-14", "attr", "default|b", "资产字段", "ADD"))]
        assert synth_renames(batch)[0] == []


class TestExtract:
    """提取与校验：add_field 候选/类型归类待扩展/conflict/dangling/漏标。"""

    def _std(self, extra_changes=(), extra_entity=(), extra_attr=()):
        entity = [ent(), ent(table="dim_channel", alias="c")] + list(extra_entity)
        attrs = [attr(tcol="order_id", alias="a", stable="ods_trade_order_di", scol="order_id"),
                 attr()] + list(extra_attr)
        mapping = mapping_of(entity, attrs)
        all_changes = STD_CHANGES + list(extra_changes)
        batch = [_to_entry(e) for e in all_changes if "10-14" in e["变更时间"]]
        return mapping, batch

    def test_extract_add_field(self, facts):
        mapping, batch = self._std()
        renames, rest = synth_renames(batch)
        add_fields, unsupported, diags = extract_and_check(rest, renames, mapping, facts, "202610", "")
        assert [f["field"] for f in add_fields] == ["channel_name"]
        f = add_fields[0]
        assert f["source"]["table"] == "dim_channel" and f["cn"] == "渠道名称"
        assert f["new_source_table"] is True
        assert not [d for d in diags if d["level"] == "error"]

    def test_extract_add_field_uppercase_key(self, facts):
        """真实填写形态：变更 key 全大写（DEFAULT|CHANNEL_NAME）也能命中属性级小写行。"""
        entity = [ent(), ent(table="dim_channel", alias="c")]
        attrs = [attr(tcol="order_id", alias="a", stable="ods_trade_order_di", scol="order_id"), attr()]
        mapping = mapping_of(entity, attrs)
        batch = [_to_entry(chg(2, "2026-10-14", "attr", "DEFAULT|CHANNEL_NAME", "资产字段", "ADD"))]
        renames, rest = synth_renames(batch)
        add_fields, unsupported, diags = extract_and_check(rest, renames, mapping, facts, "202610", "")
        assert [f["field"] for f in add_fields] == ["channel_name"], \
            "大写 key 归一后应命中属性级小写行"
        assert not [d for d in diags if d["level"] == "error"]

    def test_modify_delete_entity_add_classified_unsupported(self, facts):
        extra = [chg(3, "2026-10-14", "attr", "default|order_id", "映射表达式", "MODIFY"),
                 chg(4, "2026-10-14", "attr", "default|gone_f", "资产字段", "DELETE"),
                 chg(5, "2026-10-14", "entity", "default|dim_shop", "资产字段", "ADD"),
                 chg(6, "2026-10-14", "attr", "default|order_id", "备注", "ADD")]
        mapping, batch = self._std(extra)
        renames, rest = synth_renames(batch)
        _, unsupported, _ = extract_and_check(rest, renames, mapping, facts, "202610", "")
        kinds = {(u["change_type"], u["name"]) for u in unsupported}
        assert ("modify", "order_id") in kinds
        assert ("delete", "gone_f") in kinds
        assert ("add_source", "dim_shop") in kinds
        assert ("add_column", "order_id.备注") in kinds

    def test_rename_reported_unsupported(self, facts):
        extra = [chg(3, "2026-10-14", "attr", "default|order_amt", "目标字段名", "DELETE",
                     "order_amt", "order_amount"),
                 chg(4, "2026-10-14", "attr", "default|order_amount", "资产字段", "ADD")]
        mapping, batch = self._std(extra)
        renames, rest = synth_renames(batch)
        assert renames, "先删后加对应合成 rename"
        _, unsupported, _ = extract_and_check(rest, renames, mapping, facts, "202610", "")
        assert any(u["change_type"] == "rename" and "order_amt→order_amount" in u["name"]
                   for u in unsupported)

    def test_conflict_and_dangling_and_row_missing(self, facts):
        mapping, batch = self._std(extra_changes=[
            chg(7, "2026-10-14", "attr", "default|order_id", "资产字段", "ADD"),   # baseline 已有
            chg(8, "2026-10-14", "attr", "default|ghost_f", "资产字段", "ADD"),    # 当前态无行
        ])
        renames, rest = synth_renames(batch)
        add_fields, unsupported, diags = extract_and_check(rest, renames, mapping, facts, "202610", "")
        codes = {d["code"] for d in diags if d["level"] == "error"}
        assert "add_field_conflict" in codes
        assert "add_field_row_missing" in codes
        assert [f["field"] for f in add_fields] == ["channel_name"]

    def test_alias_dangling(self, facts):
        mapping, batch = self._std(extra_changes=[
            chg(9, "2026-10-14", "attr", "default|dangle_f", "资产字段", "ADD"),
        ], extra_attr=[attr(tcol="dangle_f", alias="nope", stable="dim_x", scol="x")])
        renames, rest = synth_renames(batch)
        _, _, diags = extract_and_check(rest, renames, mapping, facts, "202610", "")
        assert any(d["code"] == "source_alias_dangling" for d in diags if d["level"] == "error")

    def test_unmarked_new_field_warns(self, facts):
        # 属性级当前态有 extra_f 不在 baseline 且不在变更记录 → 漏标 warn（台账漂移防线）
        mapping, batch = self._std(extra_attr=[
            attr(tcol="extra_f", alias="a", stable="ods_trade_order_di", scol="extra_f")])
        renames, rest = synth_renames(batch)
        _, _, diags = extract_and_check(rest, renames, mapping, facts, "202610", "")
        assert any(d["code"] == "unmarked_new_field" and "extra_f" in d["message"]
                   for d in diags if d["level"] == "warn")

    def test_rs_material_reconciliation(self, facts):
        mapping, batch = self._std()
        renames, rest = synth_renames(batch)
        _, _, diags = extract_and_check(rest, renames, mapping, facts, "202610",
                                        "新增 other_f 字段")   # RS 段没提 channel_name
        assert any(d["code"] == "rs_field_not_mentioned" for d in diags if d["level"] == "warn")


class TestRsParsing:
    """RS 材料角色（v3：版本锚定主源已移至 mapping 变更记录页签）。"""

    def test_version_section_anchor(self):
        rs = "前文\n202610版本 需求正文A\n202603版本 需求正文B\n"
        assert "需求正文A" in extract_version_section(rs, "202610")
        assert "202603版本" not in extract_version_section(rs, "202610")

    def test_parse_change_log_material(self):
        rs = "## 3.3 变更记录\n\n| 日期 | 版本 | 修改人 | 修改内容 |\n|---|---|---|---|\n| 2026-10-14 | v3 | x | 优化 |\n"
        assert parse_change_log(rs)[0]["date"] == "2026-10-14"


def _opt_ready(root, baseline_ts):
    arc = root / "archive"
    arc.mkdir(parents=True, exist_ok=True)
    (arc / "ts.json").write_text(json.dumps(baseline_ts, ensure_ascii=False), encoding="utf-8")
    return arc


@pytest.fixture()
def demo_baseline():
    demo = json.loads((FIXTURES / "baseline_v1_demo_full.json").read_text(encoding="utf-8"))
    ts, _ = build_ts_baseline(demo)
    return ts


class TestMainEndToEnd:
    def test_direct_paths_flow(self, tmp_path, demo_baseline):
        arc = _opt_ready(tmp_path, demo_baseline)
        pkg = make_pkg(tmp_path / "pkg",
                       [ent(), ent(table="dim_channel", alias="c")],
                       [attr(tcol="order_id", alias="a", stable="ods_trade_order_di", scol="order_id"),
                        attr()],
                       STD_CHANGES)
        rc = main(["--mapping", str(pkg / PKG_XLSX), "--rs", str(pkg / PKG_RS),
                   "--ts-baseline", str(arc / "ts.json"), "--opt-root", str(tmp_path)])
        assert rc == 0
        cr = json.loads((tmp_path / "build" / "_internal" / "change_request.json").read_text())
        assert cr["version"] == "202610"
        assert [f["field"] for f in cr["fields"]] == ["channel_name"]
        assert len(cr["change_entries"]) == 1          # 本批次（历史 202603 批次行不混入）
        assert "mapping" in cr["source_files"]

    def test_explicit_version_override_picks_history_batch(self, tmp_path, demo_baseline):
        arc = _opt_ready(tmp_path, demo_baseline)
        pkg = make_pkg(tmp_path / "pkg", [ent()],
                       [attr(tcol="pay_type", alias="a", stable="ods_trade_order_di", scol="pay_type"),
                        attr(tcol="order_id", alias="a", stable="ods_trade_order_di", scol="order_id")],
                       STD_CHANGES)
        rc = main(["--mapping", str(pkg / PKG_XLSX), "--rs", str(pkg / PKG_RS),
                   "--ts-baseline", str(arc / "ts.json"), "--opt-root", str(tmp_path),
                   "--version", "202603"])
        assert rc in (0, 1)
        cr = json.loads((tmp_path / "build" / "_internal" / "change_request.json").read_text())
        assert cr["version"] == "202603"
        assert [f["field"] for f in cr["fields"]] == ["pay_type"]

    def test_blocked_exit_2(self, tmp_path, demo_baseline):
        arc = _opt_ready(tmp_path, demo_baseline)
        pkg = make_pkg(tmp_path / "pkg",
                       [ent(target="dwb_other_asset_d")],     # 资产不一致 → 阻断
                       [attr()], STD_CHANGES)
        rc = main(["--mapping", str(pkg / PKG_XLSX), "--rs", str(pkg / PKG_RS),
                   "--ts-baseline", str(arc / "ts.json"), "--opt-root", str(tmp_path)])
        assert rc == 2

    def test_missing_input_file_exit_2(self, tmp_path, demo_baseline):
        arc = _opt_ready(tmp_path, demo_baseline)
        rc = main(["--mapping", str(tmp_path / "nope.xlsx"), "--rs", str(tmp_path / "nope.md"),
                   "--ts-baseline", str(arc / "ts.json"), "--opt-root", str(tmp_path)])
        assert rc == 2


class TestBaselineViewBackfill:
    def test_view_rendered_when_missing(self):
        from preprocess_opt import render_baseline_view_from_ts
        ts = {"meta": {"target": {"f_table": {"schema": "dws", "table": "t_f"}}},
              "rules": {"R0001": {"exec_sequence": 1, "load_mode": "no_delete",
                                  "target_table": "dws.t_f",
                                  "source_tables": [{"schema": "ods", "table": "s"}]}},
              "tables": {"t_f": {"fields": [{"name": "a"}, {"name": "b"}]}}}
        view = render_baseline_view_from_ts(ts)
        assert "R0001" in view and "t_f" in view and "2 字段" in view


class TestWorkspaceReady:
    def test_build_cleared_and_tmp_created(self, tmp_path, demo_baseline):
        arc = _opt_ready(tmp_path, demo_baseline)
        stale = tmp_path / "build" / "stale.txt"
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_text("旧现场残留", encoding="utf-8")
        pkg = make_pkg(tmp_path / "pkg", [ent(), ent(table="dim_channel", alias="c")],
                       [attr(tcol="order_id", alias="a", stable="ods_trade_order_di", scol="order_id"),
                        attr()], STD_CHANGES)
        main(["--mapping", str(pkg / PKG_XLSX), "--rs", str(pkg / PKG_RS),
              "--ts-baseline", str(arc / "ts.json"), "--opt-root", str(tmp_path)])
        assert not stale.exists()                       # 开工清场
        assert (tmp_path / "archive_tmp" / "ts.json").exists()   # 临时档案=档案副本起步


class TestFieldTypeDrift:
    """存量字段类型对账（同名异容，2026-10-21 三方一致性补位）+ unsupported 存在性事实。"""

    def test_drift_warns_on_type_change(self, facts):
        """mapping 改存量字段类型（VARCHAR(64)→128）无变更记录 → warn 披露两侧类型。"""
        from preprocess_opt import field_type_drift
        rows = [{"target_column": "order_id", "target_type": "VARCHAR(128)"}]
        diags = field_type_drift(rows, facts["field_types"], set())
        assert [d["code"] for d in diags] == ["field_type_drift"]
        assert "VARCHAR(128)" in diags[0]["message"] and "VARCHAR(64)" in diags[0]["message"]
        assert diags[0]["level"] == "warn"

    def test_normalized_form_not_warned(self, facts):
        """书写形态差异（NUMBER(18,2) vs 基线 DECIMAL(18,2)；小写 varchar）归一后不报。"""
        from preprocess_opt import field_type_drift
        rows = [{"target_column": "total_amount", "target_type": "NUMBER(18,2)"},
                {"target_column": "order_id", "target_type": "varchar(64)"}]
        assert field_type_drift(rows, facts["field_types"], set()) == []

    def test_family_change_warned(self, facts):
        from preprocess_opt import field_type_drift
        rows = [{"target_column": "order_id", "target_type": "numeric(20,0)"}]
        diags = field_type_drift(rows, facts["field_types"], set())
        assert [d["code"] for d in diags] == ["field_type_drift"]

    def test_skip_and_empty_sides(self, facts):
        """skip（本批新增/改名）跳过；任一侧类型空=宁放过；不在基线=漏标扫描的领地。"""
        from preprocess_opt import field_type_drift
        rows = [{"target_column": "order_id", "target_type": "VARCHAR(128)"},   # 命中 skip
                {"target_column": "cust_id", "target_type": ""},                # 声明侧空
                {"target_column": "channel_name", "target_type": "INT"}]       # 不在基线
        assert field_type_drift(rows, facts["field_types"], {"order_id"}) == []

    def test_extract_chain_emits_drift(self, facts):
        """真实链路：extract_and_check 对存量字段类型漂移产 warn（本批 ADD 不受影响）。"""
        extra_attr = [attr(tcol="order_id", alias="a", stable="ods_trade_order_di",
                           scol="order_id", ttype="VARCHAR(200)")]
        mapping, batch = self._std(extra_attr=extra_attr) if hasattr(self, "_std") else (None, None)
        std = TestExtract()
        mapping, batch = std._std(extra_attr=extra_attr)
        renames, rest = synth_renames(batch)
        add_fields, unsupported, diags = extract_and_check(rest, renames, mapping, facts, "202610", "")
        drift = [d for d in diags if d["code"] == "field_type_drift"]
        assert drift and "order_id" in drift[0]["message"]
        assert [f["field"] for f in add_fields] == ["channel_name"]  # 本批 ADD 照常

    def test_unsupported_existence_note(self, facts):
        """unsupported 报告的目标存在性事实：笔误/台账滞后/两侧都有（真待支持）三分。"""
        extra = [chg(3, "2026-10-14", "attr", "default|typo_f", "映射表达式", "MODIFY"),      # 两侧都无
                 chg(4, "2026-10-14", "attr", "default|total_amount", "目标字段类型", "MODIFY"),  # 基线有当前态无
                 chg(5, "2026-10-14", "attr", "default|order_id", "备注", "ADD")]            # 两侧都有
        std = TestExtract()
        mapping, batch = std._std(extra_changes=extra)
        renames, rest = synth_renames(batch)
        _, unsupported, _ = extract_and_check(rest, renames, mapping, facts, "202610", "")
        notes = {u["name"]: u.get("note", "") for u in unsupported}
        assert "疑似笔误" in notes["typo_f"]
        assert "台账滞后" in notes["total_amount"]
        assert notes.get("order_id", "") == "" or "order_id.备注" not in notes
        # 列级 ADD 的 note 键名是 "order_id.备注"（key 是字段名——两侧都有 → 空 note）
        col_add = next(u for u in unsupported if u["change_type"] == "add_column")
        assert col_add.get("note", "") == ""

    def test_entity_unsupported_note(self, facts):
        """实体级 unsupported：key 未命中实体级当前态（别名/分组）→ 事实附加。"""
        extra = [chg(6, "2026-10-14", "entity", "default|ghost_src", "资产字段", "ADD")]
        std = TestExtract()
        mapping, batch = std._std(extra_changes=extra)
        renames, rest = synth_renames(batch)
        _, unsupported, _ = extract_and_check(rest, renames, mapping, facts, "202610", "")
        ent = next(u for u in unsupported if u["level"] == "entity")
        assert "实体级当前态" in ent.get("note", "")


class TestMultiAliasAddField:
    """多别名形态（2026-10-22 内网反馈）：新增加工字段的源表别名列填多别名分号隔开
    （提示性登记不保证完整）——拆分号任一命中实体级即过；全不命中 → dangling error
    且**漏标扫描不误报**（声明集与通过集分离：变更记录明确写了 ADD 的字段不会被说
    "不在本次变更记录中"）。"""

    def _mapping_with(self, alias):
        """channel_name 行用指定别名形态（替掉默认行——同名行会让 hits 取首行失真）。"""
        entity = [ent(), ent(table="dim_channel", alias="c")]
        attrs = [attr(tcol="order_id", alias="a", stable="ods_trade_order_di", scol="order_id"),
                 attr(tcol="channel_name", alias=alias, stable="dim_channel", scol="channel_name")]
        mapping = mapping_of(entity, attrs)
        batch = [_to_entry(c) for c in STD_CHANGES if "10-14" in c["变更时间"]]
        return mapping, batch

    def test_multi_alias_first_hit_used(self, facts):
        """别名 'a;b'（a 命中实体级，b 不存在）→ 无 dangling；source.alias=首个命中 a。"""
        mapping, batch = self._mapping_with("a;b")
        renames, rest = synth_renames(batch)
        add_fields, unsupported, diags = extract_and_check(rest, renames, mapping, facts, "202610", "")
        assert not [d for d in diags if d["code"] == "source_alias_dangling"], diags
        assert add_fields and add_fields[0]["source"]["alias"] == "a"

    def test_full_width_semicolon_also_splits(self, facts):
        """全角分号 'a；c'（a 命中、c 是实体级 dim_channel 的别名）→ 命中即过。"""
        mapping, batch = self._mapping_with("a；c")
        renames, rest = synth_renames(batch)
        add_fields, _, diags = extract_and_check(rest, renames, mapping, facts, "202610", "")
        assert not [d for d in diags if d["code"] == "source_alias_dangling"], diags
        assert add_fields[0]["source"]["alias"] == "a"

    def test_dangling_not_misreported_as_unmarked(self, facts):
        """连带问题回归：别名全不命中 → dangling error 照报，但该字段是变更记录
        明确声明的 ADD——漏标扫描不得再说它'不在本次变更记录中'。"""
        mapping, batch = self._mapping_with("xx;yy")
        renames, rest = synth_renames(batch)
        add_fields, _, diags = extract_and_check(rest, renames, mapping, facts, "202610", "")
        dangling = [d for d in diags if d["code"] == "source_alias_dangling"]
        unmarked = [d for d in diags if d["code"] == "unmarked_new_field"
                    and "channel_name" in d["message"]]
        assert dangling, "全不命中应报 dangling"
        assert not unmarked, f"变更记录已声明 ADD 的字段不得被漏标误报: {unmarked}"
