"""LTS 调度任务路径解析（2026-09-14 自 assemble_ts 抽出——两消费者：assemble_ts[f/view/init] + assemble_dq[dq]）。

只含任务路径键的读取与解析；lts_config 其余段（cluster_local/db_name/group_code/
dep_task_ids）归 assemble_export 导出期消费，键不重叠互不干扰。
"""

import json
from pathlib import Path

from config_paths import lts_config_path


def load_schedule_config(config_path: str = "") -> dict:
    """读 lts_config.json 的任务路径段（2026-09-10 与 LTS 导出配置合一，schedule_config 退役）。

    结构：{default: {project_name, task_group, init/dq 子键（可选，任务种类独立路径）, 导出期键...},
           schema_mappings: {schema: 同 default 结构},
           dep_task_ids: {...}}
    """
    if not config_path:
        config_path = str(lts_config_path())
    p = Path(config_path)
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    # 过滤掉 _comment / _structure 等说明字段
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def resolve_schedule_path(sched_config: dict, schema: str, task_kind: str) -> dict:
    """按 schema + 任务种类解析调度任务路径（project_name/task_group）。

    task_kind: 'f' | 'view' | 'dq' | 'init'（f/view=main 路径）
    查找优先级（两维度嵌套——schema 块内的任务种类子键差异化）：
      schema_mappings.{schema}.{kind子键} → schema_mappings.{schema}.平铺
      → default.{kind子键} → default.平铺
    init/dq 子键为空或省略 = 同 main。

    返回 {project_name, task_group}（找不到都为空串，不报错）。
    """
    if not sched_config:
        return {"project_name": "", "task_group": ""}

    default_cfg = sched_config.get("default", {}) or {}
    schema_cfg = (sched_config.get("schema_mappings", {}) or {}).get(schema, {}) or {}

    kind_key = {"init": "init", "dq": "dq"}.get(task_kind, "")  # f/view 走平铺

    def _pick(layer: dict) -> tuple[str, str]:
        if kind_key and isinstance(layer.get(kind_key), dict):
            p_ = layer[kind_key].get("project_name") or layer.get("project_name") or ""
            g_ = layer[kind_key].get("task_group") or layer.get("task_group") or ""
        else:
            p_ = layer.get("project_name") or ""
            g_ = layer.get("task_group") or ""
        return p_, g_

    s_p, s_g = _pick(schema_cfg)
    d_p, d_g = _pick(default_cfg)
    return {"project_name": s_p or d_p, "task_group": s_g or d_g}
