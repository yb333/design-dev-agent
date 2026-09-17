#!/usr/bin/env python3
"""
UT 链路函数库：被 ut_precheck.py / ut_execute.py import，自身不可单独执行。

new-pipe 的 UT 执行走两阶段（ut_precheck 秒级预检 + ut_execute 分钟级执行），
两者共用本库的函数。本库**不含**单执行器入口——历史 main() 单执行器已被
6a/6b 两阶段流程取代（如需独立排查，直接调 ut_precheck/ut_execute）。

提供的函数：
- 参数替换：resolve_test_value / substitute_params / resolve_all_params
- SELECT 包装：wrap_insert / wrap_write / read_select
- UT 检查：run_ut_check（主键唯一 / 审计非空 / 行数，失败抓样例供归因）
"""

import sys
import re
import json
from pathlib import Path
from datetime import datetime, timedelta

# 行缓冲 stdout——子进程模式下主控能实时看到 DDL/SELECT/INSERT 各节点进度
try:
    sys.stdout.reconfigure(line_buffering=True)
except AttributeError:
    pass

# 依赖全在 shared 同目录（dws_db/sql_parse），无需跨目录引导
from dws_db import load_test_params
from sql_parse import read_sql


# ============================================================
# 参数替换：执行前把 ${PARAM} 替换为实际值（模拟术加平台运行时注入）
# ============================================================

# 动态表达式注册表：当天日期类参数在 UT 时按规则算出值
DYNAMIC_EXPRS = {
    "today_ymdhms":  lambda: datetime.now().strftime("%Y%m%d") + "000000",            # 批次号
    "today_ymd":     lambda: datetime.now().strftime("%Y%m%d"),                       # 业务日期
    "yesterday_ymd": lambda: (datetime.now() - timedelta(days=1)).strftime("%Y%m%d"),  # 增量起点（T+1）
}


def resolve_test_value(param_name: str, cfg: dict | None) -> str | None:
    """解析单个参数的测试值。

    cfg 取自 db-sources.json 的 test_params.{param_name}，两种形态：
      {"type": "dynamic", "expr": "today_ymdhms"}  → 按表达式算
      {"type": "static",  "value": "20260101"}      → 直接用值
    cfg 为 None → 返回 None（调用方 fail loud）
    """
    if not cfg:
        return None
    t = cfg.get("type", "static")
    if t == "dynamic":
        expr = cfg.get("expr", "")
        fn = DYNAMIC_EXPRS.get(expr)
        if not fn:
            raise ValueError(f"未知动态表达式: {expr}（参数 {param_name}）")
        return fn()
    # static
    return cfg.get("value", "")


def substitute_params(sql: str, param_values: dict) -> str:
    """${PARAM} → 实际值。SQL 里用了某参数但 param_values 没值 → fail loud。"""
    def replacer(m):
        name = m.group(1)
        if name not in param_values:
            raise ValueError(f"SQL 用了参数 ${{{name}}}，但没配测试值")
        return str(param_values[name])
    return re.sub(r"\$\{([A-Z_][A-Z0-9_]*)\}", replacer, sql)


def resolve_all_params(ts: dict, config_path: str) -> dict:
    """算出全部参数的实际值（UT 执行前替换 ${PARAM}）。

    三层兜底链（都不缺值，不 exit）：
      1. test_params 配置（db-sources.json，精确/动态，最高优先级）
      2. ts.exec_params.{name}.default_value（标准参数内置 / designer 给的业务参数默认值）
      3. 类型兜底（按 value_type 推：date→今天，number→0，string→空）
    第 2/3 层 warn 提示（UT 验证 SQL 结构不受影响），不阻断。
    """
    declared = ts.get("meta", {}).get("schedule", {}).get("exec_params", {})
    if not declared:
        return {}
    test_cfg = load_test_params(config_path)
    values = {}
    defaulted = []
    for pname, pdecl in declared.items():
        # 1. test_params 配置（最高优先级）
        val = resolve_test_value(pname, test_cfg.get(pname))
        if val is None or val == "":
            # 2. ts.default_value（标准参数内置 / designer 给）
            dv = (pdecl or {}).get("default_value")
            if dv is not None and dv != "" and dv != {}:
                val = _resolve_default_value(pname, dv)
                defaulted.append(pname)
            else:
                # 3. 类型兜底（最后退路）
                val = _type_fallback(pdecl)
                defaulted.append(pname)
        values[pname] = val
    if defaulted:
        print(
            f"⚠️ 以下参数未在 test_params 配置，用 default_value/类型兜底: {', '.join(defaulted)}",
            file=sys.stderr,
        )
        print(
            "   UT 验证 SQL 结构不受影响；如需精确数据请在 test_params 段配真实值",
            file=sys.stderr,
        )
    return values


def _resolve_default_value(pname: str, dv) -> str:
    """解析 ts.default_value：支持裸串（=static）或 {type, expr/value}（=static/dynamic）。"""
    if isinstance(dv, dict):
        return resolve_test_value(pname, dv) or ""
    return str(dv)


def _type_fallback(pdecl: dict) -> str:
    """参数既无 test_params 也无 default_value 时的最后兜底（按 value_type 推）。"""
    vt = (pdecl or {}).get("value_type", "string")
    if vt == "date":
        return datetime.now().strftime("%Y%m%d")
    if vt == "datetime":
        return datetime.now().strftime("%Y%m%d%H%M%S")
    if vt == "number":
        return "0"
    return ""



def rule_output_fields(rule: dict) -> set:
    """规则产出列集（三桶 target 并集，小写）——INSERT/MERGE 列清单交集过滤用。

    2026-09-15 定调"列清单=结构源序 ∩ 规则产出列"：部分来源资产（多规则写同表/
    accumulate）单规则只产子集，其余列不写——INSERT 缺省 NULL（全新行等价显式
    NULL 补位），MERGE 的 UPDATE SET 只 SET 产出列（**保留其余列旧值**——全列 SET
    +NULL 补位会把本规则不负责的列清成 NULL，是 bug 不是惯例）。direct 桶
    'alias.col AS target' 取 AS 后段（装配产物一律带 AS）。
    """
    out = set()
    f = rule.get("fields") or {}
    for p in (f.get("processed") or []):
        if isinstance(p, dict) and p.get("target"):
            out.add(str(p["target"]).lower())
    for a in (f.get("assign") or []):
        if isinstance(a, dict) and a.get("target"):
            out.add(str(a["target"]).lower())
    for d in (f.get("direct") or []):
        s = str(d)
        t = s.rsplit(" AS ", 1)[-1].strip() if " AS " in s else s.rsplit(".", 1)[-1].strip()
        if t:
            out.add(t.lower())
    if not out:
        # 兼容旧形态（rule.fields-only 更早的 field_targets 数组；opt baseline 档案）
        for t in (rule.get("field_targets") or []):
            if str(t).strip():
                out.add(str(t).strip().lower())
    return out


def _resolve_insert_columns(table_fields: list, produced: set = None) -> list[str]:
    """INSERT 字段列表——结构源序 ∩ 规则产出列（2026-09-15 精确化）。

    权威仍是结构源：ts.tables.{目标表}.fields（DDL 同源，顺序=装配顺序=切片顺序），
    不从 SELECT 文本解析（2026-09-11 内网实证 CTE 炸批的教训不回退）；produced
    （规则三桶 target 集，rule_output_fields 产）非空时按结构源序过滤到产出列（空集/
    None=全列——旧档无产出声明保守全列）——
    coder 不必为未产出列写 NULL AS x 凑全列（INSERT 缺省 NULL 等价；MERGE SET
    产出列=保留其余列旧值）。produced=None 全列（单规则全字段/兼容旧调用）。

    SELECT 实际输出列与清单的一致性由 6a describe 对账守（权威解释器是数据库）。
    平台等价性：平台按 SELECT 输出顺序拼列（位置对齐）——UT 清单=SELECT 实际
    输出（产出列）与平台形态一致；coder 按切片顺序输出 + 6a 列序对账。

    Args:
        table_fields: 表的全部字段（dict 列表取 target_field；或字符串列表）。
        produced: 规则产出列集（小写；空集/None=不过滤全列）。
    返回: 字段名列表（结构源顺序过滤后）；空清单抛 ValueError（fail-visible）。
    """
    if table_fields and isinstance(table_fields[0], dict):
        names = [f.get("target_field", "") for f in table_fields]
    elif table_fields:
        names = [str(f) for f in table_fields]
    else:
        names = []
    names = [n for n in names if n]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        raise ValueError(f"INSERT 字段清单含重复列 {dup}——结构源异常（同表字段应被 C9 查重拦）")
    if not names:
        raise ValueError(
            "INSERT 字段清单为空——ts.tables 里目标表无字段声明（检查 ts 装配/表短名匹配）")
    if produced:
        _pl = {str(p).lower() for p in produced}
        _miss = sorted(_pl - {n.lower() for n in names})
        if _miss:
            raise ValueError(f"规则产出列不在目标表结构源内: {_miss}——对照 ts.tables 改 field_targets/拼写")
        names = [n for n in names if n.lower() in _pl]
        if not names:
            raise ValueError("产出列过滤后清单为空——规则 fields 三桶无有效 target")
    return names


def wrap_insert(select_sql: str, target_table: str, table_fields: list,
                produced: set = None) -> str:
    """把 SELECT 包装成 INSERT 语句（模拟平台构建）。

    平台规则：
    - INSERT INTO 目标表 (字段列表)
    - SELECT 内容不变
    - 字段列表 = 结构源序 ∩ 规则产出列（见 _resolve_insert_columns——不从 SELECT 文本解析）

    table_fields: 该表的全部字段（从 tables 段取，已含审计字段）。
    produced: 规则产出列集（rule_output_fields；None=全列）。
    """
    field_names = _resolve_insert_columns(table_fields, produced)
    columns = ",\n    ".join(field_names)

    return f"""INSERT INTO {target_table} (
    {columns}
)
{select_sql.strip().rstrip(';')};
"""


def wrap_write(select_sql: str, target_table: str, table_fields: list,
               load_mode: str = "truncate_table", write_condition: str = "",
               produced: set = None) -> str:
    """按 load_mode + write_condition 把 SELECT 包装成平台写入语句（模拟平台构建）。

    平台规则（用户确认）：目标表别名 T，源（SELECT 结果）别名 T1。
    - truncate_table / no_delete → INSERT（wrap_insert）
    - truncate_partition → INSERT（分区清空由 ut_execute 预处理做，这里仍 INSERT）
    - delete → INSERT（删除由 ut_execute 预处理做，这里仍 INSERT）
    - merge_into / update → MERGE INTO ... USING (SELECT) T1 ON ... WHEN MATCHED/NOT MATCHED

    Args:
        select_sql: coder 产的 SELECT。
        target_table: 目标表全名（schema.table）。
        table_fields: 目标表全部字段（dict列表或字符串列表）。
        load_mode: 写入方式。
        write_condition: 写入条件（merge 的 ON、partition 的分区名、delete 的 WHERE）。
        produced: 规则产出列集（rule_output_fields；None=全列）。MERGE 的 UPDATE SET
            只 SET 产出列——**保留其余列旧值**（全列 SET 会把本规则不负责的列清成 NULL）。
    """
    # 非 merge/update 的都走 INSERT（partition/delete 的清空动作在 ut_execute 预处理）
    if load_mode not in ("merge_into", "update"):
        return wrap_insert(select_sql, target_table, table_fields, produced)

    # MERGE / UPDATE：拼 MERGE INTO 语句
    # ★ 字段列表 = 结构源序 ∩ 规则产出列（见 _resolve_insert_columns；列序一致性由 6a describe 对账守）
    field_names = _resolve_insert_columns(table_fields, produced)

    columns = ", ".join(field_names)
    # UPDATE SET：源字段赋值（T1.col 对应每个目标字段，审计字段不更新由业务定，这里全量 UPDATE）
    update_set = ",\n        ".join(f"T.{c} = T1.{c}" for c in field_names)
    on_cond = write_condition.strip() if write_condition.strip() else "1=1"

    return f"""MERGE INTO {target_table} T
USING (
{select_sql.strip().rstrip(';')}
) T1
ON {on_cond}
WHEN MATCHED THEN UPDATE SET
        {update_set}
WHEN NOT MATCHED THEN INSERT (
        {columns}
    ) VALUES (
        {", ".join(f"T1.{c}" for c in field_names)}
    );
"""


def read_select(select_dir: Path, rule_code: str) -> str:
    """读 coder 产的 SELECT 文件。

    文件名约定：{rule_code}.sql 或 {rule_code}_描述_loadmode.sql
    确定文件名优先，不以 glob 模糊匹配。
    """
    # 尝试精确文件名
    path = select_dir / f"{rule_code}.sql"
    if path.exists():
        return path.read_text(encoding="utf-8")
    # coder 可能产出了 {rule_code}_描述.sql 格式，用前缀确定匹配（不用两侧通配）
    candidates = sorted(select_dir.glob(f"{rule_code}_*.sql"))
    if candidates:
        return candidates[0].read_text(encoding="utf-8")
    return ""


def dq_filename(idx: int, check_type: str) -> str:
    """DQ 检查 SQL 文件确定名：dq_{NN}_{清洗check_type}.sql。

    唯一键是规则数组序号（check_type 是"检查类型"不是规则身份，重复是
    常态——两条空值检查同名文件会互相覆盖静默丢检查）；check_type 清洗后保留
    在文件名里（闸口② 人看文件友好）：去首尾空格，非字母/数字/中文/下划线换 `_`。
    单点在本函数：UT 侧（run_dq_checks）与装配侧（assemble_dq 派生校验/producer SKILL 契约）
    同源派生，两侧不自拼。序号两侧按同一 dq.json 的 rules 顺序（闸口①后冻结）。
    """
    safe = re.sub(r"[^\w\u4e00-\u9fff]+", "_", (check_type or "").strip())
    return f"dq_{idx:02d}_{safe}.sql"


def load_dq_rules(build_dir) -> list:
    """读 DQ 规则清单（双源，2026-09-14 DQ 拆分）：build/dq.json 优先；无则兜底旧 ts.json 的 dq_rules。

    返回规则列表（条目含 mode/anchored_fields 等 dq.json 新字段；旧 ts 兜底条目无新字段，
    消费方按缺省处理）。两处都无 → 空列表（DQ 为空的资产合法态）。
    """
    build = Path(build_dir)
    dq_json = build / "dq.json"
    if dq_json.exists():
        try:
            return json.loads(dq_json.read_text(encoding="utf-8")).get("rules") or []
        except (json.JSONDecodeError, OSError):
            pass
    ts_json = build / "ts.json"
    if ts_json.exists():
        try:
            legacy = json.loads(ts_json.read_text(encoding="utf-8")).get("dq_rules") or []
            return [{**d, "mode": d.get("mode") or "assertion"} for d in legacy]
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _dq_err_hint(err_text) -> str:
    """DQ SQL 执行报错的分类提示（2026-09-15 内网反馈：报错无提示，producer 得自己推测）：
    给修复方向——语法/聚合结构/列/类型/权限，分清 SQL 写法问题还是环境问题。"""
    low = str(err_text or "").lower()
    if any(k in low for k in ("syntax", "语法", "or near")):
        return "【提示】语法错——核函数名/括号/方言（DWS 不认的写法查替换）"
    if any(k in low for k in ("must appear in the group by", "group by")):
        return "【提示】聚合结构错——非聚合列须进 GROUP BY 或包聚合函数"
    if any(k in low for k in ("column", "字段", "does not exist", "不存在")):
        return "【提示】列不存在——核字段拼写/别名归属（对照目标表/源表字段）"
    if any(k in low for k in ("invalid input", "无效", "type", "类型")):
        return "【提示】类型/字面量形态——核 WHERE 值写法与列类型匹配"
    if any(k in low for k in ("permission", "denied", "权限")):
        return "【提示】权限/环境问题——非 SQL 写法问题"
    return ""


def run_dq_checks(executor, dq_dir, dq_rules: list, param_values: dict,
                  sample_limit: int = 5) -> list[dict]:
    """执行 DQ 检查 SQL（对 UT 已灌数的目标表）——DQ 是上生产的制品，交付前必须执行验证。

    契约：DQ SELECT = **违规行探测器**——0 行通过，非 0 行告警；阈值/比例逻辑全收在
    SQL 的 WHERE/HAVING 里，这里只判行数。文件名 = dq_filename（dq_{NN}_{清洗
    check_type}.sql，序号消重名、清洗消非法字符），缺文件 = 发现项（coder 未按
    切片 _file 契约产出）。

    行数用 COUNT 包裹查（不拉全量结果集），告警才追加 LIMIT 采样抓违规行样例。
    返回 [{rule_name, check_type, mode, waived, file, status, detail, rows, samples}]，status：
    PASS（0 行）/ ALERT（非 0 行）/ FAIL（执行报错/参数缺测试值）/ MISSING（文件缺失）。
    分流（2026-09-14 DQ 拆分后）：FAIL/MISSING 回 dws-dq-producer（SQL 类）；ALERT 归闸口②
    人判三选一（回改 / 取消调口径 / 豁免），零自动回路。
    """
    results = []
    for i, rule in enumerate(dq_rules or [], 1):
        check_type = (rule.get("check_type") or "").strip()
        rule_name = rule.get("rule_name") or check_type
        fname = dq_filename(i, check_type)
        entry = {"rule_name": rule_name, "check_type": check_type, "file": fname,
                 "mode": rule.get("mode") or "assertion", "waived": bool(rule.get("waived")),
                 "status": "PASS", "detail": "", "rows": 0, "samples": []}
        fpath = Path(dq_dir) / fname
        if not check_type or not fpath.exists():
            entry["status"] = "MISSING"
            entry["detail"] = f"检查 SQL 文件缺失（预期 {fname}）"
            results.append(entry)
            continue
        sql = read_sql(str(fpath)).strip().rstrip(";")
        try:
            sql = substitute_params(sql, param_values)
        except ValueError as ve:
            entry["status"] = "FAIL"
            entry["detail"] = str(ve)
            results.append(entry)
            continue
        count_sql = f"SELECT COUNT(*) AS cnt FROM ({sql}) _dq_check"
        r = executor.execute(count_sql)
        if not r.success:
            entry["status"] = "FAIL"
            _hint = _dq_err_hint(r.error)
            entry["detail"] = f"执行失败: {(r.error or '')[:200]}" + (f" | {_hint}" if _hint else "")
            results.append(entry)
            continue
        cnt = ((r.rows or [{}])[0].get("cnt", 0)) or 0
        entry["rows"] = cnt
        if cnt:
            entry["status"] = "ALERT"
            entry["detail"] = f"{cnt} 行违规（0 行=通过，非 0 行=告警——方向反/阈值不合理/数据真脏三岔，闸口②人判）"
            sample_sql = f"SELECT * FROM ({sql}) _dq_check LIMIT {sample_limit}"
            rs = executor.execute(sample_sql)
            entry["samples"] = [" | ".join(f"{k}={v}" for k, v in row.items())
                                for row in (rs.rows or [])[:sample_limit]]
        else:
            entry["detail"] = "0 行，通过"
        results.append(entry)
    return results



def _find_cte_section_end(sql: str) -> int | None:
    """找 WITH CTE 定义段的结束位置（最后一个 CTE 体闭合括号后）。

    用于判断主表位置是否在 CTE 定义之后。
    返回字符位置；找不到返回 None。
    """
    # 简化：找 WITH 后的括号配对，最后一个 ) AS 之前的 ) 就是 CTE 结束
    # 更简单：找 "WITH ... ) SELECT" 模式里的 ) 位置
    import re
    # 找 CTE 定义结束（最后的 ")" 在主 SELECT 之前）
    # 主 SELECT 的标志：) SELECT 或 ) 主查询
    m = re.search(r'\)\s*(?:SELECT|INSERT)', sql, re.IGNORECASE)
    if m:
        return m.start()  # ) 的位置
    return None


def run_ut_check(executor, target_table: str, business_key: list, audit_fields: dict) -> list[dict]:
    """跑 UT 检查，返回检查结果列表。

    每个 entry 含 sql 字段（执行的 SQL），供 ut_execute 落地 debug 用。
    """

    results = []

    # 检查1: 行数
    sql = f"SELECT COUNT(*) AS cnt FROM {target_table}"
    r = executor.execute(sql)
    if r.success and r.rows:
        count = r.rows[0]["cnt"]
        results.append({
            "check": "行数合理",
            "status": "PASS" if count > 0 else "WARN",
            "detail": f"{count} 行" + ("（为空，确认源表是否有数据）" if count == 0 else ""),
            "sql": sql,
        })
    else:
        results.append({
            "check": "行数合理",
            "status": "FAIL",
            "detail": f"查询失败: {r.error}",
            "sql": sql,
        })

    # 检查2: 业务主键唯一（重复时抓样例供 designer 归因，不抓一堆）
    if business_key:
        key_cols = ", ".join(business_key)
        sql = f"SELECT {key_cols}, COUNT(*) AS cnt FROM {target_table} GROUP BY {key_cols} HAVING COUNT(*) > 1 LIMIT 5"
        r = executor.execute(sql)
        if r.success:
            dup_count = len(r.rows)
            entry = {
                "check": "业务主键唯一",
                "status": "PASS" if dup_count == 0 else "FAIL",
                "detail": f"{'无重复' if dup_count == 0 else f'{dup_count} 个重复键（最多展示5个）'}（键: {key_cols}）",
                "sql": sql,
            }
            if dup_count > 0:
                entry["samples"] = [dict(row) for row in r.rows]
            results.append(entry)
        else:
            results.append({
                "check": "业务主键唯一",
                "status": "FAIL",
                "detail": f"查询失败: {r.error}",
                "sql": sql,
            })

    # 检查3: 审计字段非空（有空值时抓样例）
    for aname in audit_fields.keys():
        sql = f"SELECT COUNT(*) AS cnt FROM {target_table} WHERE {aname} IS NULL"
        r = executor.execute(sql)
        if r.success and r.rows:
            null_count = r.rows[0]["cnt"]
            entry = {
                "check": f"审计字段非空({aname})",
                "status": "PASS" if null_count == 0 else "FAIL",
                "detail": f"{null_count} 行为空" if null_count > 0 else "无空值",
                "sql": sql,
            }
            if null_count > 0:
                # 抓3行空值样例，供 designer 判断是关联 LEFT JOIN 配错还是源数据问题
                samp_sql = f"SELECT * FROM {target_table} WHERE {aname} IS NULL LIMIT 3"
                rs = executor.execute(samp_sql)
                if rs.success and rs.rows:
                    entry["samples"] = [dict(row) for row in rs.rows]
            results.append(entry)

    return results
