"""risk_checks —— 预检检测原语（new-pipe precheck 与 opt-pipe precheck_opt 共用）。

2026-09-04 从 new-pipe/precheck.py 搬体留名下沉（函数体零改动、原名保留——precheck
re-export 同名，两 pipe 的既有 import 面零破坏）。承载：预检结果收集器、类型风险
检测/决策骨架/决策校验、关联键决策骨架/校验、值域探测、键值采样、pg_stats 统计原语。
依赖：type_compat（shared）+ dws_db（shared，函数内局部 import）。
"""
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


BATCH_RISKS = {"length_overflow", "precision_loss"}


INDIVIDUAL_RISKS = {"type_incompatible"}

# 处置选项（中文，给决策文件校验用）


BATCH_OPTIONS = {"加安全处理", "不加"}


INDIVIDUAL_OPTIONS = {"转换", "不加", "返源端"}


JOIN_RISK_OPTIONS = {"转换", "改关联键", "接受"}


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
            "# === 逐个决策（跨大类不兼容/字符长度语义差异，风险高，需单独看每个字段）===",
            "# 字符语义差异 = nvarchar↔varchar 等口径互跨（字节/字符），同长度也可能装不下中文；",
            "# 到底装不装得下取决于字段实际数据——批量定策略不合适，逐个定。",
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


def _sample_join_key_values(executor, schema: str, table: str, col: str, limit: int = 5) -> list[str]:
    """连库采样键值（DISTINCT + LIMIT，给人决策当证据）。异常/失败返回空。"""
    import re as _re
    ident = f"{schema}.{table}.{col}"
    if not _re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", ident):
        return []
    try:
        sql = (f"SELECT DISTINCT {col}::text AS v FROM {schema}.{table} "
               f"WHERE {col} IS NOT NULL LIMIT {limit}")
        r = executor.execute(sql)
        if r.success and r.rows:
            return [str(row.get("v")) for row in r.rows]
    except Exception:
        pass
    return []


def _parse_stats_bounds(histogram_text):
    """pg_stats.histogram_bounds 文本（'{a,b,...}'）→ (首元素, 末元素) 字符串。

    无统计（None/'{}'/空）或解析失败返回 (None, None)——统计是近似增益，坏了不猜。
    """
    if not histogram_text:
        return None, None
    t = str(histogram_text).strip()
    if not (t.startswith("{") and t.endswith("}")):
        return None, None
    inner = t[1:-1].strip()
    if not inner:
        return None, None
    parts = [p.strip().strip('"') for p in inner.split(",")]
    return parts[0], parts[-1]


def _integer_digits(value_text) -> int:
    """数值文本的整数位宽：'123.456'→3、'-12.3'→2、'0.5'→1。非法返回 -1。"""
    try:
        import decimal
        d = decimal.Decimal(str(value_text).strip())
        return 1 if d == 0 else len(str(int(abs(d))))
    except Exception:
        return -1


def _fetch_pg_stats(executor, schema: str, table: str, cols: list) -> dict:
    """按表批量查 pg_stats → {列名: (avg_width, histogram_bounds文本)}。异常返回 {}。"""
    import re as _re
    if not _re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", f"{schema}.{table}"):
        return {}
    try:
        cols_sql = ", ".join(f"'{c}'" for c in cols)
        sql = ("SELECT attname, avg_width, histogram_bounds::text AS hb "
               f"FROM pg_stats WHERE schemaname='{schema}' AND tablename='{table}' "
               f"AND attname IN ({cols_sql})")
        r = executor.execute(sql)
        if r.success and r.rows:
            return {str(row.get("attname", "")).lower():
                    (row.get("avg_width"), row.get("hb")) for row in r.rows}
    except Exception:
        pass
    return {}


# ============================================================
# 值域探测（pg_stats 统计信息版，≈零成本：读 catalog 不扫表）
#
# 事件边界（2026-08-31 定调）：安全处理（守卫式转换/CAST）守的是"转换动作"
# ——防个别脏值炸批（失败模式从崩溃变可检测降级）；**不兜底值域**——正常数据
# 装不下目标定义 = 模型设计问题（BA 的 mapping 目标类型定窄了），退源端改模型。
# 实证案例：numeric → numeric(7,6)，源值 123.456——整数 3 位 > 目标整数位 1 位，
# CAST/ROUND 均无解，UT 才炸且被 coder 打"超长置空"补丁掩埋根因。
#
# 判定（"直接复制"字段中目标定义收窄于源的候选）：
#   - 数值：目标 numeric(p,s) 整数位 p-s < 源统计上界整数位 → error 阻断
#     （退 BA 改 mapping 目标类型；置空/截断=静默丢数据，必须人显式拍板，本闸只认改模型）
#   - 字符：目标 varchar(n) < 源统计 avg_width → warn 披露（会发生截断，闸口①人确认）
#   - 无库/无统计 → warn 汇总（值域未验，UT 兜底：值域类报错分流退人禁回 coder）
# ============================================================


def _check_value_range(rs_input: dict, result: PrecheckResult, rs_input_path=None):
    """值域探测主入口：有库走 pg_stats 统计判定，无库降 warn（UT 兜底）。"""
    from type_compat import parse_type_info

    numeric_candidates = []   # 目标 numeric(p,s)：源实际整数位可能超目标整数位
    char_candidates = []      # 目标 varchar(n)：源更宽/无长度，可能截断
    for fm in rs_input.get("field_mappings", []):
        rule = (fm.get("transform_rule") or fm.get("mapping_rule") or "").strip()
        if rule != "直接复制":
            continue
        st, tt = (fm.get("source_type") or "").strip(), (fm.get("target_type") or "").strip()
        if not st or not tt:
            continue
        ti_src, ti_tgt = parse_type_info(st), parse_type_info(tt)
        common = {
            "target_column": (fm.get("target_column") or "").strip(),
            "schema": (fm.get("source_schema") or "").strip(),
            "table": (fm.get("source_table") or "").strip(),
            "col": (fm.get("source_column") or "").strip(),
            "source_type": st, "target_type": tt,
        }
        if (ti_tgt.get("family") == "numeric" and ti_tgt.get("length") is not None
                and ti_tgt.get("scale") is not None and ti_src.get("family") == "numeric"):
            common["int_limit"] = ti_tgt["length"] - ti_tgt["scale"]
            if common["int_limit"] >= 0:
                numeric_candidates.append(common)
        elif (ti_tgt.get("family") == "varchar" and ti_tgt.get("length")
              and ti_src.get("family") == "varchar"
              and (ti_src.get("length") is None or ti_src["length"] > ti_tgt["length"])):
            common["n"] = ti_tgt["length"]
            char_candidates.append(common)
    if not numeric_candidates and not char_candidates:
        return  # 无候选（无收窄场景）不打扰

    target_schema = ((rs_input.get("meta", {}).get("target", {}) or {})
                     .get("f_table", {}) or {}).get("schema", "")
    executor = None
    try:
        from dws_db import create_executor_for_schema
        executor = create_executor_for_schema(target_schema, role="etl")
        if not executor.test_connection():
            executor.close()
            executor = None
    except Exception:
        executor = None
    if executor is None:
        result.add_warn("[值域探测跳过] 无库/连不上：值域未验（UT 阶段值域类报错兜底，"
                        "分流规则见 new-pipe 剧本步骤 6——退人禁回 coder）")
        return

    try:
        by_table: dict = {}
        for c in numeric_candidates + char_candidates:
            by_table.setdefault((c["schema"].lower(), c["table"].lower()), []).append(c)
        stats_cache: dict = {}
        for (sch, tbl), items in by_table.items():
            cols = list({c["col"] for c in items if c["col"]})
            if cols:
                stats_cache[(sch, tbl)] = _fetch_pg_stats(executor, sch, tbl, cols)

        no_stats = []
        for c in numeric_candidates:
            stats = stats_cache.get((c["schema"].lower(), c["table"].lower()), {}).get(c["col"].lower())
            if not stats:
                no_stats.append(c["target_column"] or c["col"])
                continue
            first, last = _parse_stats_bounds(stats[1])
            digits = max(_integer_digits(first), _integer_digits(last))
            if digits > c["int_limit"]:
                bound = last if _integer_digits(last) >= _integer_digits(first) else first
                result.add_error(
                    f"[值域溢出·模型问题] {c['target_column']}（{c['source_type']}→{c['target_type']}）："
                    f"pg_stats 统计上界 {bound}（整数位 {digits} 位）> 目标 {c['target_type']} "
                    f"整数位 {c['int_limit']} 位（precision-scale）——目标定义装不下源数据。"
                    f"与类型风险决策无关（\"加安全处理\"防的是脏值炸批，对整数位溢出无效）。二选一："
                    f"① 源输入问题退 BA——改 mapping 目标类型后重跑 1a+1b（确定性解法）；"
                    f"② SE 显式拍板置空/截断（设计/实现决策不改业务需求，静默丢数据须明知）"
                    f"→ designer 写显式口径→coder 实现")
        for c in char_candidates:
            stats = stats_cache.get((c["schema"].lower(), c["table"].lower()), {}).get(c["col"].lower())
            if not stats:
                no_stats.append(c["target_column"] or c["col"])
                continue
            try:
                avg_w = float(stats[0] or 0)
            except (TypeError, ValueError):
                continue
            if avg_w > c["n"]:
                result.add_warn(
                    f"[截断披露] {c['target_column']}（{c['source_type']}→{c['target_type']}）："
                    f"源统计平均宽度 {avg_w:.0f} > 目标长度 {c['n']}——安全截取会发生截断"
                    f"（静默丢尾部）。闸口①确认业务可接受，或退 BA 改长度")
        if no_stats:
            result.add_warn(f"[值域未验] {len(no_stats)} 个收窄字段无统计信息（{no_stats[:5]}"
                            f"{'…' if len(no_stats) > 5 else ''}）——表未 analyze 或统计过期，"
                            f"UT 阶段值域类报错兜底")
    finally:
        try:
            executor.close()
        except Exception:
            pass


def _generate_join_risk_skeleton(decision_path: Path, risks: list[dict]):
    """生成关联键类型决策骨架（全中文 key，处置留空待人/agent 填）。"""
    lines = [
        "# 关联键类型对账决策（预检自动生成，编排层 agent 会用 question 问用户填写）",
        "# 只拦跨大类（如字符↔数值、字符↔日期）；灰色地带（同族/整数↔数值）已放行。",
        "# 采样值是双侧键值证据——内容能不能对上，人看样例一眼判断。",
        "",
        "关联风险对:",
    ]
    for rk in risks:
        lines.append(f'  - 关联条件: "{rk["condition"]}"')
        lines.append(f'    左侧: "{rk["left"]} ({rk["left_type"]})"')
        lines.append(f'    右侧: "{rk["right"]} ({rk["right_type"]})"')
        lines.append(f'    左采样: "{rk.get("left_samples", "")}"')
        lines.append(f'    右采样: "{rk.get("right_samples", "")}"')
        lines.append('    处置: ""          # ★ 填：转换 | 改关联键 | 接受')
        lines.append('                      # 转换 = 内容实际兼容（如 \'123\' 对 123），designer 在 joins 里声明 cast')
        lines.append('                      # 改关联键 = 关联字段选错了，改 mapping.xlsx 源文件后重跑 preprocess')
        lines.append('                      # 接受 = 业务确认就这么关联（豁免，闸口①可见）')
        lines.append('    原因: ""          # 选"改关联键/接受"时建议填')
    decision_path.parent.mkdir(parents=True, exist_ok=True)
    decision_path.write_text("\n".join(lines), encoding="utf-8")


def _validate_join_risk_decision(decision_path: Path, risks: list[dict],
                                 result: PrecheckResult) -> bool:
    """校验关联键决策文件填全。返回 True=通过。"""
    import yaml
    try:
        dec = yaml.safe_load(decision_path.read_text(encoding="utf-8"))
    except Exception as e:
        result.add_error(f"关联键决策文件解析失败({decision_path}): {e}")
        return False
    if not isinstance(dec, dict):
        result.add_error("关联键决策文件格式错误（顶层应为字典）")
        return False

    ok = True
    entries = [it for it in (dec.get("关联风险对") or []) if isinstance(it, dict)]
    dec_conds = {it.get("关联条件", "") for it in entries}
    detected = {rk["condition"] for rk in risks}
    if dec_conds != detected:
        result.add_error(
            f"关联风险对清单与决策不一致（缺: {sorted(detected - dec_conds)} / "
            f"多余: {sorted(dec_conds - detected)}），已重新生成骨架，请填后重跑")
        return False
    for it in entries:
        cond = it.get("关联条件", "")
        action = (it.get("处置") or "").strip()
        if not action:
            result.add_error(f"关联键决策未填：'{cond}' 的处置")
            ok = False
        elif action not in JOIN_RISK_OPTIONS:
            result.add_error(f"关联键 '{cond}' 的处置 '{action}' 不合法（应为：转换/改关联键/接受）")
            ok = False
    return ok

