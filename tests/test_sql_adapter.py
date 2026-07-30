"""sql_adapter 单元测试"""

import os
import re
from datetime import datetime
import pytest
from sql_adapter import adapt_for_postgresql, adapt_file, adapt_directory


# ── adapt_for_postgresql ───────────────────────────────


class TestAdaptForPostgresql:

    def test_替换P_CYCLE_ID占位符(self):
        sql = "INSERT INTO t VALUES ('${P_CYCLE_ID}');"
        adapted, changes = adapt_for_postgresql(sql, cycle_id="test_001")
        assert "${P_CYCLE_ID}" not in adapted
        assert "test_001" in adapted
        assert any("P_CYCLE_ID" in c for c in changes)

    def test_替换P_CYCLE_ID自动生成格式(self):
        sql = "INSERT INTO t VALUES ('${P_CYCLE_ID}');"
        adapted, changes = adapt_for_postgresql(sql)
        assert re.search(r"test_\d{8}_\d{6}", adapted)
        assert len(changes) == 1

    def test_移除DISTRIBUTE_BY_HASH(self):
        sql = "CREATE TABLE t (id INT) DISTRIBUTE BY HASH(id);"
        adapted, changes = adapt_for_postgresql(sql)
        assert "DISTRIBUTE" not in adapted
        assert any("DISTRIBUTE" in c for c in changes)

    def test_移除DISTRIBUTE_BY_REPLICATION(self):
        sql = "CREATE TABLE t (id INT) DISTRIBUTE BY REPLICATION;"
        adapted, changes = adapt_for_postgresql(sql)
        assert "DISTRIBUTE" not in adapted
        assert any("DISTRIBUTE" in c for c in changes)

    def test_移除WITH选项(self):
        sql = "CREATE TABLE t (id INT) WITH (ORIENTATION=COLUMN, COMPRESSION=MIDDLE);"
        adapted, changes = adapt_for_postgresql(sql)
        assert "ORIENTATION" not in adapted
        assert "COMPRESSION" not in adapted
        assert any("WITH" in c.upper() or "ORIENTATION" in c for c in changes)

    def test_三种特性同时处理(self):
        sql = (
            "INSERT INTO t VALUES ('${P_CYCLE_ID}');\n"
            "CREATE TABLE t (id INT)\n"
            "WITH (ORIENTATION=COLUMN, COMPRESSION=LOW)\n"
            "DISTRIBUTE BY HASH(id);"
        )
        adapted, changes = adapt_for_postgresql(sql, cycle_id="test_001")
        assert "${P_CYCLE_ID}" not in adapted
        assert "DISTRIBUTE" not in adapted
        assert "ORIENTATION" not in adapted
        assert len(changes) == 3

    def test_纯SQL无DWS特性_原样返回(self):
        sql = "CREATE TABLE t (id INT, name VARCHAR(100));"
        adapted, changes = adapt_for_postgresql(sql)
        assert adapted.strip() == sql
        assert changes == []

    def test_返回元组结构(self):
        sql = "SELECT 1;"
        result = adapt_for_postgresql(sql)
        assert isinstance(result, tuple)
        assert len(result) == 2
        adapted, changes = result
        assert isinstance(adapted, str)
        assert isinstance(changes, list)

    def test_多余空行被清理(self):
        sql = (
            "CREATE TABLE t (id INT)\n"
            "WITH (ORIENTATION=COLUMN)\n"
            "DISTRIBUTE BY HASH(id);"
        )
        adapted, _ = adapt_for_postgresql(sql)
        assert "\n\n\n" not in adapted

    def test_DISTRIBUTE_BY大小写不敏感(self):
        sql = "CREATE TABLE t (id INT) distribute by hash(id);"
        adapted, changes = adapt_for_postgresql(sql)
        assert "distribute" not in adapted.lower()
        assert any("DISTRIBUTE" in c for c in changes)


# ── adapt_file ──────────────────────────────────────────


class TestAdaptFile:

    def test_postgresql模式_调用adapt_for_postgresql(self, tmp_path):
        input_file = tmp_path / "input" / "test.sql"
        input_file.parent.mkdir()
        input_file.write_text(
            "CREATE TABLE t (id INT) DISTRIBUTE BY HASH(id);",
            encoding="utf-8",
        )
        output_file = tmp_path / "output" / "test.sql"

        success, changes = adapt_file(str(input_file), str(output_file), target="postgresql")

        assert success is True
        assert len(changes) > 0
        assert output_file.exists()
        content = output_file.read_text(encoding="utf-8")
        assert "DISTRIBUTE" not in content

    def test_dws模式_不移除DISTRIBUTE_BY(self, tmp_path):
        input_file = tmp_path / "input" / "test.sql"
        input_file.parent.mkdir()
        sql = "CREATE TABLE t (id INT) DISTRIBUTE BY HASH(id);"
        input_file.write_text(sql, encoding="utf-8")
        output_file = tmp_path / "output" / "test.sql"

        success, changes = adapt_file(str(input_file), str(output_file), target="dws")

        assert success is True
        content = output_file.read_text(encoding="utf-8")
        assert "DISTRIBUTE" in content
        assert any("DWS" in c for c in changes)

    def test_dws模式_仅替换P_CYCLE_ID(self, tmp_path):
        input_file = tmp_path / "input" / "test.sql"
        input_file.parent.mkdir()
        sql = "INSERT INTO t VALUES ('${P_CYCLE_ID}') DISTRIBUTE BY HASH(id);"
        input_file.write_text(sql, encoding="utf-8")
        output_file = tmp_path / "output" / "test.sql"

        success, _ = adapt_file(str(input_file), str(output_file), target="dws")

        assert success is True
        content = output_file.read_text(encoding="utf-8")
        assert "${P_CYCLE_ID}" not in content
        assert "DISTRIBUTE" in content

    def test_自动创建输出目录(self, tmp_path):
        input_file = tmp_path / "test.sql"
        input_file.write_text("SELECT 1;", encoding="utf-8")
        output_file = tmp_path / "deep" / "nested" / "output.sql"

        success, _ = adapt_file(str(input_file), str(output_file))

        assert success is True
        assert output_file.parent.exists()
        assert output_file.exists()

    def test_返回success和changes(self, tmp_path):
        input_file = tmp_path / "test.sql"
        input_file.write_text("SELECT 1;", encoding="utf-8")
        output_file = tmp_path / "output.sql"

        success, changes = adapt_file(str(input_file), str(output_file))

        assert success is True
        assert isinstance(changes, list)

    def test_输入文件不存在_返回失败(self, tmp_path):
        output_file = tmp_path / "output.sql"
        success, changes = adapt_file("/nonexistent/path.sql", str(output_file))
        assert success is False
        assert any("错误" in c for c in changes)

    def test_cycle_id参数生效(self, tmp_path):
        input_file = tmp_path / "test.sql"
        input_file.write_text(
            "INSERT INTO t VALUES ('${P_CYCLE_ID}');",
            encoding="utf-8",
        )
        output_file = tmp_path / "output.sql"

        adapt_file(str(input_file), str(output_file), cycle_id="my_cycle_123")

        content = output_file.read_text(encoding="utf-8")
        assert "my_cycle_123" in content


# ── adapt_directory ─────────────────────────────────────


class TestAdaptDirectory:

    def test_处理所有SQL文件(self, tmp_path):
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        output_dir = tmp_path / "output"

        (input_dir / "a.sql").write_text(
            "CREATE TABLE t1 (id INT) DISTRIBUTE BY HASH(id);", encoding="utf-8"
        )
        (input_dir / "b.sql").write_text(
            "CREATE TABLE t2 (id INT) DISTRIBUTE BY REPLICATION;", encoding="utf-8"
        )
        (input_dir / "c.sql").write_text("SELECT 1;", encoding="utf-8")

        results = adapt_directory(str(input_dir), str(output_dir))

        assert len(results) == 3
        filenames = [r[0] for r in results]
        assert "a.sql" in filenames
        assert "b.sql" in filenames
        assert "c.sql" in filenames
        assert all(success for _, success, _ in results)

    def test_返回元组结构_filename_success_changes(self, tmp_path):
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        output_dir = tmp_path / "output"
        (input_dir / "test.sql").write_text("SELECT 1;", encoding="utf-8")

        results = adapt_directory(str(input_dir), str(output_dir))

        assert len(results) == 1
        filename, success, changes = results[0]
        assert filename == "test.sql"
        assert isinstance(success, bool)
        assert isinstance(changes, list)

    def test_空目录返回空列表(self, tmp_path):
        input_dir = tmp_path / "empty"
        input_dir.mkdir()
        output_dir = tmp_path / "output"

        results = adapt_directory(str(input_dir), str(output_dir))

        assert results == []

    def test_只处理sql文件(self, tmp_path):
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        output_dir = tmp_path / "output"

        (input_dir / "test.sql").write_text("SELECT 1;", encoding="utf-8")
        (input_dir / "readme.txt").write_text("not sql", encoding="utf-8")
        (input_dir / "config.json").write_text("{}", encoding="utf-8")

        results = adapt_directory(str(input_dir), str(output_dir))

        assert len(results) == 1
        assert results[0][0] == "test.sql"

    def test_输出文件内容正确(self, tmp_path):
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        output_dir = tmp_path / "output"
        (input_dir / "test.sql").write_text(
            "CREATE TABLE t (id INT) DISTRIBUTE BY HASH(id);", encoding="utf-8"
        )

        adapt_directory(str(input_dir), str(output_dir))

        output_content = (output_dir / "test.sql").read_text(encoding="utf-8")
        assert "DISTRIBUTE" not in output_content
        assert "CREATE TABLE" in output_content

    def test_dws模式批量处理(self, tmp_path):
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        output_dir = tmp_path / "output"
        (input_dir / "test.sql").write_text(
            "CREATE TABLE t (id INT) DISTRIBUTE BY HASH(id);", encoding="utf-8"
        )

        results = adapt_directory(str(input_dir), str(output_dir), target="dws")

        assert len(results) == 1
        output_content = (output_dir / "test.sql").read_text(encoding="utf-8")
        assert "DISTRIBUTE" in output_content
