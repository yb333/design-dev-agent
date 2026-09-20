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

用法（评估层唯一动作——2026-09-17 整体化：草稿随 view 预置[预填表单模式]，designer
只补 ? 答案后一次调用，结果单=上报正文）：
  # view 的「评估清单」段预置草稿；填空只读 view（mapping 中文名对物理名，对不出留空）。
  # 唯一一次工具调用（stdin 只给 ? 行答案 别名|键|限定；预填行自动跑不用抄）：
  python explore.py --rs {deliver}/_internal/rs_input.json --eval <<'EOF'
  c1|cust_code|status=1 and del_flag='N'
  EOF
  # 无 stdin=兜底出草稿（全预填[零 ? 行]时当场连跑直接出结果单）

单查形态（engineer 定向验证用）：
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
    """构造 JOIN 键唯一性试算 SQL（--key 支持逗号分隔复合键）。

    单键：SELECT COUNT(1), COUNT(DISTINCT {键}) FROM {表} [WHERE ...]
    复合键：DWS（PG9.2 内核）COUNT(DISTINCT) 只收单表达式——count(distinct a,b)
    报错（2026-09-18 内网实证），改子查询先 DISTINCT 再计数（官方替代三选一：
    拼接/子查询/UNIQ[近似，不用于精确判定]——子查询语义最准：NULL 组合按一组
    去重，与"NULL 键不算发散"同向）。

    单表查询，不 JOIN——避免 JOIN 发散污染结论。
    """
    if not schema or not table or not key:
        raise ValueError("schema/table/key 都不能为空")
    # 列名/表名只允许字母数字下划线和点（防 SQL 注入；这些值来自 designer/RS，不是用户直接输入）
    keys = split_key(key)
    _validate_identifier(f"{schema}.{table}")
    for k in keys:
        _validate_identifier(k)
    where_part = f" WHERE {where_clause.strip()}" if where_clause and where_clause.strip() else ""
    if len(keys) > 1:
        cols = ", ".join(keys)
        return (f"SELECT COUNT(1) AS total, "
                f"(SELECT COUNT(1) FROM (SELECT DISTINCT {cols} "
                f"FROM {schema}.{table}{where_part}) AS _dx) AS distinct_cnt "
                f"FROM {schema}.{table}{where_part}")
    return (f"SELECT COUNT(1) AS total, COUNT(DISTINCT {keys[0]}) AS distinct_cnt "
            f"FROM {schema}.{table}{where_part}")


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
    --key 逗号分隔复合键 → 各列 ::text 后 '~|~' 拼接整串归一（record cast
    `(a,b)::text` 在 DWS 上不可靠，拼接是采样启发可接受的碰撞面）。
    """
    _validate_identifier(f"{schema}.{table}")
    keys = split_key(key)
    for k in keys:
        _validate_identifier(k)
    key_expr = (f"{keys[0]}::text" if len(keys) == 1
                else " || '~|~' || ".join(f"{k}::text" for k in keys))
    sql = (f"SELECT DISTINCT {key_expr} AS v FROM {schema}.{table}")
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
            # 报错分类提示（2026-09-15 内网反馈：designer 不知道失败是不是自己参数写错）
            low = str(r.error or "").lower()
            if any(k in low for k in ("column", "字段", "does not exist", "不存在")):
                hint = "\n  【自检】键/条件里的字段名在该表不存在——核 --key 拼写与 --where 引用的列名（这就是参数写错）"
            elif any(k in low for k in ("invalid input", "无效", "type", "类型")):
                hint = "\n  【自检】--where 里字面量与列类型不符（如 varchar 列=裸数值）——核条件值写法"
            else:
                hint = "\n  【自检】语法错先核 --where 写法；确认无误=环境问题上报"
            return format_skip(f"SQL 执行失败: {r.error}{hint}")
        if not r.rows:
            return format_skip("SQL 无返回行")
        row = r.rows[0]
        total = int(row.get("total", 0))
        distinct_cnt = int(row.get("distinct_cnt", 0))
        base = format_join_key_result(schema, table, key, total, distinct_cnt, where_clause)
        # 不唯一时抓重复组样例（2026-09-15：designer 此前只看到数字不知道下一步——
        # 给 3 组重复键+组内行数，差异列线索自己看组内其他列或窄范围再试）
        if total > distinct_cnt:
            try:
                keys = [k.strip() for k in key.split(",") if k.strip()]
                key_expr = ", ".join(keys) if keys else key
                sample_sql = (f"SELECT {key_expr}, COUNT(1) AS dup_cnt "
                              f"FROM {schema}.{table}"
                              + (f" WHERE {where_clause}" if where_clause else "")
                              + f" GROUP BY {key_expr} HAVING COUNT(1) > 1 ORDER BY dup_cnt DESC LIMIT 3")
                rs2 = executor.execute(sample_sql)
                if rs2.success and rs2.rows:
                    _samples = [" | ".join(f"{k}={v}" for k, v in row2.items()) for row2 in rs2.rows]
                    base += ("\n  重复组样例（键→组内行数，看差异列线索）：\n    "
                             + "\n    ".join(_samples)
                             + "\n  下一步：疑点照第4层疑点清单上报（疑似方向=一句话猜测），勿自行多轮试探")
            except Exception:
                pass  # 样例失败不影响主结论（fail-soft）
        return base
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

# ============================================================
# 评估层作业台（2026-09-17 整体化：草稿随 view 预置[预填表单/slot-filling 模式]，
# designer 唯一动作=--eval——stdin 只给 ? 行答案，内部重拉草稿[与 view 同源必然一致]
# 合并后跑流水线出三段结果单=上报正文。预填行零誊写；填对→事实行/填错→存在性闸拦
# [疑点]/未答→自动进疑点/免实测行→事实行自动生成——每条路必然落到结果单，无路可飘。
# 通道=stdin：bash <<'EOF' / PowerShell @'...'@ 管道逐字透传——argv 内联 JSON 已退役
# （PS 5.1 剥内层双引号 + where 里 SQL 字面量 'N' 与 JSON 定界符同形，argv 通道无解）。
# 草稿生成器住 design-dev-shared/eval_workbench.py（双消费者：preprocess view 段+此处）。
# ============================================================

from eval_workbench import build_eval_plan_data, render_eval_draft


def parse_eval_lines(stdin_text: str) -> list[dict]:
    """行协议解析：别名|键|限定（兼容显式 别名|schema.table|键|限定；#注释/空行跳过；
    首行 BOM 防御性剥除——PS 5.1 管道 UTF8 带 BOM 前导，\\ufeff 不被 strip 当空白）。"""
    items = []
    for raw in str(stdin_text or "").splitlines():
        line = raw.strip().lstrip("\ufeff")
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) == 3:
            alias, key, where = parts
            sch = tbl = ""
        elif len(parts) == 4:
            alias, st_full, key, where = parts
            if "." not in st_full:
                items.append({"alias": alias, "schema": "", "table": "", "key": key,
                              "where": where, "err": f"表形态应为 schema.table: {st_full}"})
                continue
            sch, tbl = st_full.split(".", 1)
        elif len(parts) == 2:
            alias, key, where = parts[0], parts[1], ""
            sch = tbl = ""
        else:
            items.append({"alias": line, "schema": "", "table": "", "key": "", "where": "",
                          "err": f"行格式应为 别名|键|限定: {raw}"})
            continue
        items.append({"alias": alias, "schema": sch, "table": tbl, "key": key,
                      "where": where, "err": "" if (alias and key) else "缺别名/键"})
    return items


def _resolve_aliases(rs: dict, items: list[dict]) -> list[dict]:
    """别名→schema.table 反解（rs_input.source_tables，大小写归一；显式 schema.table 优先）。"""
    amap, dup = {}, set()
    for st in rs.get("source_tables") or []:
        al = str(st.get("source_alias") or "").strip().lower()
        if not al:
            continue
        if al in amap:
            dup.add(al)
        amap[al] = (str(st.get("source_schema") or ""), str(st.get("source_table") or ""))
    avail = sorted(a for a in amap if a)
    for it in items:
        if it["err"]:
            continue
        if not (it["schema"] and it["table"]):
            al = it["alias"].strip().lower()
            if al in dup:
                it["err"] = f"别名 {it['alias']} 在 rs_input 重复——用显式形态 别名|schema.table|键|限定"
                continue
            hit = amap.get(al)
            if not hit or not hit[1]:
                it["err"] = f"别名 {it['alias']} 不在 rs_input（可用: {avail}）——正路是核 rs_input，不是绕过"
                continue
            it["schema"], it["table"] = hit
    return items


def run_eval(rs_path: str, target_schema: str, stdin_text: str) -> str:
    """评估层唯一动作：内部重拉草稿（与 view 同源必然一致）+ stdin 答案合并 →
    流水线（存在性闸+唯一性实测）→ 结果单。

    产出按判读者视角砍常态噪声：✓ 常态折叠一行汇总；仅异常行（疑点/未答/未实测/
    失败）逐条列；join_safety 事实行=交付物（单行 yaml 直贴 decisions）；疑点只列
    事实——疑似方向由 designer 上报时补，不产出空占位。填对→事实行/填错→存在性
    闸拦[疑点]/未答→自动疑点/免实测→事实行，每条路必然落单。连不上库→存在性
    照出，唯一性标未实测（不阻断）。
    """
    rs = json.loads(Path(rs_path).read_text(encoding="utf-8"))
    plan = build_eval_plan_data(rs)
    answers = _resolve_aliases(rs, parse_eval_lines(stdin_text))
    ans_by_alias: dict = {}
    for it in answers:
        ans_by_alias.setdefault(it["alias"].strip().lower(), []).append(it)
    treat_aliases = {t["alias"].strip().lower() for t in plan["treat"]}
    # plan 行元数据索引（is_main/partner——engineer 侧 --edge --doubt 别名驱动派生用）
    meta_by_alias = {r["alias"].strip().lower():
                     {"is_main": bool(r.get("is_main")), "partner": r.get("partner") or "",
                      "schema": r["schema"], "table": r["table"]}
                     for r in plan["run"]}
    ok_tags, exc, facts, doubts = [], [], [], []
    eval_rows: list = []  # 落盘 eval_result.json（engineer 诊断派生源，2026-09-20）

    # 免实测行：✓ 核对一致折叠进汇总（事实行自动生成）；不一致/口径不全→疑点
    for t in plan["treat"]:
        if t["check_ok"] is True:
            ok_tags.append(t["alias"])
            facts.append(f"- {{alias: {t['alias']}, join_key_unique: true, "
                         f"reason: \"输入声明取一处理（{t['signal']}；开窗键=关联键一致）\"}}")
        else:
            doubts.append(f"{t['alias']}/{t['table']}: {t['check']}")

    # 合并：plan run 行 + stdin 答案（按别名覆盖/补空；额外别名=自设关联）
    merged = []  # (tag, sch, tbl, key, where)
    answered = set()
    for r in plan["run"]:
        al = r["alias"].strip().lower()
        got = ans_by_alias.get(al)
        if got:
            answered.add(al)
            for it in got:
                if it["err"]:
                    exc.append(f"[{it['alias']}] ✗ {it['err']}")
                    continue
                merged.append((it["alias"], it["schema"], it["table"], it["key"], it["where"]))
        else:
            merged.append((r["alias"], r["schema"], r["table"], r["key"], r["where"]))
    for al, items in ans_by_alias.items():
        if al in answered:
            continue
        for it in items:
            if al in treat_aliases:
                exc.append(f"[{it['alias']}] 免实测行忽略（声明依据已定；认为声明有误=疑点上报）")
            elif it["err"]:
                exc.append(f"[{it['alias']}] ✗ {it['err']}")
            else:
                merged.append((it["alias"], it["schema"], it["table"], it["key"], it["where"]))

    # 未答 ? 行 → 自动疑点（留空=合法答案；主表线未答=粒度无据，另点名）
    for tag, sch, tbl, key, where in merged:
        if not key:
            exc.append(f"[{tag}] {tbl} ？未答")
            _m = meta_by_alias.get(tag.strip().lower(), {})
            eval_rows.append({"alias": tag, "schema": sch, "table": tbl, "key": "",
                              "where": where, "is_main": _m.get("is_main", False),
                              "partner": _m.get("partner", ""), "verdict": "not_answered"})
            if _m.get("is_main"):
                doubts.append(f"{tag}/{tbl}: 主表业务主键未确定（粒度无据——RS/mapping 声明的键"
                              "对不出或未填）——粒度/键声明问题，无关联边可试算")
            else:
                doubts.append(f"{tag}/{tbl}: 键未确定（自然语言条件对不出物理名，原文见 view 评估清单）")

    from schema_query import lookup_table, _similar_names
    to_run = []  # (tag, sch, tbl, key, where, gate_note)
    seen: dict = {}  # (schema,table,key,where) -> 首个 tag（同表同键同限定只跑一次）
    cache_map: dict = {}
    for tag, sch, tbl, key, where in merged:
        if not key:
            continue
        _m2 = meta_by_alias.get(tag.strip().lower(), {})
        dedup = (sch.lower(), tbl.lower(), key.lower(), where.lower())
        if dedup in seen:
            exc.append(f"[{tag}] 与 [{seen[dedup]}] 查同一表同键同限定——只跑一次，结论共用")
            continue
        seen[dedup] = tag
        ck = (sch.lower(), tbl.lower())
        if ck not in cache_map:
            cache_map[ck] = lookup_table(rs_path, sch, tbl)
        st, cols = cache_map[ck]
        missing = []
        if st == "ok" and cols:
            colsl = {str(c).lower() for c in cols}
            missing = [k for k in split_key(key) if k.lower() not in colsl]
        if missing:
            sim = []
            for k in missing:
                s = _similar_names(k, cols or {})
                if s:
                    sim.append(f"{k}→相近 {','.join(s)}")
            exc.append(f"[{tag}] {tbl} key=({key}) ✗ 键字段不存在: {', '.join(missing)}"
                       + (f"（{'；'.join(sim)}）" if sim else ""))
            doubts.append(f"{tag}/{tbl}: 键字段 {', '.join(missing)} 物理不存在"
                          + (f"（相近名: {'；'.join(s.split('→相近 ')[-1] for s in sim)}"
                             "——给调用方核实的线索）" if sim else ""))
            eval_rows.append({"alias": tag, "schema": sch, "table": tbl, "key": key,
                              "where": where, "is_main": _m2.get("is_main", False),
                              "partner": _m2.get("partner", ""), "verdict": "gate_missing"})
            continue
        gate_note = "" if st == "ok" else (
            f"（键存在性未核: {'无 schema_cache' if st == 'no_cache' else f'{sch}.{tbl} 不在 cache'}）")
        to_run.append((tag, sch, tbl, key, where, gate_note))

    # 唯一性实测（连不上库→逐行标未实测，存在性结论照出）
    meas: dict = {}
    if to_run:
        executor = None
        try:
            from dws_db import create_executor_for_schema
            executor = create_executor_for_schema(target_schema, role="etl")
            if not executor.test_connection():
                executor = None
        except Exception:
            executor = None
        if executor is not None:
            try:
                for tag, sch, tbl, key, where, gate_note in to_run:
                    try:
                        sql = build_join_key_sql(sch, tbl, key, where)
                        r = executor.execute(sql)
                        if not r.success:
                            exc.append(f"[{tag}] {tbl} key=({key}) 执行失败: "
                                       f"{str(r.error)[:120]}【自检：字段名/条件写法】")
                            continue
                        row = (r.rows or [{}])[0]
                        total, uniq = int(row.get("total", 0)), int(row.get("distinct_cnt", 0))
                        meas[(tag, sch, tbl, key, where)] = (total, uniq)
                        if total != uniq:
                            sample = ""
                            try:
                                ke = ", ".join(split_key(key))
                                s2 = (f"SELECT {ke}, COUNT(1) AS dup_cnt FROM {sch}.{tbl}"
                                      + (f" WHERE {where}" if where else "")
                                      + f" GROUP BY {ke} HAVING COUNT(1)>1 ORDER BY dup_cnt DESC LIMIT 2")
                                r2 = executor.execute(s2)
                                if r2.success and r2.rows:
                                    sample = "（重复组: " + "; ".join(
                                        ",".join(f"{k}={v}" for k, v in rr.items()) for rr in r2.rows) + "）"
                            except Exception:
                                pass
                            exc.append(f"[{tag}] {tbl} key=({key}) ✗ 不唯一（重复 {total - uniq}）{sample}")
                            _m = meta_by_alias.get(tag.strip().lower(), {})
                            if _m.get("is_main"):
                                doubts.append(f"{tag}/{tbl}: 主表业务主键 {key} 不唯一"
                                              f"（{total} 行重复 {total - uniq}）——粒度/键声明问题，"
                                              f"无关联边可试算；方向=补键[复合]/退BA修数据/收敛策略")
                            else:
                                doubts.append(f"{tag}/{tbl}: {key} 限定({where or '无'})下不唯一"
                                              f"（{total} 行重复 {total - uniq}）")
                    except Exception as e:
                        exc.append(f"[{tag}] 查询异常: {e}")
            finally:
                try:
                    executor.close()
                except Exception:
                    pass
    for tag, sch, tbl, key, where, gate_note in to_run:
        got = meas.get((tag, sch, tbl, key, where))
        q = f"限定({where})" if where else "无限定"
        _m = meta_by_alias.get(tag.strip().lower(), {})
        if got is None:
            exc.append(f"[{tag}] {tbl} key=({key}) 唯一性未实测（连不上库）{gate_note}")
            facts.append(f"- {{alias: {tag}, join_key_unique: \"未验证\", "
                         f"reason: \"连不上库未实测 {key} {q}\"}}")
            eval_rows.append({"alias": tag, "schema": sch, "table": tbl, "key": key,
                              "where": where, "is_main": _m.get("is_main", False),
                              "partner": _m.get("partner", ""), "verdict": "unverified"})
        else:
            total, uniq = got
            if total == uniq:
                ok_tags.append(tag)
                facts.append(f"- {{alias: {tag}, join_key_unique: true, "
                             f"reason: \"实测: {key} {q}，{total} 行零重复\"}}")
                eval_rows.append({"alias": tag, "schema": sch, "table": tbl, "key": key,
                                  "where": where, "is_main": _m.get("is_main", False),
                                  "partner": _m.get("partner", ""), "verdict": "unique",
                                  "total": total})
            else:
                facts.append(f"- {{alias: {tag}, join_key_unique: false, "
                             f"reason: \"实测: {key} {q}，{total} 行重复 {total - uniq}\", strategy: \"\"}}")
                eval_rows.append({"alias": tag, "schema": sch, "table": tbl, "key": key,
                                  "where": where, "is_main": _m.get("is_main", False),
                                  "partner": _m.get("partner", ""), "verdict": "non_unique",
                                  "total": total, "dup": total - uniq})
    parts = [f"── 评估结果（实测 {len(seen)} 项；✓ 唯一 {len(ok_tags)}："
             f"{'、'.join(ok_tags) if ok_tags else '无'}）──"]
    parts.extend(exc)
    parts.append("\n── join_safety 事实行（直贴 decisions；join_key_unique=false 的行 strategy 必填）──")
    parts.extend(facts if facts else ["（无）"])
    parts.append("\n── 疑点（各补一句疑似方向后随回复上报；上报疑点是合格交卷的一部分）──")
    if doubts:
        parts.extend(f"{i}) {d}" for i, d in enumerate(doubts, 1))
    else:
        parts.append("（无——评估层无疑点，直接进五层）")
    # 落盘 eval_result.json（engineer 侧 --edge --doubt 别名驱动派生的参数源，2026-09-20；
    # stdout 是 designer 面，此文件是 engineer 诊断输入——角色面分立）
    try:
        (Path(rs_path).parent / "eval_result.json").write_text(
            json.dumps({"rows": eval_rows,
                        "main_alias": next((r["alias"] for r in plan["run"] if r.get("is_main")), "")},
                       ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass  # 落盘失败不阻断评估主流程
    return "\n".join(parts)


def run_batch_check(target_schema: str, batch_src: str) -> str:
    """批量关联唯一性校验（2026-09-15 决策 B 补环：关联是一等分析单位——同表多关联
    各自带限定逐条校验，一个命令跑完；同表同键同限定自动去重只跑一次）。

    批量清单 YAML/JSON：[{tag, schema, table, key, where}]——tag=关联标识（如
    别名 c1/c2，输出对账用）；where 可空（无限定）。输出汇总表+重复组样例。
    """
    # 输入双形态（2026-09-15 权限面修正：designer 的 write 白名单只有 decisions——
    # 文件形态它创建不了，功能空转；内联 JSON=命令行单参数，bash python 权限即匹配）：
    # 以 [ 开头=内联 JSON（designer 常用）；否则=文件路径（engineer 全权侧/复杂场景）
    import yaml
    try:
        if batch_src.lstrip().startswith("["):
            return ("[argv 内联 JSON 已退役] PS 5.1 剥内层双引号 + where 里 SQL 字面量 'N' "
                    "与 JSON 定界符同形，argv 通道无解——designer 用 --batch-stdin 行协议"
                    "（stdin 逐字透传，引号免疫）；本参数只收 YAML/JSON 文件路径（engineer 侧）")
        items = yaml.safe_load(Path(batch_src).read_text(encoding="utf-8")) or []
    except Exception as e:
        return f"[批量清单解析失败（YAML/JSON 文件路径）]: {e}"
    if not isinstance(items, list) or not items:
        return "[批量清单为空] 应为列表: [{tag, schema, table, key, where}]"

    try:
        from dws_db import create_executor_for_schema
        executor = create_executor_for_schema(target_schema, role="etl")
    except Exception as e:
        return format_skip(f"无法创建执行器: {e}")
    out = []
    seen = {}  # (schema,table,key,where_lower) -> tag（去重：同表同键同限定只跑一次）
    dup_notes = []
    try:
        if not executor.test_connection():
            return format_skip("数据库连接失败")
        for i, it in enumerate(items, 1):
            if not isinstance(it, dict):
                out.append(f"[{i}] 条目格式错（应为 dict）: {it}")
                continue
            tag = str(it.get("tag") or f"#{i}")
            sch = str(it.get("schema") or "").strip()
            tbl = str(it.get("table") or "").strip()
            key = str(it.get("key") or "").strip()
            where = str(it.get("where") or "").strip()
            if not (tbl and key):
                out.append(f"[{tag}] 缺 table/key——跳过")
                continue
            dedup = (sch.lower(), tbl.lower(), key.lower(), where.lower())
            if dedup in seen:
                dup_notes.append(f"[{tag}] 与 [{seen[dedup]}] 同表同键同限定——去重（结果同）")
                continue
            seen[dedup] = tag
            try:
                sql = build_join_key_sql(sch, tbl, key, where)
                r = executor.execute(sql)
                if not r.success:
                    out.append(f"[{tag}] {sch}.{tbl} key=({key}) where=({where or '无'}) → 执行失败: "
                               f"{str(r.error)[:120]}【自检：字段名/条件写法】")
                    continue
                row = (r.rows or [{}])[0]
                total, uniq = int(row.get("total", 0)), int(row.get("distinct_cnt", 0))
                if total == uniq:
                    out.append(f"[{tag}] {sch}.{tbl} key=({key}) where=({where or '无'}) → ✓ 唯一"
                               f"（{total} 行）——join_key_unique=true 可声明")
                else:
                    _sample = ""
                    try:
                        keys = [k.strip() for k in key.split(",") if k.strip()]
                        ke = ", ".join(keys)
                        s2 = (f"SELECT {ke}, COUNT(1) AS dup_cnt FROM {sch}.{tbl}"
                              + (f" WHERE {where}" if where else "")
                              + f" GROUP BY {ke} HAVING COUNT(1)>1 ORDER BY dup_cnt DESC LIMIT 2")
                        r2 = executor.execute(s2)
                        if r2.success and r2.rows:
                            _sample = " | 重复组: " + "; ".join(
                                ",".join(f"{k}={v}" for k, v in rr.items()) for rr in r2.rows)
                    except Exception:
                        pass
                    out.append(f"[{tag}] {sch}.{tbl} key=({key}) where=({where or '无'}) → ✗ 不唯一"
                               f"（{total} 行/唯一 {uniq}，重复 {total-uniq}）{_sample}"
                               f"——记疑点清单（疑似方向一句话，验证归 engineer）")
            except Exception as e:
                out.append(f"[{tag}] 查询异常: {e}")
    finally:
        try:
            executor.close()
        except Exception:
            pass
    header = [f"批量关联唯一性校验（{len(seen)} 项执行/{len(dup_notes)} 项去重）——按关联逐条带限定："]
    return "\n".join(header + out + dup_notes)


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
    parser.add_argument("--batch", default="",
                        help="批量关联唯一性（YAML/JSON 文件路径，engineer 侧）——同表多关联"
                             "各自带限定逐条校验+自动去重。designer 用 --eval")
    parser.add_argument("--eval", action="store_true",
                        help="评估层唯一动作：草稿随 view 预置（预填表单），stdin 只给 ? 行答案"
                             "（别名|键|限定，heredoc/管道逐字透传引号免疫）——内部重拉草稿合并后"
                             "跑存在性+唯一性，出三段结果单=上报正文；无 stdin=兜底出草稿"
                             "（全预填时当场连跑），需 --rs")
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

    if args.eval:
        if not args.rs:
            print(format_skip("--eval 需要 --rs rs_input.json（草稿派生+别名反解+选源锚点）"))
            return
        try:
            target_schema = read_target_schema_from_rs(args.rs) or args.schema
        except Exception as e:
            print(format_skip(f"读取锚点失败（{args.rs}）: {e}"))
            return
        # BOM 安全读取（PS 5.1 管道 UTF8 带 BOM 前导——utf-8-sig 有则剥无则不动；
        # errors=replace 让坏编码以可读替换符进解析报错，不整命令崩溃）
        if sys.stdin.isatty():
            stdin_text = ""
        else:
            try:
                stdin_text = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
            except AttributeError:
                stdin_text = sys.stdin.read().lstrip("\ufeff")
        if not stdin_text.strip():
            try:
                rs = json.loads(Path(args.rs).read_text(encoding="utf-8"))
                plan = build_eval_plan_data(rs)
                if plan["run"] and all(r["key"] for r in plan["run"]):
                    print(run_eval(args.rs, target_schema, ""))  # 全预填：无 ? 行，当场连跑
                else:
                    print(render_eval_draft(rs))  # 兜底草稿（正常流程草稿随 view 预置）
            except Exception as e:
                print(f"[eval 失败] {e}")
            return
        print(run_eval(args.rs, target_schema, stdin_text))
        return

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

    if args.batch:
        # 批量模式：target schema 锚点同单查（--rs/--ts 任一）
        ts_anchor = args.ts or args.rs
        if not ts_anchor:
            print(format_skip("批量模式需要 --rs 或 --ts 锚点（选数据源）"))
            return
        target_schema = ""
        for anchor, reader in ((args.ts, read_target_schema), (args.rs, read_target_schema_from_rs)):
            if anchor:
                try:
                    target_schema = reader(anchor)
                except Exception:
                    pass
                if target_schema:
                    break
        if not target_schema:
            target_schema = args.schema
        print(run_batch_check(target_schema, args.batch))
        return

    if not args.check_join_key:
        parser.error("请指定模式：--eval（评估层唯一动作，需 --rs）/ "
                     "--check-join-key（单查唯一性，engineer 定向验证）/ "
                     "--check-overlap（重叠率）/ --batch 文件（批量，engineer）")

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
