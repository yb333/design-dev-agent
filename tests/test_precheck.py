import json
import pytest
from precheck import ETLPrechecker, PrecheckResult, FieldStatistics, CompletenessIssue, format_output


# ── ETLPrechecker.analyze with valid mapping ───────────────

class TestETLPrecheckerAnalyzeValid:

    def test_正常mapping_precheck_result不是INCOMPLETE(self, sample_mapping_json):
        prechecker = ETLPrechecker(sample_mapping_json)
        result = prechecker.analyze()
        assert result.precheck_result in ("PASS", "WARNING")
        assert result.precheck_result != "INCOMPLETE"

    def test_正常mapping_field_count(self, sample_mapping_json):
        prechecker = ETLPrechecker(sample_mapping_json)
        result = prechecker.analyze()
        assert result.field_count == 9

    def test_正常mapping_source_table_count(self, sample_mapping_json):
        prechecker = ETLPrechecker(sample_mapping_json)
        result = prechecker.analyze()
        assert result.source_table_count == 3

    def test_正常mapping_completeness_pass(self, sample_mapping_json):
        prechecker = ETLPrechecker(sample_mapping_json)
        result = prechecker.analyze()
        assert result.completeness_pass is True

    def test_正常mapping_field_statistics不为None(self, sample_mapping_json):
        prechecker = ETLPrechecker(sample_mapping_json)
        result = prechecker.analyze()
        assert result.field_statistics is not None


# ── FieldStatistics ────────────────────────────────────────

class TestFieldStatistics:

    def test_total字段数(self, sample_mapping_json):
        prechecker = ETLPrechecker(sample_mapping_json)
        result = prechecker.analyze()
        assert result.field_statistics.total == 9

    def test_direct直取数量(self, sample_mapping_json):
        prechecker = ETLPrechecker(sample_mapping_json)
        result = prechecker.analyze()
        assert result.field_statistics.direct == 8

    def test_processed加工数量(self, sample_mapping_json):
        prechecker = ETLPrechecker(sample_mapping_json)
        result = prechecker.analyze()
        assert result.field_statistics.processed == 1

    def test_with_source_table数量(self, sample_mapping_json):
        prechecker = ETLPrechecker(sample_mapping_json)
        result = prechecker.analyze()
        assert result.field_statistics.with_source_table == 9


# ── Completeness: missing_source_table (MAJOR) ─────────────

class TestCompletenessMissingSourceTable:

    def test_加工字段缺少来源表_报MAJOR(self):
        mapping_data = {
            "source_tables": [
                {"source_table": "src_table", "target_table": "tgt_table"}
            ],
            "field_mappings": [
                {
                    "source_column": "col_a",
                    "mapping_rule": "直取",
                    "target_column": "col_a",
                    "source_table": "src_table"
                },
                {
                    "source_column": "",
                    "mapping_rule": "加工",
                    "mapping_expression": "some_unknown_col + another_unknown_col",
                    "target_column": "computed_col",
                    "source_table": ""
                }
            ],
            "design_pattern": "single_source"
        }
        prechecker = ETLPrechecker(mapping_data)
        result = prechecker.analyze()
        major_issues = [i for i in result.completeness_issues if i.severity == "MAJOR"]
        assert any("missing_source_table" in i.issue_type for i in major_issues)


# ── Completeness: pure calculation (no MAJOR) ──────────────

class TestCompletenessPureCalculation:

    def test_纯计算字段_不报MAJOR(self):
        mapping_data = {
            "source_tables": [
                {"source_table": "src_table", "target_table": "tgt_table"}
            ],
            "field_mappings": [
                {
                    "source_column": "price",
                    "mapping_rule": "直取",
                    "target_column": "price",
                    "source_table": "src_table"
                },
                {
                    "source_column": "",
                    "mapping_rule": "加工",
                    "mapping_expression": "price * 1.1",
                    "target_column": "adjusted_price",
                    "source_table": ""
                }
            ],
            "design_pattern": "single_source"
        }
        prechecker = ETLPrechecker(mapping_data)
        result = prechecker.analyze()
        major_issues = [i for i in result.completeness_issues if i.severity == "MAJOR"]
        has_missing_source = any("missing_source_table" in i.issue_type for i in major_issues)
        assert has_missing_source is False


# ── Completeness: duplicate target fields (CRITICAL) ───────

class TestCompletenessDuplicateTarget:

    def test_重复目标字段_报CRITICAL(self):
        mapping_data = {
            "source_tables": [
                {"source_table": "src_table", "target_table": "tgt_table"}
            ],
            "field_mappings": [
                {
                    "source_column": "a",
                    "mapping_rule": "直取",
                    "target_column": "dup_col",
                    "source_table": "src_table"
                },
                {
                    "source_column": "b",
                    "mapping_rule": "直取",
                    "target_column": "dup_col",
                    "source_table": "src_table"
                }
            ],
            "design_pattern": "single_source"
        }
        prechecker = ETLPrechecker(mapping_data)
        result = prechecker.analyze()
        critical_issues = [i for i in result.completeness_issues if i.severity == "CRITICAL"]
        assert any("duplicate_target_field" in i.issue_type for i in critical_issues)


# ── Completeness: invalid identifiers (CRITICAL) ───────────

class TestCompletenessInvalidIdentifiers:

    def test_目标字段数字开头_报CRITICAL(self):
        mapping_data = {
            "source_tables": [
                {"source_table": "src_table", "target_table": "tgt_table"}
            ],
            "field_mappings": [
                {
                    "source_column": "col_a",
                    "mapping_rule": "直取",
                    "target_column": "123invalid",
                    "source_table": "src_table"
                }
            ],
            "design_pattern": "single_source"
        }
        prechecker = ETLPrechecker(mapping_data)
        result = prechecker.analyze()
        critical_issues = [i for i in result.completeness_issues if i.severity == "CRITICAL"]
        assert any("invalid_target_column_name" in i.issue_type for i in critical_issues)

    def test_目标字段包含横杠_报CRITICAL(self):
        mapping_data = {
            "source_tables": [
                {"source_table": "src_table", "target_table": "tgt_table"}
            ],
            "field_mappings": [
                {
                    "source_column": "col_a",
                    "mapping_rule": "直取",
                    "target_column": "has-space",
                    "source_table": "src_table"
                }
            ],
            "design_pattern": "single_source"
        }
        prechecker = ETLPrechecker(mapping_data)
        result = prechecker.analyze()
        critical_issues = [i for i in result.completeness_issues if i.severity == "CRITICAL"]
        assert any("invalid_target_column_name" in i.issue_type for i in critical_issues)


# ── format_output ──────────────────────────────────────────

class TestFormatOutput:

    def test_json格式_返回有效JSON(self, sample_mapping_json):
        prechecker = ETLPrechecker(sample_mapping_json)
        result = prechecker.analyze()
        output = format_output(result, output_format="json")
        parsed = json.loads(output)
        assert "precheck_result" in parsed
        assert "field_count" in parsed
        assert "source_table_count" in parsed
        assert "completeness_issues" in parsed
        assert "field_statistics" in parsed

    def test_text格式_返回人类可读文本(self, sample_mapping_json):
        prechecker = ETLPrechecker(sample_mapping_json)
        result = prechecker.analyze()
        output = format_output(result, output_format="text")
        assert "ETL" in output or "预检" in output or "字段统计" in output
