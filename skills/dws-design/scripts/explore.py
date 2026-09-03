#!/usr/bin/env python3
"""
设计探索脚本：JOIN 键唯一性试算 + 键值重叠率试算。

designer 做 join_safety 分析时，不确定 JOIN 键在右表唯一不唯一——这是
"关联会不会发散"的事实依据。本脚本对单表跑 COUNT(1) / COUNT(DISTINCT key)，
给出唯一性结论。

键值重叠率（--check-overlap）：类型全兼容但内容语义不确定时用（'1' vs '01'、
编码 vs 名称——这类不报错只静默空关联）。双侧 DISTINCT 采样各 500，交集在
Python 算，重叠率是启发证据不是证明。

设计约束：
- 复用 design-dev-shared/scripts/dws_db 的 create_executor_for_schema，不重写连库逻辑
- 只读（etl 账号），只查单表（不跑 JOIN，不会发散）
- 连不上库静默跳过（和 precheck 一致），退出码 0 不阻断设计
- 不需要采样（单表 count 不会发散；重叠率模式用 DISTINCT LIMIT 500 受控采样）

用法（designer 在关联安全分析时按需调）：
  python explore.py --rs {deliver}/_internal/rs_input.json \\
      --check-join-key --schema dim --table dim_store --key store_id \\
      --where "is_current = 1"

  python explore.py --rs {deliver}/_internal/rs_input.json \\
      --check-overlap --schema-a ods --table-a t1 --key-a cust_code \\
      --schema-b dim --table-b dim_cust --key-b cust_id

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

def split_key(key: str) -> list[str]:
    """--key 逗号分隔多列 → 列表（复合键支持，2026-09-03 内网实测：多字段关联条件
    此前查不了——COUNT(DISTINCT 单列) 对复合键必误报不唯一）。"""
    return [k.strip() for k in (key or "").split(",") if k.strip()]


def build_join_key_sql(schema: str, table: str, key: str, where_clause: str = "") -> str:
    """构造 JOIN 键唯一性试算 SQL（--key 支持逗号分隔复合键——COUNT(DISTINCT (a,b))）。

    SELECT COUNT(1) AS total, COUNT(DISTINCT {键}) AS distinct_cnt
    FROM {schema}.{table}
    [WHERE {where_clause}]

    单表查询，不 JOIN——避免 JOIN 发散污染结论。
    """
    if not schema or not table or not key:
        raise ValueError("schema/table/key 都不能为空")
    # 列名/表名只允许字母数字下划线和点（防 SQL 注入；这些值来自 designer/RS，不是用户直接输入）
    keys = split_key(key)
    _validate_identifier(f"{schema}.{table}")
    for k in keys:
        _validate_identifier(k)
    key_expr = f"({', '.join(keys)})" if len(keys) > 1 else keys[0]
    sql = (
        f"SELECT COUNT(1) AS total, COUNT(DISTINCT {key_expr}) AS distinct_cnt "
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


# ============================================================
# 键值重叠率试算（关联内容语义探测：类型全兼容但内容对不上时用）
# ============================================================

# 采样量是统计输入不是输出：500 行在脚本进程内算交集，designer 只看到
# 摘要（计数/重叠率/≤5 个交集样例），不进 agent 上下文。不能改小——
# 20 条会把 1% 真实重叠率误判成"零交集"（误报，违反宁放过）。
OVERLAP_SAMPLE_LIMIT = 500


def build_overlap_sample_sql(schema: str, table: str, key: str,
                             where_clause: str = "") -> str:
    """构造键值采样 SQL（DISTINCT + LIMIT，双侧各采一批，交集在 Python 算）。

    SELECT DISTINCT {key}::text AS v FROM {schema}.{table} [WHERE ...] LIMIT 500
    ::text 归一显示形态（数值/日期侧也能跟字符侧直观比对）。
    --key 逗号分隔复合键 → DISTINCT (a,b)::text 整串归一（内网实测：多字段关联
    此前查不了）。
    """
    _validate_identifier(f"{schema}.{table}")
    keys = split_key(key)
    for k in keys:
        _validate_identifier(k)
    key_expr = f"({', '.join(keys)})" if len(keys) > 1 else keys[0]
    sql = (f"SELECT DISTINCT {key_expr}::text AS v FROM {schema}.{table}")
    if where_clause and where_clause.strip():
        sql += f" WHERE {where_clause.strip()}"
    sql += f" LIMIT {OVERLAP_SAMPLE_LIMIT}"
    return sql


def compute_overlap(samples_a: list, samples_b: list) -> dict:
    """算双侧采样键值的重叠率（纯函数）。

    返回 {a_n, b_n, common, common_samples, rate_a, rate_b}——
    rate_a = 交集占 a 侧采样比。重叠率是启发证据不是证明：采样 500 条，
    低重叠 → 疑似内容对不上（拿编码关联了名称这类），高重叠 → 内容语义吻合。
    """
    sa = {str(v).strip() for v in samples_a if v is not None}
    sb = {str(v).strip() for v in samples_b if v is not None}
    common = sa & sb
    common_samples = sorted(common)[:5]
    return {
        "a_n": len(sa), "b_n": len(sb), "common": len(common),
        "common_samples": common_samples,
        "rate_a": round(len(common) / len(sa), 4) if sa else None,
        "rate_b": round(len(common) / len(sb), 4) if sb else None,
    }


def format_overlap_result(side_a: str, key_a: str, side_b: str, key_b: str,
                          overlap: dict) -> str:
    """格式化键值重叠率结果为人读文本（给 designer 看，结论鲜明）。"""
    rate_a = overlap.get("rate_a")
    rate_a_str = f"{rate_a:.1%}" if isinstance(rate_a, float) else "N/A"
    rate_b = overlap.get("rate_b")
    rate_b_str = f"{rate_b:.1%}" if isinstance(rate_b, float) else "N/A"
    common_str = "、".join(overlap.get("common_samples", [])) or "（无交集样例）"
    if overlap.get("common", 0) == 0:
        verdict = ("❌ 采样零交集——两侧键内容完全对不上，关联逻辑大概率错误"
                   "（如拿编码关联名称/主键），回 mapping 核对关联字段")
    elif isinstance(rate_a, float) and rate_a < 0.1:
        verdict = ("⚠️ 重叠率很低——键内容疑似对不上，人工核对两侧取值口径"
                   "（前导零/格式/编码表范围）")
    else:
        verdict = "✅ 重叠率较高——键内容语义吻合（采样口径下）"
    return (
        f"键值重叠率试算 {side_a}.{key_a} ↔ {side_b}.{key_b}：\n"
        f"  采样数: 左 {overlap.get('a_n', 0)} / 右 {overlap.get('b_n', 0)}（各 LIMIT {OVERLAP_SAMPLE_LIMIT}）\n"
        f"  交集: {overlap.get('common', 0)}（左 {rate_a_str} / 右 {rate_b_str}）\n"
        f"  交集样例: {common_str}\n"
        f"  结论: {verdict}"
    )


def run_overlap_check(target_schema: str,
                      schema_a: str, table_a: str, key_a: str,
                      schema_b: str, table_b: str, key_b: str,
                      where_a: str = "", where_b: str = "") -> str:
    """跑键值重叠率试算（双侧采样 + Python 交集），返回人读结果文本。

    连不上库 → 返回跳过提示，退出码 0（和唯一性试算一致，不阻断设计）。
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
        samples_a, samples_b = [], []
        for (sch, tbl, key, where), out in (
            ((schema_a, table_a, key_a, where_a), "a"),
            ((schema_b, table_b, key_b, where_b), "b"),
        ):
            sql = build_overlap_sample_sql(sch, tbl, key, where)
            r = executor.execute(sql)
            if not r.success:
                return format_skip(f"SQL 执行失败: {r.error}")
            if out == "a":
                samples_a = [row.get("v") for row in (r.rows or [])]
            else:
                samples_b = [row.get("v") for row in (r.rows or [])]
        overlap = compute_overlap(samples_a, samples_b)
        return format_overlap_result(f"{schema_a}.{table_a}", key_a,
                                     f"{schema_b}.{table_b}", key_b, overlap)
    except Exception as e:
        return format_skip(f"试算异常: {e}")
    finally:
        try:
            executor.close()
        except Exception:
            pass


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

def read_target_schema_from_rs(rs_path: str) -> str:
    """设计期锚点：rs_input.json 的 meta.target.f_table.schema。

    ★ 循环依赖破解（2026-09-03 实证）：explore 的数据源锚点曾是 --ts ts.json，
    但设计期调 explore（第4层关联安全）时 ts.json 还没组装出来——传 --ts 文件
    不存在、不传则退化为按源表 schema 选源（dim 等不在 db 配置必连不上），
    designer 被逼去找替代通道（如 DB MCP——数据源/权限无关必得错误结论）。
    rs_input 与 ts 同源同事实（meta.target），设计期它一直在。"""
    data = json.loads(Path(rs_path).read_text(encoding="utf-8"))
    target = ((data.get("meta") or {}).get("target") or {})
    return str((target.get("f_table") or {}).get("schema") or "").strip()


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
        description="设计探索：JOIN 键唯一性试算 + 键值重叠率试算"
    )
    parser.add_argument("--ts", help="ts.json 路径（取 target schema 选数据源——组装后才存在）")
    parser.add_argument("--rs", default="",
                        help="rs_input.json 路径（设计期锚点：meta.target.f_table.schema——"
                             "第4层调 explore 时 ts.json 还没产，用这个）")
    parser.add_argument("--schema", help="要试算的表 schema", default="")
    parser.add_argument("--table", help="要试算的表名", default="")
    parser.add_argument("--key", help="JOIN 键列名（复合键逗号分隔，如 tenant_id,order_no）", default="")
    parser.add_argument("--where", help="WHERE 限定条件（可选，如 is_current = 1）",
                        default="")
    parser.add_argument("--check-join-key", action="store_true",
                        help="执行 JOIN 键唯一性检查")
    parser.add_argument("--check-overlap", action="store_true",
                        help="执行键值重叠率检查（双侧采样算交集，探测内容语义是否吻合）")
    parser.add_argument("--schema-a", default="", help="重叠率：左表 schema")
    parser.add_argument("--table-a", default="", help="重叠率：左表名")
    parser.add_argument("--key-a", default="", help="重叠率：左表键列（复合键逗号分隔）")
    parser.add_argument("--where-a", default="", help="重叠率：左表 WHERE 限定（可选）")
    parser.add_argument("--schema-b", default="", help="重叠率：右表 schema")
    parser.add_argument("--table-b", default="", help="重叠率：右表名")
    parser.add_argument("--key-b", default="", help="重叠率：右表键列（复合键逗号分隔）")
    parser.add_argument("--where-b", default="", help="重叠率：右表 WHERE 限定（可选）")
    args = parser.parse_args()

    if args.check_overlap:
        # target schema：从 ts.json 取（选数据源用）；--schema-a 兜底
        target_schema = ""
        for anchor, reader in ((args.ts, read_target_schema), (args.rs, read_target_schema_from_rs)):
            if anchor:
                try:
                    target_schema = reader(anchor)
                except Exception as e:
                    print(format_skip(f"读取锚点失败（{anchor}）: {e}"))
                    return
                if target_schema:
                    break
        target_schema = target_schema or args.schema_a
        if not target_schema:
            print(format_skip("无法确定 target schema（设计期传 --rs rs_input.json；"
                              "组装后可传 --ts；--schema-a 兜底）"))
            return
        missing = [n for n, v in (
            ("--schema-a", args.schema_a), ("--table-a", args.table_a), ("--key-a", args.key_a),
            ("--schema-b", args.schema_b), ("--table-b", args.table_b), ("--key-b", args.key_b),
        ) if not v]
        if missing:
            parser.error(f"--check-overlap 需要 {' '.join(missing)}")
        print(run_overlap_check(
            target_schema=target_schema,
            schema_a=args.schema_a, table_a=args.table_a, key_a=args.key_a,
            where_a=args.where_a,
            schema_b=args.schema_b, table_b=args.table_b, key_b=args.key_b,
            where_b=args.where_b,
        ))
        return

    if not args.check_join_key:
        parser.error("请指定模式：--check-join-key（唯一性）或 --check-overlap（键值重叠率）")

    # target schema：从 ts.json 取（选数据源用）；--schema 是要查的表的 schema
    target_schema = ""
    for anchor, reader in ((args.ts, read_target_schema), (args.rs, read_target_schema_from_rs)):
        if anchor:
            try:
                target_schema = reader(anchor)
            except Exception as e:
                print(format_skip(f"读取锚点失败（{anchor}）: {e}"))
                return
            if target_schema:
                break
    else:
        # 没传锚点，用 --schema 兜底选源（源表 schema 可能不在 db 配置——优先 --rs）
        target_schema = args.schema

    if not target_schema:
        print(format_skip("无法确定 target schema（设计期传 --rs rs_input.json；"
                          "组装后可传 --ts；--schema 兜底）"))
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
