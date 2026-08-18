"""baseline 存档与对比。

每次评测存 results/{case}/{timestamp}/result.json（含 git_sha、各层分数、
每断言详细结果）。下次自动找最新一份做 baseline，逐项对比：
- PASS→FAIL = 回退
- FAIL→PASS = 修复
- 新增 FAIL = 新问题
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

# 复用 base.py
_EVAL_SUITE = Path(__file__).resolve().parent.parent
if str(_EVAL_SUITE) not in sys.path:
    sys.path.insert(0, str(_EVAL_SUITE))

from validators.base import CheckStatus  # type: ignore

from engine import EvalResult

# baseline 存档根目录
RESULTS_DIR = _EVAL_SUITE / "results"


@dataclass
class CheckRecord:
    """单条断言的存档记录（可序列化）。"""

    layer: str
    key: str  # 稳定标识（从 detail 提取的断言名）
    status: str  # pass/fail/skip
    detail: str


@dataclass
class BaselineSnapshot:
    """一次评测的完整存档。"""

    case_name: str
    timestamp: str
    git_sha: str
    layer_stats: dict  # {layer: {pass, fail, skip}}
    checks: list[CheckRecord]
    pipeline_steps: list[dict] = field(default_factory=list)
    score: int | None = None  # 两级评分总分（跨轮可比）
    passed: bool | None = None  # 及格门（致命项零失败）
    deductions: list[dict] = field(default_factory=list)  # [{cat,weight,desc}]
    stage_times: dict[str, float] = field(default_factory=dict)  # {阶段:秒}（真实=流锚点时间线/重放=步骤耗时）
    stage_loops: dict[str, int] = field(default_factory=dict)  # {阶段:出现次数}（>1=执行回路）


def _git_sha() -> str:
    """获取当前 git commit short sha（失败返回 unknown）。"""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5,
            cwd=str(_EVAL_SUITE.parent),
        )
        return r.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _check_key(layer: str, detail: str) -> str:
    """从断言 detail 提取稳定标识（保证同一条断言跨轮 key 一致）。

    detail 形如：
    - design 层："business_key 匹配: ['order_id']" / "business_key 不符: ..."
    - artifacts 层："ts.json 顶层键齐全" / "audit_fields 正确 (4 个)"
    - code 层："R0001: GROUP BY 缺列: ['x']" / "R0001: 字段完整 (7/7)"

    稳定标识 = 断言名（不随状态变的部分）：
    - code 层：rule_code + 冒号后的断言类型词（如 "R0001:GROUP"）
    - 其他层：detail 的首个词（如 "business_key"、"ts.json"），忽略冒号后的状态描述
    """
    if layer == "code" and ":" in detail:
        prefix = detail.split(":", 1)[0].strip()  # R0001
        rest = detail.split(":", 1)[1].strip()
        # 断言类型词（GROUP/字段/JOIN/del_flag/CASE/SELECT/审计 的首个词）
        kw = rest.split()[0] if rest.split() else rest[:15]
        return f"{prefix}:{kw}"
    # 非 code 层：只取首个词（断言名），忽略冒号后的状态描述
    words = detail.split()
    return words[0] if words else detail[:15]


def snapshot_from_result(result: EvalResult) -> BaselineSnapshot:
    """把 EvalResult 转成可存档的 BaselineSnapshot。"""
    checks: list[CheckRecord] = []
    for layer, results in result.layer_results.items():
        for r in results:
            status = r.status.value if hasattr(r.status, "value") else str(r.status)
            checks.append(
                CheckRecord(
                    layer=layer,
                    key=_check_key(layer, r.detail),
                    status=status,
                    detail=r.detail,
                )
            )
    pipeline_records = [
        {
            "step": s.step,
            "status": s.status.value if hasattr(s.status, "value") else str(s.status),
            "duration": round(s.duration_seconds, 1),
        }
        for s in result.pipeline_steps
    ]
    return BaselineSnapshot(
        case_name=result.case_name,
        timestamp=datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        git_sha=_git_sha(),
        layer_stats=result.summary(),
        checks=checks,
        pipeline_steps=pipeline_records,
    )


def save_snapshot(snapshot: BaselineSnapshot) -> Path:
    """存档到 results/{case}/{timestamp}/result.json，返回路径。"""
    case_dir = RESULTS_DIR / _safe_name(snapshot.case_name)
    ts_dir = case_dir / snapshot.timestamp.replace(":", "-")
    ts_dir.mkdir(parents=True, exist_ok=True)
    path = ts_dir / "result.json"
    data = {
        "case_name": snapshot.case_name,
        "timestamp": snapshot.timestamp,
        "git_sha": snapshot.git_sha,
        "layer_stats": snapshot.layer_stats,
        "pipeline_steps": snapshot.pipeline_steps,
        "checks": [asdict(c) for c in snapshot.checks],
        "score": snapshot.score,
        "passed": snapshot.passed,
        "deductions": snapshot.deductions,
        "stage_times": snapshot.stage_times,
        "stage_loops": snapshot.stage_loops,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def find_latest_baseline(case_name: str) -> BaselineSnapshot | None:
    """找该用例最新的 baseline（按时间戳排序），无则返回 None。"""
    case_dir = RESULTS_DIR / _safe_name(case_name)
    if not case_dir.exists():
        return None
    ts_dirs = sorted(
        [d for d in case_dir.iterdir() if d.is_dir() and (d / "result.json").exists()],
        key=lambda d: d.name,
    )
    if not ts_dirs:
        return None
    latest = ts_dirs[-1]
    return _load_snapshot(latest / "result.json")


def _load_snapshot(path: Path) -> BaselineSnapshot | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    checks = [
        CheckRecord(layer=c["layer"], key=c["key"], status=c["status"], detail=c["detail"])
        for c in data.get("checks", [])
    ]
    return BaselineSnapshot(
        case_name=data["case_name"],
        timestamp=data["timestamp"],
        git_sha=data.get("git_sha", "unknown"),
        layer_stats=data.get("layer_stats", {}),
        checks=checks,
        pipeline_steps=data.get("pipeline_steps", []),
        score=data.get("score"),
        passed=data.get("passed"),
        deductions=data.get("deductions", []),
        stage_times=data.get("stage_times", {}),
        stage_loops=data.get("stage_loops", {}),
    )


@dataclass
class BaselineDiff:
    """与上轮 baseline 的对比结果。"""

    regressions: list[str] = field(default_factory=list)  # PASS→FAIL（回退）
    fixes: list[str] = field(default_factory=list)  # FAIL→PASS（修复）
    new_failures: list[str] = field(default_factory=list)  # 新出现的 FAIL
    has_baseline: bool = False
    baseline_timestamp: str = ""
    baseline_git_sha: str = ""
    baseline_score: int | None = None


def diff_against_baseline(
    current: EvalResult, baseline: BaselineSnapshot | None
) -> BaselineDiff:
    """对比当前结果与 baseline。"""
    d = BaselineDiff()
    if baseline is None:
        return d
    d.has_baseline = True
    d.baseline_timestamp = baseline.timestamp
    d.baseline_git_sha = baseline.git_sha
    d.baseline_score = baseline.score

    # 建 baseline 的 (layer, key) → status 索引
    base_map: dict[tuple[str, str], str] = {}
    for c in baseline.checks:
        base_map[(c.layer, c.key)] = c.status

    # 逐项对比当前结果
    current_seen: set[tuple[str, str]] = set()
    for layer, results in current.layer_results.items():
        for r in results:
            status = r.status.value if hasattr(r.status, "value") else str(r.status)
            key = _check_key(layer, r.detail)
            current_seen.add((layer, key))
            prev = base_map.get((layer, key))
            label = f"[{layer}] {r.detail[:50]}"
            if prev == "pass" and status == "fail":
                d.regressions.append(label)
            elif prev == "fail" and status == "pass":
                d.fixes.append(label)
            elif prev is None and status == "fail":
                d.new_failures.append(label)

    return d


def _safe_name(name: str) -> str:
    """用例名转安全目录名。"""
    return name.replace("/", "_").replace(" ", "_")
