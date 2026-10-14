"""baseline_v1 契约消费端校验器（vendor 侧）。

职责（docs/specs/opt/09-契约-baseline_v1.md §三）：
- vendored JSON Schema 校验（必填/类型/结构）
- 语义性条件约束（JSON Schema 表达不了的）：delete_mode=6 必须 merge_on 非空
- 版本支持检查：本仓支持的契约版本清单，不匹配 fail loud

纯函数、无外部状态；schema 默认取随仓 vendor 拷贝，可注入。
调用方（assemble_ts_baseline / 测试）拿违规清单自行决定 fail-loud 形态。
"""
from pathlib import Path
import json
from typing import Dict, List, Optional

from jsonschema import Draft202012Validator

# 本仓支持的契约版本（与 vendor schema 同步维护）
# "1.0"：初版（09-契约 交接基线）；"1.1"：write_plan 增量（analyzer 仓主导，
#   权威契约见 dws-analyzer-skill/docs/baseline_v1-契约.md §二）
# "1.2"：DDL 物理属性透传 tables[].table_props + fields[].is_distribute_key +
#   provenance[].sheets 定位（2026-10-14 编排合入波次，消费方同步指南 §七）
# "1.3"：产物更名 asset_facts.json + facts 两路径入口（--dir/--output）+ 分拣三修正
#   （混放不阻断进 warnings / .sql·.ddl 后缀即型 / DQ 两态化）——2026-10-14 12 章 v3 全量落地
SUPPORTED_VERSIONS = {"1.0", "1.1", "1.2", "1.3"}

# vendor schema 路径：opt-pipe/schemas/asset_facts.schema.json（v1.3 起随产物更名；旧产物按 version 字段兼容校验）
DEFAULT_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "asset_facts.schema.json"

_SCHEMA_CACHE: Dict[str, dict] = {}


def norm_asset(name: str) -> str:
    """资产名镜像归一（资产对账口径，唯一源——镜像语义只在 _f↔_i 之间，用户裁定）：
    剥 schema 前缀 + 去 _f/_i 尾（I 视图与 F 表互为镜像）。**_d 不剥**——dwb 层表的 _d
    是层命名不是镜像尾缀（dwb_cust_asset_d 的资产名就是原名，它的镜像写法不存在）。"""
    n = (name or "").strip()
    if "." in n:
        n = n.rsplit(".", 1)[-1]
    import re as _re
    return _re.sub(r"_[fi]$", "", n.lower())


def load_schema(schema_path: Optional[Path] = None) -> dict:
    """加载 vendored baseline_v1 JSON Schema（带简单缓存）。"""
    path = Path(schema_path) if schema_path else DEFAULT_SCHEMA_PATH
    key = str(path)
    if key not in _SCHEMA_CACHE:
        _SCHEMA_CACHE[key] = json.loads(path.read_text(encoding="utf-8"))
    return _SCHEMA_CACHE[key]


def validate_baseline_v1(data: dict, schema: Optional[dict] = None) -> List[str]:
    """校验 baseline_v1 数据，返回违规清单（空列表 = 通过）。

    三层检查：版本支持 → JSON Schema 结构 → 语义性条件约束。
    """
    errors: List[str] = []

    # 1. 版本支持（fail loud 的第一道）
    version = data.get("version")
    if not version:
        errors.append("[契约] 缺 version 字段（必填，双端校验锚点）")
    elif version not in SUPPORTED_VERSIONS:
        errors.append(
            f"[契约] 不支持的版本 {version!r}（本仓支持: {sorted(SUPPORTED_VERSIONS)}；"
            f"请与 analyzer 侧同步契约并升级 vendor schema）"
        )

    # 2. JSON Schema 结构校验
    sch = schema if schema is not None else load_schema()
    for err in sorted(Draft202012Validator(sch).iter_errors(data), key=lambda e: list(e.path)):
        loc = "/".join(str(p) for p in err.path) or "<root>"
        errors.append(f"[契约] {loc}: {err.message}")

    # 3. 语义性条件约束（schema 表达不了）
    for rule in data.get("rules") or []:
        if rule.get("delete_mode") == "6" and not (rule.get("merge_on") or "").strip():
            errors.append(
                f"[契约] 规则 {rule.get('rule_code', '?')} delete_mode=6（MERGE）但缺 merge_on——dm=6 必供"
            )

    return errors
