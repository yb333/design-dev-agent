"""sql_fence —— SQL 级围栏判定纯函数库（docs/specs/opt/05 §二）。

三段审计链第三段（结构→代码）：新 SELECT vs baseline SELECT 的 AST 级比对。
- 老投影列：逐列**结构等价**（双方各自 parse→generate 归一后比较——格式/空白差异消解，
  其余一切文本差异（含语义等价改写如 ='N' 改 <>'Y'）= 越界。笨标准，不做语义等价推断。
- 新列：只允许 change 段声明的新增字段（按输出列名比对）；声明的字段必须出现（漏改）。
- FROM/JOIN/WHERE/GROUP BY：存量冻结；新 JOIN 只允许声明过的（按别名+表名匹配）。
- 不支持的形态（UNION 顶层、SELECT * 等）= 显式违规"机器审不了→人工审查"（原则9），
  绝不静默放行。

调用方（闸门单点在 pipe，coder 经 check_sql 自测为可选习惯）：
  violations = check_sql_fence(baseline_sql, new_sql, rule_decl)
  rule_decl 由 rule_declaration(ts_v2["change"], rule_code) 从 change 段派生。
"""
from typing import Dict, List, Optional

import sqlglot
from sqlglot import exp

# 归一化生成参数：双方走同一生成器，格式/空白差异天然消解；注释剥离
_GEN_KW = {"comments": False}


def _norm(node) -> str:
    return node.sql(**_GEN_KW) if node is not None else ""


def _top_select(tree):
    """取顶层 Select；其他形态（UNION 等）返回 None（机器审不了）。"""
    if isinstance(tree, exp.Select):
        return tree
    if isinstance(tree, exp.Paren):
        return _top_select(tree.this)
    return None


def _projection_names(select) -> Dict[str, str]:
    """输出列名 → 归一化表达式文本。SELECT * 标记为 {'*': '*'}。"""
    out: Dict[str, str] = {}
    for e in select.expressions:
        if isinstance(e, exp.Star):
            return {"*": "*"}
        out[e.alias_or_name] = _norm(e)
    return out


def _join_key(j: exp.Join) -> Optional[tuple]:
    """JOIN 身份 = (表名, 别名)。"""
    table = j.this
    if isinstance(table, exp.Table):
        return (table.name, table.alias_or_name)
    return None


def rule_declaration(v2_change: dict, rule_code: str) -> dict:
    """从 ts_v2.change 段派生单规则的许可声明。"""
    fields, joins = [], []
    for f in (v2_change or {}).get("fields", []):
        if rule_code in f.get("placed_rules", []):
            fields.append(f["field"])
            joins.extend(j for j in f.get("new_joins", []) if j.get("rule") == rule_code)
    return {"rule": rule_code, "fields": fields, "new_joins": joins}


def check_sql_fence(baseline_sql: str, new_sql: str, rule_decl: dict) -> List[dict]:
    """返回违规清单（空=通过）。"""
    v: List[dict] = []

    def bad(msg):
        v.append({"type": "overreach", "message": f"[SQL围栏][{rule_decl.get('rule', '?')}] {msg}"})

    def miss(msg):
        v.append({"type": "missing", "message": f"[SQL围栏][{rule_decl.get('rule', '?')}] {msg}"})

    try:
        b_tree = sqlglot.parse_one(baseline_sql)
        n_tree = sqlglot.parse_one(new_sql)
    except Exception as e:  # 解析失败：交给常规 SQL 报错链路，这里只报不可比
        bad(f"SQL 解析失败，无法围栏比对：{e}")
        return v

    b_sel, n_sel = _top_select(b_tree), _top_select(n_tree)
    if b_sel is None or n_sel is None:
        bad("顶层非单 SELECT（UNION 等形态）——机器审不了，转人工审查（原则9）")
        return v

    # ---- CTE：存量冻结（add_field 不需要动 CTE；需要时走矩阵扩展）----
    b_with = _norm(b_sel.args.get("with")) if b_sel.args.get("with") else ""
    n_with = _norm(n_sel.args.get("with")) if n_sel.args.get("with") else ""
    if b_with != n_with:
        bad("WITH/CTE 被修改——add_field 冻结（新 JOIN 需要包 CTE 时先扩展围栏矩阵）")

    # ---- FROM 主表：冻结 ----
    b_from = b_sel.args.get("from")
    n_from = n_sel.args.get("from")
    if _norm(b_from.this if b_from else None) != _norm(n_from.this if n_from else None):
        bad("FROM 主表被修改——冻结")

    # ---- JOIN：存量冻结 + 新 JOIN 须声明 ----
    b_joins = {_join_key(j) for j in b_sel.find_all(exp.Join)}
    n_joins = {_join_key(j) for j in n_sel.find_all(exp.Join)}
    declared = {(j.get("table", "").split(".")[-1], j.get("alias", ""))
                for j in rule_decl.get("new_joins", [])}
    for gone in b_joins - n_joins:
        bad(f"存量 JOIN 被删除/改写 {gone}")
    for added in n_joins - b_joins - declared:
        bad(f"未声明的新 JOIN {added}（新 JOIN 必须先在 change 段声明）")

    # ---- WHERE / GROUP BY：冻结 ----
    if _norm(b_sel.args.get("where")) != _norm(n_sel.args.get("where")):
        bad("WHERE 被修改——冻结（等价改写也需先声明，笨标准）")
    if _norm(b_sel.args.get("group")) != _norm(n_sel.args.get("group")):
        bad("GROUP BY 被修改——冻结")

    # ---- 投影列：老列不动 + 仅追加声明列 + 声明列必须落 ----
    b_cols = _projection_names(b_sel)
    n_cols = _projection_names(n_sel)
    if "*" in b_cols or "*" in n_cols:
        bad("SELECT * 无法逐列审计——存量含 * 请先改写为显式列清单（另立变更）")
        return v
    declared_fields = set(rule_decl.get("fields", []))
    for name, b_expr in b_cols.items():
        if name not in n_cols:
            bad(f"老列 {name!r} 丢失")
        elif n_cols[name] != b_expr:
            bad(f"老列 {name!r} 表达式被修改：{b_expr!r} → {n_cols[name]!r}")
    for name in n_cols:
        if name not in b_cols and name not in declared_fields:
            bad(f"未声明的新列 {name!r}（新列只允许 change 声明的字段）")
    for name in declared_fields:
        if name not in n_cols:
            miss(f"声明字段 {name!r} 未出现在 SELECT——漏改")
    return v
