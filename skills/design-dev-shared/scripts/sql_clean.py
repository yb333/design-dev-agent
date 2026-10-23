# -*- coding: utf-8 -*-
"""sql_clean —— 平台 SQL 解析预处理链（vendor 拷贝，全仓围栏侧唯一入口）。

★ vendor 纪律（同 baseline_v1 schema 的 vendor 协议）：
  - **权威在 analyzer 仓**（dws-analyzer-skill/dws-pipeline-analyzer/references/engine.py
    @8d41a04）——坑的演进驱动力在逆向侧（新制品包先经过它），修复一律改彼侧权威，
    本仓随后 re-vendor（拷贝+更新版本锚），**不在本文件单边演化**（单边改=两份分叉，
    tests/test_vendor_sync.py 的指纹联锁会拦）。
  - 围栏私有的变换不进本文件——写在消费方（sql_fence）自己的 fence-local 层
    （本文件保持纯拷贝，指纹可比）。
  - 用途：让 sqlglot 吃下术加平台 SQL（parse 存活门票）——剔注释/DWS 特有语法清理/
    占位符字面量化。**内存只读变换，不改 SQL 文件本体**（UT 阶段的 substitute_params
    语义替换拿到的仍是文件原文，两阶段互不干扰）。
"""
import re

# DWS 语法清理正则
_DIST_BY_PATTERN = re.compile(
    r"\bDISTRIBUTE[D]?\s+BY\s+(?:HASH\s*\([^)]+\)|REPLICATION|ROUNDROBIN)",
    re.IGNORECASE | re.DOTALL,
)
_TO_GROUP_PATTERN = re.compile(r"\bTO\s+GROUP\s+\S+", re.IGNORECASE)
# PARTITION(part_name) 语法（DWS/GaussDB 分区查询，sqlglot 不支持）
_PARTITION_PATTERN = re.compile(r"\s+PARTITION\s*\([^)]+\)", re.IGNORECASE)
_WITH_PARAMS_PATTERN = re.compile(
    r"\)\s*WITH\s*\(\s*"
    r"(?:ORIENTATION\s*=\s*(?:COLUMN|ROW)\s*,?\s*)?"
    r"(?:COMPRESSION\s*=\s*(?:LOW|MIDDLE|HIGH)\s*,?\s*)?"
    r"(?:\w+\s*=\s*\w+\s*,?\s*)*"
    r"\)",
    re.IGNORECASE,
)
_PARAM_PLACEHOLDER = re.compile(r"\$\{[^}]+\}")
# 平台变量替换语法: #var_name = value# （成对的 # 包裹）
_PLATFORM_VAR_PATTERN = re.compile(r"#[^#]*?#", re.DOTALL)
# 行注释：-- 到行尾（-- 后至少一个空格或直接到行尾，兼容 --xxx 和 -- xxx）
_LINE_COMMENT_RE = re.compile(r"--[^\n]*")
# 块注释：/* */（非贪婪，跨行）
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)

_SYSDATE_PATTERN = re.compile(r"\bSYSDATE\s*\(\s*\)", re.IGNORECASE)
_SYSDATE_NOPAREN_PATTERN = re.compile(r"\bSYSDATE\b(?!\s*\()", re.IGNORECASE)


def _strip_sql_comments(sql: str) -> str:
    """剔除 SQL 注释（行注释 -- 和块注释 /* */）。

    必须在按分号分割语句之前调用——注释里的分号会导致 split(";")
    错误截断 SQL，使截断点之后的 FROM/JOIN 表名全部丢失。

    注意：字符串字面量内的 -- 或 /* 不应被误删，但 SQL 查询里
    字符串包含注释语法的场景极少，MVP 不做字符串感知的剔除。
    """
    # 先剔块注释（可能跨行），再剔行注释
    sql = _BLOCK_COMMENT_RE.sub(" ", sql)
    sql = _LINE_COMMENT_RE.sub("", sql)
    return sql


def _strip_dws_clauses(sql: str) -> str:
    """移除 DWS 特有语法，供 sqlglot 解析"""
    sql = _DIST_BY_PATTERN.sub("", sql)
    sql = _TO_GROUP_PATTERN.sub("", sql)
    sql = _PARTITION_PATTERN.sub("", sql)
    sql = _WITH_PARAMS_PATTERN.sub(")", sql)
    # sysdate() / sysdate → CURRENT_TIMESTAMP（sqlglot oracle 方言不兼容）
    sql = _SYSDATE_PATTERN.sub("CURRENT_TIMESTAMP", sql)
    sql = _SYSDATE_NOPAREN_PATTERN.sub("CURRENT_TIMESTAMP", sql)
    return sql


def _replace_placeholders(sql: str) -> str:
    """替换平台变量占位符为合法 SQL 值（保留原始变量名）

    支持两种语法:
    1. ${XXX}        → '${XXX}'（字符串字面量，保留变量名）
    2. #var = value# → '#var = value#'（字符串字面量）

    处理 ${XXX} 已在引号内的情况（'${XXX}' → '${XXX}'，不双层引号）
    """
    # 先去掉 '${...}' 的外层引号，避免双层引号
    sql = re.sub(r"'\$\{([^}]+)\}'", r"${\1}", sql)
    sql = re.sub(r"'#[^#]*#'", lambda m: m.group(0)[1:-1], sql)  # '#...#' 去引号
    # 再统一加引号
    sql = _PARAM_PLACEHOLDER.sub(lambda m: "'" + m.group(0) + "'", sql)
    sql = _PLATFORM_VAR_PATTERN.sub(lambda m: "'" + m.group(0) + "'", sql)
    return sql


def clean_platform_sql(sql: str) -> str:
    """围栏消费入口：注释剔除 → DWS 语法清理 → 占位符量化 → 尾分号剥离。

    （本函数为 vendor 侧新增的组合入口——逆向侧的组合发生在 parse_single_sql
    内联处；三个子函数本体与权威侧逐字一致，指纹联锁比对子函数。）
    """
    clean = _strip_sql_comments(sql)
    clean = _strip_dws_clauses(clean)
    clean = _replace_placeholders(clean)
    return clean.strip().rstrip(";").strip()


# SQLGLOT_DIALECT：方言固定 oracle（权威侧同款决策——DWS/GaussDB 兼容 Oracle
# 语法，oracle 方言让 NVL/DECODE/SUBSTR 原样解析不被转写成 COALESCE/CASE）
SQLGLOT_DIALECT = "oracle"
