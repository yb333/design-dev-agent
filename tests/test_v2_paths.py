"""_paths 公共定位函数测试：etl 新格式与 select 老格式的双兼容。

这是断点2（v2 断言只认老格式）的回归保护——保证两种产出格式都能被定位到。
"""

import sys
from pathlib import Path

import pytest

_V2_DIR = Path(__file__).resolve().parent.parent / "eval-suite" / "v2"
if str(_V2_DIR) not in sys.path:
    sys.path.insert(0, str(_V2_DIR))

import _paths


class TestFindSelectFile:
    def test_etl_only_new_pipe_format(self, tmp_path):
        """只有 etl/（new-pipe 真实产出）→ 能找到。"""
        (tmp_path / "etl").mkdir()
        (tmp_path / "etl" / "R0001.sql").write_text("-- etl", encoding="utf-8")
        f = _paths.find_select_file(tmp_path, "R0001")
        assert f is not None
        assert f.name == "R0001.sql"

    def test_etl_with_suffix_loadmode_naming(self, tmp_path):
        """new-pipe 带 load_mode/表名后缀：etl/R0001_shop_truncate_table.sql → 能找到。

        覆盖内网真实产出命名（assemble_export.py 同款处理）。
        """
        (tmp_path / "etl").mkdir()
        (tmp_path / "etl" / "R0001_shop_truncate_table.sql").write_text("-- x", encoding="utf-8")
        f = _paths.find_select_file(tmp_path, "R0001")
        assert f is not None
        assert f.name == "R0001_shop_truncate_table.sql"

    def test_exact_preferred_over_suffix(self, tmp_path):
        """精确 {code}.sql 和 {code}_xxx.sql 都有 → 优先精确。"""
        (tmp_path / "etl").mkdir()
        (tmp_path / "etl" / "R0001.sql").write_text("-- exact", encoding="utf-8")
        (tmp_path / "etl" / "R0001_shop_truncate_table.sql").write_text("-- suffix", encoding="utf-8")
        f = _paths.find_select_file(tmp_path, "R0001")
        assert f.name == "R0001.sql"

    def test_suffix_prefix_not_match_other_rule(self, tmp_path):
        """R0001_ 前缀不会误匹配 R0002 的查找。"""
        (tmp_path / "etl").mkdir()
        (tmp_path / "etl" / "R0001_shop_truncate_table.sql").write_text("-- x", encoding="utf-8")
        assert _paths.find_select_file(tmp_path, "R0002") is None

    def test_none_when_both_absent(self, tmp_path):
        """两种都没有 → None。"""
        assert _paths.find_select_file(tmp_path, "R0001") is None


class TestListSelectRules:
    def test_etl_multiple_rules_dedup(self, tmp_path):
        """etl/ 多规则枚举，同 code（精确 + 带后缀）去重排序。"""
        (tmp_path / "etl").mkdir()
        (tmp_path / "etl" / "R0001.sql").write_text("x", encoding="utf-8")
        (tmp_path / "etl" / "R0002.sql").write_text("x", encoding="utf-8")
        # R0001 同时有精确和带后缀 → 去重为一个
        (tmp_path / "etl" / "R0001_shop_truncate_table.sql").write_text("x", encoding="utf-8")
        assert _paths.list_select_rules(tmp_path) == ["R0001", "R0002"]

    def test_empty_when_no_dir(self, tmp_path):
        assert _paths.list_select_rules(tmp_path) == []

    def test_extract_code_from_suffix_filename(self, tmp_path):
        """带后缀文件名提取 code：R0001_shop_truncate_table.sql → R0001。"""
        (tmp_path / "etl").mkdir()
        (tmp_path / "etl" / "R0001_shop_truncate_table.sql").write_text("x", encoding="utf-8")
        (tmp_path / "etl" / "R0002_user_merge_into.sql").write_text("x", encoding="utf-8")
        assert _paths.list_select_rules(tmp_path) == ["R0001", "R0002"]


# ============================================================
# 产出目录定位（固定三层 {appid}/{schema}/{资产}）
# ============================================================


def _make_deliver_at(path: Path) -> Path:
    """在 path 下造 ddlc_design_dev/ts.json，返回 deliver 目录。"""
    d = path / "ddlc_design_dev"
    d.mkdir(parents=True, exist_ok=True)
    (d / "ts.json").write_text("{}", encoding="utf-8")
    return d


class TestFindDeliver:
    def test_three_level_structure(self, tmp_path):
        """三层：{appid}/{schema}/{asset}/ddlc_design_dev/ts.json。"""
        d = _make_deliver_at(tmp_path / "app001" / "dwb" / "dwb_x")
        assert _paths.find_deliver(tmp_path, "dwb_x") == d

    def test_flat_not_recognized(self, tmp_path):
        """平铺（老结构）不再识别——三层是唯一约定。"""
        _make_deliver_at(tmp_path / "dwb_x")
        assert _paths.find_deliver(tmp_path, "dwb_x") is None

    def test_requires_ts_json(self, tmp_path):
        """三层下目录存在但无 ts.json → 不算产出。"""
        (tmp_path / "app" / "dwb" / "dwb_x" / "ddlc_design_dev").mkdir(parents=True)
        assert _paths.find_deliver(tmp_path, "dwb_x") is None

    def test_none_when_absent(self, tmp_path):
        assert _paths.find_deliver(tmp_path, "nope") is None


class TestScanDeliverAssets:
    def test_three_level_scan(self, tmp_path):
        """跨 appid/schema 扫描，资产名统一收集。"""
        a = _make_deliver_at(tmp_path / "app001" / "dwb" / "dwb_a")
        b = _make_deliver_at(tmp_path / "app002" / "dws" / "dwb_b")
        assets = _paths.scan_deliver_assets(tmp_path)
        assert assets == {"dwb_a": a, "dwb_b": b}

    def test_flat_ignored(self, tmp_path):
        """平铺产出不进发现结果。"""
        _make_deliver_at(tmp_path / "dwb_flat")
        assert _paths.scan_deliver_assets(tmp_path) == {}

    def test_empty_when_no_base(self, tmp_path):
        assert _paths.scan_deliver_assets(tmp_path / "nodir") == {}


class TestFindTsMd:
    def test_plain_ts_md(self, tmp_path):
        """老格式 ts.md。"""
        (tmp_path / "ts.md").write_text("x", encoding="utf-8")
        assert _paths.find_ts_md(tmp_path).name == "ts.md"

    def test_asset_ts_md_new_pipe(self, tmp_path):
        """new-pipe 格式 {资产}_ts.md 也能找到。"""
        (tmp_path / "dwb_shop_center_f_ts.md").write_text("x", encoding="utf-8")
        assert _paths.find_ts_md(tmp_path).name == "dwb_shop_center_f_ts.md"

    def test_plain_preferred_over_asset(self, tmp_path):
        """ts.md 和 {资产}_ts.md 都有 → 优先 ts.md。"""
        (tmp_path / "ts.md").write_text("x", encoding="utf-8")
        (tmp_path / "dwb_x_ts.md").write_text("x", encoding="utf-8")
        assert _paths.find_ts_md(tmp_path).name == "ts.md"

    def test_none_when_absent(self, tmp_path):
        assert _paths.find_ts_md(tmp_path) is None


# ============================================================
# 案例输入文件发现（mapping / RS，文件名不做硬性约定）
# ============================================================


class TestFindMappingFile:
    def test_only_xlsx_is_mapping(self, tmp_path):
        """目录里唯一的 xlsx 就是 mapping（不看文件名）。"""
        (tmp_path / "连接层粒度转换案例.xlsx").write_text("x", encoding="utf-8")
        assert _paths.find_mapping_file(tmp_path).name == "连接层粒度转换案例.xlsx"

    def test_multiple_xlsx_prefers_mapping_keyword(self, tmp_path):
        """多个 xlsx：名字含 mapping 的优先。"""
        (tmp_path / "a别的表.xlsx").write_text("x", encoding="utf-8")
        (tmp_path / "b资产mapping.xlsx").write_text("x", encoding="utf-8")
        assert _paths.find_mapping_file(tmp_path).name == "b资产mapping.xlsx"

    def test_none_when_no_xlsx(self, tmp_path):
        assert _paths.find_mapping_file(tmp_path) is None

    def test_eval_own_files_not_mistaken(self, tmp_path):
        """评测自己的 yaml/json 不占 xlsx 后缀，不干扰识别。"""
        (tmp_path / "mapping.xlsx").write_text("x", encoding="utf-8")
        (tmp_path / "RS.md").write_text("x", encoding="utf-8")
        (tmp_path / "checks.yaml").write_text("x", encoding="utf-8")
        (tmp_path / "expectations.json").write_text("x", encoding="utf-8")
        (tmp_path / "checks.seeded.yaml").write_text("x", encoding="utf-8")
        assert _paths.find_mapping_file(tmp_path).name == "mapping.xlsx"
        assert _paths.find_rs_file(tmp_path).name == "RS.md"


class TestFindRsFile:
    def test_only_md_is_rs(self, tmp_path):
        """目录里唯一的 md 就是 RS（不看文件名）。"""
        (tmp_path / "订单中心需求说明.md").write_text("x", encoding="utf-8")
        assert _paths.find_rs_file(tmp_path).name == "订单中心需求说明.md"

    def test_multiple_md_prefers_rs_keyword(self, tmp_path):
        """多个 md：名字含 rs/需求 的优先。"""
        (tmp_path / "a笔记.md").write_text("x", encoding="utf-8")
        (tmp_path / "b需求文档.md").write_text("x", encoding="utf-8")
        assert _paths.find_rs_file(tmp_path).name == "b需求文档.md"

    def test_none_when_no_md(self, tmp_path):
        assert _paths.find_rs_file(tmp_path) is None
