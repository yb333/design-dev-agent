"""explain_check —— 执行计划两门槛（EXPLAIN ANALYZE 计划解析与判定）。

2026-09-04 从 new-pipe/ut_precheck.py 搬体留名下沉（零改动）。ut_precheck（new-pipe 6a）
与 ut_opt（opt 步骤 5）共用：STREAM 算子计数/不下推官方判据/顶层实际行数解析（多格式，
宁缺勿错）/计划原文落盘。
"""
from pathlib import Path

# ── 执行计划两门槛（2026-09-02 第二批，用户定调：只做这两个，其他性能分析暂不做）──
# 纯 EXPLAIN（毫秒级零执行成本——两门槛都是计划形状信号，无需 ANALYZE 实际行数）。
# 不下推判据=Data Node Scan（官方）；首版误用 Row Adapter 已纠正（行列转换算子非判据）。
# 过程可视：计划原文全量落盘 _internal/diagnose/plan_{rule}.txt（好坏都留，人可回溯），
# stdout 只出结论。提示级不阻断（性能归人判——与质检体系"披露不代答"一致）。
import re as _re

# STREAM 算子计数：所有 Streaming/Stream 算子节点（Gather/Redistribute/Broadcast 及
# PART 变体——type: 任意值都算），Streaming (type: GATHER) / Stream[name:S1, type: ...] 格式都认
_STREAM_PATTERN = _re.compile(
    r"(?:Streaming|Stream)\s*[\(\[][^)\]]*?type\s*:", _re.IGNORECASE)
# 不下推标志（华为云《语句下推调优》官方判据，2026-09-02 查证）：
#   计划中出现 Data Node Scan 节点（伴随 _REMOTE_TABLE_QUERY_）= 不可下推——
#   可下推部分下推、剩余中间结果拉到 CN 执行，CN 成性能瓶颈；
#   出现 Streaming 节点 = 可下推（分布式计划）。Row Adapter 只是行列转换算子
#   （混合存储合法出现），不是判据（首版误用已纠正）。
_NO_PUSHDOWN_MARKERS = ("Data Node Scan",)
STREAM_LIMIT = 50   # 算子出现个数上限（过多→大量线程消耗、性能下降）


# 实际行数解析（EXPLAIN ANALYZE 顶层 actual rows；解析不出返回 None=宁缺勿错
# 跳过 0 行告警，不猜——猜错列会把 E-rows/内存值当行数，比没有更糟）
_ACTUAL_ROWS_TEXT_PATTERNS = [
    _re.compile(r"actual\s+time\s*=\S+\s+rows\s*=\s*(\d+)"),   # PG 文本式 (actual time=.. rows=N loops=..)
    _re.compile(r"\brows\s*=\s*(\d+)\s+loops"),                   # 同上变体
]


def _parse_actual_rows(plan_text: str):
    """从 EXPLAIN ANALYZE 计划文本解析顶层实际行数。

    两格式：PG 文本式（actual time=.. rows=N）直接正则；DWS 表格式**表头驱动**
    （找含 A-rows/A-rows 列名的表头定位列号，再取 id=1 行该列——不猜列位）。
    都不中返回 None（宁缺勿错）。"""
    for pat in _ACTUAL_ROWS_TEXT_PATTERNS:
        m = pat.search(plan_text)
        if m:
            return int(m.group(1))
    # 表格式：表头驱动定位 A-rows 列
    lines = plan_text.splitlines()
    header_idx = next((i for i, ln in enumerate(lines)
                       if "|" in ln and _re.search(r"a-?rows", ln, _re.IGNORECASE)), None)
    if header_idx is None:
        return None
    header_cols = [c.strip().lower() for c in lines[header_idx].split("|")]
    try:
        col = next(i for i, c in enumerate(header_cols) if _re.search(r"a-?rows", c))
    except StopIteration:
        return None
    for ln in lines[header_idx + 1:]:
        if _re.match(r"^\s*1\s*\|", ln):                    # id=1 行（顶层）
            cols = [c.strip() for c in ln.split("|")]
            if col < len(cols):
                m = _re.search(r"\d+", cols[col].replace(",", ""))
                if m:
                    return int(m.group())
            break
    return None


def _analyze_plan(plan_text: str, rule_code: str, ts_path) -> tuple[list[str], str]:
    """分析计划文本跑两门槛：①不下推（Data Node Scan 官方判据）②STREAM 算子数≤50。
    计划原文（含 actual 值）落盘可回溯。返回 (问题列表[空=通过], 计划文件路径)。"""
    plan_path = ts_path.parent / "_internal" / "diagnose" / f"plan_{rule_code}.txt"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(f"-- EXPLAIN ANALYZE {rule_code}\n\n{plan_text}\n", encoding="utf-8")
    issues = []
    streams = _STREAM_PATTERN.findall(plan_text)
    if len(streams) > STREAM_LIMIT:
        issues.append(f"STREAM 算子 {len(streams)} 个 > {STREAM_LIMIT}"
                      f"（gather/redistribute/broadcast 过多→大量线程消耗性能下降，人判改写/分布键）")
    hits = [m for m in _NO_PUSHDOWN_MARKERS if m in plan_text]
    if hits:
        remote = "（伴随 _REMOTE_TABLE_QUERY_）" if "_REMOTE_TABLE_QUERY_" in plan_text else ""
        issues.append(f"疑似不下推（计划含 {'/'.join(hits)}{remote}——官方判据：中间结果拉回 CN 执行，"
                      f"CN 成瓶颈；常见诱因：不支持下推的函数/语法/分布列不齐，人判改写）")
    return issues, str(plan_path)
