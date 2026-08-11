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
    def test_etl_priority_over_select(self, tmp_path):
        """etl/ 和 select/ 都有 → 优先 etl/（new-pipe 新格式）。"""
        (tmp_path / "etl").mkdir()
        (tmp_path / "select").mkdir()
        (tmp_path / "etl" / "R0001.sql").write_text("-- etl", encoding="utf-8")
        (tmp_path / "select" / "R0001_select.sql").write_text("-- select", encoding="utf-8")
        f = _paths.find_select_file(tmp_path, "R0001")
        assert f is not None
        assert f.parent.name == "etl"

    def test_select_fallback_old_format(self, tmp_path):
        """只有 select/ → 回退 select/（002 等虚拟案例 + v2 fixture 老格式）。"""
        (tmp_path / "select").mkdir()
        (tmp_path / "select" / "R0001_select.sql").write_text("-- select", encoding="utf-8")
        f = _paths.find_select_file(tmp_path, "R0001")
        assert f is not None
        assert f.parent.name == "select"

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
    def test_merge_etl_and_select_dedup(self, tmp_path):
        """合并 etl/ 和 select/ 的规则，按 code 去重排序。"""
        (tmp_path / "etl").mkdir()
        (tmp_path / "select").mkdir()
        (tmp_path / "etl" / "R0001.sql").write_text("x", encoding="utf-8")
        (tmp_path / "etl" / "R0002.sql").write_text("x", encoding="utf-8")
        (tmp_path / "select" / "R0003_select.sql").write_text("x", encoding="utf-8")
        # R0001 在两边都有 → 去重
        (tmp_path / "select" / "R0001_select.sql").write_text("x", encoding="utf-8")
        assert _paths.list_select_rules(tmp_path) == ["R0001", "R0002", "R0003"]

    def test_empty_when_no_dir(self, tmp_path):
        assert _paths.list_select_rules(tmp_path) == []

    def test_extract_code_from_suffix_filename(self, tmp_path):
        """带后缀文件名提取 code：R0001_shop_truncate_table.sql → R0001。"""
        (tmp_path / "etl").mkdir()
        (tmp_path / "etl" / "R0001_shop_truncate_table.sql").write_text("x", encoding="utf-8")
        (tmp_path / "etl" / "R0002_user_merge_into.sql").write_text("x", encoding="utf-8")
        assert _paths.list_select_rules(tmp_path) == ["R0001", "R0002"]


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
