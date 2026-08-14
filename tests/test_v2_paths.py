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
# 产出目录定位（平铺 / 三层 appid-schema 兼容）
# ============================================================


def _make_deliver_at(path: Path) -> Path:
    """在 path 下造 ddlc_design_dev/ts.json，返回 deliver 目录。"""
    d = path / "ddlc_design_dev"
    d.mkdir(parents=True, exist_ok=True)
    (d / "ts.json").write_text("{}", encoding="utf-8")
    return d


class TestFindDeliver:
    def test_flat_structure(self, tmp_path):
        """平铺（老结构）：{asset}/ddlc_design_dev/ts.json。"""
        d = _make_deliver_at(tmp_path / "dwb_x")
        assert _paths.find_deliver(tmp_path, "dwb_x") == d

    def test_three_level_structure(self, tmp_path):
        """三层（新结构）：{appid}/{schema}/{asset}/ddlc_design_dev/ts.json。"""
        d = _make_deliver_at(tmp_path / "app001" / "dwb" / "dwb_x")
        assert _paths.find_deliver(tmp_path, "dwb_x") == d

    def test_flat_preferred_over_three_level(self, tmp_path):
        """平铺与三层同名 → 平铺优先。"""
        flat = _make_deliver_at(tmp_path / "dwb_x")
        _make_deliver_at(tmp_path / "app" / "dwb" / "dwb_x")
        assert _paths.find_deliver(tmp_path, "dwb_x") == flat

    def test_none_when_absent(self, tmp_path):
        assert _paths.find_deliver(tmp_path, "nope") is None


class TestScanDeliverAssets:
    def test_flat_and_three_level_merged(self, tmp_path):
        """平铺 + 三层混合扫描，资产名统一收集。"""
        a = _make_deliver_at(tmp_path / "dwb_flat")
        b = _make_deliver_at(tmp_path / "app001" / "dwb" / "dwb_three")
        assets = _paths.scan_deliver_assets(tmp_path)
        assert assets == {"dwb_flat": a, "dwb_three": b}

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
