#!/usr/bin/env python3
"""
输入预检: 校验 rs_input.json 的完整性。

独立于 preprocess.py（只做转换），本脚本只做校验。
用户修改 mapping.xlsx 或 RS.md 后，重新跑 preprocess 转换，再跑本脚本校验。

用法:
    python precheck.py --input rs_input.json
    python precheck.py --input rs_input.json --output precheck_report.md
"""

import sys
import argparse
from typing import Any
from pathlib import Path


class PrecheckResult:
    def __init__(self):
        self.passed: list[str] = []
        self.warnings: list[str] = []
        self.errors: list[str] = []

    @property
    def return_code(self) -> int:
        if self.errors:
            return 2  # INCOMPLETE
        if self.warnings:
            return 1  # WARNING
        return 0  # PASS

    def add_pass(self, msg: str):
        self.passed.append(msg)

    def add_warn(self, msg: str):
        self.warnings.append(msg)

    def add_error(self, msg: str):
        self.errors.append(msg)

    def summary(self) -> str:
        lines = [
            f"预检结果: {'PASS' if self.return_code == 0 else 'WARNING' if self.return_code == 1 else 'INCOMPLETE'}",
            f"  通过: {len(self.passed)}  警告: {len(self.warnings)}  错误: {len(self.errors)}",
        ]
        if self.warnings:
            lines.append("警告:")
            for w in self.warnings:
                lines.append(f"  ⚠ {w}")
        if self.errors:
            lines.append("错误:")
            for e in self.errors:
                lines.append(f"  ✗ {e}")
        return "\n".join(lines)


# 合法的映射规则类型
VALID_RULES = {"直接复制", "数据加工", "赋值", "序列"}


def precheck(
    rs_input: dict[str, Any],
    cache_path: Path | None = None,
    refresh_schema: bool = False,
    decision_path: Path | None = None,
    rs_input_path: Path | None = None,
) -> PrecheckResult:
    """预检 rs_input.json 完整性。

    Args:
        rs_input: rs_input.json 的 dict。
        cache_path: 表结构缓存路径（schema_cache.json），None 则不缓存。
        refresh_schema: 强制连库刷新缓存（忽略过期判断）。
        decision_path: 类型风险决策文件路径（type_risk_decision.yaml），None 则不做类型风险检测。
        rs_input_path: rs_input.json 文件路径。决策通过后回写它（转换字段改"数据加工"，
            让类型决策流进主链路 designer→coder），并同步 rs_input_view.json。None 则只校验不回写。
    """
    result = PrecheckResult()

    # 1. 目标表基本信息
    target = rs_input.get("meta", {}).get("target", {})
    # rs_input 的 target 结构是 {f_table: {schema, table, cn}, i_view: {schema, table, cn}}
    f_table = target.get("f_table", {})
    target_schema = f_table.get("schema", "")
    target_table = f_table.get("table", "")
    if not target_schema or not target_table:
        result.add_error("目标表 schema/table 缺失")
    else:
        result.add_pass(f"目标表: {target_schema}.{target_table}")

    # 2. 源表
    source_tables = rs_input.get("source_tables", [])
    if not source_tables:
        result.add_error("无源表 (source_tables 为空)")
    else:
        result.add_pass(f"源表数: {len(source_tables)}")
        for st in source_tables:
            if not st.get("source_alias"):
                result.add_warn(f"源表 {st.get('source_table', '?')} 缺少别名 (source_alias)")

    # 3. 字段映射 (含映射规则交叉校验)
    field_mappings = rs_input.get("field_mappings", [])
    if not field_mappings:
        result.add_error("无字段映射 (field_mappings 为空)")
    else:
        result.add_pass(f"字段映射数: {len(field_mappings)}")

        for fm in field_mappings:
            target_field = fm.get("target_column", "")
            if not target_field:
                result.add_error("存在无目标字段名的映射行")
                continue

            rule = (fm.get("transform_rule") or fm.get("mapping_rule") or "").strip()
            expr = (fm.get("transform_detail") or fm.get("mapping_expression") or "").strip()
            source_field = (fm.get("source_column") or "").strip()

            # 3a. 映射规则必须有值且合法
            if not rule:
                result.add_error(f"字段 {target_field} 缺少映射规则")
                continue
            if rule not in VALID_RULES:
                result.add_error(f"字段 {target_field} 的映射规则 '{rule}' 不合法 (应为: 直接复制/数据加工/赋值/序列)")
                continue

            # 3b. 交叉校验
            if rule == "直接复制":
                # 直接复制填了表达式不报——BA 从关联从表取值时常在这里标注关联关系，是习惯写法
                if not source_field:
                    result.add_error(f"字段 {target_field} 是'直接复制'但缺少来源字段 (source_column)")
            elif rule == "数据加工":
                if not expr or expr == "-":
                    result.add_error(f"字段 {target_field} 是'数据加工'但映射表达式为空 (必须描述加工逻辑)")
                if not source_field:
                    result.add_warn(f"字段 {target_field} 是'数据加工'但没有来源字段, 确认是否为纯派生字段")
            elif rule == "赋值":
                if not expr or expr == "-":
                    result.add_error(f"字段 {target_field} 是'赋值'但映射表达式为空 (必须说明赋什么值)")
            elif rule == "序列":
                result.add_pass(f"字段 {target_field} 是'序列'类型 (自增序列, 特殊处理)")

    # 4. 目标字段重复检查
    seen_fields: dict[str, int] = {}
    for fm in field_mappings:
        tf = fm.get("target_column", "")
        if tf:
            seen_fields[tf] = seen_fields.get(tf, 0) + 1
    for field, count in seen_fields.items():
        if count > 1:
            result.add_error(f"目标字段 '{field}' 重复出现 {count} 次")

    # 5. 调度信息 (来自 RS)
    schedule = rs_input.get("schedule", {})
    no_rs = rs_input.get("_no_rs_mode", False)
    if no_rs:
        # 无RS模式：调度信息是默认值兜底的，提示 designer/export 阶段需注意
        result.add_warn(
            "无RS模式：调度/增量/DQ 信息用默认值兜底（全量调度/T+1/无DQ）。"
            "export 阶段的调度配置和上游依赖可能不完整，建议后续补 RS 再重跑"
        )
    else:
        if not schedule.get("frequency"):
            result.add_warn("调度频率缺失 (RS L07 调度频率)")
        if not schedule.get("upstream"):
            result.add_warn("上游调度任务缺失 (RS L07 湖表调度信息)")

    # 5b. 增量校验：标了增量必须有驱动表+增量字段，驱动表须在 source_tables 里
    incremental_key = (schedule.get("incremental_key") or "").strip()
    incremental_tables = schedule.get("incremental_tables", [])
    # 增量识别方式判断：值为空 或 含"不涉及"/"无"/"全量" 都算全量（覆盖"不涉及（全量调度）"等变体）
    is_incremental = bool(incremental_key) and not any(
        kw in incremental_key for kw in ("不涉及", "无", "全量")
    )

    if is_incremental:
        # 增量场景：必须有驱动表信息
        if not incremental_tables:
            result.add_error(
                f"调度方案标了增量（增量识别方式={incremental_key}），"
                f"但 RS 的'增量表及增量字段'段为空——必须有驱动表+增量字段"
            )
        else:
            result.add_pass(f"增量场景: {len(incremental_tables)} 张驱动表")
            # 校验每张驱动表：须有增量字段、表名须在 source_tables 里
            src_table_names = {
                (st.get("source_table") or "").strip().lower() for st in source_tables
            }
            for it in incremental_tables:
                drv_table = (it.get("source_table") or "").strip()
                drv_key = (it.get("incremental_key") or "").strip()
                if not drv_table:
                    result.add_error("增量驱动表的来源表名为空")
                elif not drv_key:
                    result.add_error(f"增量驱动表 '{drv_table}' 没填增量字段")
                else:
                    # 驱动表名可能是 schema.table 或纯表名，取表名部分比对
                    drv_table_short = drv_table.split(".")[-1].lower()
                    if (drv_table_short not in src_table_names
                            and drv_table.lower() not in src_table_names):
                        result.add_error(
                            f"增量驱动表 '{drv_table}' 不在 mapping 的 source_tables 里"
                            f"（检查表名拼写或补充源表）"
                        )
    else:
        # 全量场景：不应有增量驱动表（RS 增量识别=不涉及，但填了驱动表→矛盾）
        if incremental_tables:
            result.add_warn(
                f"增量识别方式='{incremental_key}'（全量），但 RS 填了 "
                f"{len(incremental_tables)} 张增量驱动表——确认是否应为增量"
            )

    # 6. 别名一致性 + 表别名重复 + 字段级/表级一致性
    # 跳过赋值/序列字段——它们无真实来源表，source_alias 留空是正常的
    entity_aliases = {st.get("source_alias") for st in source_tables if st.get("source_alias")}
    for fm in field_mappings:
        fm_rule = (fm.get("transform_rule") or fm.get("mapping_rule") or "").strip()
        if fm_rule in ("赋值", "序列"):
            continue
        fm_alias = (fm.get("source_alias") or "").strip()
        if not fm_alias:
            # 直接复制/数据加工字段该填 source_alias 没填 → error（多表 JOIN 会歧义，单表也无法定位来源）
            result.add_error(
                f"字段 {fm.get('target_column', '?')} 的 source_alias 为空"
                f"（映射规则='{fm_rule}'，需声明来源表别名以便 JOIN 定位）"
            )
        elif fm_alias not in entity_aliases:
            result.add_error(f"字段 {fm.get('target_column', '?')} 的来源别名 '{fm_alias}' 在实体级 mapping 中不存在")

    # 6a. 表别名重复检查（实体级同别名出现多次 → JOIN 时歧义）
    alias_count: dict[str, int] = {}
    for st in source_tables:
        al = (st.get("source_alias") or "").strip()
        if al:
            alias_count[al] = alias_count.get(al, 0) + 1
    for al, cnt in alias_count.items():
        if cnt > 1:
            result.add_error(f"实体级表别名 '{al}' 重复出现 {cnt} 次（JOIN 时会歧义）")

    # 6b. 字段级与表级一致性：字段级的 source_schema/source_table 应在实体级定义范围内
    # 跳过赋值/序列字段——它们没有真实来源表（赋值是固定值，如 NULL AS），
    # preprocess 可能把表达式的字符解析成 source_table='-'，不该校验
    entity_tables = {
        ((st.get("source_schema") or "").strip(), (st.get("source_table") or "").strip())
        for st in source_tables
    }
    for fm in field_mappings:
        fm_rule = (fm.get("transform_rule") or fm.get("mapping_rule") or "").strip()
        if fm_rule in ("赋值", "序列"):
            continue  # 赋值/序列无来源表，跳过
        fm_sch = (fm.get("source_schema") or "").strip()
        fm_tbl = (fm.get("source_table") or "").strip()
        if fm_sch and fm_tbl and (fm_sch, fm_tbl) not in entity_tables:
            result.add_error(
                f"字段 {fm.get('target_column', '?')} 的来源表 {fm_sch}.{fm_tbl} "
                f"在实体级 mapping 中未定义"
            )

    # 6c. source_column 不能是中文（应是英文物理列名，中文是另一个字段"源表字段中文名"）
    import re as _re
    for fm in field_mappings:
        sc = (fm.get("source_column") or "").strip()
        if sc and _re.search(r"[\u4e00-\u9fff]", sc):
            result.add_error(
                f"字段 {fm.get('target_column', '?')} 的 source_column '{sc}' 含中文"
                f"（应为英文物理列名，中文列名应在'源表字段中文名'列）"
            )

    # 7. 映射表达式模糊术语检查
    biz_terms = ["等等", "之类", "相关", "之类的", "等等等"]
    for fm in field_mappings:
        expr = fm.get("transform_detail") or fm.get("mapping_expression") or ""
        for term in biz_terms:
            if term in str(expr):
                result.add_warn(f"字段 {fm.get('target_column', '?')} 的映射表达式含模糊术语: '{term}'")

    # 8. 审计字段校验
    _check_audit_fields(field_mappings, result)

    # 9. DB 校验：连得上库或缓存可用时，校验来源表/字段真实性（连不上则静默跳过）
    # ★ 短路：静态检查已有 error 就不进 DB 校验（schema/字段都没了，查库白费几百毫秒建连）
    # 缓存命中时不需要连库，不受"连库白费"影响，但仍遵守短路（静态错了先解决静态）
    if not result.errors:
        _check_db_schema(rs_input, result, cache_path, refresh_schema)

    # 10. 类型转换风险检测（仅"直接复制"字段，DB 校验之后）
    # ★ 短路：有 error 就不检测类型风险（先解决前面的错）
    if not result.errors and decision_path is not None:
        _check_type_risk(rs_input, result, decision_path, rs_input_path)

    return result


# ============================================================
# 类型转换风险检测（仅"直接复制"字段）
# ============================================================

# 风险分类：常规（批量定）vs 跨大类（逐个定）
BATCH_RISKS = {"length_overflow", "precision_loss"}
INDIVIDUAL_RISKS = {"type_incompatible"}

# 处置选项（中文，给决策文件校验用）
BATCH_OPTIONS = {"加安全处理", "不加"}
INDIVIDUAL_OPTIONS = {"转换", "不加", "返源端"}


def _detect_type_risks(rs_input: dict) -> tuple[list, list]:
    """检测所有"直接复制"字段的类型风险，返回 (常规风险列表, 跨大类风险列表)。

    每个风险项: {target_column, source_type, target_type, risk}
    跳过：非直接复制字段、缺 source_type/target_type 的字段。
    """
    from type_compat import assess_type_risk, RISK_LABEL_CN

    batch = []
    individual = []
    for fm in rs_input.get("field_mappings", []):
        rule = (fm.get("transform_rule") or fm.get("mapping_rule") or "").strip()
        if rule != "直接复制":
            continue
        source_type = (fm.get("source_type") or "").strip()
        target_type = (fm.get("target_type") or "").strip()
        target_column = (fm.get("target_column") or "").strip()
        if not source_type or not target_type:
            continue  # 缺类型无法判，跳过
        risk = assess_type_risk(source_type, target_type)
        if risk is None:
            continue
        item = {
            "target_column": target_column,
            "source_type": source_type,
            "target_type": target_type,
            "risk": risk,
            "risk_cn": RISK_LABEL_CN.get(risk, risk),
        }
        if risk in BATCH_RISKS:
            batch.append(item)
        else:
            individual.append(item)
    return batch, individual


def _generate_type_risk_skeleton(decision_path: Path, batch: list, individual: list):
    """生成决策文件骨架（全中文 key）。字段列表预填，处置留空待人/agent 填。"""
    lines = [
        "# 类型转换风险处置决策（预检自动生成，编排层 agent 会用 question 问用户填写）",
        "# 只有\"直接复制\"字段才检测类型风险；加工类字段由设计师在 design_logic 处理。",
        "",
    ]
    if batch:
        lines += [
            "# === 批量决策（常规风险：长度超长/精度收窄，性质一致，批量定一个策略）===",
            "# 这些字段风险相同，填一个处置策略即可全部适用。",
            '批量处置策略: ""    # ★ 填：加安全处理 | 不加',
            "                  # 加安全处理 = ETL SELECT 里对超长截取、精度收窄做转换（改 ETL，DDL 目标类型不变）",
            "                  # 不加 = 接受风险，数据问题以报错暴露（人签字接受）",
            "常规风险字段:",
        ]
        for item in batch:
            lines.append(f'  - 目标字段: "{item["target_column"]}"')
            lines.append(f'    源类型: "{item["source_type"]}"')
            lines.append(f'    目标类型: "{item["target_type"]}"')
            lines.append(f'    风险: "{item["risk_cn"]}"')
        lines.append("")
    else:
        lines += ["# （无常规风险字段）", '批量处置策略: ""', "常规风险字段: []", ""]

    if individual:
        lines += [
            "# === 逐个决策（跨大类不兼容，风险高，需单独看每个字段）===",
            "跨大类风险字段:",
        ]
        for item in individual:
            lines.append(f'  - 目标字段: "{item["target_column"]}"')
            lines.append(f'    源类型: "{item["source_type"]}"')
            lines.append(f'    目标类型: "{item["target_type"]}"')
            lines.append(f'    风险: "{item["risk_cn"]}"')
            lines.append('    处置: ""          # ★ 填：转换 | 不加 | 返源端')
            lines.append('                      # 转换 = ETL SELECT 加转换函数 CAST/TO_DATE（改 ETL，DDL 目标类型不变）')
            lines.append('    原因: ""          # 选"返源端"时必填')
        lines.append("")
    else:
        lines += ["# （无跨大类风险字段）", "跨大类风险字段: []", ""]

    decision_path.parent.mkdir(parents=True, exist_ok=True)
    decision_path.write_text("\n".join(lines), encoding="utf-8")


def _validate_type_risk_decision(
    decision_path: Path, batch: list, individual: list, result: PrecheckResult
) -> bool:
    """校验决策文件是否填全。返回 True=通过，False=有问题（已 add_error）。"""
    try:
        import yaml
        dec = yaml.safe_load(decision_path.read_text(encoding="utf-8"))
    except Exception as e:
        result.add_error(f"类型风险决策文件解析失败({decision_path}): {e}")
        return False
    if not isinstance(dec, dict):
        result.add_error(f"类型风险决策文件格式错误（顶层应为字典）")
        return False

    ok = True
    # 字段一致性校验：检测到的风险字段必须和决策文件里的字段清单一致（防 mapping 改了决策过期）
    dec_batch_cols = {item.get("目标字段", "") for item in (dec.get("常规风险字段") or []) if isinstance(item, dict)}
    detected_batch_cols = {item["target_column"] for item in batch}
    if dec_batch_cols != detected_batch_cols:
        missing_b = detected_batch_cols - dec_batch_cols
        extra_b = dec_batch_cols - detected_batch_cols
        hint = []
        if missing_b:
            hint.append(f"决策缺字段: {missing_b}")
        if extra_b:
            hint.append(f"决策多余字段: {extra_b}")
        result.add_error(f"常规风险字段清单与决策不一致（{'; '.join(hint)}），已重新生成骨架，请填后重跑")
        ok = False

    dec_ind_cols = {item.get("目标字段", "") for item in (dec.get("跨大类风险字段") or []) if isinstance(item, dict)}
    detected_ind_cols = {item["target_column"] for item in individual}
    if dec_ind_cols != detected_ind_cols:
        missing_i = detected_ind_cols - dec_ind_cols
        extra_i = dec_ind_cols - detected_ind_cols
        hint = []
        if missing_i:
            hint.append(f"决策缺字段: {missing_i}")
        if extra_i:
            hint.append(f"决策多余字段: {extra_i}")
        result.add_error(f"跨大类风险字段清单与决策不一致（{'; '.join(hint)}），已重新生成骨架，请填后重跑")
        ok = False

    # 批量决策
    if batch:
        strategy = (dec.get("批量处置策略") or "").strip()
        if not strategy:
            result.add_error("类型风险决策未填：批量处置策略（加安全处理/不加）")
            ok = False
        elif strategy not in BATCH_OPTIONS:
            result.add_error(f"批量处置策略 '{strategy}' 不合法（应为：加安全处理/不加）")
            ok = False
    # 跨大类逐个决策
    ind_dec = dec.get("跨大类风险字段") or []
    ind_filled = {item.get("目标字段", ""): item for item in ind_dec if isinstance(item, dict)}
    for item in individual:
        col = item["target_column"]
        entry = ind_filled.get(col)
        if not entry:
            result.add_error(f"类型风险决策未填：跨大类字段 '{col}' 的处置")
            ok = False
            continue
        action = (entry.get("处置") or "").strip()
        if not action:
            result.add_error(f"类型风险决策未填：跨大类字段 '{col}' 的处置")
            ok = False
        elif action not in INDIVIDUAL_OPTIONS:
            result.add_error(f"字段 '{col}' 的处置 '{action}' 不合法（应为：转换/不加/返源端）")
            ok = False
        elif action == "返源端":
            reason = (entry.get("原因") or "").strip()
            if not reason:
                result.add_error(f"字段 '{col}' 选了'返源端'但没填原因")
                ok = False
    return ok


def _apply_type_decision(rs_input: dict, decision_path: Path) -> int:
    """按类型决策把转换字段改"数据加工"（嵌入主链路）。

    类型决策原本只在 precheck 放行（外挂），designer/coder 看不到——字段仍是"直接复制"，
    coder 按直取写 SELECT 漏转换。回写后这些字段走正常加工流程：
    designer 读到加工字段写 field_logic → ts.json → coder 按 logic 加 CAST/TO_DATE。

    注意：所有处置都是改 ETL（SELECT 加转换），DDL 目标类型一律不变。
    返回改写字段数。只处理"直接复制"字段（风险只检它们），已加工的跳过（幂等）。
    """
    import yaml
    try:
        dec = yaml.safe_load(decision_path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    if not isinstance(dec, dict):
        return 0

    batch_on = (dec.get("批量处置策略") or "").strip() == "加安全处理"
    batch_cols = {item.get("目标字段", "") for item in (dec.get("常规风险字段") or []) if isinstance(item, dict)}
    ind_action = {
        item.get("目标字段", ""): (item.get("处置") or "").strip()
        for item in (dec.get("跨大类风险字段") or []) if isinstance(item, dict)
    }

    changed = 0
    for fm in rs_input.get("field_mappings", []):
        col = fm.get("target_column", "")
        if (fm.get("transform_rule") or "").strip() != "直接复制":
            continue
        st, tt = fm.get("source_type", ""), fm.get("target_type", "")
        if col in batch_cols and batch_on:
            fm["transform_rule"] = "数据加工"
            fm["transform_detail"] = f"类型安全处理：{st}→{tt}（长度截取/精度舍入；改 ETL 不改 DDL）"
            changed += 1
        elif ind_action.get(col) == "转换":
            fm["transform_rule"] = "数据加工"
            fm["transform_detail"] = f"类型转换：{st}→{tt}（跨大类；改 ETL 不改 DDL）"
            changed += 1
    return changed


def _sync_compact_view(rs_input: dict, rs_input_path: Path):
    """回写 rs_input 后同步 compact 视图（designer 读 rs_input_view.json，保持一致）。"""
    try:
        import json
        from preprocess import build_compact
        view_path = rs_input_path.parent / "rs_input_view.json"
        view_path.write_text(
            json.dumps(build_compact(rs_input), ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass  # view 同步失败不阻断（designer 还可读完整 rs_input）


def _check_type_risk(rs_input: dict, result: PrecheckResult, decision_path: Path,
                     rs_input_path: Path | None = None):
    """检测直接复制字段的类型风险，阻断式交互（生成骨架→人/agent填→重跑放行+回写）。"""
    import json

    batch, individual = _detect_type_risks(rs_input)

    # 无风险 → 不生成文件、不阻断（含回写后重跑：转换字段已是"数据加工"，不再检测 → 天然幂等）
    if not batch and not individual:
        return

    # 有风险 → 看决策文件是否已填全
    if decision_path.exists():
        if _validate_type_risk_decision(decision_path, batch, individual, result):
            # 决策已填全，放行 + ★回写 rs_input（转换字段改"数据加工"，决策流进主链路）
            if rs_input_path is not None:
                changed = _apply_type_decision(rs_input, decision_path)
                if changed:
                    rs_input_path.write_text(
                        json.dumps(rs_input, ensure_ascii=False, indent=2), encoding="utf-8")
                    _sync_compact_view(rs_input, rs_input_path)
                    result.add_pass(
                        f"类型决策已回写 rs_input：{changed} 个字段改'数据加工'"
                        "（designer 写转换 field_logic，coder 加 CAST——改 ETL 不改 DDL）")
            return
        # 决策没填全或不一致 → 重新生成骨架（覆盖），下面阻断
        result.add_error("类型风险决策文件未填全或字段不一致，已重新生成骨架，请填后重跑")
    else:
        result.add_error(f"检测到类型风险待人工决策（决策文件将生成于：{decision_path}）")

    # 生成/覆盖骨架
    _generate_type_risk_skeleton(decision_path, batch, individual)

    # stdout 输出 TYPE_RISK_PENDING 摘要（给编排层 agent 解析）
    summary = {
        "batch": batch,
        "individual": individual,
        "decision_file": str(decision_path),
    }
    print(f"TYPE_RISK_PENDING {json.dumps(summary, ensure_ascii=False)}")


# 标准审计字段（4个固定字段）
STANDARD_AUDIT_FIELDS = ["del_flag", "crt_cycle_id", "last_upd_cycle_id", "dw_last_update_date"]


def _is_audit_field(fm: dict) -> bool:
    """判断一个字段是否审计字段：备注优先（含'审计字段'），字段名兜底（匹配标准名）。"""
    remark = (fm.get("remark") or "").strip()
    if "审计字段" in remark:
        return True
    target = (fm.get("target_column") or "").strip().lower()
    return target in STANDARD_AUDIT_FIELDS


def _check_audit_fields(field_mappings: list, result: PrecheckResult):
    """审计字段校验：来源提供了则校验规范性，没提供则警告。"""
    audit_fields = [fm for fm in field_mappings if _is_audit_field(fm)]

    if not audit_fields:
        result.add_warn(
            "RS/mapping 未提供审计字段，将由 assemble_ts.py 自动补充 4 个标准审计字段"
            f"（{'、'.join(STANDARD_AUDIT_FIELDS)}）"
        )
        return

    result.add_pass(f"审计字段: mapping 提供了 {len(audit_fields)} 个")

    # 校验数量（标准是 4 个）
    if len(audit_fields) < 4:
        missing = set(STANDARD_AUDIT_FIELDS) - {
            (fm.get("target_column") or "").lower() for fm in audit_fields
        }
        result.add_warn(
            f"审计字段数量不足 ({len(audit_fields)}/4)，缺少: {'、'.join(sorted(missing))}"
            f"，缺失的将由 assemble 自动补充"
        )

    # 逐个校验规范性
    for fm in audit_fields:
        target = fm.get("target_column", "")
        target_lower = target.lower()
        rule = (fm.get("transform_rule") or fm.get("mapping_rule") or "").strip()
        expr = (fm.get("transform_detail") or fm.get("mapping_expression") or "").strip()
        target_type = (fm.get("target_type") or "").strip().lower()

        if target_lower == "del_flag":
            # del_flag 可以有逻辑：赋值（固定值）、直接复制（取源字段）、
            # 数据加工（多表整合判断，如 IF(status='已作废','Y','N')）—— 都是合理的
            pass  # 不限制映射规则类型
        else:
            # 其他三个审计字段应是标准赋值
            if rule and rule not in ("赋值", "直接复制"):
                result.add_warn(
                    f"审计字段 {target} 的映射规则是 '{rule}'，"
                    f"标准审计字段应是赋值（固定值），请确认"
                )

        # 类型与标准比对（审计是平台契约，不因 mapping 漂移；不一致 assemble_ts 强制标准，此处源头提示）
        try:
            from assemble_ts import STANDARD_AUDIT_TEMPLATE as _AUDIT_STD
        except ImportError:
            _AUDIT_STD = {}
        std = _AUDIT_STD.get(target_lower)
        if std:
            mt = (std["type"] or "").lower().replace(" ", "")
            if target_type and target_type.replace(" ", "") != mt:
                result.add_warn(
                    f"审计字段 {target} 类型 '{target_type}' 与标准 '{std['type']}' 不一致"
                    f"（assemble_ts 将按标准覆盖，建议修正 mapping）"
                )


def _load_schema_cache(cache_path: Path) -> dict:
    """读表结构缓存。返回 {cached_at, tables: {schema.table: {col: type}}}。"""
    if not cache_path.exists():
        return {"cached_at": "", "tables": {}}
    try:
        import json

        return json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return {"cached_at": "", "tables": {}}


def _save_schema_cache(cache_path: Path, cache: dict):
    """写表结构缓存。"""
    try:
        import json
        from datetime import datetime

        cache["cached_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass  # 缓存写失败不影响校验


def _is_cache_expired(cached_at: str, ttl_hours: int = 24) -> bool:
    """缓存是否过期。"""
    if not cached_at:
        return True
    try:
        from datetime import datetime, timedelta

        cached_time = datetime.strptime(cached_at, "%Y-%m-%dT%H:%M:%S")
        return datetime.now() - cached_time > timedelta(hours=ttl_hours)
    except Exception:
        return True


def _fetch_tables_schema_batch(
    executor, tables: list[tuple[str, str]]
) -> dict[tuple[str, str], dict[str, str]]:
    """连库批量查多张表的列名+类型（UNION ALL，实测 DWS 上最快）。

    每张表一个 UNION ALL 分支，每个分支走精确等值（n.nspname= AND c.relname=），
    优化器不用处理 OR，执行计划稳定。一次往返查完全部表。

    Args:
        executor: DB executor。
        tables: [(schema, table), ...] 待查的表。

    Returns:
        {(schema_lower, table_lower): {column_name_lower: type}}。
        表不存在/无权限 → 该表对应空 dict。
    """
    if not tables:
        return {}

    # 构造 UNION ALL：每个分支带 schema/table 标记列 + 列名 + 类型
    # format_type 输出归一化类型（如 "character varying(64)"、"bigint"）
    branches = []
    for (sch, tbl) in tables:
        branches.append(
            f"SELECT '{sch.lower()}' AS nsp, '{tbl.lower()}' AS rel, "
            "a.attname AS col, format_type(a.atttypid, a.atttypmod) AS col_type "
            "FROM pg_attribute a "
            "JOIN pg_class c ON a.attrelid = c.oid "
            "JOIN pg_namespace n ON c.relnamespace = n.oid "
            f"WHERE n.nspname = '{sch.lower()}' AND c.relname = '{tbl.lower()}' "
            "AND a.attnum > 0 AND NOT a.attisdropped"
        )
    sql = "\nUNION ALL\n".join(branches)

    r = executor.execute(sql)
    result: dict[tuple[str, str], dict[str, str]] = {}
    # 初始化所有表为空 dict（表不存在/查询失败时保留空 dict）
    for (sch, tbl) in tables:
        result[(sch.lower(), tbl.lower())] = {}

    if r.success and r.rows:
        for row in r.rows:
            key = (row["nsp"].lower(), row["rel"].lower())
            result.setdefault(key, {})[row["col"].lower()] = (row["col_type"] or "").lower()
    return result


def _check_db_schema(
    rs_input: dict[str, Any],
    result: PrecheckResult,
    cache_path: Path | None = None,
    refresh_schema: bool = False,
):
    """DB 校验：连得上库时，校验来源表/字段在库里的真实性。

    表结构本地缓存优先（schema_cache.json）：命中且未过期 → 纯本地对比秒级；
    缺失/过期/强制刷新 → 只连库捞缺失的表，逐表查（走索引），追加缓存。

    能连上库或缓存可用 → 表/字段不存在报 error（阻断设计）。
    连不上库且无缓存 → 静默跳过（不阻断）。

    账号选用逻辑与 UT 一致：按目标 schema 查 schema_mapping 选源。
    """
    # 从 field_mappings 收集"要用到的来源字段"：{(schema, table): {column: target_field}}
    # 跳过纯派生行（赋值/序列、source_column 空/占位符）和审计字段——这些不查源表
    field_mappings = rs_input.get("field_mappings", [])
    # {(schema, table): {source_column_lower: (原source_column, [target_fields], source_type)}}
    # 同一来源字段映射多个目标时，target_fields 累积成列表（避免覆盖丢失）
    needed: dict[tuple[str, str], dict[str, list]] = {}
    for fm in field_mappings:
        # 赋值/序列字段无真实来源表（值是固定的或自增），不查库
        rule = (fm.get("transform_rule") or fm.get("mapping_rule") or "").strip()
        if rule in ("赋值", "序列"):
            continue
        # source_column 空 或 占位符（-、/、\ 等）都不是真实列名，跳过
        source_column = (fm.get("source_column") or "").strip()
        if not source_column or source_column in ("-", "/", "\\", "—", "--"):
            continue
        if _is_audit_field(fm):
            continue
        schema = (fm.get("source_schema") or "").strip()
        table = (fm.get("source_table") or "").strip()
        if not schema or not table:
            continue
        col_key = source_column.lower()
        tbl_map = needed.setdefault((schema, table), {})
        if col_key not in tbl_map:
            source_type = (fm.get("source_type") or "").strip()
            tbl_map[col_key] = [source_column, [], source_type]
        # 累积目标字段（同一来源字段可能映射到多个目标）
        tbl_map[col_key][1].append(fm.get("target_column", "?"))

    if not needed:
        return

    total_fields = sum(len(cols) for cols in needed.values())
    all_tables = list(needed.keys())

    # ── 缓存有效就用（整体），无效就连库整体查所有表 ──
    # 缓存粒度 = 本次用到的全部来源表；不做按表补缺（同用例来源表固定，整体刷新更简单）
    # found: {(sch, tbl): {col_lower: type_lower}}
    found: dict[tuple[str, str], dict[str, str]] = {}
    cache_used = False

    if cache_path and not refresh_schema:
        cache = _load_schema_cache(cache_path)
        if not _is_cache_expired(cache.get("cached_at", ""), ttl_hours=72):
            # 缓存未过期：用缓存里的表结构（本次用到的表都应在缓存里）
            raw_tables = cache.get("tables", {})
            for (sch, tbl) in all_tables:
                key = f"{sch.lower()}.{tbl.lower()}"
                if key in raw_tables:
                    # 缓存里是 {col: type}，兼容旧格式（list 时转无类型 dict）
                    raw = raw_tables[key]
                    if isinstance(raw, dict):
                        found[(sch.lower(), tbl.lower())] = {k.lower(): v.lower() for k, v in raw.items()}
                    elif isinstance(raw, list):
                        found[(sch.lower(), tbl.lower())] = {c.lower(): "" for c in raw}
            cache_used = True

    # ── 缓存无效（过期/不存在/强制刷新）→ 连库整体查所有表 ──
    if not cache_used:
        target = rs_input.get("meta", {}).get("target", {})
        target_schema = target.get("f_table", {}).get("schema", "") or target.get("schema", "")
        sys.path.insert(
            0,
            str(Path(__file__).resolve().parent.parent.parent / "design-dev-shared" / "scripts"),
        )
        from dws_db import create_executor_for_schema

        # create_executor 失败：区分环境问题（ImportError 驱动缺失→warn）vs 配置错误（→error 阻断）
        try:
            executor = create_executor_for_schema(target_schema)
        except ImportError as e:
            # 依赖缺失（psycopg2 未安装）= 环境问题 → warn 跳过
            result.add_warn(f"[DB校验跳过] 数据库驱动缺失: {e}")
            return
        except Exception as e:
            # 配置错误（schema_mapping 缺/source 名错/role 缺）→ error 阻断
            result.add_error(f"[DB配置错误] {e}")
            return

        # 连接诊断：配置错误（密码错/库名错）→ error 阻断；环境不可用（连不上）→ warn 跳过
        # 不再静默 return——至少把原因报出来（不掩盖配置错误）
        status = executor.diagnose_connection()
        if not status.ok:
            if status.category in ("auth_failed", "db_not_found"):
                result.add_error(
                    f"[DB连接失败·配置错误] 数据源 '{executor.get_current_source()}': {status.reason}"
                )
            else:
                result.add_warn(
                    f"[DB校验跳过] 数据源 '{executor.get_current_source()}' 连不上: {status.reason}"
                )
            executor.close()
            return

        # 连接正常 → 连库捞表结构
        try:
            fetched = _fetch_tables_schema_batch(executor, all_tables)
            executor.close()
            found = fetched
            # 写缓存（存 {col: type}）
            if cache_path:
                cache_new = {"cached_at": "", "tables": {}}
                for (sch, tbl), cols in fetched.items():
                    cache_new["tables"][f"{sch}.{tbl}"] = cols  # 已是 {col: type}
                _save_schema_cache(cache_path, cache_new)
        except Exception as e:
            result.add_warn(f"[DB校验异常] {e}")
            executor.close()
            return

    # ── 比对（纯本地）──
    result.add_pass(
        f"DB 校验: 校验 {len(all_tables)} 张表 / {total_fields} 个字段"
        f"（{'缓存命中' if cache_used else '连库刷新'}）"
    )

    for (sch, tbl), cols_map in needed.items():
        found_cols = found.get((sch.lower(), tbl.lower()), {})
        for col_lower, entry in cols_map.items():
            orig_col, target_fields, source_type = entry
            # 报错归属以"来源字段"为主语（存在性/类型是来源字段的属性，与目标无关）
            # 顺带显示受影响的目标字段：单个直接显示，多个显示数量
            targets_str = target_fields[0] if len(target_fields) == 1 else f"{len(target_fields)}个目标字段"

            if col_lower not in found_cols:
                # 字段不存在 = mapping 写错了表名/列名，或源表结构变了
                result.add_error(
                    f"[字段不存在] 来源字段 '{orig_col}'（{sch}.{tbl}，→{targets_str}）"
                    f"在库中不存在——检查 mapping 的表名/列名拼写，或源表结构是否已变更"
                )
                continue
            # 类型严格匹配（mapping 的 source_type vs 库里实际类型）
            actual_type = found_cols.get(col_lower, "")
            if source_type and actual_type:
                expected_norm = _normalize_type(source_type)
                actual_norm = _normalize_type(actual_type)
                if expected_norm != actual_norm:
                    # 类型不符 = mapping 标的 source_type 和库里的对不上（mapping 可能标错，或库改了类型）
                    # 与 type_risk（source→target 转换风险）不同：这是 source 本身标错
                    result.add_error(
                        f"[类型不符] 来源字段 '{orig_col}'（{sch}.{tbl}，→{targets_str}）"
                        f"mapping 标的 source_type='{source_type}' 与库里的实际类型 '{actual_type}' 不一致"
                        f"——以库为准修正 mapping，或确认库结构是否已变更"
                    )


def _normalize_type(raw: str) -> str:
    """类型名归一化（识别同义异名，用于严格对比）。

    目的：把"同一类型的不同写法"归一到相同名字，避免方言/别名差异导致误报。

    整数类型（(n) 位宽优先）：
    - int8(64) / bigint / int(64) 都归一 "bigint"（64bit=8字节）
    - int4(32) / integer / int / int(32) 都归一 "integer"（32bit=4字节）
    - int2(16) / smallint 都归一 "smallint"（16bit=2字节）
    - 有 (n) 时 n（bit 数）决定精度；无 (n) 时 base name 决定

    其他类型：varchar/character varying 归一（PG 官方别名，确定同义，都字符语义）；
    char/character、numeric/decimal、bool/boolean 同理。
    varchar2/nvarchar2 不归一（字节/字符语义不同，归一会漏判长度超长）。

    与 type_compat.is_type_compatible 不同：那个判"兼容"（源能否被目标兜底），
    这个判"同名"（mapping 标的 source_type 和库 actual_type 该是同一类型）。

    时间类型家族（with/without time zone 底层存储不同，分开归一）：
    - timestamp / timestamp(n) / without time zone → 统一 ts_notz（忽略精度）
    - timestamptz / timestamp(n) with time zone     → 统一 ts_tz（忽略精度）
    """
    import re
    t = raw.strip().lower().replace(" ", "")
    if not t:
        return ""

    # 时间类型族：先判 with/without time zone（底层不同，不归一），再忽略精度
    if "timestamp" in t:
        is_tz = "withtimezone" in t or t.startswith("timestamptz")
        return "ts_tz" if is_tz else "ts_notz"

    base = t.split("(")[0]
    # 提取 (n) 第一个数字（整数类是 bit 数，字符/数值类是长度/精度）
    m = re.search(r"\((\d+)", t)
    n_first = int(m.group(1)) if m else None

    # 整数类：(n) bit 数优先决定精度等级，其次 base name
    # int8/int4/int2 是 PG 内部名（pg_type），bigint/integer/smallint 是 SQL 标准名，二者等价
    INT_BASE_TO_NAME = {
        "bigint": "bigint", "int8": "bigint", "bigserial": "bigint",
        "integer": "integer", "int": "integer", "int4": "integer", "serial": "integer",
        "smallint": "smallint", "int2": "smallint", "smallserial": "smallint",
        "tinyint": "tinyint", "int1": "tinyint",
    }
    INT_BIT_TO_NAME = {64: "bigint", 32: "integer", 16: "smallint", 8: "tinyint"}
    if base in INT_BASE_TO_NAME:
        if n_first is not None and n_first in INT_BIT_TO_NAME:
            return INT_BIT_TO_NAME[n_first]  # (n) 位宽优先
        return INT_BASE_TO_NAME[base]  # 无 (n) 或 n 非标准位宽 → base name 决定

    # 其他类型：归一别名 + 保留长度/精度后缀
    # 注意：varchar2/nvarchar2 不归一到 varchar——长度语义不同（varchar2 按字节，
    # varchar 在 PG 模式按字符；nvarchar2 按字符但是国家字符集），归一会漏判长度超长
    rest = "(" + t.split("(", 1)[1] if "(" in t else ""
    aliases = {
        "varchar": "charactervarying",
        "char": "character",
        "string": "text",
        "bool": "boolean",
        "decimal": "numeric",
    }
    return aliases.get(base, base) + rest


def main():
    parser = argparse.ArgumentParser(description="输入预检: 校验 rs_input.json 完整性")
    parser.add_argument("--input", required=True, help="rs_input.json 路径")
    parser.add_argument(
        "--refresh-schema",
        action="store_true",
        help="强制连库刷新表结构缓存（忽略过期判断）",
    )
    parser.add_argument(
        "--decision",
        default=None,
        help="类型风险决策文件路径（type_risk_decision.yaml）。"
        "默认 rs_input 同目录下。不传则不做类型风险检测。",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"错误: 文件不存在: {input_path}", file=sys.stderr)
        sys.exit(1)

    import json
    rs_input = json.loads(input_path.read_text(encoding="utf-8"))

    # 缓存放 rs_input.json 同目录（_internal/schema_cache.json）
    cache_path = input_path.parent / "schema_cache.json"

    # 类型风险决策文件路径（默认 rs_input 同目录，即 _internal/type_risk_decision.yaml）
    decision_path = None
    if args.decision:
        decision_path = Path(args.decision)
    else:
        default_decision = input_path.parent / "type_risk_decision.yaml"
        if default_decision.exists():
            decision_path = default_decision
        else:
            # 检测是否有风险，有则启用（生成在默认路径）
            decision_path = default_decision

    result = precheck(rs_input, cache_path, args.refresh_schema, decision_path, input_path)
    print(result.summary())
    sys.exit(result.return_code)


if __name__ == "__main__":
    main()
