#!/usr/bin/env python3
"""
设计探索脚本：JOIN 键唯一性试算。

designer 做 join_safety 分析时，不确定 JOIN 键在右表唯一不唯一——这是
"关联会不会发散"的事实依据。本脚本对单表跑 count(*) / count(DISTINCT key)，
给出唯一性结论。

设计约束：
- 复用 design-dev-shared/scripts/dws_db 的 create_executor_for_schema，不重写连库逻辑
- 只读（etl 账号），只查单表（不跑 JOIN，不会发散）
- 连不上库静默跳过（和 precheck 一致），退出码 0 不阻断设计
- 不需要采样（单表 count 不会发散）

用法（designer 在步骤7关联安全分析时调）：
  python explore.py --ts {deliver}/ts.json \\
      --check-join-key --schema dim --table dim_store --key store_id \\
      --where "is_current = 1"

退出码：0（总是，连不上库也跳过不阻断）
"""

import sys
import re
import json
import argparse
from pathlib import Path

# 复用 design-dev-shared 的连库能力（和 precheck.py 一样的 sys.path 推算）
sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent.parent / "design-dev-shared" / "scripts"),
)


# ============================================================
# 核心逻辑（纯函数，可单测，不连库）
# ============================================================

def build_join_key_sql(schema: str, table: str, key: str, where_clause: str = "") -> str:
    """构造 JOIN 键唯一性试算 SQL。

    SELECT count(*) AS total, count(DISTINCT {key}) AS distinct_cnt
    FROM {schema}.{table}
    [WHERE {where_clause}]

    单表查询，不 JOIN——避免 JOIN 发散污染结论。
    """
    if not schema or not table or not key:
        raise ValueError("schema/table/key 都不能为空")
    # 列名/表名只允许字母数字下划线和点（防 SQL 注入；这些值来自 designer/RS，不是用户直接输入）
    _validate_identifier(f"{schema}.{table}")
    _validate_identifier(key)
    sql = (
        f"SELECT count(*) AS total, count(DISTINCT {key}) AS distinct_cnt "
        f"FROM {schema}.{table}"
    )
    if where_clause and where_clause.strip():
        sql += f" WHERE {where_clause.strip()}"
    return sql


def _validate_identifier(name: str) -> None:
    """简单校验标识符：只允许字母/数字/下划线/点。防 SQL 注入。"""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", name):
        raise ValueError(f"非法标识符（只允许字母数字下划线点）: {name}")


def format_join_key_result(schema: str, table: str, key: str,
                           total: int, distinct_cnt: int,
                           where_clause: str = "") -> str:
    """格式化 JOIN 键唯一性试算结果为人读文本。

    返回多行字符串（给 designer 看，结论鲜明）。
    """
    dup = max(total - distinct_cnt, 0)
    is_unique = (dup == 0)
    where_note = f"（限定: {where_clause.strip()}）" if where_clause and where_clause.strip() else ""
    if is_unique:
        verdict = "✅ 唯一（此表在此键上可安全 LEFT JOIN，不发散）"
    else:
        verdict = "❌ 不唯一（JOIN 此表可能发散，join_safety 需给对齐策略）"
    return (
        f"表 {schema}.{table} 的 {key}{where_note}：\n"
        f"  总行数: {total}\n"
        f"  去重数: {distinct_cnt}\n"
        f"  重复数: {dup}\n"
        f"  结论: {verdict}"
    )


def format_skip(msg: str) -> str:
    """连不上库 / 无配置时的跳过提示（不阻断设计）。"""
    return f"⚠️ 无法连库，跳过试算：{msg}"


# ============================================================
# 连库执行（薄封装，复用 dws_db）
# ============================================================

def run_join_key_check(target_schema: str, schema: str, table: str, key: str,
                       where_clause: str = "") -> str:
    """跑 JOIN 键唯一性试算，返回人读结果文本。

    连不上库（无配置 / 无 psycopg2 / 连接失败）→ 返回跳过提示，退出码 0。
    """
    try:
        from dws_db import create_executor_for_schema  # type: ignore
    except ImportError:
        return format_skip("dws_db 模块不可用")

    try:
        executor = create_executor_for_schema(target_schema, role="etl")
    except Exception as e:
        return format_skip(f"无法创建执行器: {e}")

    try:
        if not executor.test_connection():
            return format_skip("数据库连接失败（检查 db-sources.json 配置）")
        sql = build_join_key_sql(schema, table, key, where_clause)
        r = executor.execute(sql)
        if not r.success:
            return format_skip(f"SQL 执行失败: {r.error}")
        if not r.rows:
            return format_skip("SQL 无返回行")
        row = r.rows[0]
        total = int(row.get("total", 0))
        distinct_cnt = int(row.get("distinct_cnt", 0))
        return format_join_key_result(schema, table, key, total, distinct_cnt, where_clause)
    except Exception as e:
        return format_skip(f"试算异常: {e}")
    finally:
        try:
            executor.close()
        except Exception:
            pass


# ============================================================
# ts.json 读取（取 target schema 选源）
# ============================================================

def read_target_schema(ts_path: str) -> str:
    """从 ts.json 读 target f_table 的 schema（用来按 schema 选数据源）。"""
    p = Path(ts_path)
    if not p.exists():
        raise FileNotFoundError(f"ts.json 不存在: {ts_path}")
    ts = json.loads(p.read_text(encoding="utf-8"))
    f_table = ts.get("meta", {}).get("target", {}).get("f_table", {})
    schema = f_table.get("schema", "")
    if not schema:
        raise ValueError(f"ts.json 里取不到 target f_table schema: {ts_path}")
    return schema


# ============================================================
# 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="设计探索：JOIN 键唯一性试算（单表 count vs count DISTINCT）"
    )
    parser.add_argument("--ts", help="ts.json 路径（取 target schema 选数据源）")
    parser.add_argument("--schema", help="要试算的表 schema", default="")
    parser.add_argument("--table", help="要试算的表名", default="")
    parser.add_argument("--key", help="JOIN 键列名", default="")
    parser.add_argument("--where", help="WHERE 限定条件（可选，如 is_current = 1）",
                        default="")
    parser.add_argument("--check-join-key", action="store_true",
                        help="执行 JOIN 键唯一性检查")
    args = parser.parse_args()

    if not args.check_join_key:
        parser.error("目前只支持 --check-join-key，请加上该参数")

    # target schema：从 ts.json 取（选数据源用）；--schema 是要查的表的 schema
    target_schema = ""
    if args.ts:
        try:
            target_schema = read_target_schema(args.ts)
        except Exception as e:
            print(format_skip(f"读取 ts.json 失败: {e}"))
            return
    else:
        # 没传 ts.json，用 --schema 兜底选源
        target_schema = args.schema

    if not target_schema:
        print(format_skip("无法确定 target schema（请传 --ts 或 --schema）"))
        return

    print(run_join_key_check(
        target_schema=target_schema,
        schema=args.schema,
        table=args.table,
        key=args.key,
        where_clause=args.where,
    ))


if __name__ == "__main__":
    main()
