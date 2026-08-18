"""menu._discover_real_cases + seed._resolve_case_dir 测试（二级分类结构）。

cases_real 采用分类二级结构：cases_real/{分类}/{资产}/。
10_project_deliver 保持平铺。deliver_only 案例默认归"未分类"。
"""

import sys
from pathlib import Path

import pytest

_EVAL_SUITE = Path(__file__).resolve().parent.parent / "eval-suite"
_V2_DIR = _EVAL_SUITE / "v2"
for p in (str(_EVAL_SUITE), str(_V2_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import menu
import seed


def _make_deliver(base: Path, asset: str) -> None:
    """在 base 下造三层产出 {appid}/{schema}/{asset}/ddlc_design_dev/ts.json。"""
    d = base / "app1" / "sch1" / asset / "ddlc_design_dev"
    d.mkdir(parents=True, exist_ok=True)
    (d / "ts.json").write_text("{}", encoding="utf-8")


def _make_real_input(base: Path, category: str, asset: str, with_checks: bool = False) -> Path:
    """造 cases_real/{category}/{asset}/ 输入目录（含 mapping.xlsx）。"""
    d = base / category / asset
    d.mkdir(parents=True, exist_ok=True)
    (d / "mapping.xlsx").write_text("x", encoding="utf-8")
    if with_checks:
        (d / "checks.yaml").write_text("case: {}", encoding="utf-8")
    return d


class TestDiscoverRealCases:
    def test_deliver_only_defaults_to_uncategorized(self, tmp_path, monkeypatch):
        """cases_real 不存在 + 10_project_deliver 有产出 → deliver_only，分类=未分类。"""
        _make_deliver(tmp_path, "dwb_shop_center_f")
        monkeypatch.setattr(menu, "DELIVER_BASE", tmp_path)
        monkeypatch.setattr(menu, "CASES_REAL_DIR", tmp_path / "cases_real")
        cases = menu._discover_real_cases()
        assert len(cases) == 1
        c = cases[0]
        assert c.name == "dwb_shop_center_f"
        assert c.has_deliver is True
        assert c.input_dir is None
        assert c.category == "未分类"
        assert "✗输入" in c.status_tag and "✓产出" in c.status_tag

    def test_input_ready_carries_category(self, tmp_path, monkeypatch):
        """cases_real/{分类}/{资产}/ 有 mapping → input_ready，category=分类名。"""
        _make_real_input(tmp_path / "cases_real", "增量合并", "dwb_x")
        _make_deliver(tmp_path, "dwb_x")
        monkeypatch.setattr(menu, "DELIVER_BASE", tmp_path)
        monkeypatch.setattr(menu, "CASES_REAL_DIR", tmp_path / "cases_real")
        cases = menu._discover_real_cases()
        assert len(cases) == 1
        c = cases[0]
        assert c.category == "增量合并"
        assert c.input_dir is not None
        assert "✓输入" in c.status_tag

    def test_has_checks_flag(self, tmp_path, monkeypatch):
        _make_real_input(tmp_path / "cases_real", "多源去重", "dwb_x", with_checks=True)
        _make_deliver(tmp_path, "dwb_x")
        monkeypatch.setattr(menu, "DELIVER_BASE", tmp_path)
        monkeypatch.setattr(menu, "CASES_REAL_DIR", tmp_path / "cases_real")
        cases = menu._discover_real_cases()
        assert cases[0].has_checks is True
        assert "✓要点" in cases[0].status_tag

    def test_asset_moved_to_uncategorized_still_found(self, tmp_path, monkeypatch):
        """deliver_only 案例后续被补输入到 cases_real/未分类/{资产}/ 也能发现。"""
        _make_real_input(tmp_path / "cases_real", "未分类", "dwb_x")
        _make_deliver(tmp_path, "dwb_x")
        monkeypatch.setattr(menu, "DELIVER_BASE", tmp_path)
        monkeypatch.setattr(menu, "CASES_REAL_DIR", tmp_path / "cases_real")
        cases = menu._discover_real_cases()
        assert len(cases) == 1
        assert cases[0].category == "未分类"

    def test_placed_without_mapping_carries_category(self, tmp_path, monkeypatch):
        """目录在分类下但没 mapping（seed 后 mv 过去）→ category=分类名，✗输入。

        覆盖"目录位置决定 category，mapping 只决定 ✓输入 标记"的修复点。
        """
        # 只建目录，不建 mapping.xlsx（模拟 seed 后 mv 到分类）
        (tmp_path / "cases_real" / "增量合并" / "dwb_x").mkdir(parents=True)
        _make_deliver(tmp_path, "dwb_x")
        monkeypatch.setattr(menu, "DELIVER_BASE", tmp_path)
        monkeypatch.setattr(menu, "CASES_REAL_DIR", tmp_path / "cases_real")
        cases = menu._discover_real_cases()
        assert len(cases) == 1
        c = cases[0]
        assert c.category == "增量合并"  # 目录位置决定分类
        assert c.input_dir is None  # 没 mapping → ✗输入
        assert "✗输入" in c.status_tag

    def test_empty_when_neither(self, tmp_path, monkeypatch):
        monkeypatch.setattr(menu, "DELIVER_BASE", tmp_path)
        monkeypatch.setattr(menu, "CASES_REAL_DIR", tmp_path / "cases_real")
        assert menu._discover_real_cases() == []


class TestResolveCaseDir:
    def test_one_level_exact_match(self, tmp_path):
        """一级精确匹配（假设案例 cases/{资产}）。"""
        d = tmp_path / "002_dwb_x"
        d.mkdir()
        assert seed._resolve_case_dir("002_dwb_x", tmp_path) == d

    def test_numeric_prefix_match(self, tmp_path):
        """数字前缀（002 → 002_dwb_xxx，假设案例）。"""
        d = tmp_path / "002_dwb_trade_order_d"
        d.mkdir()
        assert seed._resolve_case_dir("002", tmp_path) == d

    def test_two_level_category_match(self, tmp_path):
        """二级分类匹配 cases_real/{分类}/{资产}。"""
        asset = tmp_path / "增量合并" / "dwb_x"
        asset.mkdir(parents=True)
        assert seed._resolve_case_dir("dwb_x", tmp_path) == asset

    def test_fallback_to_deliver_builds_uncategorized(self, tmp_path, monkeypatch):
        """10_project_deliver 有产出 + cases_real 无 → 建 cases_real/未分类/{资产} 占位。"""
        deliver_base = tmp_path / "deliver"
        _make_deliver(deliver_base, "dwb_x")
        cases_real = tmp_path / "cases_real"
        cases_real.mkdir()
        monkeypatch.setattr(seed, "DELIVER_BASE", deliver_base)
        monkeypatch.setattr(seed, "CASES_REAL_DIR", cases_real)
        result = seed._resolve_case_dir("dwb_x", cases_real)
        assert result == cases_real / "未分类" / "dwb_x"
        assert result.exists()

    def test_none_when_truly_absent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(seed, "DELIVER_BASE", tmp_path / "nodir")
        monkeypatch.setattr(seed, "CASES_REAL_DIR", tmp_path / "cases_real")
        assert seed._resolve_case_dir("nope", tmp_path) is None


class TestSeedCaseDeliverNone:
    """回归：三层下找不到产出时 seed 不得崩溃（原 None / "ts.json" 报错）。"""

    def test_returns_error_string_not_crash(self, tmp_path, monkeypatch):
        import seed as seed_mod

        monkeypatch.setattr(seed_mod, "DELIVER_BASE", tmp_path)  # 无任何产出
        case = tmp_path / "cases_real" / "分类" / "dwb_x"
        case.mkdir(parents=True)
        draft = seed_mod.seed_case(case)
        assert draft.startswith("# 错误")
        assert "未找到" in draft and "--from" in draft

    def test_from_override_seeds_flat_deliver(self, tmp_path, monkeypatch):
        """--from 指向任意产出目录（如旧平铺）可直接抽草稿。"""
        import json as j
        import seed as seed_mod

        monkeypatch.setattr(seed_mod, "DELIVER_BASE", tmp_path)  # 三层扫描必空
        deliver = tmp_path / "old_flat" / "dwb_x" / "ddlc_design_dev"
        (deliver / "_internal").mkdir(parents=True)
        (deliver / "etl").mkdir()
        (deliver / "ts.json").write_text(j.dumps({
            "design": {"business_key": ["shop_id"]},
            "rules": {"R0001": {"load_mode": "truncate_table"}},
        }), encoding="utf-8")
        (deliver / "etl" / "R0001.sql").write_text(
            "SELECT a.shop_id AS shop_id FROM ods.t a", encoding="utf-8")
        (deliver / "_internal" / "design_decisions.yaml").write_text(
            "rules:\n- rule_code: R0001\n  field_targets: [shop_id]\n", encoding="utf-8")

        case = tmp_path / "cases_real" / "分类" / "dwb_x"
        case.mkdir(parents=True)
        draft = seed_mod.seed_case(case, deliver_override=deliver)
        assert "business_key" in draft and "R0001" in draft
