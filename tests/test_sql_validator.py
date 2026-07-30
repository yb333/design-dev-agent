import pytest
from sql_validator import SQLValidator


@pytest.fixture
def validator():
    return SQLValidator()


# ── check_bracket_balance ──────────────────────────────────

class TestCheckBracketBalance:

    def test_括号平衡_正常SQL(self, validator):
        content = "SELECT (a + b) FROM t WHERE c IN (1, 2)"
        passed, msg = validator.check_bracket_balance(content, "test.sql")
        assert passed is True
        assert msg == ""

    def test_括号缺失右括号(self, validator):
        content = "SELECT (a + b FROM t"
        passed, msg = validator.check_bracket_balance(content, "test.sql")
        assert passed is False
        assert "未闭合" in msg

    def test_括号缺失左括号_多余右括号(self, validator):
        content = "SELECT a + b) FROM t"
        passed, msg = validator.check_bracket_balance(content, "test.sql")
        assert passed is False

    def test_嵌套括号平衡(self, validator):
        content = "SELECT COALESCE(AVG(LENGTH(name)), 0) FROM t"
        passed, msg = validator.check_bracket_balance(content, "test.sql")
        assert passed is True
        assert msg == ""

    def test_方括号平衡(self, validator):
        content = "SELECT arr[1], arr[2] FROM t"
        passed, msg = validator.check_bracket_balance(content, "test.sql")
        assert passed is True
        assert msg == ""


# ── check_quote_balance ────────────────────────────────────

class TestCheckQuoteBalance:

    def test_单引号平衡(self, validator):
        content = "SELECT 'hello' FROM t"
        passed, msg = validator.check_quote_balance(content, "test.sql")
        assert passed is True
        assert msg == ""

    def test_单引号未闭合(self, validator):
        content = "SELECT 'hello FROM t"
        passed, msg = validator.check_quote_balance(content, "test.sql")
        assert passed is False
        assert "单引号" in msg

    def test_双引号平衡(self, validator):
        content = 'SELECT "hello" FROM t'
        passed, msg = validator.check_quote_balance(content, "test.sql")
        assert passed is True
        assert msg == ""

    def test_引号中包含撇号_正确处理(self, validator):
        content = "SELECT 'it''s fine' FROM t"
        passed, msg = validator.check_quote_balance(content, "test.sql")
        assert passed is True


# ── check_insert_field_match ───────────────────────────────

class TestCheckInsertFieldMatch:

    def test_字段数量匹配(self, validator):
        content = "INSERT INTO t (a, b, c) SELECT x, y, z FROM s"
        passed, msg = validator.check_insert_field_match(content, "test.sql")
        assert passed is True
        assert msg == ""

    def test_插入字段多于选择字段(self, validator):
        content = "INSERT INTO t (a, b, c) SELECT x, y FROM s"
        passed, msg = validator.check_insert_field_match(content, "test.sql")
        assert passed is False
        assert "不匹配" in msg

    def test_选择字段多于插入字段(self, validator):
        content = "INSERT INTO t (a, b) SELECT x, y, z FROM s"
        passed, msg = validator.check_insert_field_match(content, "test.sql")
        assert passed is False
        assert "不匹配" in msg

    def test_无INSERT语句_返回通过(self, validator):
        content = "SELECT a, b FROM t"
        passed, msg = validator.check_insert_field_match(content, "test.sql")
        assert passed is True
        assert msg == ""


# ── check_case_when_else ───────────────────────────────────

class TestCheckCaseWhenElse:

    def test_有ELSE分支(self, validator):
        content = "SELECT CASE WHEN x = 1 THEN 'a' ELSE 'b' END FROM t"
        passed, msg = validator.check_case_when_else(content, "test.sql")
        assert passed is True
        assert msg == ""

    def test_缺少ELSE分支(self, validator):
        content = "SELECT CASE WHEN x = 1 THEN 'a' END FROM t"
        passed, msg = validator.check_case_when_else(content, "test.sql")
        assert passed is False
        assert "缺少ELSE" in msg

    def test_多个CASE_部分缺少ELSE(self, validator):
        content = "SELECT CASE WHEN a = 1 THEN 'x' ELSE 'y' END, CASE WHEN b = 2 THEN 'z' END FROM t"
        passed, msg = validator.check_case_when_else(content, "test.sql")
        assert passed is False
        assert "缺少ELSE" in msg


# ── check_join_on_condition ────────────────────────────────

class TestCheckJoinOnCondition:

    def test_JOIN有ON条件(self, validator):
        content = "SELECT * FROM t1 LEFT JOIN t2 ON t1.id = t2.id"
        passed, msg = validator.check_join_on_condition(content, "test.sql")
        assert passed is True
        assert msg == ""

    def test_JOIN缺少ON条件(self, validator):
        content = "SELECT * FROM t1 LEFT JOIN t2 WHERE t1.id = 1"
        passed, msg = validator.check_join_on_condition(content, "test.sql")
        assert passed is False
        assert "缺少ON" in msg

    def test_多个JOIN_一个缺少ON(self, validator):
        content = "SELECT * FROM t1 LEFT JOIN t2 ON t1.id = t2.id INNER JOIN t3 WHERE t1.x = 1"
        passed, msg = validator.check_join_on_condition(content, "test.sql")
        assert passed is False
        assert "缺少ON" in msg


# ── check_select_star ──────────────────────────────────────

class TestCheckSelectStar:

    def test_使用SELECT_STAR(self, validator):
        content = "SELECT * FROM t"
        passed, msg = validator.check_select_star(content, "test.sql")
        assert passed is False
        assert "SELECT *" in msg

    def test_指定具体字段(self, validator):
        content = "SELECT a, b, c FROM t"
        passed, msg = validator.check_select_star(content, "test.sql")
        assert passed is True
        assert msg == ""


# ── check_ddl_distributed_syntax ───────────────────────────

class TestCheckDdlDistributedSyntax:

    def test_DISTRIBUTE_BY_HASH拼写不完整(self, validator):
        content = "CREATE TABLE t (a INT) DISTRIBUTE BY HASH(a)"
        passed, msg = validator.check_ddl_distributed_syntax(content, "test.sql")
        assert passed is False
        assert "DISTRIBUTED BY" in msg

    def test_DISTRIBUTED_BY_HASH合法(self, validator):
        content = "CREATE TABLE t (a INT) DISTRIBUTED BY HASH(a)"
        passed, msg = validator.check_ddl_distributed_syntax(content, "test.sql")
        assert passed is True
        assert msg == ""

    def test_DISTRIBUTED_BY_REPLICATION合法(self, validator):
        content = "CREATE TABLE t (a INT) DISTRIBUTED BY REPLICATION"
        passed, msg = validator.check_ddl_distributed_syntax(content, "test.sql")
        assert passed is True
        assert msg == ""

    def test_DISTRIBUTE_BY_HASH缺失D(self, validator):
        content = "CREATE TABLE t (a INT) DISTRIBUTE BY HASH(a)"
        passed, msg = validator.check_ddl_distributed_syntax(content, "test.sql")
        assert passed is False
        assert "DISTRIBUTED BY" in msg

    def test_分布键未指定方式(self, validator):
        content = "CREATE TABLE t (a INT) DISTRIBUTED BY a"
        passed, msg = validator.check_ddl_distributed_syntax(content, "test.sql")
        assert passed is False
        assert "HASH" in msg


# ── check_duplicate_fields_ddl ─────────────────────────────

class TestCheckDuplicateFieldsDdl:

    def test_无重复字段(self, validator):
        content = "CREATE TABLE t (\n    a INT,\n    b VARCHAR(10),\n    c BIGINT\n)"
        passed, msg = validator.check_duplicate_fields_ddl(content, "test.sql")
        assert passed is True

    def test_有重复字段(self, validator):
        content = "CREATE TABLE t (\n    a INT,\n    b VARCHAR(10),\n    a BIGINT\n)"
        passed, msg = validator.check_duplicate_fields_ddl(content, "test.sql")
        assert passed is False
        assert "重复字段" in msg


# ── check_audit_field_types ────────────────────────────────

class TestCheckAuditFieldTypes:

    def test_审计字段类型正确(self, validator):
        content = "CREATE TABLE t (\n    crt_cycle_id BIGINT,\n    last_upd_cycle_id BIGINT,\n    dw_last_update_date TIMESTAMP(0) WITHOUT TIME ZONE\n)"
        passed, msg = validator.check_audit_field_types(content, "test.sql")
        assert passed is True
        assert msg == ""

    def test_审计字段类型错误(self, validator):
        content = "CREATE TABLE t (\n    crt_cycle_id INT,\n    last_upd_cycle_id VARCHAR(10)\n)"
        passed, msg = validator.check_audit_field_types(content, "test.sql")
        assert passed is False
        assert "crt_cycle_id" in msg


# ── validate_file ──────────────────────────────────────────

class TestValidateFile:

    def test_验证DDL文件_返回正确结构(self, validator, tmp_path):
        ddl_content = "CREATE TABLE t (\n    a INT,\n    b VARCHAR(10)\n) DISTRIBUTE BY HASH(a);"
        f = tmp_path / "test_ddl.sql"
        f.write_text(ddl_content, encoding="utf-8")
        result = validator.validate_file(str(f), "DDL")
        assert "file" in result
        assert "type" in result
        assert result["type"] == "DDL"
        assert "checks" in result
        assert len(result["checks"]) > 0

    def test_验证ETL文件_返回正确结构(self, validator, tmp_path):
        etl_content = "INSERT INTO t (a, b) SELECT x, y FROM s LEFT JOIN s2 ON s.id = s2.id;"
        f = tmp_path / "test_etl.sql"
        f.write_text(etl_content, encoding="utf-8")
        result = validator.validate_file(str(f), "ETL")
        assert result["type"] == "ETL"
        assert "checks" in result
        assert len(result["checks"]) > 0

    def test_失败项记入checks(self, validator, tmp_path):
        bad_content = "INSERT INTO t (a, b) SELECT x FROM s;"
        f = tmp_path / "bad.sql"
        f.write_text(bad_content, encoding="utf-8")
        result = validator.validate_file(str(f), "ETL")
        failed = [c for c in result["checks"] if not c["passed"]]
        assert len(failed) > 0

    def test_使用fixture_DDL文件验证(self, validator, sample_ddl_sql, tmp_path):
        f = tmp_path / "sample.sql"
        f.write_text(sample_ddl_sql, encoding="utf-8")
        result = validator.validate_file(str(f), "DDL")
        assert result["file"] == "sample.sql"
        assert result["type"] == "DDL"

    def test_使用fixture_ETL文件验证(self, validator, sample_etl_sql, tmp_path):
        f = tmp_path / "sample.sql"
        f.write_text(sample_etl_sql, encoding="utf-8")
        result = validator.validate_file(str(f), "ETL")
        assert result["file"] == "sample.sql"
        assert result["type"] == "ETL"
