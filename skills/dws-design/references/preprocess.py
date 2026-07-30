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
# RS.md markdown 表格解析
# RS 是 BA 写的纯 markdown 文档（有固定模板）。
# 按章节标题定位表格 + 按表头列名匹配提取，不依赖 YAML 标记块。
# ============================================================

# RS 各章节的标题关键词 → 用于定位
RS_SECTION_KEYWORDS = {
    "asset": ["资产基本信息"],
    "sched": ["L07", "初始化及调度"],
    "upstream": ["湖表调度"],
    "dq": ["L06", "数据质量检查规则"],
}

# 资产基本信息表格：表头列名 → rs_input 字段名
ASSET_HEADER_MAP = {
    "SCHEMA": "target_full",       # 匹配 "资产 SCHEMA.接口视图"
    "资产描述": "description",
    "业务对象": "business_object",
    "逻辑数据实体": "grain",
    "owner 部门": "owner_dept",    # 匹配 "数据 owner 部门"
    "owner 人员": "owner_person",  # 匹配 "数据 owner 人员"
    "重点资产": "is_key_asset",
    "消费情况": "consumption",
}

# 调度配置表格：表头列名 → rs_input 字段名
SCHED_HEADER_MAP = {
    "调度方案": "strategy",
    "调度频率": "frequency",
    "调度完成时间要求": "sla",
    "初始化时间范围": "init_time_range",
    "增量识别方式": "incremental_key",
}

# 湖表调度表格：表头列名 → upstream 字段名
UPSTREAM_HEADER_MAP = {
    "湖表": "table",
    "任务名": "task",
    "环境": "env",
    "应用": "app",
    "项目": "project",
    "任务组": "group",
}

# DQ 规则表格：表头列名 → dq 字段名
DQ_HEADER_MAP = {
    "检查范围": "scope",
    "检查类型": "check_type",
    "规则名称": "rule_name",
    "规则描述": "rule_desc",
}


def _find_section(content: str, keywords: list[str]) -> str:
    """按标题关键词或加粗文字定位章节，返回章节内容到下一个同级标记。
    支持两种定位：
    - markdown 标题（### xxx）
    - 加粗文字（**xxx**）—— RS 模板里 L01-L09 用加粗而非标题
    """
    lines = content.split("\n")
    in_section = False
    match_level = 0       # 匹配到的标题级别（0=加粗定位）
    result: list[str] = []

    for line in lines:
        stripped = line.strip()

        if not in_section:
            # 查找章节起点
            if stripped.startswith("#"):
                level = len(stripped) - len(stripped.lstrip("#"))
                title = stripped.lstrip("# ").strip()
                if any(kw in title for kw in keywords):
                    in_section = True
                    match_level = level
                    continue
            elif stripped.startswith("**") and stripped.endswith("**") and stripped.count("**") == 2:
                bold_text = stripped.strip("*").strip()
                if any(kw in bold_text for kw in keywords):
                    in_section = True
                    match_level = 0  # 加粗定位
                    continue
        else:
            # 在章节内，检查结束条件
            if stripped.startswith("#"):
                level = len(stripped) - len(stripped.lstrip("#"))
                # 标题定位的章节：遇到同级或更高级标题结束
                if match_level > 0 and level <= match_level:
                    break
                # 加粗定位的章节：遇到三级及以上标题结束
                if match_level == 0 and level <= 3:
                    break
            elif stripped.startswith("**") and stripped.endswith("**") and stripped.count("**") == 2:
                bold_text = stripped.strip("*").strip()
                # 遇到另一个 Lxx 或湖表标记时结束
                if bold_text.startswith("L0") or bold_text.startswith("湖表"):
                    break
            result.append(line)

    return "\n".join(result)


def _parse_md_table(table_text: str) -> tuple[list[str], list[list[str]]]:
    """解析 markdown 表格，返回 (表头列表, 数据行列表)。"""
    lines = table_text.strip().split("\n")
    headers: list[str] = []
    rows: list[list[str]] = []

    for line in lines:
        line = line.strip()
        if not line or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")]
        # 去掉首尾空（| 分割产生的空串）
        cells = [c for c in cells if c != "" or True]
        cells = [c for c in line.split("|")]
        cells = cells[1:-1] if len(cells) >= 2 else cells  # 去掉首尾 |
        cells = [c.strip() for c in cells]

        # 跳过分隔行（|---|---|）
        if all(re.match(r"^[-:]+$", c) for c in cells if c):
            continue

        if not headers:
            headers = cells
        else:
            rows.append(cells)

    return headers, rows


def _extract_kv_table(section: str, header_map: dict[str, str]) -> dict[str, str]:
    """从章节里提取键值表格（| 属性 | 内容 | 格式），按表头列名匹配。"""
    headers, rows = _parse_md_table(section)
    if not headers or not rows:
        return {}

    result: dict[str, str] = {}
    # 找到"内容"列的索引（通常是第二列）
    value_col = 1 if len(headers) >= 2 else 0
    key_col = 0

    for row in rows:
        if len(row) <= key_col:
            continue
        key_text = row[key_col].strip()
        value_text = row[value_col].strip() if len(row) > value_col else ""

        # 模糊匹配表头
        for rs_key, target_key in header_map.items():
            if rs_key in key_text or key_text in rs_key:
                result[target_key] = value_text
                break

    return result


def _extract_list_table(section: str, header_map: dict[str, str]) -> list[dict[str, str]]:
    """从章节里提取列表表格（多行数据），按表头列名匹配。"""
    headers, rows = _parse_md_table(section)
    if not headers or not rows:
        return []

    # 建立列名 → 索引的映射（模糊匹配）
    col_map: dict[str, int] = {}
    for rs_key, target_key in header_map.items():
        for i, h in enumerate(headers):
            if rs_key in h or h in rs_key:
                col_map[target_key] = i
                break

    result: list[dict[str, str]] = []
    for row in rows:
        item: dict[str, str] = {}
        for target_key, col_idx in col_map.items():
            item[target_key] = row[col_idx].strip() if len(row) > col_idx else ""
        if any(v for v in item.values()):  # 至少有一个非空值
            result.append(item)

    return result


def extract_rs_data(rs_path: str) -> dict[str, Any]:
    """从 RS.md 的 markdown 表格提取结构化数据（按章节定位+表头匹配）。"""
    content = Path(rs_path).read_text(encoding="utf-8")
    rs_data: dict[str, Any] = {}
    errors: list[str] = []

    # 1. 资产基本信息
    section = _find_section(content, RS_SECTION_KEYWORDS["asset"])
    asset = _extract_kv_table(section, ASSET_HEADER_MAP)
    if asset:
        # 解析 target_full（schema.table 格式）
        target_full = asset.pop("target_full", "")
        if target_full and "." in target_full:
            parts = target_full.split(".")
            asset.setdefault("schema", parts[0])
            asset.setdefault("table", ".".join(parts[1:]))
        rs_data["meta"] = asset
    else:
        errors.append("资产基本信息表格未找到或为空")

    # 2. 调度配置
    section = _find_section(content, RS_SECTION_KEYWORDS["sched"])
    sched = _extract_kv_table(section, SCHED_HEADER_MAP)
    rs_data["schedule"] = sched

    # 3. 湖表调度（上游任务）
    section = _find_section(content, RS_SECTION_KEYWORDS["upstream"])
    upstream = _extract_list_table(section, UPSTREAM_HEADER_MAP)
    rs_data["schedule"]["upstream"] = upstream

    # 4. DQ 规则（可选）
    section = _find_section(content, RS_SECTION_KEYWORDS["dq"])
    dq = _extract_list_table(section, DQ_HEADER_MAP)
    rs_data["dq_requirements"] = dq

    rs_data["_extract_errors"] = errors
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

    # 3. 字段映射（含映射规则交叉校验）
    field_mappings = rs_input.get("field_mappings", [])
    if not field_mappings:
        result.add_error("无字段映射（field_mappings 为空）")
    else:
        result.add_pass(f"字段映射数: {len(field_mappings)}")

        # 合法的映射规则类型
        VALID_RULES = {"直接复制", "数据加工", "赋值", "序列"}

        for fm in field_mappings:
            target_field = fm.get("target_column", "")
            if not target_field:
                result.add_error("存在无目标字段名的映射行")
                continue

            rule = (fm.get("transform_rule") or fm.get("mapping_rule") or "").strip()
            expr = (fm.get("transform_detail") or fm.get("mapping_expression") or "").strip()
            source_field = (fm.get("source_column") or "").strip()

            # 3a. 映射规则必须有值且合法
            if not rule:
                result.add_error(f"字段 {target_field} 缺少映射规则")
                continue
            if rule not in VALID_RULES:
                result.add_error(f"字段 {target_field} 的映射规则 '{rule}' 不合法（应为：直接复制/数据加工/赋值/序列）")
                continue

            # 3b. 交叉校验：规则类型 vs 映射表达式 vs 来源字段
            if rule == "直接复制":
                # 直接复制：不该有加工表达式
                if expr and expr != "-":
                    result.add_warn(f"字段 {target_field} 是'直接复制'但填了映射表达式 '{expr[:30]}'，若有加工逻辑应改为'数据加工'")
                # 直接复制：必须有来源字段
                if not source_field:
                    result.add_error(f"字段 {target_field} 是'直接复制'但缺少来源字段（source_column）")

            elif rule == "数据加工":
                # 数据加工：必须有加工表达式
                if not expr or expr == "-":
                    result.add_error(f"字段 {target_field} 是'数据加工'但映射表达式为空（必须描述加工逻辑）")
                # 数据加工：通常需要来源字段（除非是纯派生字段）
                if not source_field:
                    result.add_warn(f"字段 {target_field} 是'数据加工'但没有来源字段，确认是否为纯派生字段")

            elif rule == "赋值":
                # 赋值：必须有赋值表达式（说明赋什么值）
                if not expr or expr == "-":
                    result.add_error(f"字段 {target_field} 是'赋值'但映射表达式为空（必须说明赋什么值，如 'N' 或 ${{P_CYCLE_ID}}）")
                # 赋值：不需要来源字段（正常）

            elif rule == "序列":
                # 序列：极少见，标记一下
                result.add_pass(f"字段 {target_field} 是'序列'类型（自增序列，特殊处理）")

    # 4. 目标字段重复检查
    seen_fields: dict[str, int] = {}
    for fm in field_mappings:
        tf = fm.get("target_column", "")
        if tf:
            seen_fields[tf] = seen_fields.get(tf, 0) + 1
    for field, count in seen_fields.items():
        if count > 1:
            result.add_error(f"目标字段 '{field}' 重复出现 {count} 次")

    # 5. 调度信息（来自 RS）
    schedule = rs_input.get("schedule", {})
    if not schedule.get("frequency"):
        result.add_warn("调度频率缺失（RS L07 调度频率）")
    if not schedule.get("upstream"):
        result.add_warn("上游调度任务缺失（RS L07 湖表调度信息）")

    # 6. 别名一致性（属性级的别名必须在实体级存在）
    entity_aliases = {st.get("source_alias") for st in source_tables if st.get("source_alias")}
    for fm in field_mappings:
        fm_alias = fm.get("source_alias", "")
        if fm_alias and fm_alias not in entity_aliases:
            result.add_error(f"字段 {fm.get('target_column', '?')} 的来源别名 '{fm_alias}' 在实体级 mapping 中不存在")

    # 7. 映射表达式模糊术语检查
    biz_terms = ["等等", "之类", "相关", "之类的", "等等等"]
    for fm in field_mappings:
        expr = fm.get("transform_detail") or fm.get("mapping_expression") or ""
        for term in biz_terms:
            if term in str(expr):
                result.add_warn(f"字段 {fm.get('target_column', '?')} 的映射表达式含模糊术语: '{term}'")

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
