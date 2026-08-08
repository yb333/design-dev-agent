"""类型兼容性判定模块。

复用自 analyzer 项目（dws-pipeline-analyzer/references/engine.py L5844-5989）的类型矩阵，
封装为自包含模块，避免与 precheck.py 已有的 _normalize_type 命名冲突。

判定口径：源类型能否被目标类型冗余兜底（不丢数据）。
- 同家族 + 目标长度≥源 → 兼容
- integer → numeric 安全跨类（整数可精确表示为数值）
- 整数家族互转（int/bigint/smallint）兼容
- 其他跨大类（int↔varchar↔date）不兼容

对外暴露：
- assess_type_risk(source_type, target_type) → 风险类型 | None（高层 API）
- RISK_LABEL_CN（风险类型中文映射，给决策文件用）
"""

# 类型大类归一化映射（6 大类）
_TYPE_FAMILY_MAP = {
    "int": "integer", "integer": "integer", "bigint": "integer",
    "smallint": "integer", "tinyint": "integer", "int2": "integer",
    "int4": "integer", "int8": "integer", "serial": "integer",
    "varchar": "varchar", "character": "varchar", "char": "varchar",
    "text": "varchar", "string": "varchar", "nvarchar": "varchar",
    "nvarchar2": "varchar", "varchar2": "varchar",
    "numeric": "numeric", "decimal": "numeric", "number": "numeric",
    "float": "numeric", "double": "numeric", "real": "numeric",
    "float4": "numeric", "float8": "numeric", "precision": "numeric",
    "date": "datetime", "timestamp": "datetime", "time": "datetime",
    "datetime": "datetime",
    "boolean": "boolean", "bool": "boolean",
}


def normalize_type_simple(type_str: str) -> str:
    """归一化类型字符串：去空格、统一小写。

    注意：与 precheck.py 的 _normalize_type（带 timestamp tz 拆分和别名替换）不同，
    这里只用最简归一化做兼容判定（与 analyzer 同口径）。
    """
    if not type_str:
        return ""
    return type_str.replace(" ", "").lower()


def same_int_family(type1: str, type2: str) -> bool:
    """两个类型是否都是整数家族（int/bigint/smallint/tinyint 等）。

    sqlglot 解析时会把 bigint 标准化成 int，整数互转不丢数据，不该报。
    """
    INT_TYPES = {"int", "integer", "bigint", "smallint", "tinyint"}
    base1 = type1.split("(")[0]
    base2 = type2.split("(")[0]
    return base1 in INT_TYPES and base2 in INT_TYPES


def parse_type_info(type_str: str) -> dict:
    """解析类型字符串为结构化信息：{family, raw, length, scale}。

    family: 归一化大类（integer/varchar/numeric/datetime/boolean/unknown）
    length: 长度（varchar 的 n，或 numeric 的 precision）
    scale: 小数位数（numeric 的 scale）
    """
    import re
    if not type_str:
        return {"family": "unknown", "raw": "", "length": None, "scale": None}

    raw = type_str.strip()
    lower = raw.lower()

    type_name_match = re.match(r'^([a-zA-Z][a-zA-Z\s]*?)(?:\s*\(|\s*$)', lower)
    if type_name_match:
        base_name = type_name_match.group(1).strip()
        if "character" in base_name and "varying" in lower:
            base_name = "varchar"
        elif base_name == "character":
            base_name = "char"
    else:
        base_name = lower.split("(")[0].split()[0] if lower.split() else "unknown"

    family = _TYPE_FAMILY_MAP.get(base_name, "unknown")

    length = None
    scale = None
    param_match = re.search(r'\(([^)]*)\)', lower)
    if param_match:
        params = [p.strip() for p in param_match.group(1).split(",")]
        if params:
            try:
                length = int(params[0])
            except (ValueError, TypeError):
                pass
        if len(params) > 1:
            try:
                scale = int(params[1])
            except (ValueError, TypeError):
                pass

    return {"family": family, "raw": raw, "length": length, "scale": scale}


def is_type_compatible(source_type: str, target_type: str) -> bool:
    """源类型能否被目标类型冗余兜底（不丢数据）。

    与 analyzer impact_analyzer._assess_type_change 同一套逻辑。
    """
    src = parse_type_info(source_type)
    tgt = parse_type_info(target_type)

    # 整数家族互转（含 sqlglot bigint→int 标准化场景）
    if same_int_family(normalize_type_simple(source_type), normalize_type_simple(target_type)):
        return True

    # integer → numeric 安全跨类：目标精度要能容纳整数位数
    if src["family"] == "integer" and tgt["family"] == "numeric":
        src_len = src["length"]
        if src_len is None:
            src_len_map = {"int": 10, "integer": 10, "bigint": 19,
                           "smallint": 5, "tinyint": 3}
            src_base = normalize_type_simple(source_type).split("(")[0]
            src_len = src_len_map.get(src_base, 10)
        if tgt["length"] is not None:
            return tgt["length"] >= src_len
        return True  # 目标 numeric 无精度限制（罕见），兼容

    # 同家族比长度
    if src["family"] == tgt["family"]:
        # 目标无长度（如 text）→ 不限制
        if tgt["length"] is None:
            return True
        # 源无长度 → 无法判，保守兼容
        if src["length"] is None:
            return True
        # varchar 比长度
        if src["family"] == "varchar":
            return tgt["length"] >= src["length"]
        # numeric 比精度+标度
        if src["family"] == "numeric":
            if tgt["length"] < src["length"]:
                return False
            if src["scale"] is not None and tgt["scale"] is not None:
                if tgt["scale"] < src["scale"]:
                    return False
            return True
        # 整数/datetime/boolean 同家族
        return True

    # 跨大类（int↔varchar↔date）不兼容
    return False


def is_precision_change(type1: str, type2: str) -> bool:
    """判断两个类型是否仅精度/长度不同（类型族相同）。"""
    base1 = type1.split("(")[0]
    base2 = type2.split("(")[0]
    return base1 == base2 and type1 != type2


# 风险类型 → 中文标签（给决策文件用）
RISK_LABEL_CN = {
    "length_overflow": "长度超长",
    "precision_loss": "精度收窄",
    "type_incompatible": "跨大类不兼容",
}


def assess_type_risk(source_type: str, target_type: str) -> str | None:
    """评估源→目标类型风险。

    返回 None=无风险（相同或兼容），否则返回风险类型：
        "length_overflow"     长度超长（varchar 同家族目标更窄）
        "precision_loss"      精度丢失（numeric 精度/标度收窄）
        "type_incompatible"   跨大类不兼容（int↔varchar↔date 等）
    """
    if not source_type or not target_type:
        return None

    src_norm = normalize_type_simple(source_type)
    tgt_norm = normalize_type_simple(target_type)

    # 类型完全一致 → 无风险
    if src_norm == tgt_norm:
        return None

    # 兼容（冗余兜底）→ 无风险
    if is_type_compatible(source_type, target_type):
        return None

    # 不兼容 → 区分风险类型
    src = parse_type_info(source_type)
    tgt = parse_type_info(target_type)

    # 同家族但目标更窄 → 精度/长度问题
    if src["family"] == tgt["family"]:
        if src["family"] == "varchar":
            # varchar 同家族目标更窄 → 长度超长
            if tgt["length"] is not None and src["length"] is not None and tgt["length"] < src["length"]:
                return "length_overflow"
            return "length_overflow"  # 同家族 varchar 不兼容的只剩长度问题
        if src["family"] == "numeric":
            # numeric 精度/标度收窄
            return "precision_loss"
        # integer/datetime/boolean 同家族不兼容极少见，归精度问题
        return "precision_loss"

    # 跨大类 → 类型不兼容
    return "type_incompatible"
