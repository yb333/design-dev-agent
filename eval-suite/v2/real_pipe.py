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
    "【调用方显式声明：非交互批量评测——闸口①②跳过人工确认，"
    "全程不要 question 停下，需要人决策的事项记录后继续】"
)


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
    watcher = _StageWatcher(case_dir, deliver_base)

    def _do() -> tuple[bool, str]:
        # 不带 --format json：降低内网包壳启动器的旗标兼容面，默认格式流式输出更适合看进度
        code, out = _run_stream(
            opencode_cmd() + ["run", "--command", "new-pipe", message],
            timeout,
            label="new-pipe 真实流程",
            stage_provider=watcher.stage_text,
        )
        deliver = find_deliver(deliver_base, case_dir.name)
        return judge_real_run(deliver, code, out)

    steps = [_step("new-pipe(真实流程)", _do)]
    stage_times = watcher.finish()
    return steps, stage_times


# ============================================================
# 产出文件观察器：阶段反推 + 耗时估算（与 opencode 内部零耦合，只认产出文件）
# ============================================================

# marker 按流水线顺序：文件/目录首现 → 该阶段完成的信号
_STAGE_MARKERS: list[tuple[str, str]] = [
    ("预处理", "_internal/rs_input.json"),
    ("设计决策", "_internal/design_decisions.yaml"),
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


class _StageWatcher:
    """轮询产出目录，按 marker 首现时间反推当前阶段与各阶段耗时。"""

    def __init__(self, case_name: str, base: Path):
        self._base = base
        self._asset = case_name
        self._start = time.monotonic()
        self._seen: dict[str, float] = {}  # 阶段名 → 首现耗时
        self._etl_count = 0
        self._stop = threading.Event()
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
        etl_dir = self._deliver / "etl"
        if etl_dir.exists():
            self._etl_count = sum(1 for f in etl_dir.iterdir() if f.suffix == ".sql")

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
