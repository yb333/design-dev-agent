# -*- coding: utf-8 -*-
"""explore 设计期锚点（--rs）测试——循环依赖破解回归。

实证（2026-09-03）：explore 数据源锚点曾是 --ts ts.json，但设计期（第4层关联安全）
调 explore 时 ts.json 还没组装——传 --ts 文件不存在、不传退化为按源表 schema 选源
（dim 等不在 db 配置必连不上），designer 被逼去找替代通道（DB MCP——数据源/权限
无关必得错误结论）。--rs 读 rs_input.json 的 meta.target.f_table.schema（设计期
一直在，与 ts 同源同事实）。
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "skills" / "dws-design" / "scripts"))

from explore import read_target_schema_from_rs  # noqa: E402


def _rs(tmp_path, schema="dws"):
    (tmp_path / "rs_input.json").write_text(json.dumps(
        {"meta": {"target": {"f_table": {"schema": schema, "table": "dwb_x_f"}}}}),
        encoding="utf-8")
    return tmp_path / "rs_input.json"


class TestRsAnchor:
    def test_reads_target_schema_from_rs(self, tmp_path):
        assert read_target_schema_from_rs(str(_rs(tmp_path, "dws_tmp"))) == "dws_tmp"

    def test_missing_meta_returns_empty_not_raise(self, tmp_path):
        (tmp_path / "rs_input.json").write_text("{}", encoding="utf-8")
        assert read_target_schema_from_rs(str(tmp_path / "rs_input.json")) == ""

    def test_cli_rs_anchor_beats_schema_fallback(self, tmp_path, monkeypatch, capsys):
        """CLI：--rs 提供目标 schema（不再退化到源表 schema 选源）。fake executor
        记录 create_executor_for_schema 收到的 schema——应是 rs 的目标 schema（dws）
        而非被查表的 schema（dim）。"""
        import explore
        import dws_db
        got = []
        monkeypatch.setattr(dws_db, "create_executor_for_schema",
                            lambda schema, role="etl": got.append(schema) or _FakeEx())
        rs = _rs(tmp_path, "dws")
        explore.main_args = None  # 防意外
        import sys as _sys
        _sys.argv = ["explore.py", "--rs", str(rs), "--check-join-key",
                     "--schema", "dim", "--table", "dim_cust", "--key", "cust_code"]
        try:
            explore.main()
        finally:
            _sys.argv = ["explore.py"]
        assert got == ["dws"]          # 目标 schema 选源（部署事实：有全部源表权限）
        out = capsys.readouterr().out
        assert "唯一" in out or "检查" in out


class _FakeEx:
    def test_connection(self):
        return True

    def execute(self, sql):
        class _R:
            success = True
            rows = [{"cnt": 10, "distinct_cnt": 10}]
        return _R()

    def close(self):
        pass


class TestCompositeKey:
    """复合键支持（2026-09-03 内网实测：多字段关联条件此前查不了）。"""

    def test_join_key_sql_composite(self):
        from explore import build_join_key_sql
        sql = build_join_key_sql("dim", "t", "tenant_id, order_no", "is_current = 1")
        assert "COUNT(DISTINCT (tenant_id, order_no))" in sql
        assert "COUNT(1)" in sql and "count(*)" not in sql

    def test_overlap_sql_composite_row_text(self):
        from explore import build_overlap_sample_sql
        # 复合键行构造器整体转 text（单列输出，交集逻辑不变）
        assert "(x, y)::text" in build_overlap_sample_sql("ods", "t1", "x,y")
        assert "k::text" in build_overlap_sample_sql("ods", "t1", "k")

    def test_split_key(self):
        from explore import split_key
        assert split_key("a, b,,c") == ["a", "b", "c"]
        assert split_key("k") == ["k"]
