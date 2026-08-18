"""跑流水线：实时流式输出 + 阶段横幅 + 计时 + 可配置超时。

阶段：preprocess → precheck → designer(+assemble_ts) → coder →
      assemble_ddl → export
（UT 连库阶段不在评测流水线内——需显式 opt-in，见 eval-suite/README.md）

调起 designer/coder 用 `opencode run --agent`（CLI，无 sidecar 依赖，适合内网）。

可观测性约定：
- 子进程输出实时上屏（缩进 4 格），不再憋到结束——用户随时知道跑到哪了
- 每阶段起止打横幅（▶ 开始 / ✅❌ 结果+耗时）
- 失败详情取输出尾部（traceback 崩溃行在末尾）+ 全文落盘
  {deliver}/_internal/diagnose/pipeline_{step}.log
- 超时可配（--timeout-ai / --timeout-script 传入），超时 kill 进程标记失败，
  不拖垮整轮（单案例失败由 run.py 继续下一个）
"""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

# 复用 base.py 的 CheckStatus
_VALIDATORS_DIR = Path(__file__).resolve().parent.parent / "validators"
if str(_VALIDATORS_DIR) not in sys.path:
    sys.path.insert(0, str(_VALIDATORS_DIR))

from base import CheckStatus  # type: ignore

from engine import PipelineStepResult
from _paths import find_mapping_file, find_rs_file

# 项目根
ROOT = Path(__file__).resolve().parents[2]
# skill 脚本目录：repo 内源优先（最新且必然存在），回退全局安装（install.py 装）。
# pipe 管线脚本归 design-dev-shared/scripts（2026-08 按调用方归位：preprocess/precheck/
# assemble_ddl/assemble_export/ut_*/check_db 等；dws-design/dws-coding 下只剩 agent 用的）。
_REPO_SHARED = ROOT / "skills" / "design-dev-shared" / "scripts"
_GLOBAL_SHARED = Path.home() / ".config" / "opencode" / "skills" / "design-dev-shared" / "scripts"
SHARED_REFS = _REPO_SHARED if _REPO_SHARED.exists() else _GLOBAL_SHARED

# 默认超时（秒）：AI 阶段（designer/coder 走 opencode）与管线脚本阶段，可由 CLI 覆盖
DEFAULT_TIMEOUT_AI = 1800
DEFAULT_TIMEOUT_SCRIPT = 120

# 输出模式：False=安静（默认，关键节点+旋转动画，子进程全文静默进 log，失败才展示尾部）；
# True=verbose（实时流式全量上屏，调试用，--verbose 开启）
VERBOSE = False


def set_verbose(v: bool) -> None:
    global VERBOSE
    VERBOSE = v


_SPIN_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

# 实时全文日志目录（安静模式也能随时查看子进程在干嘛，不用 --verbose 重跑）
_LIVE_DIR = ROOT / "eval-suite" / "results" / "_live"
# 输出静默超过该秒数，spinner 切 ⚠ 提示"可能卡住或长思考"
_QUIET_WARN_SECONDS = 60

# opencode 解析缓存（Windows 下 Popen 解析不到 .cmd，见 opencode_cmd）
_OPENCODE_RESOLVED: list[str] | None = None


def opencode_cmd() -> list[str]:
    """解析 agent 启动器（opencode 家族），返回可作 Popen argv 前缀的列表。

    内网用自包壳启动器 `nga run "提示词"`，本地/标准环境用 `opencode`——
    两者 run 子命令形态一致，只是可执行名不同，统一走本解析器。
    优先级：环境变量 EVAL_OPENCODE（run.py --opencode 注入，可指向任意启动器）
    > shutil.which("nga")（内网包壳）> shutil.which("opencode")。

    Windows 坑：npm 全局装的是 opencode.cmd，Popen 不按 PATHEXT 解析
    .cmd/.bat → WinError 2；shutil.which 按 PATHEXT 找完整路径，跨平台安全。
    """
    global _OPENCODE_RESOLVED
    if _OPENCODE_RESOLVED is None:
        exe = os.environ.get("EVAL_OPENCODE", "").strip()
        if not exe:
            exe = shutil.which("nga") or shutil.which("opencode")
        if not exe:
            raise RuntimeError(
                "未找到 agent 启动器（先找 nga，再找 opencode）。确认已安装并在 PATH；"
                "或用 --opencode 传完整路径（Windows npm 形如 "
                "C:/Users/<你>/AppData/Roaming/npm/opencode.cmd；内网包壳传 nga 完整路径）"
            )
        _OPENCODE_RESOLVED = [exe]
    return _OPENCODE_RESOLVED


# ============================================================
# 子进程运行（流式 + 超时）
# ============================================================


def _run_stream(
    cmd: list[str], timeout: float, cwd: Path | None = None, label: str = "",
    stage_provider=None,
) -> tuple[int, str]:
    """运行命令：全量缓存输出；超时 kill 并标记。

    输出模式（VERBOSE）：
    - 安静（默认）：不实时上屏，终端显示旋转动画（label+耗时，原地刷新，
      仅 TTY；重定向时完全静默）；失败时由 _fail_detail 展示尾部+全文
    - verbose：实时流式上屏（调试用）

    返回 (退出码, 合并输出)。超时返回 -1，输出尾部带 [TIMEOUT] 标记。
    读子进程输出走独立线程 + 队列，主循环按 deadline 轮询——
    僵死进程（无输出无退出）也能被超时收割。
    """
    try:
        # Windows 重定向/GBK 控制台遇 UTF-8 子进程输出（emoji/中文）不炸整轮
        try:
            sys.stdout.reconfigure(errors="replace")
        except Exception:
            pass
        # 执行窗口回显完整提交命令（人能直接看到/复制重跑；含空格参数加引号）
        quoted = [f'"{c}"' if " " in str(c) else str(c) for c in cmd]
        print(f"    $ {' '.join(quoted)}", flush=True)
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            # 强制 UTF-8 解码：子进程（opencode/nga）输出 UTF-8，中文 Windows 的
            # Popen(text=True) 默认按 locale(GBK) 解 → UnicodeDecodeError 崩读线程
            encoding="utf-8",
            errors="replace",
            cwd=str(cwd or ROOT),
        )
    except Exception as e:
        return -1, str(e)

    q: queue.Queue = queue.Queue()

    def _reader() -> None:
        try:
            for line in proc.stdout:  # type: ignore[union-attr]
                q.put(line)
        finally:
            q.put(None)

    threading.Thread(target=_reader, daemon=True).start()

    buf: list[str] = []
    start = time.monotonic()
    deadline = start + timeout
    timed_out = False
    is_tty = sys.stdout.isatty()
    spin_idx = 0
    last_spin = start
    last_output = start  # 最近一次子进程输出时间（卡住 vs 正常的判别信号）
    out_bytes = 0

    # 实时全文日志（带 label 的调用才开；每次运行覆盖，可随时打开看进度）
    live_f = None
    live_path = None
    if label:
        try:
            _LIVE_DIR.mkdir(parents=True, exist_ok=True)
            safe = re.sub(r"[^\w\-]+", "_", label)
            live_path = _LIVE_DIR / f"{safe}.log"
            live_f = open(live_path, "w", encoding="utf-8", errors="replace")
        except Exception:
            live_f = None
    if live_path:
        try:
            hint = f"    （实时全文可查看: {live_path.relative_to(ROOT)}）"
        except Exception:
            hint = f"    （实时全文可查看: {live_path}）"
        print(hint, flush=True)

    def _spin() -> None:
        nonlocal spin_idx, last_spin
        if not is_tty or VERBOSE:
            return
        now = time.monotonic()
        if now - last_spin >= 0.5:
            quiet_s = int(now - last_output)
            # 输出静默超阈值 → ⚠：可能是模型长思考，也可能真卡了（区分不了就如实说）
            frame = "⚠" if quiet_s >= _QUIET_WARN_SECONDS else _SPIN_FRAMES[spin_idx % len(_SPIN_FRAMES)]
            spin_idx += 1
            stage_txt = ""
            if stage_provider is not None:
                try:
                    st = stage_provider()
                    if st:
                        stage_txt = f" · 阶段:{st}"
                except Exception:
                    pass
            stats = f"{stage_txt} · {len(buf)}行/{out_bytes // 1024}KB · 静默{quiet_s}s"
            warn = f"（可能卡住或长思考，超时上限{int(timeout)}s）" if quiet_s >= _QUIET_WARN_SECONDS else ""
            sys.stdout.write(f"\r    {frame} {label or '执行中'} {int(now - start)}s{stats}{warn}   ")
            sys.stdout.flush()
            last_spin = now

    def _spin_end() -> None:
        if is_tty and not VERBOSE:
            sys.stdout.write("\r" + " " * 60 + "\r")
            sys.stdout.flush()

    while True:
        try:
            item = q.get(timeout=0.5)
        except queue.Empty:
            if time.monotonic() > deadline:
                timed_out = True
                proc.kill()
                break
            _spin()
            continue
        if item is None:
            break
        buf.append(item)
        out_bytes += len(item)
        last_output = time.monotonic()
        if live_f:
            try:
                live_f.write(item)
            except Exception:
                pass
        if VERBOSE:
            print("    " + item, end="", flush=True)  # 缩进区分子进程输出
        else:
            _spin()

    _spin_end()
    if live_f:
        try:
            live_f.close()
        except Exception:
            pass
    if timed_out:
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        combined = "".join(buf) + f"\n[TIMEOUT] 超时({timeout:.0f}s)已终止: {' '.join(cmd[:3])}..."
        print(f"    {combined.rsplit(chr(10), 1)[-1]}", flush=True)
        return -1, combined
    # EOF 后有界等待：读线程若异常退出（等编码问题），子进程可能还卡在写管道，
    # 无界 wait 会死锁——给 30s 宽限后 kill 收割
    try:
        proc.wait(timeout=30)
    except Exception:
        proc.kill()
        proc.wait()
    return proc.returncode or 0, "".join(buf)


def _run_python(script: str, args: list[str], timeout: float) -> tuple[int, str]:
    """运行 Python 脚本（当前解释器），返回 (退出码, 合并输出)。"""
    return _run_stream([sys.executable, script] + args, timeout, label=Path(script).stem)


def _fail_detail(step: str, deliver: Path, out: str) -> str:
    """失败详情：取输出尾部（traceback 的崩溃行在末尾），全文落盘到 _internal/diagnose/。"""
    try:
        diag_dir = deliver / "_internal" / "diagnose"
        diag_dir.mkdir(parents=True, exist_ok=True)
        (diag_dir / f"pipeline_{step}.log").write_text(out, encoding="utf-8")
        log_path = str(diag_dir / f"pipeline_{step}.log")
    except Exception:
        log_path = "(log落盘失败)"
    tail = out[-600:].strip() if out.strip() else "(无输出)"
    return f"{tail}\n[全文] {log_path}"


def _step(name: str, fn) -> PipelineStepResult:
    """包装一个阶段：横幅 + 计时 + 转 PipelineStepResult。"""
    print(f"\n▶ {name}", flush=True)
    start = time.monotonic()
    try:
        ok, detail = fn()
    except Exception as e:
        ok, detail = False, f"异常: {e}"
    duration = time.monotonic() - start
    status = CheckStatus.PASS if ok else CheckStatus.FAIL
    icon = "✅" if ok else "❌"
    print(f"{icon} {name} ({duration:.1f}s)" + (f" — {detail}" if detail else ""), flush=True)
    return PipelineStepResult(step=name, status=status, detail=detail, duration_seconds=duration)


# ============================================================
# 各阶段实现（每步返回 (ok: bool, detail: str)）
# ============================================================


def _preprocess(deliver: Path, mapping: Path, rs: Path, timeout: float) -> tuple[bool, str]:
    internal = deliver / "_internal"
    internal.mkdir(parents=True, exist_ok=True)
    rs_input = internal / "rs_input.json"
    args = ["--mapping", str(mapping), "--output", str(rs_input)]
    # 只有 RS 真实存在才传 --rs（None=无RS模式；Path 恒为真，不能直接 if rs）
    if rs and rs.exists():
        args.extend(["--rs", str(rs)])
    code, out = _run_python(str(SHARED_REFS / "preprocess.py"), args, timeout)
    if code == 0:
        data = json.loads(rs_input.read_text(encoding="utf-8"))
        n_fields = len(data.get("field_mappings", []))
        n_sources = len(data.get("source_tables", []))
        return True, f"{n_fields}字段, {n_sources}源表"
    return False, _fail_detail("preprocess", deliver, out)


def _precheck(deliver: Path, timeout: float) -> tuple[bool, str]:
    rs_input = deliver / "_internal" / "rs_input.json"
    code, out = _run_python(str(SHARED_REFS / "precheck.py"), ["--input", str(rs_input)], timeout)
    if code == 0:
        return True, "全部通过"
    if code == 1:
        return True, "有警告但不阻断"
    return False, _fail_detail("precheck", deliver, out)


def _designer(deliver: Path, skip_ai: bool, timeout: float) -> tuple[bool, str]:
    internal = deliver / "_internal"
    rs_input = internal / "rs_input.json"
    if skip_ai:
        return (internal / "design_decisions.yaml").exists(), "跳过AI"

    abs_rs = str(rs_input.resolve())
    abs_internal = str(internal.resolve())
    abs_deliver = str(deliver.resolve())

    prompt = (
        f"读取 {abs_rs}，产出 design_decisions.yaml 到 {abs_internal}/。"
        f"然后调 assemble_ts.py --rs {abs_rs} "
        f"--decisions {abs_internal}/design_decisions.yaml "
        f"--outdir {abs_deliver} 组装 ts.json + ts.md。"
    )
    _, out = _run_stream(
        opencode_cmd() + ["run", "--agent", "dws-designer", "--format", "json", prompt], timeout,
        label="designer",
    )

    ts_json = deliver / "ts.json"
    decisions = internal / "design_decisions.yaml"
    if ts_json.exists() and decisions.exists():
        ts = json.loads(ts_json.read_text(encoding="utf-8"))
        n_rules = len(ts.get("rules", {}))
        return True, f"{n_rules}规则"
    return False, _fail_detail("designer", deliver, out or "(opencode 无输出)")


def _coder(deliver: Path, rule_code: str, skip_ai: bool, timeout: float) -> tuple[bool, str]:
    etl_dir = deliver / "etl"
    etl_dir.mkdir(exist_ok=True)
    if skip_ai:
        return False, "跳过AI"

    abs_ts = str((deliver / "ts.json").resolve())
    abs_etl = str(etl_dir.resolve())
    prompt = f"ts.json 路径: {abs_ts}，编码规则: {rule_code}，产出 SELECT 到 {abs_etl}/{rule_code}.sql"

    _, out = _run_stream(
        opencode_cmd() + ["run", "--agent", "dws-coder", "--format", "json", prompt], timeout,
        label=f"coder({rule_code})",
    )

    # 确定性文件名（不用 glob）；带后缀命名由评测层 find_select_file 兼容
    select_file = etl_dir / f"{rule_code}.sql"
    if select_file.exists():
        n_lines = len(select_file.read_text(encoding="utf-8").strip().splitlines())
        return True, f"{n_lines}行 SELECT"
    return False, _fail_detail(f"coder_{rule_code}", deliver, out or "(opencode 无输出)")


def _assemble_ddl(deliver: Path, timeout: float) -> tuple[bool, str]:
    code, out = _run_python(
        str(SHARED_REFS / "assemble_ddl.py"),
        ["--ts", str(deliver / "ts.json"), "--outdir", str(deliver)],
        timeout,
    )
    ddl_dir = deliver / "ddl"
    # 确定性检查：目录存在即可（具体文件名由产物层断言检查）
    if code == 0 and ddl_dir.exists():
        return True, "DDL 生成完成"
    return False, _fail_detail("assemble_ddl", deliver, out)


def _assemble_export(deliver: Path, timeout: float) -> tuple[bool, str]:
    code, out = _run_python(
        str(SHARED_REFS / "assemble_export.py"),
        [
            "--ts", str(deliver / "ts.json"),
            "--etl-dir", str(deliver / "etl"),
            "--ddl-dir", str(deliver / "ddl"),
            "--outdir", str(deliver),
        ],
        timeout,
    )
    export_dir = deliver / "export"
    if code == 0 and export_dir.exists():
        return True, "制品包生成完成"
    return False, _fail_detail("assemble_export", deliver, out)


# ============================================================
# 主流水线
# ============================================================


def run_pipeline(
    case_dir: Path,
    deliver: Path,
    skip_ai: bool = False,
    timeout_ai: float = DEFAULT_TIMEOUT_AI,
    timeout_script: float = DEFAULT_TIMEOUT_SCRIPT,
) -> list[PipelineStepResult]:
    """跑完整流水线，返回各阶段结果（带计时）。

    Args:
        case_dir: 用例目录（含 mapping.xlsx + RS.md）。
        deliver: 产出目录（ddlc_design_dev）。
        skip_ai: 跳过 AI 阶段（只跑脚本链路）。
        timeout_ai: AI 阶段（designer/coder）超时秒数。
        timeout_script: 管线脚本阶段超时秒数。
    """
    steps: list[PipelineStepResult] = []
    # 输入文件按特征发现（用户业务文件名多样，不硬编码 mapping.xlsx/RS.md）
    mapping = find_mapping_file(case_dir) or (case_dir / "mapping.xlsx")
    rs = find_rs_file(case_dir)

    # 1. preprocess
    steps.append(_step("preprocess", lambda: _preprocess(deliver, mapping, rs, timeout_script)))
    # preprocess 失败立即短路：rs_input.json 缺失/残留旧版时继续跑 precheck
    # 只会产生级联误报（读垃圾输入报 NoneType 之类），掩盖真正的失败原因
    if steps[-1].status == CheckStatus.FAIL:
        return steps
    # 2. precheck
    steps.append(_step("precheck", lambda: _precheck(deliver, timeout_script)))

    # 前置失败则不继续
    if any(s.status == CheckStatus.FAIL for s in steps):
        return steps

    # 3. designer
    steps.append(_step("designer", lambda: _designer(deliver, skip_ai, timeout_ai)))
    if steps[-1].status == CheckStatus.FAIL:
        return steps

    # 4. coder（每规则）
    ts_path = deliver / "ts.json"
    if ts_path.exists():
        ts = json.loads(ts_path.read_text(encoding="utf-8"))
        rules = list(ts.get("rules", {}).keys())
        for code in rules:
            steps.append(
                _step(f"coder({code})", lambda c=code: _coder(deliver, c, skip_ai, timeout_ai))
            )

    # 5. assemble_ddl
    steps.append(_step("assemble_ddl", lambda: _assemble_ddl(deliver, timeout_script)))
    # 6. export
    steps.append(_step("export", lambda: _assemble_export(deliver, timeout_script)))

    return steps
