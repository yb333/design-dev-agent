#!/usr/bin/env python3
"""
旧格式 mapping → 新格式 mapping + RS.md 转换器

旧格式特征：
- 实体级：无源表别名，有调度任务/执行路径/依赖参数
- 属性级：无序号/分组/别名/备注，映射规则用"直取/加工"

新格式特征：
- 实体级：有源表别名，调度信息归 RS
- 属性级：有序号/分组/别名/备注，映射规则用"直接复制/数据加工/赋值/序列"

用法:
  python convert_old_mapping.py --input 旧mapping.xlsx --outdir cases/xxx/
"""

import sys
import argparse
from pathlib import Path
import openpyxl
from openpyxl.styles import Font

# 映射规则名转换
RULE_MAP = {
    "直取": "直接复制",
    "加工": "数据加工",
    "赋值": "赋值",
    "序列": "序列",
    "直接复制": "直接复制",
    "数据加工": "数据加工",
}

# 标准审计字段（旧mapping没有，需要补充）
STANDARD_AUDIT = [
    ("del_flag", "删除标识", "NVARCHAR(1)", "'N'"),
    ("crt_cycle_id", "创建批次ID", "BIGINT", "'${P_CYCLE_ID}'"),
    ("last_upd_cycle_id", "最后更新批次ID", "BIGINT", "'${P_CYCLE_ID}'"),
    ("dw_last_update_date", "数仓最后更新时间", "TIMESTAMP(0) WITHOUT TIME ZONE", "CURRENT_TIMESTAMP"),
]


def auto_alias(table_name: str, existing: set, index: int) -> str:
    """从表名生成别名"""
    # 取表名首字母或前缀
    parts = table_name.replace(".", "_").split("_")
    if len(parts) == 1:
        alias = parts[0][:2]
    else:
        # 取每部分首字母
        alias = "".join(p[0] for p in parts if p)[:3]
    # 如果冲突，加序号
    base = alias
    while alias in existing:
        alias = f"{base}{index}"
    existing.add(alias)
    return alias


def convert(input_path: str, outdir: str):
    """转换旧格式 mapping 到新格式 + RS"""
    wb_old = openpyxl.load_workbook(input_path, data_only=True)

    # 读实体级
    ws_entity = wb_old["实体级mapping"]
    entity_rows = []
    aliases = set()
    for i, row in enumerate(ws_entity.iter_rows(values_only=True), 1):
        if i == 1:
            continue  # 跳过表头
        cells = [str(c) if c is not None else "" for c in row]
        if not cells[1]:  # 源表名为空跳过
            continue
        src_schema = cells[0]
        src_table = cells[1]
        src_cn = cells[2]
        tgt_schema = cells[3]
        tgt_cn = cells[4]
        tgt_table = cells[5]
        join_cond = cells[6]
        remark = cells[7]
        alias = auto_alias(src_table, aliases, i)
        entity_rows.append({
            "src_schema": src_schema, "src_table": src_table, "src_cn": src_cn,
            "tgt_schema": tgt_schema, "tgt_cn": tgt_cn, "tgt_table": tgt_table,
            "join_cond": join_cond, "remark": remark, "alias": alias,
        })

    if not entity_rows:
        print("错误：实体级mapping无数据", file=sys.stderr)
        return

    # 读属性级
    ws_attr = wb_old["属性级mapping"]
    attr_rows = []
    # 建表名→别名映射
    table_to_alias = {e["src_table"]: e["alias"] for e in entity_rows}

    for i, row in enumerate(ws_attr.iter_rows(values_only=True), 1):
        if i == 1:
            continue
        cells = [str(c) if c is not None else "" for c in row]
        if not cells[6]:  # 目标字段名为空跳过
            continue
        src_schema = cells[0]
        src_table = cells[1]
        src_field_cn = cells[2] if len(cells) > 2 else ""
        src_field = cells[2] if len(cells) > 2 else ""  # 旧格式可能是中文字段名
        src_type = cells[3] if len(cells) > 3 else ""
        old_rule = cells[4] if len(cells) > 4 else "直取"
        expression = cells[5] if len(cells) > 5 else ""
        target_field = cells[6] if len(cells) > 6 else ""
        target_cn = cells[7] if len(cells) > 7 else ""
        target_type = cells[8] if len(cells) > 8 else ""

        rule = RULE_MAP.get(old_rule, "直接复制")
        alias = table_to_alias.get(src_table, "")

        attr_rows.append({
            "src_schema": src_schema, "src_table": src_table, "alias": alias,
            "src_field_cn": src_field_cn, "src_field": src_field, "src_type": src_type,
            "rule": rule, "expression": expression,
            "target_field": target_field, "target_cn": target_cn, "target_type": target_type,
        })

    # 检查审计字段是否已有
    existing_targets = {a["target_field"].lower() for a in attr_rows}
    has_audit = any(audit[0] in existing_targets for audit in STANDARD_AUDIT)

    # 生成新格式 mapping
    wb_new = openpyxl.Workbook()
    tgt_table = entity_rows[0]["tgt_table"]
    tgt_schema = entity_rows[0]["tgt_schema"]
    tgt_cn = entity_rows[0]["tgt_cn"]

    # Sheet1: 实体级
    ws1 = wb_new.active
    ws1.title = "实体级mapping"
    ws1.append(["源表schema", "源表物理表名", "源表中文名", "源表别名",
                "目标表schema", "目标表中文名", "目标表物理表名", "关联&限定条件", "备注"])
    for e in entity_rows:
        ws1.append([e["src_schema"], e["src_table"], e["src_cn"], e["alias"],
                    e["tgt_schema"], e["tgt_cn"], e["tgt_table"], e["join_cond"], e["remark"]])

    # Sheet2: 属性级
    ws2 = wb_new.create_sheet("属性级mapping")
    ws2.append(["序号", "分组", "源Schema", "源表物理表名", "源表物理表别名",
                "源表字段中文名", "源表字段名", "源表字段类型",
                "映射规则*", "映射表达式", "目标字段名*", "目标字段中文名", "目标字段类型", "备注"])
    seq = 1
    for a in attr_rows:
        remark = ""
        if seq == 1:
            remark = "主键"  # 第一个字段通常是主键
        ws2.append([seq, "default", a["src_schema"], a["src_table"], a["alias"],
                    a["src_field_cn"], a["src_field"], a["src_type"],
                    a["rule"], a["expression"] if a["expression"] else "-",
                    a["target_field"], a["target_cn"], a["target_type"], remark])
        seq += 1

    # 补充审计字段（如果旧mapping没有）
    if not has_audit:
        for aname, acn, atype, aexpr in STANDARD_AUDIT:
            ws2.append([seq, "default", "", "", "", "", "", "",
                        "赋值", aexpr, aname, acn, atype, "审计字段"])
            seq += 1

    # 保存
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    mapping_path = outdir / "mapping.xlsx"
    wb_new.save(str(mapping_path))

    # 生成 RS.md
    rs_path = outdir / "RS.md"
    rs_content = f"""# RS - {tgt_cn}

## 1.1 资产基本信息

| 属性 | 内容 |
|------|------|
| SCHEMA | {tgt_schema} |
| 资产名称 | {tgt_table} |
| 资产描述 | {tgt_cn} |
| 业务对象 | {tgt_cn.replace('宽表', '').replace('中心', '')} |
| 逻辑数据实体 | 每行一个{tgt_cn.replace('宽表', '').replace('中心', '')}记录 |
| owner 部门 | 数据开发部 |
| owner 人员 | zhangsan |

## L07 初始化及调度

| 配置项 | 内容 |
|--------|------|
| 调度方案 | 全量调度 |
| 调度频率 | T+1，一天一调 |
| 调度完成时间 | 3:30 |
| 增量识别 | 不涉及 |
"""
    rs_path.write_text(rs_content, encoding="utf-8")

    n_audit = 0 if has_audit else 4
    print(f"✅ {tgt_table}: {len(attr_rows)}业务字段 + {n_audit}审计 = {len(attr_rows)+n_audit}总, {len(entity_rows)}源表")
    print(f"   mapping: {mapping_path}")
    print(f"   RS: {rs_path}")
    return tgt_table


def main():
    parser = argparse.ArgumentParser(description="旧格式mapping→新格式+RS转换")
    parser.add_argument("--input", required=True, help="旧格式mapping.xlsx路径")
    parser.add_argument("--outdir", required=True, help="输出目录")
    args = parser.parse_args()

    convert(args.input, args.outdir)


if __name__ == "__main__":
    main()
