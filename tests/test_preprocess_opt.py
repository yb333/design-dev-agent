"""preprocess_opt v2 测试：真实输入格式（全量 mapping 备注版本标记 + RS 变更记录）。

场景构造对齐 docs/specs/opt/11-测试指引：需求包目录（全量 mapping + RS）、
baseline 由 demo fixture 现场组装。不连库。
"""
import json
from pathlib import Path

from openpyxl import Workbook

import pytest

from assemble_ts_baseline import build_ts_baseline
from preprocess_opt import (
    scan_input_dir, parse_change_log, normalize_yyyymm, pick_current_version,
    extract_version_section, remark_markers, extract_and_check, main,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "opt"

ENTITY_COLS = ["源表schema", "源表物理表名", "源表别名", "目标表逻辑schema",
               "目标表物理名称", "关联&限定条件", "备注"]
ATTR_COLS = ["源表别名", "源表物理表名", "源表字段名", "映射规则", "映射表达式",
             "目标字段名", "目标字段中文名", "目标字段类型", "备注"]

RS_MD = """# 某资产需求规格

## 3.3 变更记录

| 日期 | 版本 | 修改人 | 修改内容 |
|------|------|--------|----------|
| 2026-03-10 | v1.0 | 张三 | 初始版本 |
| 2026-08-21 | v2.0 | 李四 | 优化版本：新增渠道相关字段 |

## 4. 字段需求

202608版本新增需求：新增 channel_name（渠道名称），来源渠道维表，
按订单关联取渠道名称；202603版本新增需求：旧版本内容示例。
"""


def ent(remark="", table="ods_trade_order_di", alias="a", target="dwb_trade_order_d"):
    return {"源表schema": "ods", "源表物理表名": table, "源表别名": alias,
            "目标表逻辑schema": "dws", "目标表物理名称": target,
            "关联&限定条件": "", "备注": remark}


def attr(remark="", tcol="channel_name", tcol_cn="渠道名称", ttype="VARCHAR(64)",
         alias="c", stable="dim_channel", scol="channel_name"):
    return {"源表别名": alias, "源表物理表名": stable, "源表字段名": scol,
            "映射规则": "直取", "映射表达式": "-", "目标字段名": tcol,
            "目标字段中文名": tcol_cn, "目标字段类型": ttype, "备注": remark}


@pytest.fixture(scope="module")
def facts():
    demo = json.loads((FIXTURES / "baseline_v1_demo_full.json").read_text(encoding="utf-8"))
    ts, _ = build_ts_baseline(demo)
    from preprocess_opt import baseline_facts
    return baseline_facts(ts)


def make_pkg(pkg_dir: Path, entity_rows, attr_rows, rs_md=RS_MD,
             mapping_name="dwb_trade_order_d_全量mapping.xlsx"):
    pkg_dir.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws1 = wb.active; ws1.title = "实体级mapping"; ws1.append(ENTITY_COLS)
    for r in entity_rows:
        ws1.append([r.get(c, "") for c in ENTITY_COLS])
    ws2 = wb.create_sheet("属性级mapping"); ws2.append(ATTR_COLS)
    for r in attr_rows:
        ws2.append([r.get(c, "") for c in ATTR_COLS])
    wb.save(pkg_dir / mapping_name)
    (pkg_dir / "RS_需求文档.md").write_text(rs_md, encoding="utf-8")
    (pkg_dir / "冗余说明.txt").write_text("多余文件", encoding="utf-8")
    return pkg_dir


def std_rows(extra_entity=(), extra_attr=(), with_old=False):
    """标准行集：干净 happy path；with_old=True 加一行 202603 标记字段（台账/实跑漂移场景）。"""
    attr_rows = [attr(remark="202608版本新增"),
                 attr(remark="", tcol="order_id", tcol_cn="订单ID", alias="a",
                      stable="ods_trade_order_di", scol="order_id")]
    if with_old:
        attr_rows.append(attr(remark="202603版本新增", tcol="pay_type", tcol_cn="支付类型",
                              alias="a", stable="ods_trade_order_di", scol="pay_type"))
    return ([ent(),
             ent(remark="202608版本新增", table="dim_channel", alias="c")] + list(extra_entity),
            attr_rows + list(extra_attr))


ATTR_EN = {"源表别名": "source_alias", "源表物理表名": "source_table", "源表字段名": "source_column",
           "映射规则": "mapping_rule", "映射表达式": "mapping_expression",
           "目标字段名": "target_column", "目标字段中文名": "target_column_cn",
           "目标字段类型": "target_type", "备注": "remark", "分组": "scene_group"}
ENT_EN = {"源表schema": "source_schema", "源表物理表名": "source_table", "源表别名": "source_alias",
          "目标表逻辑schema": "target_schema", "目标表物理名称": "target_table",
          "关联&限定条件": "join_condition", "备注": "remark"}


def mapping_of(entity_rows, attr_rows):
    """中文列名行 → extract_and_check 消费的英文键行（与 read_full_mapping 归一后同构）。"""
    to_en = lambda rows, m: [{m.get(k, k): v for k, v in r.items()} for r in rows]
    return {"entity": to_en(entity_rows, ENT_EN), "attr": to_en(attr_rows, ATTR_EN)}


class TestScan:
    def test_unique_xlsx_md(self, tmp_path):
        pkg = make_pkg(tmp_path, *std_rows())
        scan = scan_input_dir(pkg)
        assert "全量mapping" in scan["full_mapping"].name
        assert scan["rs"].name.endswith(".md")
        assert scan["ignored"] == ["冗余说明.txt"]

    def test_multi_xlsx_keyword_pick(self, tmp_path):
        pkg = make_pkg(tmp_path, *std_rows())
        # 再丢一个非 mapping 的 xlsx（含"最新"关键词的才该被选中）
        (pkg / "其他_台账.xlsx").write_bytes((pkg / "dwb_trade_order_d_全量mapping.xlsx").read_bytes())
        scan = scan_input_dir(pkg)
        assert "全量mapping" in scan["full_mapping"].name

    def test_ambiguous_fail_loud(self, tmp_path):
        pkg = make_pkg(tmp_path, *std_rows(), mapping_name="mapping_A.xlsx")
        (pkg / "mapping_B.xlsx").write_bytes((pkg / "mapping_A.xlsx").read_bytes())
        with pytest.raises(ValueError, match="显式指定"):
            scan_input_dir(pkg)


class TestRsParsing:
    def test_change_log_and_version(self):
        rows = parse_change_log(RS_MD)
        assert rows[0]["desc"].startswith("初始版本") and rows[1]["ver"] == "v2.0"
        ver, row = pick_current_version(rows)
        assert ver == "202608" and "优化" in row["desc"]

    def test_normalize_variants(self):
        assert normalize_yyyymm("2026-08-21") == "202608"
        assert normalize_yyyymm("2026/8/1") == "202608"
        assert normalize_yyyymm("202608") == "202608"
        with pytest.raises(ValueError):
            normalize_yyyymm("不知道")

    def test_version_section_anchor(self):
        sec = extract_version_section(RS_MD, "202608")
        assert "channel_name" in sec and "202603版本" not in sec


class TestRemarkMarkers:
    def test_multi_markers(self):
        assert remark_markers("202603版本新增；202608版本新增") == [("202603", "新增"), ("202608", "新增")]
        assert remark_markers("202608版本修改") == [("202608", "修改")]
        assert remark_markers("") == []

    def test_extract_add_field(self, facts):
        entity, attr_rows = std_rows()
        mapping = mapping_of(entity, attr_rows)
        adds, unsup, diags = extract_and_check(mapping, facts, "202608", "channel_name 在此")
        assert [f["field"] for f in adds] == ["channel_name"], "202603 标记与无标记行都不进本次"
        assert adds[0]["new_source_table"] is True
        assert unsup == []
        assert diags == [], "202603 字段在 baseline？——不在，会触发漏标 warn，见下个测试"

    def test_old_version_field_not_in_baseline_warns(self, facts):
        """202603 版本新增的字段不在 baseline（台账/实跑漂移）→ warn 提示而非静默。"""
        entity, attr_rows = std_rows(with_old=True)
        mapping = mapping_of(entity, attr_rows)
        _, _, diags = extract_and_check(mapping, facts, "202608", "channel_name")
        assert any(d["code"] == "unmarked_new_field" and "pay_type" in d["message"] for d in diags)

    def test_unsupported_verb_recognized_not_rejected(self, facts):
        entity, attr_rows = std_rows(
            extra_attr=[attr(remark="202608版本修改", tcol="total_amount", tcol_cn="订单总额",
                             alias="a", stable="ods_trade_order_di", scol="amount")])
        mapping = mapping_of(entity, attr_rows)
        adds, unsup, diags = extract_and_check(mapping, facts, "202608", "channel_name total_amount")
        assert [f["field"] for f in adds] == ["channel_name"]
        assert any(u["change_type"] == "modify" and u["name"] == "total_amount" for u in unsup)
        assert not any(d["level"] == "error" for d in diags), "识别待扩展不是错误"

    def test_conflict_and_dangling(self, facts):
        entity, attr_rows = std_rows(
            extra_attr=[attr(remark="202608版本新增", tcol="order_id")])
        mapping = mapping_of(entity, attr_rows)
        _, _, diags = extract_and_check(mapping, facts, "202608", "channel_name order_id")
        assert any(d["code"] == "add_field_conflict" for d in diags)


class TestMainEndToEnd:
    def test_input_dir_flow(self, tmp_path, demo_baseline):
        pkg = make_pkg(tmp_path / "rs_mapping", *std_rows())
        out = tmp_path / "internal"
        rc = main(["--input-dir", str(pkg), "--ts-baseline", str(demo_baseline),
                   "--outdir", str(out)])
        assert rc == 0
        cr = json.loads((out / "change_request.json").read_text(encoding="utf-8"))
        assert cr["version"] == "202608" and cr["change_type"] == "add_field"
        assert cr["change_log_summary"]["ver"] == "v2.0"
        assert [f["field"] for f in cr["fields"]] == ["channel_name"]
        assert "channel_name" in cr["rs_opt_section"]
        mf = json.loads((out / "input_manifest.json").read_text(encoding="utf-8"))
        assert mf["version"] == "202608" and mf["ignored"] == ["冗余说明.txt"]

    def test_explicit_version_override(self, tmp_path, demo_baseline):
        pkg = make_pkg(tmp_path / "rs_mapping", *std_rows())
        rc = main(["--input-dir", str(pkg), "--ts-baseline", str(demo_baseline),
                   "--outdir", str(tmp_path / "internal"), "--version", "202609"])
        assert rc in (0, 1)   # 无 202609 标记行 → 提取为空 + rs warn；不阻断（版本是显式的）
        cr = json.loads((tmp_path / "internal" / "change_request.json").read_text(encoding="utf-8"))
        assert cr["version"] == "202609" and cr["fields"] == []

    def test_blocked_exit_2(self, tmp_path, demo_baseline):
        entity, attr_rows = std_rows(extra_attr=[attr(remark="202608版本新增", tcol="order_id")])
        pkg = make_pkg(tmp_path / "rs_mapping", entity, attr_rows)
        rc = main(["--input-dir", str(pkg), "--ts-baseline", str(demo_baseline),
                   "--outdir", str(tmp_path / "internal")])
        assert rc == 2
        assert not (tmp_path / "internal" / "change_request.json").exists()


@pytest.fixture(scope="module")
def demo_baseline(tmp_path_factory):
    import assemble_ts_baseline as m
    demo = json.loads((FIXTURES / "baseline_v1_demo_full.json").read_text(encoding="utf-8"))
    d = tmp_path_factory.mktemp("baseline")
    src = d / "baseline_v1.json"
    src.write_text(json.dumps(demo, ensure_ascii=False), encoding="utf-8")
    outdir = d / "internal"
    assert m.main(["--baseline", str(src), "--outdir", str(outdir)]) == 0
    return outdir / "ts_baseline.json"
