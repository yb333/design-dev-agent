"""preprocess_opt 测试：标注解析 → change_request + 一致性校验（docs/specs/opt/03）。

不连库。mapping.xlsx 由 openpyxl 现场构造（模板列 + 变更标识列）；baseline 用
assemble_ts_baseline.build_ts_baseline 现场组装 demo fixture（消费链闭环）。
"""
import json
from pathlib import Path

from openpyxl import Workbook

import pytest

from assemble_ts_baseline import build_ts_baseline
from preprocess_opt import (
    read_marked_mapping, extract_and_check, baseline_facts,
    extract_rs_opt_section, main,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "opt"

ENTITY_COLS = ["源表schema", "源表物理表名", "源表别名", "目标表逻辑schema",
               "目标表物理名称", "关联&限定条件", "变更标识"]
ATTR_COLS = ["源表别名", "源表物理表名", "源表字段名", "映射规则", "映射表达式",
             "目标字段名", "目标字段中文名", "目标字段类型", "变更标识"]


def make_marked_mapping(path: Path, entity_rows, attr_rows):
    wb = Workbook()
    ws1 = wb.active
    ws1.title = "实体级mapping"
    ws1.append(ENTITY_COLS)
    for r in entity_rows:
        ws1.append([r.get(c, "") for c in ENTITY_COLS])
    ws2 = wb.create_sheet("属性级mapping")
    ws2.append(ATTR_COLS)
    for r in attr_rows:
        ws2.append([r.get(c, "") for c in ATTR_COLS])
    wb.save(path)
    return path


@pytest.fixture(scope="module")
def facts():
    demo = json.loads((FIXTURES / "baseline_v1_demo_full.json").read_text(encoding="utf-8"))
    ts, _ = build_ts_baseline(demo)
    return baseline_facts(ts)


@pytest.fixture(scope="module")
def demo_and_baseline(tmp_path_factory):
    """demo 契约 fixture → 现场组装 ts_baseline 文件（真实产物，非手工构造）。"""
    import assemble_ts_baseline as m
    demo = json.loads((FIXTURES / "baseline_v1_demo_full.json").read_text(encoding="utf-8"))
    d = tmp_path_factory.mktemp("baseline")
    src = d / "baseline_v1.json"
    src.write_text(json.dumps(demo, ensure_ascii=False), encoding="utf-8")
    outdir = d / "internal"
    assert m.main(["--baseline", str(src), "--outdir", str(outdir)]) == 0
    return src, outdir / "ts_baseline.json"


def ent(flag="", table="ods_trade_order_di", alias="a", target="dwb_trade_order_d"):
    return {"源表schema": "ods", "源表物理表名": table, "源表别名": alias,
            "目标表逻辑schema": "dws", "目标表物理名称": target,
            "关联&限定条件": "", "变更标识": flag}


def attr(flag="新增", tcol="channel_name", tcol_cn="渠道名称", ttype="VARCHAR(64)",
         alias="c", stable="dim_channel", scol="channel_name"):
    return {"源表别名": alias, "源表物理表名": stable, "源表字段名": scol,
            "映射规则": "直取", "映射表达式": "-", "目标字段名": tcol,
            "目标字段中文名": tcol_cn, "目标字段类型": ttype, "变更标识": flag}


class TestHappyPath:
    def test_new_join_shape(self, facts, tmp_path):
        """B 形态：新表来源（实体级新增行 + 属性级新增行）。"""
        mp = make_marked_mapping(tmp_path / "m.xlsx",
                                 [ent(), ent(flag="新增", table="dim_channel", alias="c")],
                                 [attr()])
        mapping = read_marked_mapping(mp)
        adds, diags, unsup = extract_and_check(mapping, facts, None)
        assert not diags and not unsup
        assert len(adds) == 1
        f = adds[0]
        assert f["field"] == "channel_name" and f["cn"] == "渠道名称"
        assert f["source"]["table"] == "dim_channel" and f["source"]["alias"] == "c"
        assert f["new_source_table"] is True, "dim_channel 不在 baseline 源表清单"

    def test_same_source_direct(self, facts, tmp_path):
        """A 形态：同源直挂（存量表来源，不标实体级新增行）。"""
        mp = make_marked_mapping(tmp_path / "m.xlsx", [ent()],
                                 [attr(alias="a", stable="ods_trade_order_di",
                                       tcol="pay_channel", scol="pay_channel")])
        adds, diags, _ = extract_and_check(read_marked_mapping(mp), facts, None)
        assert not diags
        assert adds[0]["new_source_table"] is False

    def test_main_writes_change_request(self, facts, tmp_path, demo_and_baseline):
        demo_json, baseline_path = demo_and_baseline
        mp = make_marked_mapping(tmp_path / "m.xlsx",
                                 [ent(), ent(flag="新增", table="dim_channel", alias="c")],
                                 [attr()])
        rs = tmp_path / "rs.md"
        rs.write_text("# 优化需求\n\n新增 channel_name 字段，口径：渠道名称。\n", encoding="utf-8")
        rc = main(["--mapping", str(mp), "--ts-baseline", str(baseline_path),
                   "--outdir", str(tmp_path / "internal"), "--rs", str(rs)])
        assert rc == 0
        cr = json.loads((tmp_path / "internal" / "change_request.json").read_text(encoding="utf-8"))
        assert cr["change_type"] == "add_field"
        assert cr["asset"] == "dws.dwb_trade_order_d"
        assert cr["backfill"] == "pending"
        assert "channel_name" in cr["rs_opt_section"]
        assert cr["fields"][0]["source"]["table"] == "dim_channel"


class TestBlocks:
    def test_conflict_field_exists(self, facts, tmp_path):
        mp = make_marked_mapping(tmp_path / "m.xlsx", [ent()],
                                 [attr(tcol="order_id", scol="order_id")])
        _, diags, _ = extract_and_check(read_marked_mapping(mp), facts, None)
        assert any(d["code"] == "add_field_conflict" and d["level"] == "error" for d in diags)

    def test_unsupported_flag(self, facts, tmp_path):
        mp = make_marked_mapping(tmp_path / "m.xlsx", [ent()],
                                 [attr(flag="修改", tcol="total_amount")])
        _, diags, _ = extract_and_check(read_marked_mapping(mp), facts, None)
        assert any(d["code"] == "unsupported_change_flag" for d in diags)

    def test_dangling_alias(self, facts, tmp_path):
        mp = make_marked_mapping(tmp_path / "m.xlsx", [ent()],
                                 [attr(alias="zzz")])
        _, diags, _ = extract_and_check(read_marked_mapping(mp), facts, None)
        assert any(d["code"] == "source_alias_dangling" for d in diags)

    def test_asset_mismatch(self, facts, tmp_path):
        mp = make_marked_mapping(tmp_path / "m.xlsx", [ent(target="dwb_other_d")],
                                 [attr()])
        _, diags, _ = extract_and_check(read_marked_mapping(mp), facts, None)
        assert any(d["code"] == "asset_table_mismatch" for d in diags)

    def test_entity_add_on_existing_source(self, facts, tmp_path):
        """存量表标实体级'新增' → 冲突（同源直挂不需要新实体行）。"""
        mp = make_marked_mapping(tmp_path / "m.xlsx",
                                 [ent(flag="新增")],   # ods_trade_order_di 已是存量来源
                                 [attr(alias="a", stable="ods_trade_order_di")])
        _, diags, _ = extract_and_check(read_marked_mapping(mp), facts, None)
        assert any(d["code"] == "entity_add_conflict" for d in diags)

    def test_blocked_exit_2_no_change_request(self, facts, tmp_path, demo_and_baseline):
        _, baseline_path = demo_and_baseline
        mp = make_marked_mapping(tmp_path / "m.xlsx", [ent()], [attr(tcol="order_id")])
        rc = main(["--mapping", str(mp), "--ts-baseline", str(baseline_path),
                   "--outdir", str(tmp_path / "internal")])
        assert rc == 2
        assert not (tmp_path / "internal" / "change_request.json").exists()


class TestWarns:
    def test_unmarked_new_field(self, facts, tmp_path):
        mp = make_marked_mapping(tmp_path / "m.xlsx", [ent()],
                                 [attr(flag="", tcol="mystery_col")])
        _, diags, _ = extract_and_check(read_marked_mapping(mp), facts, None)
        assert any(d["code"] == "unmarked_new_field" and d["level"] == "warn" for d in diags)

    def test_rs_field_absent(self, facts, tmp_path):
        mp = make_marked_mapping(tmp_path / "m.xlsx",
                                 [ent(), ent(flag="新增", table="dim_channel", alias="c")],
                                 [attr()])
        _, diags, _ = extract_and_check(read_marked_mapping(mp), facts, "RS 全文没有提这个字段")
        assert any(d["code"] == "rs_field_not_mentioned" and d["level"] == "warn" for d in diags)

    def test_warn_exit_1_with_output(self, facts, tmp_path, demo_and_baseline):
        _, baseline_path = demo_and_baseline
        mp = make_marked_mapping(tmp_path / "m.xlsx",
                                 [ent(), ent(flag="新增", table="dim_channel", alias="c")],
                                 [attr(), attr(flag="", tcol="mystery_col")])
        rc = main(["--mapping", str(mp), "--ts-baseline", str(baseline_path),
                   "--outdir", str(tmp_path / "internal")])
        assert rc == 1
        assert (tmp_path / "internal" / "change_request.json").exists()


class TestRsSection:
    def test_extract_opt_section(self):
        md = "# 需求\nxx\n# 优化说明\n新增 a 字段\n# 其他章节\nyy"
        assert "新增 a 字段" in extract_rs_opt_section(md)
        assert "其他章节" not in extract_rs_opt_section(md)

    def test_no_opt_heading_fallback_fulltext(self):
        md = "# 需求\n只有正文"
        assert extract_rs_opt_section(md) == md
