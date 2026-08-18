"""checks.yaml 键名白名单校验测试（typo 静默失效防护）。"""

import sys
from pathlib import Path

import pytest

_EVAL_SUITE = Path(__file__).resolve().parent.parent / "eval-suite"
_V2_DIR = _EVAL_SUITE / "v2"
for p in (str(_EVAL_SUITE), str(_V2_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from checks_schema import ChecksConfig, load_checks


def _write(tmp_path, content):
    f = tmp_path / "checks.yaml"
    f.write_text(content, encoding="utf-8")
    return f


class TestSchemaValidation:
    def test_typo_rejected_loud(self, tmp_path):
        f = _write(tmp_path, "design:\n  business_keyy: [id]\n")
        with pytest.raises(ValueError, match="未知键.*business_keyy"):
            load_checks(f)

    def test_code_typo_rejected(self, tmp_path):
        f = _write(tmp_path, "code:\n  R0001:\n    fields_requred: [a]\n")
        with pytest.raises(ValueError, match="code.R0001"):
            load_checks(f)

    def test_valid_file_loads(self, tmp_path):
        f = _write(tmp_path,
                   "case:\n  name: t\n  rules_expected: [R0001]\n"
                   "design:\n  business_key: [id]\n  load_mode_expected: {R0001: merge_into}\n"
                   "code:\n  R0001:\n    fields_required: [a]\n    where_must_contain_del_flag: false\n")
        cfg = load_checks(f)
        assert cfg.rules_expected == ["R0001"]
        assert cfg.design["load_mode_expected"] == {"R0001": "merge_into"}

    def test_missing_file_returns_empty(self, tmp_path):
        cfg = load_checks(tmp_path / "nope.yaml")
        assert cfg == ChecksConfig()

    def test_dead_fields_removed(self):
        """死码已删：不再有 target_table/data_diff/style 字段。"""
        c = ChecksConfig()
        assert not hasattr(c, "target_table")
        assert not hasattr(c, "data_diff")
        assert not hasattr(c, "style")

    def test_case_section_unknown_key(self, tmp_path):
        f = _write(tmp_path, "case:\n  name: t\n  target_table: dwb_x\n")
        with pytest.raises(ValueError, match="case 段未知键.*target_table"):
            load_checks(f)
