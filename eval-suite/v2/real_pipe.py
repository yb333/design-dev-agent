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
) -> list[PipelineStepResult]:
    """真实入口：opencode run --command new-pipe。流程层=单步（真实流程不拆阶段）。

    分阶段计时/定位是 --replay 诊断模式（pipeline.py）的职责。
    """
    args = build_command_args(case_dir)
    message = " ".join(args + [NON_INTERACTIVE_CLAUSE])

    def _do() -> tuple[bool, str]:
        # 不带 --format json：降低内网包壳启动器的旗标兼容面，默认格式流式输出更适合看进度
        code, out = _run_stream(
            opencode_cmd() + ["run", "--command", "new-pipe", message],
            timeout,
        )
        deliver = find_deliver(deliver_base, case_dir.name)
        return judge_real_run(deliver, code, out)

    return [_step("new-pipe(真实流程)", _do)]
