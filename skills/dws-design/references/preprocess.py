#!/usr/bin/env python3
"""
输入预处理：mapping.xlsx + RS.md → rs_input.json

职责：
1. 解析 mapping.xlsx（2 sheet：实体级 + 属性级）→ 结构化 mapping 数据
2. 从 RS.md 提取标记块（@asset/@sched/@upstream/@dq/@dataflow/@explore）→ 结构化 RS 数据
3. 合并成 rs_input.json（designer 的输入）
4. 预检完整性（字段覆盖/上游任务/调度信息）

使用方法：
    python preprocess.py --mapping mapping.xlsx --rs RS.md --output docs/output/{table}/01_input/rs_input.json
    python preprocess.py --mapping mapping.xlsx --rs RS.md --output rs_input.json --check

依赖：excel_parser（复用其 Excel 解析能力）
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# 复用 excel_parser 解析 mapping.xlsx
sys.path.insert(0, str(Path(__file__).parent))
from excel_parser import ExcelMappingParser  # noqa: E402
from dataclasses import asdict as _asdict


def parse_mapping(xlsx_path: str) -> dict[str, Any]:
    """解析 mapping.xlsx，返回原始 dict（含 source_tables + field_mappings + 目标表信息）"""
    parser = ExcelMappingParser(xlsx_path)
    if not parser.load():
        raise RuntimeError(f"mapping.xlsx 加载失败: {xlsx_path}")
    entity_mappings = parser.parse_entity_mapping()
    attribute_mappings = parser.parse_attribute_mapping()

    # 从实体级 mapping 提取目标表信息
    target_schema = ""
    target_table = ""
    target_table_cn = ""
    if entity_mappings:
        first = entity_mappings[0]
        target_schema = first.target_schema
        target_table = first.target_table
        target_table_cn = first.target_table_cn

    return {
        "target_schema": target_schema,
        "target_table": target_table,
        "target_table_cn": target_table_cn,
        "source_tables": [_asdict(m) for m in entity_mappings],
        "field_mappings": [_asdict(m) for m in attribute_mappings],
    }


# ============================================================
# RS.md 标记块提取
# ============================================================

MARKER_PATTERN = re.compile(
    r"<!--\s*@(?:asset|sched|upstream|dq|dataflow|explore)\s*-->"
    r"(.*?)"
    r"<!--\s*/@(?:asset|sched|upstream|dq|dataflow|explore)\s*-->",
    re.DOTALL,
)


def extract_rs_blocks(rs_path: str) -> dict[str, str]:
    """从 RS.md 提取所有标记块的原始文本。返回 {block_name: raw_text}"""
    content = Path(rs_path).read_text(encoding="utf-8")
    blocks = {}
    for match in MARKER_PATTERN.finditer(content):
        # 从注释标记里提取 block name
        full = match.group(0)
        name_match = re.search(r"<!--\s*@(\w+)\s*-->", full)
        if name_match:
            blocks[name_match.group(1)] = match.group(1).strip()
    return blocks


def parse_yaml_block(text: str) -> Any:
    """简单 YAML 解析（不引入 pyyaml，处理常见的 key: value 和列表）。
    对于复杂结构，建议用 pyyaml。这里先做基础解析。"""
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text)
    except ImportError:
        # 无 pyyaml 时做最简解析
        return _simple_yaml_parse(text)


def _simple_yaml_parse(text: str) -> Any:
    """最简 YAML 解析（只支持 key: value 和 - item 列表）。"""
    result: dict[str, Any] = {}
    current_list: list[Any] | None = None
    current_key: str | None = None

    for line in text.strip().split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- "):
            val = stripped[2:].strip()
            if current_list is not None:
                current_list.append(val)
            continue
        if ":" in stripped:
            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip()
            if val:
                result[key] = val
                current_list = None
                current_key = key
            else:
                current_list = []
                result[key] = current_list
                current_key = key
    return result


def extract_rs_data(rs_path: str) -> dict[str, Any]:
    """从 RS.md 提取所有结构化数据。"""
    blocks = extract_rs_blocks(rs_path)
    rs_data: dict[str, Any] = {}

    for name, text in blocks.items():
        parsed = parse_yaml_block(text)
        if name == "asset":
            rs_data["meta"] = parsed
        elif name == "sched":
            rs_data.setdefault("schedule", {}).update(parsed if isinstance(parsed, dict) else {})
        elif name == "upstream":
            upstream = parsed if isinstance(parsed, dict) else {}
            rs_data.setdefault("schedule", {})["upstream"] = upstream.get("upstream", parsed if isinstance(parsed, list) else [])
        elif name == "dq":
            dq = parsed if isinstance(parsed, dict) else {}
            rs_data["dq_requirements"] = dq.get("rules", [])
        elif name == "dataflow":
            rs_data["data_flow_hint"] = parsed
        elif name == "explore":
            rs_data["data_exploration"] = parsed

    return rs_data


# ============================================================
# mapping 数据精简（去掉已移到 RS 的字段）
# ============================================================

# source_tables 里要删除的字段（已移到 RS @upstream）
SOURCE_TABLE_DROP_FIELDS = {"schedule_task", "exec_path", "dep_job_params"}

# field_mappings 里映射规则字段名统一
FIELD_MAPPING_RULE_MAP = {
    "mapping_rule": "transform_rule",  # 旧名 → 新名
    "mapping_expression": "transform_detail",
}


def slim_mapping_data(mapping_raw: dict[str, Any]) -> dict[str, Any]:
    """精简 mapping 数据：去掉已移到 RS 的字段，统一字段名。"""
    # source_tables 精简
    source_tables = []
    for st in mapping_raw.get("source_tables", []):
        slim_st = {k: v for k, v in st.items() if k not in SOURCE_TABLE_DROP_FIELDS}
        source_tables.append(slim_st)

    # field_mappings 精简 + 字段名统一
    field_mappings = []
    for fm in mapping_raw.get("field_mappings", []):
        slim_fm = {}
        for k, v in fm.items():
            new_key = FIELD_MAPPING_RULE_MAP.get(k, k)
            slim_fm[new_key] = v
        field_mappings.append(slim_fm)

    return {
        "source_tables": source_tables,
        "field_mappings": field_mappings,
    }


# ============================================================
# 合并 mapping + RS → rs_input.json
# ============================================================

def build_rs_input(mapping_raw: dict[str, Any], rs_data: dict[str, Any]) -> dict[str, Any]:
    """合并 mapping 数据和 RS 数据，产出 rs_input.json 结构。"""
    slim_mapping = slim_mapping_data(mapping_raw)

    # 从 mapping 提取目标表基本信息
    target_schema = mapping_raw.get("target_schema", "")
    target_table = mapping_raw.get("target_table", "")
    target_table_cn = mapping_raw.get("target_table_cn", "")

    # 从 RS @asset 提取目标表信息（RS 优先）
    rs_meta = rs_data.get("meta", {})
    rs_target = rs_meta.get("target", {}) if isinstance(rs_meta, dict) else {}

    rs_input: dict[str, Any] = {
        "meta": {
            "target": {
                "schema": rs_target.get("schema", target_schema),
                "table": rs_target.get("table", target_table),
                "cn": rs_target.get("cn", target_table_cn),
                "description": rs_meta.get("target", {}).get("description", "") if isinstance(rs_meta, dict) else "",
            },
            "owner": rs_meta.get("owner", {}) if isinstance(rs_meta, dict) else {},
            "grain": rs_meta.get("grain", "") if isinstance(rs_meta, dict) else "",
            "load_strategy": {
                "strategy": rs_data.get("schedule", {}).get("strategy", ""),
                "incremental_key": rs_data.get("schedule", {}).get("incremental_key", ""),
            },
        },
        "source_tables": slim_mapping["source_tables"],
        "field_mappings": slim_mapping["field_mappings"],
        "schedule": rs_data.get("schedule", {}),
        "data_flow_hint": rs_data.get("data_flow_hint", {}),
        "dq_requirements": rs_data.get("dq_requirements", []),
    }

    # 可选：数据探索信息
    if "data_exploration" in rs_data:
        rs_input["data_exploration"] = rs_data["data_exploration"]

    return rs_input


# ============================================================
# 预检
# ============================================================

class PrecheckResult:
    def __init__(self):
        self.passed: list[str] = []
        self.warnings: list[str] = []
        self.errors: list[str] = []

    @property
    def return_code(self) -> int:
        if self.errors:
            return 2  # INCOMPLETE
        if self.warnings:
            return 1  # WARNING
        return 0  # PASS

    def add_pass(self, msg: str):
        self.passed.append(msg)

    def add_warn(self, msg: str):
        self.warnings.append(msg)

    def add_error(self, msg: str):
        self.errors.append(msg)

    def summary(self) -> str:
        lines = [
            f"预检结果: {'PASS' if self.return_code == 0 else 'WARNING' if self.return_code == 1 else 'INCOMPLETE'}",
            f"  通过: {len(self.passed)}  警告: {len(self.warnings)}  错误: {len(self.errors)}",
        ]
        if self.warnings:
            lines.append("警告:")
            for w in self.warnings:
                lines.append(f"  ⚠ {w}")
        if self.errors:
            lines.append("错误:")
            for e in self.errors:
                lines.append(f"  ✗ {e}")
        return "\n".join(lines)


def precheck(rs_input: dict[str, Any]) -> PrecheckResult:
    """预检 rs_input.json 完整性。"""
    result = PrecheckResult()

    # 1. 目标表基本信息
    target = rs_input.get("meta", {}).get("target", {})
    if not target.get("schema") or not target.get("table"):
        result.add_error("目标表 schema/table 缺失")
    else:
        result.add_pass(f"目标表: {target['schema']}.{target['table']}")

    # 2. 源表
    source_tables = rs_input.get("source_tables", [])
    if not source_tables:
        result.add_error("无源表（source_tables 为空）")
    else:
        result.add_pass(f"源表数: {len(source_tables)}")
        for st in source_tables:
            if not st.get("source_alias"):
                result.add_warn(f"源表 {st.get('source_table', '?')} 缺少别名（source_alias）")

    # 3. 字段映射
    field_mappings = rs_input.get("field_mappings", [])
    if not field_mappings:
        result.add_error("无字段映射（field_mappings 为空）")
    else:
        result.add_pass(f"字段映射数: {len(field_mappings)}")
        # 检查每个字段映射的基本完整性
        for fm in field_mappings:
            target_field = fm.get("target_column", "")
            if not target_field:
                result.add_warn("存在无目标字段名的映射")
                continue
            rule = fm.get("transform_rule", fm.get("mapping_rule", ""))
            if not rule:
                result.add_warn(f"字段 {target_field} 缺少映射规则（transform_rule）")

    # 4. 调度信息（来自 RS）
    schedule = rs_input.get("schedule", {})
    if not schedule.get("frequency"):
        result.add_warn("调度频率缺失（RS @sched 的 frequency）")
    if not schedule.get("upstream"):
        result.add_warn("上游调度任务缺失（RS @upstream）")

    # 5. 转换规则无业务术语检查（简单版）
    biz_terms = ["等等", "之类", "相关"]  # 简单的业务术语检测
    for fm in field_mappings:
        rule_text = fm.get("transform_rule", "") or ""
        for term in biz_terms:
            if term in rule_text:
                result.add_warn(f"字段 {fm.get('target_column', '?')} 的转换规则可能含模糊术语: '{term}'")

    return result


# ============================================================
# 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="输入预处理：mapping.xlsx + RS.md → rs_input.json")
    parser.add_argument("--mapping", required=True, help="mapping.xlsx 路径")
    parser.add_argument("--rs", help="RS.md 路径（可选，无则只解析 mapping）")
    parser.add_argument("--output", required=True, help="rs_input.json 输出路径")
    parser.add_argument("--check", action="store_true", help="产出后执行预检")
    args = parser.parse_args()

    # 1. 解析 mapping.xlsx
    print(f"解析 mapping: {args.mapping}")
    try:
        mapping_raw = parse_mapping(args.mapping)
    except Exception as e:
        print(f"错误: mapping 解析失败: {e}", file=sys.stderr)
        sys.exit(1)
    if not mapping_raw.get("source_tables"):
        print("错误: mapping 解析失败", file=sys.stderr)
        sys.exit(1)
    print(f"  源表数: {len(mapping_raw.get('source_tables', []))}")
    print(f"  字段映射数: {len(mapping_raw.get('field_mappings', []))}")

    # 2. 提取 RS（如果有）
    rs_data = {}
    if args.rs:
        rs_path = Path(args.rs)
        if rs_path.exists():
            print(f"提取 RS: {args.rs}")
            rs_data = extract_rs_data(str(rs_path))
            print(f"  提取的 RS 数据块: {list(rs_data.keys())}")
        else:
            print(f"警告: RS 文件不存在: {args.rs}", file=sys.stderr)

    # 3. 合并
    rs_input = build_rs_input(mapping_raw, rs_data)

    # 4. 写出
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(rs_input, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"产出 rs_input.json: {output_path}")

    # 5. 预检（可选）
    if args.check:
        print("\n--- 预检 ---")
        result = precheck(rs_input)
        print(result.summary())
        sys.exit(result.return_code)


if __name__ == "__main__":
    main()
