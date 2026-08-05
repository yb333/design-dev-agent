"""断言引擎核心：调度各层断言，汇总结果。

P1 实现：流程层（pipeline 阶段状态）+ 产物层（assert_artifacts）。
design/code 层在 P2 实现，P1 标 SKIP。

复用 validators/base.py 的 CheckResult / CheckStatus，不重写结果抽象。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

_V2_DIR = Path(__file__).resolve().parent
if str(_V2_DIR) not in sys.path:
    sys.path.insert(0, str(_V2_DIR))
_EVAL_SUITE = Path(__file__).resolve().parent.parent
if str(_EVAL_SUITE) not in sys.path:
    sys.path.insert(0, str(_EVAL_SUITE))

from validators.base import CheckResult, CheckStatus  # type: ignore

import assert_artifacts
import assert_design
import assert_sql
from checks_schema import ChecksConfig


# 层定义（顺序即报告展示顺序）
LAYER_PIPELINE = "pipeline"
LAYER_ARTIFACTS = "artifacts"
LAYER_DESIGN = "design"
LAYER_CODE = "code"

LAYER_NAMES = {
    LAYER_PIPELINE: "流程层",
    LAYER_ARTIFACTS: "产物层",
    LAYER_DESIGN: "design 质量",
    LAYER_CODE: "code 质量",
}


@dataclass
class PipelineStepResult:
    """单个流水线阶段的结果（流程层用）。"""

    step: str
    status: CheckStatus
    detail: str = ""
    duration_seconds: float = 0.0


@dataclass
class EvalResult:
    """单用例评测总结果。"""

    case_name: str = ""
    layer_results: dict[str, list[CheckResult]] = field(default_factory=dict)
    pipeline_steps: list[PipelineStepResult] = field(default_factory=list)

    def add_layer(self, layer: str, results: list[CheckResult]):
        self.layer_results[layer] = results

    def summary(self) -> dict:
        """各层 pass/fail/skip 统计。"""
        stats = {}
        for layer, results in self.layer_results.items():
            passed = sum(1 for r in results if r.status == CheckStatus.PASS)
            failed = sum(1 for r in results if r.status == CheckStatus.FAIL)
            skipped = sum(1 for r in results if r.status == CheckStatus.SKIP)
            stats[layer] = {"pass": passed, "fail": failed, "skip": skipped}
        return stats


def run_evaluation(
    output_dir: Path,
    config: ChecksConfig,
    pipeline_steps: list[PipelineStepResult] | None = None,
) -> EvalResult:
    """对产出目录跑全部断言。

    Args:
        output_dir: ddlc_design_dev 目录。
        config: 该用例的 checks 配置。
        pipeline_steps: 流水线各阶段结果（None 表示 eval-only，无流程层）。
    """
    result = EvalResult(case_name=config.case_name or output_dir.parent.name)

    # 层1：流程层
    if pipeline_steps:
        pipeline_results = [
            CheckResult(
                check_type=LAYER_PIPELINE,
                status=s.status,
                detail=f"{s.step} ({s.duration_seconds:.1f}s){' — ' + s.detail if s.detail else ''}",
            )
            for s in pipeline_steps
        ]
        result.add_layer(LAYER_PIPELINE, pipeline_results)
        result.pipeline_steps = pipeline_steps

    # 层2：产物层
    result.add_layer(
        LAYER_ARTIFACTS, assert_artifacts.run_artifact_checks(output_dir, config.artifacts or None)
    )

    # 加载 rs_input（design 层要用它校验 field_targets 覆盖）
    rs_input = None
    rs_input_path = output_dir / "_internal" / "rs_input.json"
    if rs_input_path.exists():
        import json

        rs_input = json.loads(rs_input_path.read_text(encoding="utf-8"))

    # 加载 ts.json（code 层要用它取规则列表）
    import json

    ts = None
    ts_path = output_dir / "ts.json"
    if ts_path.exists():
        ts = json.loads(ts_path.read_text(encoding="utf-8"))

    # 层3：design 质量
    result.add_layer(
        LAYER_DESIGN,
        assert_design.run_design_checks(output_dir, config.design or None, rs_input),
    )

    # 层4：code 质量
    result.add_layer(
        LAYER_CODE, assert_sql.run_code_checks(output_dir, config.code or None, ts)
    )

    return result
