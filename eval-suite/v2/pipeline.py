"""跑流水线：封装各阶段，每步加计时器。

复用 local_eval.py 的脚本路径和调用方式（opencode run --agent CLI），
但每步返回 PipelineStepResult（带耗时），不绑死 EvalReport。

阶段：preprocess → precheck → designer(+assemble_ts) → coder →
      assemble_ddl → assemble_dq → check_sql → ut(可选) → export

调起 designer/coder 用 `opencode run --agent`（CLI，无 sidecar 依赖，适合内网）。
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

# 复用 base.py 的 CheckStatus
_VALIDATORS_DIR = Path(__file__).resolve().parent.parent / "validators"
if str(_VALIDATORS_DIR) not in sys.path:
    sys.path.insert(0, str(_VALIDATORS_DIR))

from base import CheckStatus  # type: ignore

from engine import PipelineStepResult

# 项目根
ROOT = Path(__file__).resolve().parents[2]
# skill 脚本目录（install 后在 ~/.config/opencode/skills/）
DESIGN_REFS = Path.home() / ".config" / "opencode" / "skills" / "dws-design" / "scripts"
CODING_REFS = Path.home() / ".config" / "opencode" / "skills" / "dws-coding" / "scripts"


def _run_python(script: str, args: list[str], timeout: int = 60) -> tuple[int, str]:
    """运行 Python 脚本，返回 (退出码, 合并输出)。"""
    try:
        r = subprocess.run(
            ["python3", script] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(ROOT),
        )
        combined = r.stdout + ("\n" + r.stderr if r.stderr.strip() else "")
        return r.returncode, combined
    except subprocess.TimeoutExpired:
        return -1, f"超时({timeout}s)"
    except Exception as e:
        return -1, str(e)


def _run_cmd(cmd: list[str], timeout: int = 1800) -> tuple[int, str, str]:
    """运行命令，返回 (退出码, stdout, stderr)。"""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(ROOT))
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"超时({timeout}s)"
    except Exception as e:
        return -1, "", str(e)


def _step(name: str, fn) -> PipelineStepResult:
    """包装一个阶段：计时 + 转 PipelineStepResult。"""
    start = time.monotonic()
    try:
        ok, detail = fn()
    except Exception as e:
        ok, detail = False, f"异常: {e}"
    duration = time.monotonic() - start
    status = CheckStatus.PASS if ok else CheckStatus.FAIL
    return PipelineStepResult(step=name, status=status, detail=detail, duration_seconds=duration)


# ============================================================
# 各阶段实现（每步返回 (ok: bool, detail: str)）
# ============================================================


def _preprocess(deliver: Path, mapping: Path, rs: Path) -> tuple[bool, str]:
    internal = deliver / "_internal"
    internal.mkdir(parents=True, exist_ok=True)
    rs_input = internal / "rs_input.json"
    args = ["--mapping", str(mapping), "--output", str(rs_input)]
    if rs:
        args.extend(["--rs", str(rs)])
    code, out = _run_python(str(DESIGN_REFS / "preprocess.py"), args)
    if code == 0:
        data = json.loads(rs_input.read_text(encoding="utf-8"))
        n_fields = len(data.get("field_mappings", []))
        n_sources = len(data.get("source_tables", []))
        return True, f"{n_fields}字段, {n_sources}源表"
    return False, out[:200]


def _precheck(deliver: Path) -> tuple[bool, str]:
    rs_input = deliver / "_internal" / "rs_input.json"
    code, out = _run_python(str(DESIGN_REFS / "precheck.py"), ["--input", str(rs_input)])
    if code == 0:
        return True, "全部通过"
    if code == 1:
        return True, "有警告但不阻断"
    return False, out[:200]


def _designer(deliver: Path, skip_ai: bool) -> tuple[bool, str]:
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
    _run_cmd(["opencode", "run", "--agent", "dws-designer", "--format", "json", prompt], timeout=1800)

    ts_json = deliver / "ts.json"
    decisions = internal / "design_decisions.yaml"
    if ts_json.exists() and decisions.exists():
        ts = json.loads(ts_json.read_text(encoding="utf-8"))
        n_rules = len(ts.get("rules", {}))
        return True, f"{n_rules}规则"
    return False, f"产出缺失: ts.json={ts_json.exists()}, decisions={decisions.exists()}"


def _coder(deliver: Path, rule_code: str, skip_ai: bool) -> tuple[bool, str]:
    select_dir = deliver / "select"
    select_dir.mkdir(exist_ok=True)
    if skip_ai:
        return False, "跳过AI"

    abs_ts = str((deliver / "ts.json").resolve())
    abs_select = str(select_dir.resolve())
    prompt = f"ts.json 路径: {abs_ts}，编码规则: {rule_code}，产出 SELECT 到 {abs_select}/{rule_code}_select.sql"

    _run_cmd(["opencode", "run", "--agent", "dws-coder", "--format", "json", prompt], timeout=1800)

    # 确定性文件名（不用 glob）
    select_file = select_dir / f"{rule_code}_select.sql"
    if select_file.exists():
        n_lines = len(select_file.read_text(encoding="utf-8").strip().splitlines())
        return True, f"{n_lines}行 SELECT"
    return False, f"SELECT 文件未生成: {rule_code}_select.sql"


def _assemble_ddl(deliver: Path) -> tuple[bool, str]:
    code, out = _run_python(
        str(CODING_REFS / "assemble_ddl.py"),
        ["--ts", str(deliver / "ts.json"), "--outdir", str(deliver)],
    )
    ddl_dir = deliver / "ddl"
    rollback_dir = deliver / "ddl_rollback"
    # 确定性检查：目录存在即可（具体文件名由产物层断言检查）
    if code == 0 and ddl_dir.exists():
        return True, "DDL 生成完成"
    return False, out[:200]


def _assemble_export(deliver: Path) -> tuple[bool, str]:
    code, out = _run_python(
        str(CODING_REFS / "assemble_export.py"),
        [
            "--ts", str(deliver / "ts.json"),
            "--etl-dir", str(deliver / "select"),
            "--ddl-dir", str(deliver / "ddl"),
            "--outdir", str(deliver),
        ],
        timeout=120,
    )
    export_dir = deliver / "export"
    if code == 0 and export_dir.exists():
        return True, "制品包生成完成"
    return False, out[:200]


# ============================================================
# 主流水线
# ============================================================


def run_pipeline(
    case_dir: Path,
    deliver: Path,
    skip_ai: bool = False,
) -> list[PipelineStepResult]:
    """跑完整流水线，返回各阶段结果（带计时）。

    Args:
        case_dir: 用例目录（含 mapping.xlsx + RS.md）。
        deliver: 产出目录（ddlc_design_dev）。
        skip_ai: 跳过 AI 阶段（只跑脚本链路）。
    """
    steps: list[PipelineStepResult] = []
    mapping = case_dir / "mapping.xlsx"
    rs = case_dir / "RS.md"

    # 1. preprocess
    steps.append(_step("preprocess", lambda: _preprocess(deliver, mapping, rs)))
    # 2. precheck
    steps.append(_step("precheck", lambda: _precheck(deliver)))

    # 前置失败则不继续
    if any(s.status == CheckStatus.FAIL for s in steps):
        return steps

    # 3. designer
    steps.append(_step("designer", lambda: _designer(deliver, skip_ai)))
    if steps[-1].status == CheckStatus.FAIL:
        return steps

    # 4. coder（每规则）
    ts_path = deliver / "ts.json"
    if ts_path.exists():
        ts = json.loads(ts_path.read_text(encoding="utf-8"))
        rules = list(ts.get("rules", {}).keys())
        for code in rules:
            steps.append(_step(f"coder({code})", lambda c=code: _coder(deliver, c, skip_ai)))

    # 5. assemble_ddl
    steps.append(_step("assemble_ddl", lambda: _assemble_ddl(deliver)))
    # 6. export
    steps.append(_step("export", lambda: _assemble_export(deliver)))

    return steps
