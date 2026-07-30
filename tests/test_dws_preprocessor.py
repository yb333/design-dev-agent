"""DWSSQLPreprocessor 单元测试"""

import pytest
from dws_preprocessor import DWSSQLPreprocessor, preprocess_dws_sql, validate_dws_syntax


@pytest.fixture
def preprocessor():
    return DWSSQLPreprocessor()


# ── preprocess ──────────────────────────────────────────


class TestPreprocess:

    def test_预处理_移除DISTRIBUTE_BY_HASH(self, preprocessor):
        sql = "CREATE TABLE t (id INT) DISTRIBUTE BY HASH(id);"
        clean, removed = preprocessor.preprocess(sql)
        assert "DISTRIBUTE" not in clean
        assert "HASH" not in clean
        assert len(removed["distribute_by"]) == 1
        assert "HASH(id)" in removed["distribute_by"][0]

    def test_预处理_移除DISTRIBUTE_BY_REPLICATION(self, preprocessor):
        sql = "CREATE TABLE t (id INT) DISTRIBUTE BY REPLICATION;"
        clean, removed = preprocessor.preprocess(sql)
        assert "DISTRIBUTE" not in clean
        assert len(removed["distribute_by"]) == 1
        assert "REPLICATION" in removed["distribute_by"][0]

    def test_预处理_移除WITH选项(self, preprocessor):
        sql = "CREATE TABLE t (id INT) WITH (ORIENTATION=COLUMN, COMPRESSION=MIDDLE);"
        clean, removed = preprocessor.preprocess(sql)
        assert "ORIENTATION" not in clean
        assert "COMPRESSION" not in clean
        assert len(removed["with_options"]) == 1
        assert "ORIENTATION" in removed["with_options"][0].upper()
        assert "COMPRESSION" in removed["with_options"][0].upper()

    def test_预处理_同时移除DISTRIBUTE_BY和WITH(self, preprocessor):
        sql = (
            "CREATE TABLE t (id INT)\n"
            "WITH (ORIENTATION=COLUMN, COMPRESSION=LOW)\n"
            "DISTRIBUTE BY HASH(id);"
        )
        clean, removed = preprocessor.preprocess(sql)
        assert "DISTRIBUTE" not in clean
        assert "ORIENTATION" not in clean
        assert len(removed["distribute_by"]) == 1
        assert len(removed["with_options"]) == 1

    def test_预处理_无DWS语法_原样返回(self, preprocessor):
        sql = "CREATE TABLE t (id INT, name VARCHAR(100));"
        clean, removed = preprocessor.preprocess(sql)
        assert clean == sql
        assert removed["distribute_by"] == []
        assert removed["with_options"] == []

    def test_预处理_多个DISTRIBUTE_BY(self, preprocessor):
        sql = (
            "CREATE TABLE t1 (id INT) DISTRIBUTE BY HASH(id);\n"
            "CREATE TABLE t2 (id INT) DISTRIBUTE BY HASH(name);"
        )
        clean, removed = preprocessor.preprocess(sql)
        assert "DISTRIBUTE" not in clean
        assert len(removed["distribute_by"]) == 2

    def test_预处理_大小写不敏感(self, preprocessor):
        sql = "CREATE TABLE t (id INT) distribute by hash(id);"
        clean, removed = preprocessor.preprocess(sql)
        assert "distribute" not in clean.lower()
        assert len(removed["distribute_by"]) == 1

    def test_预处理_大小写混合(self, preprocessor):
        sql = "CREATE TABLE t (id INT) Distribute By Hash(id);"
        clean, removed = preprocessor.preprocess(sql)
        assert len(removed["distribute_by"]) == 1

    def test_预处理_removed_dict结构正确(self, preprocessor):
        sql = "CREATE TABLE t (id INT) DISTRIBUTE BY HASH(id);"
        _, removed = preprocessor.preprocess(sql)
        assert set(removed.keys()) == {"distribute_by", "with_options"}

    def test_预处理_ROUNDROBIN(self, preprocessor):
        sql = "CREATE TABLE t (id INT) DISTRIBUTE BY ROUNDROBIN;"
        clean, removed = preprocessor.preprocess(sql)
        assert "DISTRIBUTE" not in clean
        assert len(removed["distribute_by"]) == 1
        assert "ROUNDROBIN" in removed["distribute_by"][0].upper()

    def test_预处理_多余空行被清理(self, preprocessor):
        sql = (
            "CREATE TABLE t (id INT)\n"
            "WITH (ORIENTATION=COLUMN)\n"
            "DISTRIBUTE BY HASH(id);"
        )
        clean, _ = preprocessor.preprocess(sql)
        assert "\n\n\n" not in clean


# ── validate_dws_syntax ─────────────────────────────────


class TestValidateDWSSyntax:

    def test_验证_HASH有列名_返回valid(self, preprocessor):
        sql = "CREATE TABLE t (id INT) DISTRIBUTE BY HASH(id);"
        result = preprocessor.validate_dws_syntax(sql)
        assert result["valid"] is True
        assert result["distribute_by"] is not None
        assert "HASH" in result["distribute_by"]

    def test_验证_HASH带WITH选项_提取orientation和compression(self, preprocessor):
        sql = (
            "CREATE TABLE t (id INT)\n"
            "WITH (ORIENTATION=COLUMN, COMPRESSION=MIDDLE)\n"
            "DISTRIBUTE BY HASH(id);"
        )
        result = preprocessor.validate_dws_syntax(sql)
        assert result["valid"] is True
        assert result["orientation"] == "COLUMN"
        assert result["compression"] == "MIDDLE"

    def test_验证_无DISTRIBUTE_BY_distribute_by为None(self, preprocessor):
        sql = "CREATE TABLE t (id INT);"
        result = preprocessor.validate_dws_syntax(sql)
        assert result["valid"] is True
        assert result["distribute_by"] is None

    def test_验证_HASH空列名_valid为False(self, preprocessor):
        sql = "CREATE TABLE t (id INT) DISTRIBUTE BY HASH( );"
        result = preprocessor.validate_dws_syntax(sql)
        assert result["valid"] is False
        assert any("缺少列名" in e for e in result["errors"])

    def test_验证_返回结构包含所有字段(self, preprocessor):
        sql = "CREATE TABLE t (id INT);"
        result = preprocessor.validate_dws_syntax(sql)
        expected_keys = {"valid", "errors", "warnings", "distribute_by", "orientation", "compression"}
        assert set(result.keys()) == expected_keys

    def test_验证_ONLY_ORIENTATION无COMPRESSION(self, preprocessor):
        sql = "CREATE TABLE t (id INT) WITH (ORIENTATION=ROW);"
        result = preprocessor.validate_dws_syntax(sql)
        assert result["orientation"] == "ROW"
        assert result["compression"] is None

    def test_验证_REPLICATION无列名_不报错(self, preprocessor):
        sql = "CREATE TABLE t (id INT) DISTRIBUTE BY REPLICATION;"
        result = preprocessor.validate_dws_syntax(sql)
        assert result["valid"] is True
        assert "REPLICATION" in result["distribute_by"]


# ── 模块级便捷函数 ─────────────────────────────────────


class TestModuleHelpers:

    def test_preprocess_dws_sql与实例方法结果一致(self):
        sql = "CREATE TABLE t (id INT) DISTRIBUTE BY HASH(id);"
        clean1, removed1 = preprocess_dws_sql(sql)
        clean2, removed2 = DWSSQLPreprocessor().preprocess(sql)
        assert clean1 == clean2
        assert removed1 == removed2

    def test_validate_dws_sql模块函数与实例方法结果一致(self):
        sql = "CREATE TABLE t (id INT) DISTRIBUTE BY HASH(id);"
        result1 = validate_dws_syntax(sql)
        result2 = DWSSQLPreprocessor().validate_dws_syntax(sql)
        assert result1 == result2
