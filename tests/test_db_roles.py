"""
dws_db 的 roles 账号模型测试。

验证按操作类型（admin/etl）选账号的逻辑：
- load_db_sources 正确解析 roles 段
- DataSource.roles 结构正确
- create_executor 传 role 后，_get_conn_params 用对应 role 的账号

不连真库——用临时 db-sources.json 文件 + 检查连接参数。
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch

# conftest 已把 design-dev-shared/references 加入 sys.path
import dws_db
from dws_db import load_db_sources, create_executor, create_executor_for_schema


# ============================================================
# 辅助：写临时 db-sources.json
# ============================================================

def _write_config(tmp_path: Path, sources: dict, schema_mapping=None, default="dws-dev"):
    """写一份临时 db-sources.json，返回路径。"""
    config = {
        "default": default,
        "sources": sources,
        "security": {"allowWriteOperations": True, "maxRows": 100, "timeout": 0},
    }
    if schema_mapping:
        config["schema_mapping"] = schema_mapping
    p = tmp_path / "db-sources.json"
    p.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    return str(p)


def _two_role_source():
    """构造一个有 admin/etl 两个 role 的数据源配置。"""
    return {
        "type": "postgresql",
        "host": "db.example.com",
        "port": 5432,
        "database": "testdb",
        "roles": {
            "admin": {"user": "admin_user", "password": "${ADMIN_PW}"},
            "etl": {"user": "etl_user", "password": "${ETL_PW}"},
        },
    }


# ============================================================
# 测试用例
# ============================================================

class TestRolesParsing:
    """roles 配置解析测试。"""

    def test_roles_parsed_correctly(self, tmp_path, monkeypatch):
        """load_db_sources 正确解析 roles 段（admin/etl 各一组 user/password）。"""
        monkeypatch.setenv("ADMIN_PW", "secret_admin")
        monkeypatch.setenv("ETL_PW", "secret_etl")
        config_path = _write_config(tmp_path, {"dws-dev": _two_role_source()})

        sources, default, security, schema_mapping = load_db_sources(config_path)

        ds = sources["dws-dev"]
        assert set(ds.roles.keys()) == {"admin", "etl"}
        assert ds.roles["admin"]["user"] == "admin_user"
        assert ds.roles["admin"]["password"] == "secret_admin"  # 环境变量已解析
        assert ds.roles["etl"]["user"] == "etl_user"
        assert ds.roles["etl"]["password"] == "secret_etl"

    def test_password_env_var_resolved(self, tmp_path, monkeypatch):
        """roles 里的密码 ${VAR} 被解析为环境变量值。"""
        monkeypatch.setenv("MY_PW", "p@ssw0rd")
        source = {
            "host": "h", "roles": {
                "admin": {"user": "a", "password": "${MY_PW}"},
                "etl": {"user": "e", "password": "plain"},
            }
        }
        config_path = _write_config(tmp_path, {"s": source})
        sources, _, _, _ = load_db_sources(config_path)

        assert sources["s"].roles["admin"]["password"] == "p@ssw0rd"
        assert sources["s"].roles["etl"]["password"] == "plain"

    def test_no_top_level_user_password(self, tmp_path):
        """新架构：顶层 user/password 不再读取（无兜底）。"""
        source = {
            "host": "h",
            # 故意不写顶层 user/password
            "roles": {
                "admin": {"user": "a", "password": "ap"},
                "etl": {"user": "e", "password": "ep"},
            }
        }
        config_path = _write_config(tmp_path, {"s": source})
        sources, _, _, _ = load_db_sources(config_path)

        # DataSource 没有 user/password 属性了
        ds = sources["s"]
        assert not hasattr(ds, "user") or getattr(ds, "user", "") == ""
        assert ds.roles["admin"]["user"] == "a"


class TestRoleSelection:
    """按 role 选账号的连接参数测试（不连真库，检查 _get_conn_params）。

    本机无 psycopg2，monkeypatch 注入假的 psycopg2 让 PsycopgExecutor 构造能过。
    """

    @pytest.fixture(autouse=True)
    def _fake_psycopg2(self, monkeypatch):
        """注入假的 psycopg2，让 PsycopgExecutor 构造不报 ImportError。"""
        import types
        fake = types.ModuleType("psycopg2")
        fake.connect = lambda **kw: None
        extras = types.ModuleType("psycopg2.extras")
        extras.RealDictCursor = type("RealDictCursor", (), {})
        fake.extras = extras
        monkeypatch.setattr("dws_db.psycopg2", fake)
        # _get_conn 用假连接，不真连库
        monkeypatch.setattr("dws_db.psycopg2.connect", lambda **kw: None)

    def test_admin_role_uses_admin_account(self, tmp_path):
        """role=admin 时，连接参数用 admin 账号。"""
        config_path = _write_config(tmp_path, {"dws-dev": _two_role_source()})
        executor = create_executor(config_path, "dws-dev", role="admin")

        params = executor._get_conn_params()
        assert params["user"] == "admin_user"
        assert params["password"] == ""  # ${ADMIN_PW} 未设环境变量，解析为空

    def test_etl_role_uses_etl_account(self, tmp_path):
        """role=etl 时，连接参数用 etl 账号。"""
        config_path = _write_config(tmp_path, {"dws-dev": _two_role_source()})
        executor = create_executor(config_path, "dws-dev", role="etl")

        params = executor._get_conn_params()
        assert params["user"] == "etl_user"
        assert params["password"] == ""

    def test_default_role_is_etl(self, tmp_path):
        """不传 role 时默认 etl。"""
        config_path = _write_config(tmp_path, {"dws-dev": _two_role_source()})
        executor = create_executor(config_path, "dws-dev")

        params = executor._get_conn_params()
        assert params["user"] == "etl_user"

    def test_missing_role_raises(self, tmp_path):
        """数据源没配请求的 role → 报清晰错误。"""
        source = {
            "host": "h",
            "roles": {"etl": {"user": "e", "password": "ep"}},  # 只有 etl，没 admin
        }
        config_path = _write_config(tmp_path, {"s": source})
        executor = create_executor(config_path, "s", role="admin")

        with pytest.raises(ValueError, match="role 'admin'"):
            executor._get_conn_params()

    def test_create_executor_for_schema_with_role(self, tmp_path):
        """create_executor_for_schema 传 role，按 schema 选源 + 按 role 选账号。"""
        config_path = _write_config(
            tmp_path,
            {"dws-dev": _two_role_source()},
            schema_mapping={"fin_dwb_isc": "dws-dev"},
        )
        executor = create_executor_for_schema("fin_dwb_isc", role="admin", config_path=config_path)

        params = executor._get_conn_params()
        assert params["user"] == "admin_user"

    def test_admin_and_etl_different_accounts(self, tmp_path):
        """同一数据源，admin 和 etl 拿到不同账号（核心：两账号隔离）。"""
        config_path = _write_config(tmp_path, {"dws-dev": _two_role_source()})
        admin_ex = create_executor(config_path, "dws-dev", role="admin")
        etl_ex = create_executor(config_path, "dws-dev", role="etl")

        admin_user = admin_ex._get_conn_params()["user"]
        etl_user = etl_ex._get_conn_params()["user"]
        assert admin_user != etl_user, "admin 和 etl 必须是不同账号"
        assert admin_user == "admin_user"
        assert etl_user == "etl_user"


class TestConnectionReuse:
    """连接复用测试：多次 execute 只建一次连接（批量查询的性能关键）。"""

    @pytest.fixture(autouse=True)
    def _fake_psycopg2_with_counter(self, monkeypatch):
        """注入假的 psycopg2，connect 调用次数可追踪。"""
        import types
        fake = types.ModuleType("psycopg2")
        extras = types.ModuleType("psycopg2.extras")
        extras.RealDictCursor = type("RealDictCursor", (), {})
        fake.extras = extras

        connect_calls = {"n": 0}

        class FakeConn:
            def __init__(self):
                self.closed = False
                self.autocommit = False
            def cursor(self, **kw):
                cur = MagicMock()
                cur.execute = lambda sql: None
                cur.description = None
                cur.rowcount = 0
                cur.close = lambda: None
                return cur
            def close(self):
                self.closed = True

        def fake_connect(**kw):
            connect_calls["n"] += 1
            return FakeConn()

        fake.connect = fake_connect
        monkeypatch.setattr("dws_db.psycopg2", fake)
        # 让测试能读到计数
        self._connect_calls = connect_calls

    def test_multiple_execute_one_connection(self, tmp_path):
        """多次 execute 只建一次连接（复用），不再每次建连/关连。"""
        config_path = _write_config(tmp_path, {"dws-dev": _two_role_source()})
        executor = create_executor(config_path, "dws-dev", role="etl")

        # 跑 5 次 execute
        for _ in range(5):
            executor.execute("SELECT 1")

        assert self._connect_calls["n"] == 1, \
            f"5次execute应只建1次连接，实际建了{self._connect_calls['n']}次"

    def test_close_releases_connection(self, tmp_path):
        """close 后再 execute 会重新建连。"""
        config_path = _write_config(tmp_path, {"dws-dev": _two_role_source()})
        executor = create_executor(config_path, "dws-dev", role="etl")

        executor.execute("SELECT 1")
        assert self._connect_calls["n"] == 1
        executor.close()
        executor.execute("SELECT 1")
        assert self._connect_calls["n"] == 2  # close 后重新建连
