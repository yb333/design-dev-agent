"""真实入口执行层：调 /new-pipe 命令跑完整真实流程（评测的默认执行方式）。

评测 = 真实入口 + 薄评判层：
- 本模块只做三件事：拼调用参数（含显式非交互声明）→ opencode run --command new-pipe → 判产出
- 编排逻辑 100% 在 commands/new-pipe.md（唯一编排剧本），本模块零编排拷贝——
  编排改了评测自动跟，不存在双写漂移
- pipeline.py（分阶段重放版）降级为 --replay 诊断模式（E2E 挂了要分阶段定位才用）

非交互声明：new-pipe.md 闸口①② 的显式例外条款——"用户/调用方显式声明了非交互
（如 opencode run 批量评测）"才允许跳过 question。本模块的声明文案即援引该条款。

UT 连库属于真实流程的一部分（new-pipe 自己会 check_db 探活决定跑不跑）——
评测不干预，测的就是真实行为。
"""

from __future__ import annotations

import re
import sys
import threading
import time
from pathlib import Path

_V2_DIR = Path(__file__).resolve().parent
_EVAL_SUITE = _V2_DIR.parent
_ROOT = _EVAL_SUITE.parent
for p in (str(_V2_DIR), str(_EVAL_SUITE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from validators.base import CheckStatus  # type: ignore

from engine import PipelineStepResult
from pipeline import _run_stream, _step, _fail_detail, opencode_cmd
from _paths import find_deliver, list_select_rules, find_mapping_file, find_rs_file

# 真实流程一整条（设计→编码→UT→export），超时给足
DEFAULT_TIMEOUT_PIPE = 3600

# 非交互声明（new-pipe.md 闸口①② 唯一合法的跳过条件：调用方显式声明）
NON_INTERACTIVE_CLAUSE = (
    "【调用方显式声明：非交互批量评测——闸口①②跳过人工确认；"
    "全程（含你派发的所有 Task/子agent）禁止调用 question 工具，"
    "派发子任务时必须把本声明原样附进子任务 prompt；"
    "需要人决策的事项一律记录到产出说明后继续】"
)

# 非交互评测中的致命流模式：question 调用=死锁（没人能应答），检测即终止
_QUESTION_PATTERNS = [
    re.compile(r"question\s*\(", re.IGNORECASE),          # 工具调用形态
    re.compile(r"asked\s+user", re.IGNORECASE),
    re.compile(r"等待用户(输入|确认|回答|选择)"),
]


def build_command_args(case_dir: Path) -> list[str]:
    """构造 /new-pipe 的 $ARGUMENTS：按文件特征发现输入（不硬编码文件名）。

    mapping 必须有（*.xlsx/xls 名含 mapping，标准名 mapping.xlsx 优先）；
    RS 可选（*.md/txt 名含 rs/需求），找到才传。
    """
    mapping = find_mapping_file(case_dir)
    if not mapping:
        raise RuntimeError(
            f"案例目录没有 mapping 文件（识别：*.xlsx/xls 且文件名含 mapping）: {case_dir}"
        )
    args = [str(mapping.resolve())]
    rs = find_rs_file(case_dir)
    if rs:
        args.append(str(rs.resolve()))
    return args


def judge_real_run(deliver: Path | None, code: int, out: str) -> tuple[bool, str]:
    """判真实跑结果：退出码 + 关键产出存在（ts.json + ≥1条 SELECT）。

    深度质量（字段全不全/设计对不对）交给断言层，这里只判"流程真的跑出东西了"。
    """
    if deliver is None:
        tail = out[-400:].strip() if out.strip() else "(opencode 无输出)"
        return False, f"未找到产出目录（new-pipe 未落产出，或案例名与资产表名不一致）\n{tail}"
    has_ts = (deliver / "ts.json").exists()
    rules = list_select_rules(deliver)
    if code != 0 or not has_ts or not rules:
        return False, _fail_detail("new-pipe", deliver, out)
    has_ddl = (deliver / "ddl").exists()
    has_export = (deliver / "export").exists()
    return True, (
        f"{len(rules)}条SELECT, ddl={'✓' if has_ddl else '✗'}, export={'✓' if has_export else '✗'}"
    )


def run_real_pipe(
    case_dir: Path, deliver_base: Path, timeout: float = DEFAULT_TIMEOUT_PIPE
) -> tuple[list[PipelineStepResult], dict[str, float]]:
    """真实入口：opencode run --command new-pipe。流程层=单步（真实流程不拆阶段）。

    阶段可见性：真实流程是一个子进程，内部阶段（预处理/设计/编码/UT）不可直接
    观察——但每阶段完成会落对应产出文件（marker），观察器盯产出目录反推当前
    阶段进 spinner；marker 首现时间戳推算各阶段耗时（估算，供统计）。

    返回 (步骤结果列表, 阶段耗时估算 {阶段名: 秒})。
    """
    args = build_command_args(case_dir)
    message = " ".join(args + [NON_INTERACTIVE_CLAUSE])
    # 双信号：流锚点（顶层 pipe 活动）+ 文件 marker（subagent 写产出的内层活动，
    # 顶层流看不到 designer/coder 内部——设计/编码阶段靠文件事件补）
    tracker = _StageTracker()
    discipline = _DisciplineTracker(stage_provider=tracker.stage_text)
    watcher = _StageWatcher(
        case_dir, deliver_base,
        on_marker=tracker.feed_file,
        on_suspect=discipline.on_file,
    )
    tracker._fallback = watcher  # 全盲兜底 + etl 计数
    discipline._watcher = watcher  # 文件违规的代理前因（marker 时间线）

    def _do() -> tuple[bool, str]:
        # 不带 --format json：降低内网包壳启动器的旗标兼容面，默认格式流式输出更适合看进度
        code, out = _run_stream(
            opencode_cmd() + ["run", "--command", "new-pipe", message],
            timeout,
            label="new-pipe 真实流程",
            stage_provider=tracker.stage_text,
            line_hook=lambda line: (tracker.feed(line), discipline.feed(line)),
            fatal_patterns=_QUESTION_PATTERNS,
        )
        deliver = find_deliver(deliver_base, case_dir.name)
        ok, detail = judge_real_run(deliver, code, out)
        if "[QUESTION]" in out:
            # 子agent/pipe 发起 question = 非交互死锁源，已快速终止——按纪律违规记录
            qline = next((l.strip()[:120] for l in out.splitlines()
                          if "[QUESTION]" not in l and l.strip() and any(
                              pat.search(l) for pat in _QUESTION_PATTERNS)), "")
            discipline._record(
                "question",
                f"发起 question（非交互评测死锁，已终止）: {qline}",
                from_stream=True,
            )
        return ok, detail

    steps = [_step("new-pipe(真实流程)", _do)]
    stage_times, stage_loops = tracker.finish()
    return steps, stage_times, stage_loops, discipline.violations


# ============================================================
# 纪律检查：抓 agent 自建临时脚本绕过流程（违反编排者铁律"不 author 脚本"）
# ============================================================

# 剧本/管线规定脚本的基名白名单（宁可宽防误报；agent 调它们是本职）
_WHITELIST_SCRIPTS = {
    "resolve_appid", "preprocess", "precheck", "fill_type_risk_decision",
    "assemble_ts", "gate_summary", "dispatch_plan", "assemble_ddl",
    "check_db", "ut_precheck", "ut_execute", "run_ut_check",
    "assemble_export", "check_sql", "slice_ts", "pick_fields",
    "explore", "check_field", "config_paths", "dws_db", "schema_query",
    "baseline_contract", "inject_tablesample", "local_eval", "run",
    "seed", "promote", "history", "menu", "engine", "report_v2",
}

# 脚本调用行（python/bash/sh + 落盘脚本路径；-c 内联与 -m 模块豁免）
_INVOKE_RE = re.compile(
    r"\b(?:python3?|bash|sh)\s+(?!-c)([^\s`\"'|;]+?\.(?:py|sh))",
    re.IGNORECASE,
)

# 上下文窗口行数（违规前文——agent 写脚本前的报错/诱因通常在这段里）
_DISCIPLINE_CONTEXT_LINES = 15


class _DisciplineTracker:
    """编排纪律跟踪：白名单外的脚本调用 + 产出目录里的自建脚本文件。

    检出即 FAIL（不进致命门）+ 扣分 + 上下文进报告待人裁决——脚本本身
    可能是对的，问题是绕过了该走的流程（掩盖根因）。
    """

    def __init__(self, stage_provider=None):
        self._stage_provider = stage_provider
        self._watcher = None  # 注入 watcher（文件违规的代理前因：marker 时间线）
        self._recent: list[str] = []  # 滚动上下文（仅主 agent 流——子 agent 内部顶层流不可见）
        self.violations: list[dict] = []
        self._seen_keys: set[str] = set()

    def feed(self, line: str) -> None:
        stripped = line.strip()
        if stripped:
            self._recent.append(stripped[:200])
            self._recent = self._recent[-30:]
        for m in _INVOKE_RE.finditer(stripped):
            script = m.group(1).replace("\\", "/")
            self._record(script, f"调用 {m.group(0)[:120]}", from_stream=True)

    def on_file(self, rel_path: str) -> None:
        """watcher 检出产出目录里的自建脚本文件（diagnose 豁免由 watcher 保证）。

        前因用代理线索拼：子 agent 的推理在它自己的会话里、顶层流拿不到——
        用 阶段 + 最近产出 marker 时间线 + 主 agent 流尾（派活语境）近似定位。
        """
        context = []
        if self._watcher is not None:
            markers = self._watcher.recent_markers()
            if markers:
                context.append(f"此前产出活动: {' → '.join(markers)}")
        if self._recent:
            context.append(f"主agent流尾| {self._recent[-1][:100]}")
        key = rel_path.replace("\\", "/")
        if key in self._seen_keys or "_internal/diagnose" in key:
            return
        stem = key.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        if stem in _WHITELIST_SCRIPTS:
            return
        self._seen_keys.add(key)
        stage = ""
        if self._stage_provider:
            try:
                stage = self._stage_provider()
            except Exception:
                pass
        self.violations.append(
            {"script": key, "action": f"自建文件 {rel_path}", "stage": stage, "context": context}
        )

    def _record(self, script: str, action: str, from_stream: bool) -> None:
        base = script.rsplit("/", 1)[-1]
        stem = base.rsplit(".", 1)[0]
        if stem in _WHITELIST_SCRIPTS:
            return
        if "_internal/diagnose" in script:
            return  # 铁律允许：诊断临时查询进 diagnose 目录
        if script in self._seen_keys:
            return
        self._seen_keys.add(script)
        stage = ""
        if self._stage_provider:
            try:
                stage = self._stage_provider()
            except Exception:
                pass
        context = list(self._recent[-_DISCIPLINE_CONTEXT_LINES:]) if from_stream else []
        self.violations.append(
            {"script": script, "action": action, "stage": stage, "context": context}
        )

    def summary(self) -> str:
        """报告用明细（多行）。"""
        if not self.violations:
            return "无自建脚本（编排铁律遵守）"
        lines = [f"发现 {len(self.violations)} 处 agent 自建脚本（绕过流程，待人裁决）:"]
        for v in self.violations:
            tag = f"[{v['stage']}]" if v["stage"] else "[?]"
            lines.append(f"  {tag} {v['action']}")
            if v["context"]:
                cause = [c for c in v["context"] if any(
                    k in c.upper() for k in ("ERROR", "FAIL", "阻断", "失败"))]
                shown = cause[-3:] if cause else v["context"][-3:]
                for c in shown:
                    lines.append(f"    前因| {c[:100]}")
            lines.append("    全文: results/_live/new-pipe_真实流程.log")
        return "\n".join(lines)


# ============================================================
# 产出文件观察器：阶段反推 + 耗时估算（与 opencode 内部零耦合，只认产出文件）
# ============================================================

# marker 按流水线顺序：文件/目录首现 → 该阶段完成的信号
_STAGE_MARKERS: list[tuple[str, str]] = [
    ("预处理", "_internal/rs_input.json"),
    ("设计", "_internal/design_decisions.yaml"),
    ("TS组装", "ts.json"),
    ("DDL生成", "ddl"),
    ("规则编码", "etl"),
    ("DQ生成", "dq"),
    ("UT执行", "_internal/ut_sql"),
    ("制品打包", "export"),
]


def _find_deliver_loose(base: Path, asset: str) -> Path | None:
    """宽松定位产出目录：三层下 {asset}/ddlc_design_dev 目录存在即可（不要求 ts.json）。

    真实流程刚起步时 ts.json 还没生成，find_deliver 会漏——观察器需要更早介入。
    """
    if not base.exists():
        return None
    for appid_dir in sorted(base.iterdir()):
        if not appid_dir.is_dir():
            continue
        for schema_dir in sorted(appid_dir.iterdir()):
            if not schema_dir.is_dir():
                continue
            cand = schema_dir / asset / "ddlc_design_dev"
            if cand.is_dir():
                return cand
    return None


# ============================================================
# L2 主力：输出流锚点匹配（new-pipe.md 硬性规定的脚本名/subagent 名天然是阶段锚点）
# ============================================================

# 顺序敏感：具体脚本名在前，防一条命令行误配早阶段（如 assemble_ts 命令含
# design_decisions 路径）。锚点全部来自剧本的确定性命令行，agent 执行必然经过。
_STREAM_ANCHORS: list[tuple["re.Pattern[str]", str]] = [
    (re.compile(r"assemble_ts\.py"), "TS组装"),
    (re.compile(r"gate_summary\.py"), "闸口①摘要"),
    (re.compile(r"dispatch_plan\.py"), "执行计划"),
    (re.compile(r"assemble_ddl\.py"), "DDL生成"),
    (re.compile(r"dq_rules|/dq/|DQ SQL"), "DQ生成"),
    (re.compile(r"dws-coder|etl/R\d{4}"), "规则编码"),
    (re.compile(r"check_db\.py|DB_OK|NO_DB_SOURCE"), "UT探活"),
    (re.compile(r"ut_precheck\.py|ut_execute\.py|run_ut_check"), "UT执行"),
    (re.compile(r"assemble_export\.py"), "制品打包"),
    (re.compile(r"dws-designer"), "设计"),
    (re.compile(r"fill_type_risk|TYPE_RISK_PENDING"), "类型风险决策"),
    (re.compile(r"precheck\.py"), "预检"),
    (re.compile(r"resolve_appid|preprocess\.py"), "预处理"),
]

# 编码段并行组（new-pipe 4a/4b/4c 同消息并行发起）：组内共存不互斥，
# 组员到达只清掉组外的旧阶段。串行阶段到达则清空整组开启新段。
_PARALLEL_GROUP = {"DDL生成", "DQ生成", "规则编码"}

# 展示排序（流水线顺序）
_STAGE_ORDER = ["预处理", "预检", "类型风险决策", "设计", "TS组装", "闸口①摘要",
                "执行计划", "DDL生成", "DQ生成", "规则编码", "UT探活", "UT执行", "制品打包"]
_STAGE_RANK = {st: i for i, st in enumerate(_STAGE_ORDER)}


class _StageTracker:
    """输出流阶段状态机（并行组模型）。

    - 串行阶段到达 → 关闭当前活动集（各阶段累计各自活跃区段），开启新段
    - 并行组（DDL/DQ/规则编码）到达 → 加入活动集与组内共存，只清组外旧阶段
      —— 对应 new-pipe 4a/4b/4c 同消息并行发起的真实形态
    - 回路：阶段清空后再次到达 → 出现次数+1（UT挂回coder天然可见）
    - 耗时：并行段内各阶段各算各的活跃窗口（真并行，允许总和>墙钟）
    """

    def __init__(self, fallback: "_StageWatcher | None" = None):
        self._fallback = fallback
        self._start = time.monotonic()
        self._active: dict[str, float] = {}  # 阶段 → 本段进入时间
        self._counts: dict[str, int] = {}
        self._totals: dict[str, float] = {}

    def feed(self, line: str) -> None:
        """流锚点事件（顶层 pipe 的脚本/agent 调用）——可回退（真实回路）。"""
        stage = self._match(line)
        if stage is not None:
            self._enter(stage)

    def feed_file(self, stage: str) -> None:
        """文件 marker 事件（subagent 写产出——设计/编码等内层活动顶层流看不到，
        靠文件观察器补）。文件事件天然滞后：秩守卫只许前进不许回退，
        防晚到文件（如预处理阶段写的 rs_input 在预检后才轮询到）把阶段拖回去。
        """
        rank = _STAGE_RANK.get(stage)
        if rank is None:
            return
        cur_max = max((_STAGE_RANK.get(st, -1) for st in self._active), default=-1)
        if rank <= cur_max:
            return  # 滞后事件，忽略
        self._enter(stage)

    def _enter(self, stage: str) -> None:
        now = time.monotonic()
        if stage in self._active:
            return  # 已在活动集（并行组内重复）
        if stage in _PARALLEL_GROUP:
            # 只清组外旧阶段，组内共存
            for st in [k for k in self._active if k not in _PARALLEL_GROUP]:
                self._close_stage(st, now)
        else:
            for st in list(self._active):
                self._close_stage(st, now)
        self._active[stage] = now
        self._counts[stage] = self._counts.get(stage, 0) + 1

    def _close_stage(self, stage: str, now: float) -> None:
        self._totals[stage] = self._totals.get(stage, 0.0) + (now - self._active.pop(stage))

    @staticmethod
    def _match(line: str) -> str | None:
        for pat, stage in _STREAM_ANCHORS:
            if pat.search(line):
                return stage
        return None

    def _stage_label(self, stage: str) -> str:
        occ = self._counts.get(stage, 1)
        label = stage + (f"(第{occ}次·回路)" if occ > 1 else "")
        if stage == "规则编码" and self._fallback is not None and self._fallback._etl_count:
            label += f"({self._fallback._etl_count}个SQL)"
        return label

    def stage_text(self) -> str:
        if not self._active:
            return self._fallback.stage_text() if self._fallback else "启动中"
        labels = [self._stage_label(st) for st in sorted(self._active, key=_STAGE_RANK.get)]
        if len(labels) > 1:
            return "+".join(labels) + "(并行)"
        return labels[0]

    def finish(self) -> tuple[dict[str, float], dict[str, int]]:
        now = time.monotonic()
        for st in list(self._active):
            self._close_stage(st, now)
        times = {k: round(v, 2) for k, v in self._totals.items()}
        if not times and self._fallback is not None:
            # 流锚点全程失明（输出格式变化/包壳吞输出）→ 兜底观察器
            return self._fallback.finish(), {}
        return times, dict(self._counts)


class _StageWatcher:
    """轮询产出目录，按 marker 首现时间反推当前阶段与各阶段耗时。"""

    def __init__(self, case_name: str, base: Path, on_marker=None, on_suspect=None):
        self._base = base
        self._asset = case_name
        self._on_marker = on_marker  # marker 首现回调（喂给 StageTracker 补内层阶段）
        self._on_suspect = on_suspect  # 自建脚本文件回调（纪律检查）
        self._start = time.monotonic()
        self._seen: dict[str, float] = {}  # 阶段名 → 首现耗时
        self._etl_count = 0
        self._stop = threading.Event()
        self._checked_suspects: set[str] = set()
        self._deliver: Path | None = None
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._poll_once()
            except Exception:
                pass
            self._stop.wait(2.0)

    def _poll_once(self) -> None:
        if self._deliver is None:
            self._deliver = _find_deliver_loose(self._base, self._asset)
            if self._deliver is None:
                return
        for stage, rel in _STAGE_MARKERS:
            if stage in self._seen:
                continue
            target = self._deliver / rel
            if target.exists() and (target.is_file() or any(target.iterdir())):
                self._seen[stage] = time.monotonic() - self._start
                if self._on_marker:
                    try:
                        self._on_marker(stage)
                    except Exception:
                        pass
        etl_dir = self._deliver / "etl"
        if etl_dir.exists():
            self._etl_count = sum(1 for f in etl_dir.iterdir() if f.suffix == ".sql")
        # 纪律检查：产出目录里的自建脚本文件（.py/.sh；diagnose 目录铁律豁免）
        if self._on_suspect:
            for f in self._deliver.rglob("*"):
                if f.is_file() and f.suffix in (".py", ".sh"):
                    rel = f.relative_to(self._deliver).as_posix()
                    if "_internal/diagnose" in rel:
                        continue
                    key = rel
                    if key not in self._checked_suspects:
                        self._checked_suspects.add(key)
                        try:
                            self._on_suspect(rel)
                        except Exception:
                            pass

    def recent_markers(self, n: int = 3) -> list[str]:
        """最近首现的 marker 阶段名（时间倒序）——文件违规的代理前因线索。"""
        ordered = sorted(self._seen.items(), key=lambda kv: kv[1], reverse=True)
        return [stage for stage, _ in ordered[:n]]

    def stage_text(self) -> str:
        """spinner 用的当前阶段文本（最近首现的 marker；编码阶段带规则计数）。"""
        if not self._seen:
            return "启动中" if self._deliver is None else "预处理中"
        latest = max(self._seen, key=self._seen.get)
        if latest == "规则编码" and self._etl_count:
            return f"规则编码({self._etl_count}个SQL)"
        return latest

    def finish(self) -> dict[str, float]:
        """停止观察，按 marker 首现顺序推算各阶段耗时（估算值）。"""
        self._stop.set()
        self._thread.join(timeout=3)
        ordered = sorted(self._seen.items(), key=lambda kv: kv[1])
        times: dict[str, float] = {}
        for i, (stage, t0) in enumerate(ordered):
            t1 = ordered[i + 1][1] if i + 1 < len(ordered) else None
            times[stage] = round((t1 - t0) if t1 is not None else max(0.0, t0), 1)
        return times
