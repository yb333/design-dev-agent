"""类型兼容性判定模块。

复用自 analyzer 项目（dws-pipeline-analyzer/references/engine.py L5844-5989）的类型矩阵，
封装为自包含模块，避免与 precheck.py 已有的 _normalize_type 命名冲突。

判定口径：源类型能否被目标类型冗余兜底（不丢数据）。
- 同家族 + 目标长度≥源 → 兼容
- integer → numeric 安全跨类（整数可精确表示为数值）
- 整数家族互转（int/bigint/smallint）兼容
- 字符类型互跨分方向：非N系(字节计) → N系(字符计) 且长度不缩 = 安全（字符数 ≤ 字节数），
  缩了报 length_overflow（常规档）；N系 → 非N系 / varchar↔varchar2 报 charset_semantics
  人工决策（字节 vs 字符口径取决于集群兼容模式，同长度也可能装不下中文）
- 日期时间 → varchar 是安全方向（确定性文本渲染，长度兜底）
- 数值家族→varchar 是安全方向（任何数值都有文本表示，目标长度兜底位数）：
  长度够=兼容放行；长度紧=报 length_overflow（常规档批量处理，不逐字段问人）
- 其余跨大类（varchar→数值、int↔date 等）不兼容——varchar→数值是危险方向，逐字段人决策

对外暴露：
- assess_type_risk(source_type, target_type) → 风险类型 | None（高层 API）
- RISK_LABEL_CN（风险类型中文映射，给决策文件用）
"""

# 类型大类归一化映射（6 大类）
_TYPE_FAMILY_MAP = {
    "int": "integer", "integer": "integer", "bigint": "integer",
    "smallint": "integer", "tinyint": "integer", "int1": "integer",
    "int2": "integer", "int4": "integer", "int8": "integer", "serial": "integer",
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

# 国家字符集类型（长度按字符/国家字符集计）；与 varchar/varchar2/char（兼容模式决定字节/字符）口径可能不同
_N_CHAR_BASES = {"nvarchar", "nvarchar2", "nchar"}


def _length_semantics_differ(base1: str, base2: str) -> bool:
    """字符类型 base 不同时，长度口径（字节 vs 字符）是否可能不同。

    - nvarchar/nvarchar2/nchar：字符/国家字符集口径
    - varchar/varchar2：不同兼容模式下可能按字节（Gauss ORA 模式 varchar2 按字节）
    同长度不保证装得下（中文 UTF-8 3字节/字）；到底哪个方向装不下取决于集群口径——
    脚本不猜，报风险走人工决策（红线：语义判断不自主）。
    """
    if base1 == base2:
        return False
    n1, n2 = base1 in _N_CHAR_BASES, base2 in _N_CHAR_BASES
    if n1 != n2:
        return True  # N 系 ↔ 非 N 系
    return {base1, base2} == {"varchar", "varchar2"}  # 字节/字符口径经典差异对


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
    int2/int4/int8 是 PG 内部名（pg_type），smallint/integer/bigint 是 SQL 标准名，等价。
    """
    INT_TYPES = {"int", "integer", "bigint", "smallint", "tinyint", "int1",
                 "int2", "int4", "int8", "serial", "bigserial", "smallserial"}
    base1 = type1.split("(")[0]
    base2 = type2.split("(")[0]
    return base1 in INT_TYPES and base2 in INT_TYPES


def parse_type_info(type_str: str) -> dict:
    """解析类型字符串为结构化信息：{family, raw, length, scale}。

    family: 归一化大类（integer/varchar/numeric/datetime/boolean/unknown）
    base: 归一前的 base 名（如 nvarchar2/varchar2，语义闸用它区分字符类型口径）
    length: 长度（varchar 的 n，或 numeric 的 precision）
    scale: 小数位数（numeric 的 scale）
    """
    import re
    if not type_str:
        return {"family": "unknown", "raw": "", "base": "", "length": None, "scale": None}

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

    return {"family": family, "raw": raw, "base": base_name, "length": length, "scale": scale}


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

    # datetime → varchar：安全方向（确定性文本渲染），长度兜底常见形态
    if src["family"] == "datetime" and tgt["family"] == "varchar":
        if tgt["length"] is None:
            return True
        needed = 10 if src["base"] == "date" else 30  # date=10；timestamp 带微秒/时区最宽约 30
        return tgt["length"] >= needed

    # 数值家族 → varchar：安全方向（任何数值都有完整文本表示），目标长度兜底位数即可
    if src["family"] in ("integer", "numeric") and tgt["family"] == "varchar":
        if tgt["length"] is None:
            return True  # text 无长度限制
        if src["family"] == "integer":
            _INT_DIGITS = {"int": 10, "integer": 10, "bigint": 19, "smallint": 5, "tinyint": 3}
            digits = src["length"] if src["length"] is not None else _INT_DIGITS.get(
                normalize_type_simple(source_type).split("(")[0], 10)
            return tgt["length"] >= digits + 1  # +1 符号位
        # numeric(p,s)：p 位数字 + 小数点 + 符号
        if src["length"] is None:
            return False  # 无精度 numeric 值宽任意，保守不判兼容（报长度风险走批量档）
        return tgt["length"] >= src["length"] + 2

    # 同家族比长度
    if src["family"] == tgt["family"]:
        # 目标无长度（如 text）→ 不限制
        if tgt["length"] is None:
            return True
        # 源无长度（无参 numeric/text/varchar，值可能任意大）+ 目标有限制 → 不兼容
        # 这才是"保守"：值可能超 target，报风险让 designer 加兜底（CAST/截取），而不是放行
        if src["length"] is None:
            return False
        # varchar 比长度
        if src["family"] == "varchar":
            # 长度口径不同的字符类型互跨：方向定安全性——
            # 非N系(字节计) → N系(字符计) 且长度不缩 = 安全（字符数 ≤ 字节数，必装得下）；
            # N系 → 非N系 同长度也可能装不下（中文 UTF-8 3字节/字），不自动放行
            if _length_semantics_differ(src["base"], tgt["base"]):
                if src["base"] not in _N_CHAR_BASES and tgt["base"] in _N_CHAR_BASES:
                    if tgt["length"] is None:
                        return True
                    if src["length"] is not None and tgt["length"] >= src["length"]:
                        return True
                return False
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


def join_key_pair_risky(type_a: str, type_b: str) -> bool:
    """JOIN 键对是否类型风险（保守判定：宁放过不误报）。

    用途：关联键对账（precheck/诊断）。与字段血缘的 assess_type_risk 不同——
    JOIN 等值比较关注的是"这个等式在数据库能不能成立/语义上说不说得通"：
    - 同 family（含 varchar 家族内部 nvarchar/varchar2 互跨）：等值成立，放行
    - integer↔numeric：数字家族互跨，PG 等值原生支持，放行
    - 其余跨 family（varchar↔numeric、varchar↔integer、varchar↔datetime 等）：
      裸等值直接报 operator does not exist；加了 cast 则执行期看内容
      （'abc'::numeric 报 invalid input syntax）——判定风险，交人决策
    """
    if not type_a or not type_b:
        return False
    fa = parse_type_info(type_a).get("family", "unknown")
    fb = parse_type_info(type_b).get("family", "unknown")
    if fa == fb:
        return False
    if {fa, fb} <= {"integer", "numeric"}:
        return False
    # unknown family（认不出的类型）放行——判不了的不硬判
    if "unknown" in (fa, fb):
        return False
    return True


# 风险类型 → 中文标签（给决策文件用）
RISK_LABEL_CN = {
    "length_overflow": "长度超长",
    "precision_loss": "精度收窄",
    "type_incompatible": "跨大类不兼容",
    "charset_semantics": "字符长度语义差异（nvarchar/varchar 字节/字符口径不同，同长度也可能装不下）",
}


def assess_type_risk(source_type: str, target_type: str) -> str | None:
    """评估源→目标类型风险。

    返回 None=无风险（相同或兼容），否则返回风险类型：
        "length_overflow"     长度超长（varchar 同家族目标更窄）
        "precision_loss"      精度丢失（numeric 精度/标度收窄）
        "type_incompatible"   跨大类不兼容（int↔varchar↔date 等）
        "charset_semantics"   字符长度语义差异（nvarchar↔varchar 等口径互跨，同长度也可能装不下）
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
            # 字符类型口径互跨：非 N 系 → N 系是安全方向（不缩长度已在兼容层放行，
            # 到这只是长度问题，归常规档）；N 系 → 非N系是字节/字符语义问题，人决策
            if _length_semantics_differ(src["base"], tgt["base"]):
                if src["base"] not in _N_CHAR_BASES and tgt["base"] in _N_CHAR_BASES:
                    return "length_overflow"
                return "charset_semantics"
            # varchar 同家族目标更窄 → 长度超长
            if tgt["length"] is not None and src["length"] is not None and tgt["length"] < src["length"]:
                return "length_overflow"
            return "length_overflow"  # 同家族 varchar 不兼容的只剩长度问题
        if src["family"] == "numeric":
            # numeric 精度/标度收窄
            return "precision_loss"
        # integer/datetime/boolean 同家族不兼容极少见，归精度问题
        return "precision_loss"

    # 安全方向（值域可完整表示）：数值→字符、日期时间→字符——到这只剩长度装不下，
    # 降级常规档批量处理，不逐字段问人（与 varchar→数值 的真跨大类危险方向区分）
    if tgt["family"] == "varchar" and src["family"] in ("integer", "numeric", "datetime"):
        return "length_overflow"

    # 跨大类 → 类型不兼容
    return "type_incompatible"
