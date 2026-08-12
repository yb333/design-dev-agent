#!/usr/bin/env python3
"""
DWS 数据库执行模块

从原 mcp-servers/postgresql-executor 内化而来。
提供数据库连接、SQL 执行、多数据源切换能力。

接口与实现分离：
- DBExecutor（抽象接口）：上层（run_ut.py 等）只依赖这个
- PsycopgExecutor（现阶段实现）：psycopg2 直连 DWS/PostgreSQL
- 未来扩展：MCPExecutor（走术加平台2.0 MCP）/ PlatformExecutor（走平台API）

配置文件：db-sources.json（多 schema 多账号映射）
"""

import os
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None


# ============================================================
# 结果数据类
# ============================================================

@dataclass
class ExecuteResult:
    """SQL 执行结果"""
    success: bool
    rowcount: int = -1           # 影响行数（DDL 返回 -1）
    rows: list = field(default_factory=list)  # 查询结果行（dict 列表）
    columns: list = field(default_factory=list)  # 列名
    error: str = ""              # 报错信息
    duration_ms: int = 0         # 执行耗时

    def summary(self) -> str:
        if self.success:
            if self.rows:
                return f"成功, {len(self.rows)}行, {self.duration_ms}ms"
            return f"成功, 影响{self.rowcount}行, {self.duration_ms}ms"
        return f"失败: {self.error}"


@dataclass
class ConnectionStatus:
    """连接诊断结果（区分配置错误 vs 环境不可用）。

    category 决定调用方（precheck）怎么处理：
    - ok：连接正常
    - auth_failed：密码错/认证失败（配置错误，应阻断）
    - db_not_found：库不存在（配置错误，应阻断）
    - server_unreachable：服务器连不上/超时（环境不可用，可跳过）
    - unknown：其他（保守 warn 跳过，不阻断）
    """
    ok: bool
    category: str = "ok"
    reason: str = ""


# ============================================================
# 配置
# ============================================================

@dataclass
class DataSource:
    """单个数据源配置。

    账号按操作类型分（roles）：admin（DDL 建表删表）、etl（SELECT/INSERT 数据读写）。
    每个数据源必须配这两个 role，同一库两个账号、密码各自独立。
    """
    name: str
    type: str = "postgresql"     # postgresql | huawei-dws
    host: str = ""
    port: int = 5432
    database: str = ""
    ssl: bool = False
    sslrootcert: str = ""
    # 按操作类型分账号（必配）：{"admin": {user,password}, "etl": {user,password}}
    roles: dict = field(default_factory=dict)


@dataclass
class SecurityConfig:
    """安全配置"""
    allow_write: bool = True     # 允许写操作（DDL/INSERT）
    max_rows: int = 1000         # 查询最大返回行数
    timeout: int = 0             # 超时（秒），0=不限制
    sample_blocks: int = 0       # UT 采样块数（0=不采样，10=SYSTEM(10)）。开发环境配>0加速，UAT/生产配0


def resolve_password(password: str) -> str:
    """解析密码中的环境变量引用（${VAR_NAME} → 环境变量值）"""
    if password.startswith("${") and password.endswith("}"):
        env_name = password[2:-1]
        return os.environ.get(env_name, "")
    return password


def load_db_sources(config_path: str) -> tuple[dict[str, DataSource], str, SecurityConfig, dict]:
    """加载 db-sources.json 配置。

    返回 (数据源字典, 默认数据源名, 安全配置, schema映射)。
    """
    p = Path(config_path)
    if not p.exists():
        raise FileNotFoundError(
            f"数据库配置文件不存在: {config_path}\n"
            f"请复制 db-sources.example.json 为 db-sources.json 并配置连接信息"
        )

    raw = json.loads(p.read_text(encoding="utf-8"))

    sources = {}
    for name, cfg in raw.get("sources", {}).items():
        # 解析 roles（每个 role 一组 user/password）
        roles = {}
        for role_name, role_cfg in cfg.get("roles", {}).items():
            roles[role_name] = {
                "user": role_cfg.get("user", ""),
                "password": resolve_password(role_cfg.get("password", "")),
            }
        sources[name] = DataSource(
            name=name,
            type=cfg.get("type", "postgresql"),
            host=cfg.get("host", ""),
            port=cfg.get("port", 5432),
            database=cfg.get("database", ""),
            ssl=cfg.get("ssl", False),
            sslrootcert=cfg.get("sslrootcert", ""),
            roles=roles,
        )

    default = raw.get("default", "")
    sec_raw = raw.get("security", {})
    security = SecurityConfig(
        allow_write=sec_raw.get("allowWriteOperations", True),
        max_rows=sec_raw.get("maxRows", 1000),
        timeout=sec_raw.get("timeout", 0),
        sample_blocks=sec_raw.get("sample_blocks", 0),
    )

    schema_mapping = raw.get("schema_mapping", {})

    return sources, default, security, schema_mapping


def resolve_source_by_schema(config_path: str, schema: str) -> str:
    """按 schema 从 schema_mapping 查找对应的数据源名。

    schema 没配 mapping → raise（强制配全，不静默回退 default 掩盖）。
    回退 default 会连到错误的库还静默通过，掩盖配置缺失。
    """
    p = Path(config_path)
    if not p.exists():
        raise FileNotFoundError(
            f"数据库配置文件不存在: {config_path}\n"
            f"请复制 db-sources.example.json 为 db-sources.json 并配置连接信息"
        )
    raw = json.loads(p.read_text(encoding="utf-8"))
    schema_mapping = raw.get("schema_mapping", {})
    if schema in schema_mapping:
        return schema_mapping[schema]
    raise ValueError(
        f"schema '{schema}' 不在 schema_mapping 配置里，请在 db-sources.json 的 "
        f"schema_mapping 段显式映射该 schema 到数据源。"
        f"已配置: {list(schema_mapping.keys()) or '(空)'}"
    )


def load_test_params(config_path: str) -> dict:
    """从 db-sources.json 读 test_params 段（参数测试值配置）。

    返回 {param_name: {type, expr/value, desc}}，未配置则返回 {}。
    被 run_ut.py 调用，执行前把 ${PARAM} 替换为实际值（模拟术加平台运行时注入）。
    """
    p = Path(config_path)
    if not p.exists():
        return {}
    raw = json.loads(p.read_text(encoding="utf-8"))
    return raw.get("test_params", {})


# ============================================================
# DBExecutor 抽象接口
# ============================================================

class DBExecutor(ABC):
    """数据库执行器抽象接口。

    上层（run_ut.py / check_sql.py）只依赖这个接口。
    现阶段用 PsycopgExecutor，未来可换 MCPExecutor / PlatformExecutor。
    """

    @abstractmethod
    def execute(self, sql: str) -> ExecuteResult:
        """执行单条 SQL，返回结构化结果。"""
        ...

    @abstractmethod
    def execute_many(self, sqls: list[str]) -> list[ExecuteResult]:
        """按顺序执行多条 SQL（如 DDL+INSERT），任一失败则停止。"""
        ...

    @abstractmethod
    def test_connection(self) -> bool:
        """测试连接是否正常。"""
        ...

    @abstractmethod
    def switch_source(self, source_name: str):
        """切换数据源（多 schema 多账号）。"""
        ...

    @abstractmethod
    def list_sources(self) -> list[str]:
        """列出所有已配置的数据源名。"""
        ...

    @abstractmethod
    def get_current_source(self) -> str:
        """当前使用的数据源名。"""
        ...


# ============================================================
# PsycopgExecutor —— 现阶段实现（psycopg2 直连）
# ============================================================

class PsycopgExecutor(DBExecutor):
    """psycopg2 直连实现。

    支持 PostgreSQL 和华为云 DWS（DWS 兼容 PostgreSQL 协议）。
    """

    def __init__(self, config_path: str, source_name: str = "", role: str = "etl"):
        if psycopg2 is None:
            raise ImportError(
                "psycopg2 未安装。请运行: pip install psycopg2-binary"
            )
        self._config_path = config_path
        self._sources, self._default, self._security, self._schema_mapping = load_db_sources(config_path)

        if not self._sources:
            raise ValueError(f"db-sources.json 里没有配置任何数据源: {config_path}")

        # 选择初始数据源（配置错误必须 fail loud，不静默换一个——掩盖根因）
        self._current = source_name or self._default
        if not self._current:
            raise ValueError(
                "未指定数据源且 db-sources.json 未配 default。"
                "请配置 sources.default 或显式传 source_name"
            )
        if self._current not in self._sources:
            raise ValueError(
                f"数据源 '{self._current}' 不在配置里。"
                f"可用: {list(self._sources.keys())}"
            )

        # 操作角色：admin（DDL 建表删表）| etl（SELECT/INSERT 数据读写）
        self._role = role
        # 缓存的连接（复用，避免每次 execute 都建连）
        self._conn = None

    def _get_conn_params(self) -> dict:
        """获取当前数据源 + 当前 role 的连接参数"""
        ds = self._sources[self._current]
        role_cfg = ds.roles.get(self._role)
        if not role_cfg:
            raise ValueError(
                f"数据源 '{self._current}' 没有配置 role '{self._role}'，"
                f"请在 db-sources.json 的 sources.{self._current}.roles.{self._role} 配置 user/password"
            )
        params = {
            "host": ds.host,
            "port": ds.port,
            "database": ds.database,
            "user": role_cfg["user"],
            "password": role_cfg["password"],
        }
        if ds.ssl:
            params["sslmode"] = "require"
            if ds.sslrootcert:
                params["sslrootcert"] = ds.sslrootcert
        return params

    def _get_conn(self):
        """获取数据库连接（复用实例缓存的连接，避免每次建连开销）"""
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(**self._get_conn_params())
            self._conn.autocommit = True  # DDL 需要 autocommit
            # 设置语句超时（security.timeout 秒，0=不限制）
            # 在连接建立时设一次，后续复用的连接都带这个超时
            if self._security.timeout > 0:
                cur = self._conn.cursor()
                cur.execute(f"SET statement_timeout = {self._security.timeout * 1000}")
                cur.close()
        return self._conn

    def close(self):
        """显式关闭缓存的连接（批量查询结束后调用）"""
        if self._conn is not None and not self._conn.closed:
            self._conn.close()
        self._conn = None

    def __del__(self):
        """析构兜底：确保连接释放（短脚本退出时也干净）"""
        try:
            self.close()
        except Exception:
            pass

    def execute(self, sql: str) -> ExecuteResult:
        """执行单条 SQL（复用连接，不再每次建连/关连）"""
        start = time.monotonic()
        sql_stripped = sql.strip().rstrip(";")

        try:
            conn = self._get_conn()
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            cur.execute(sql_stripped)

            # 判断是查询还是写操作
            is_select = sql_stripped.upper().startswith("SELECT") or \
                        sql_stripped.upper().startswith("WITH") or \
                        sql_stripped.upper().startswith("SHOW")

            rows = []
            columns = []
            rowcount = cur.rowcount

            if is_select and cur.description:
                columns = [desc[0] for desc in cur.description]
                rows = [dict(r) for r in cur.fetchmany(self._security.max_rows)]

            cur.close()

            duration = int((time.monotonic() - start) * 1000)
            return ExecuteResult(
                success=True,
                rowcount=rowcount,
                rows=rows,
                columns=columns,
                duration_ms=duration,
            )

        except Exception as e:
            duration = int((time.monotonic() - start) * 1000)
            return ExecuteResult(
                success=False,
                error=str(e),
                duration_ms=duration,
            )

    def execute_many(self, sqls: list[str]) -> list[ExecuteResult]:
        """按顺序执行多条 SQL，任一失败则停止"""
        results = []
        for i, sql in enumerate(sqls):
            r = self.execute(sql)
            results.append(r)
            if not r.success:
                # 失败停止后续
                break
        return results

    def test_connection(self) -> bool:
        """测试连接（向后兼容，返回 bool）。新代码用 diagnose_connection 拿原因和分类。"""
        return self.diagnose_connection().ok

    def diagnose_connection(self) -> ConnectionStatus:
        """诊断连接：区分配置错误（密码错/库名错）vs 环境不可用（服务器连不上）。

        调用方（precheck）据此决定：配置错误→error 阻断；环境不可用→warn 跳过。
        不再静默掩盖——至少把原因返回给调用方。
        """
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.close()
            return ConnectionStatus(ok=True)
        except Exception as e:
            msg = str(e).lower()
            # 认证失败 = 配置错误（密码错）
            if any(k in msg for k in ("authentication", "password", "invalid authorization", "登录失败")):
                return ConnectionStatus(ok=False, category="auth_failed", reason=str(e))
            # 库不存在 = 配置错误（库名错）
            if "does not exist" in msg and "database" in msg:
                return ConnectionStatus(ok=False, category="db_not_found", reason=str(e))
            # 连不上服务器 = 环境不可用
            if any(k in msg for k in ("could not connect", "connection refused", "timeout", "timed out", "not known", "name or service not known")):
                return ConnectionStatus(ok=False, category="server_unreachable", reason=str(e))
            return ConnectionStatus(ok=False, category="unknown", reason=str(e))

    def switch_source(self, source_name: str):
        """切换数据源"""
        if source_name not in self._sources:
            raise ValueError(
                f"数据源 '{source_name}' 不存在。可用: {list(self._sources.keys())}"
            )
        self._current = source_name

    def list_sources(self) -> list[str]:
        return list(self._sources.keys())

    def get_current_source(self) -> str:
        return self._current

    @property
    def security(self) -> SecurityConfig:
        return self._security


# ============================================================
# 工厂函数
# ============================================================

def create_executor(config_path: str = "", source_name: str = "", role: str = "etl") -> DBExecutor:
    """创建执行器实例。

    config_path: db-sources.json 路径。默认按以下顺序查找：
      1. 环境变量 DB_CONFIG
      2. ~/.config/opencode/db-sources.json（全局配置，install 不覆盖）
    source_name: 指定数据源。默认用配置文件里的 default。
    role: 操作角色。admin（DDL 建表删表）| etl（SELECT/INSERT 数据读写，默认）。
    """
    if not config_path:
        config_path = os.environ.get(
            "DB_CONFIG",
            str(Path.home() / ".config" / "opencode" / "db-sources.json"),
        )
    return PsycopgExecutor(config_path, source_name, role)


def resolve_config_path(config_path: str = "") -> str:
    """解析 db-sources.json 路径（公共能力：调用方不用关心配置在哪）。

    优先级：
      1. 显式传入的 config_path
      2. 环境变量 DB_CONFIG
      3. ~/.config/opencode/db-sources.json（全局配置，install 不覆盖）
    """
    if config_path:
        return config_path
    return os.environ.get(
        "DB_CONFIG",
        str(Path.home() / ".config" / "opencode" / "db-sources.json"),
    )


def create_executor_for_schema(schema: str, role: str = "etl", config_path: str = "") -> DBExecutor:
    """★ 高层封装：传入目标 schema + role，内部自动选数据源 + 建连。

    调用方（check_db / ut / precheck）只用这个函数——传 schema 和 role 即可，
    不用关心 config_path 在哪、schema_mapping 怎么查、default 是谁。
    选源逻辑：按 schema 查 schema_mapping，查不到回退 default。

    Args:
        schema: 目标表 schema（用来按 schema_mapping 选数据源）。
        role: 操作角色。admin（DDL 建表删表）| etl（SELECT/INSERT 数据读写，默认）。
        config_path: 可选，db-sources.json 路径；不传则自动查找。
    """
    resolved = resolve_config_path(config_path)
    source_name = resolve_source_by_schema(resolved, schema)
    return create_executor(resolved, source_name, role)


# ============================================================
# CLI（命令行测试用）
# ============================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="DWS 数据库执行模块（CLI 测试）")
    parser.add_argument("--config", default="", help="db-sources.json 路径")
    parser.add_argument("--source", default="", help="数据源名")
    parser.add_argument("--sql", default="", help="要执行的 SQL")
    parser.add_argument("--test", action="store_true", help="只测试连接")
    parser.add_argument("--list", action="store_true", help="列出数据源")
    args = parser.parse_args()

    try:
        executor = create_executor(args.config, args.source)
    except Exception as e:
        print(f"错误: {e}", flush=True)
        exit(1)

    if args.list:
        print(f"数据源: {executor.list_sources()}")
        print(f"当前: {executor.get_current_source()}")
        exit(0)

    if args.test:
        ok = executor.test_connection()
        print(f"连接{'成功' if ok else '失败'}: {executor.get_current_source()}")
        exit(0 if ok else 1)

    if args.sql:
        result = executor.execute(args.sql)
        print(result.summary())
        if result.rows:
            print(f"列: {result.columns}")
            for row in result.rows[:5]:
                print(f"  {row}")
            if len(result.rows) > 5:
                print(f"  ...（共 {len(result.rows)} 行）")
        if not result.success:
            exit(1)
    else:
        print("用 --sql 'SELECT 1' / --test / --list 测试")
