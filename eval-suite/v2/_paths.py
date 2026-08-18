"""v2 公共路径工具：定位 new-pipe 产出文件。

new-pipe 产出命名：
- SELECT: etl/{rule}.sql 或 etl/{rule}_{table}_{load_mode}.sql（带后缀）
- ts.md : {资产}_ts.md（部分历史产出为 ts.md，find_ts_md 兼容两种）

本模块封装定位逻辑，所有"找 SELECT / 找 ts.md"的调用方
（assert_artifacts / assert_sql / seed）都走这里，避免散落硬编码。
"""

from __future__ import annotations

from pathlib import Path


def find_select_file(output_dir: Path, code: str) -> Path | None:
    """定位某规则的 SELECT 文件（new-pipe etl/ 命名）。

    ETL 命名有两种形态（assemble_export.py 同款）：
    - 规范：etl/{code}.sql
    - 带后缀：etl/{code}_{table}_{load_mode}.sql（如 R0001_shop_truncate_table.sql）

    查找顺序：
    1. 精确 etl/{code}.sql
    2. etl/{code}_*.sql 前缀匹配（startswith 不用 glob，sorted 保证多候选确定性）
    """
    # 1. 精确 etl/{code}.sql
    exact = output_dir / "etl" / f"{code}.sql"
    if exact.exists():
        return exact
    # 2. etl/{code}_*.sql（带后缀命名）
    etl_dir = output_dir / "etl"
    if etl_dir.exists():
        for f in sorted(etl_dir.iterdir()):
            if f.is_file() and f.suffix == ".sql" and f.name.startswith(f"{code}_"):
                return f
    return None


def list_select_rules(output_dir: Path) -> list[str]:
    """枚举 etl/ 下所有规则的 code（去重排序）。

    etl/{code}.sql            → code
    etl/{code}_{后缀}.sql     → code（取首个 _ 之前；规则 code 一般无下划线）
    """
    codes: set[str] = set()
    etl_dir = output_dir / "etl"
    if etl_dir.exists():
        for f in etl_dir.iterdir():
            if f.is_file() and f.suffix == ".sql":
                codes.add(f.stem.split("_")[0])
    return sorted(codes)


def find_ts_md(output_dir: Path) -> Path | None:
    """定位 ts.md 文件。

    兼容两种命名：ts.md（老）和 {资产}_ts.md（new-pipe 新）。
    """
    plain = output_dir / "ts.md"
    if plain.exists():
        return plain
    if output_dir.exists():
        for f in output_dir.iterdir():
            if f.is_file() and f.name.endswith("_ts.md"):
                return f
    return None


# ============================================================
# 产出目录定位（固定三层 {appid}/{schema}/{资产}）
# ============================================================

# 产出目录唯一约定：10_project_deliver/{appid}/{schema}/{资产}/ddlc_design_dev/
# （appid/schema 由 new-pipe 按 schema_apps.json 建；eval 侧不依赖 config，
#  直接按资产名在三层下扫描发现）


def find_deliver(base: Path, asset: str) -> Path | None:
    """定位某资产的产出目录（ddlc_design_dev），三层 {appid}/{schema}/{asset}/ 扫描。

    返回存在 ts.json 的 ddlc_design_dev 目录，找不到返回 None。
    """
    if base.exists():
        for appid_dir in sorted(base.iterdir()):
            if not appid_dir.is_dir():
                continue
            for schema_dir in sorted(appid_dir.iterdir()):
                if not schema_dir.is_dir():
                    continue
                cand = schema_dir / asset / "ddlc_design_dev"
                if (cand / "ts.json").exists():
                    return cand
    return None


def scan_deliver_assets(base: Path) -> dict[str, Path]:
    """扫描全部资产产出（三层结构），返回 {资产名: ddlc_design_dev 目录}。"""
    assets: dict[str, Path] = {}
    if not base.exists():
        return assets
    for appid_dir in sorted(base.iterdir()):
        if not appid_dir.is_dir():
            continue
        for schema_dir in sorted(appid_dir.iterdir()):
            if not schema_dir.is_dir():
                continue
            for asset_dir in sorted(schema_dir.iterdir()):
                if not asset_dir.is_dir():
                    continue
                deliver = asset_dir / "ddlc_design_dev"
                if (deliver / "ts.json").exists():
                    assets[asset_dir.name] = deliver
    return assets


# ============================================================
# 案例输入文件发现（mapping / RS）
# ============================================================

# 案例目录的业务文件就两类：一个 xlsx/xls（mapping）+ 一个 md/txt（RS，可选）。
# 评测自己的文件（checks.yaml / expectations.json / golden/）都不占这两个后缀，
# 所以直接按后缀取：目录里唯一的 xlsx 就是 mapping，唯一的 md 就是 RS。
# 万一有多个（用户多拷了文件），名字含 mapping/rs 的优先，再按名排序取第一。


def find_mapping_file(case_dir: Path) -> Path | None:
    """目录里唯一的 *.xlsx/xls 即 mapping；多个时名字含 mapping 优先。"""
    if not case_dir.is_dir():
        return None
    candidates = sorted(
        f for f in case_dir.iterdir()
        if f.is_file() and f.suffix.lower() in (".xlsx", ".xls")
    )
    if not candidates:
        return None
    preferred = [f for f in candidates if "mapping" in f.name.lower()]
    return (preferred or candidates)[0]


def find_rs_file(case_dir: Path) -> Path | None:
    """目录里唯一的 *.md/txt 即 RS（可选输入，无则 None=无RS模式）；多个时含 rs 优先。"""
    if not case_dir.is_dir():
        return None
    candidates = sorted(
        f for f in case_dir.iterdir()
        if f.is_file() and f.suffix.lower() in (".md", ".txt")
    )
    if not candidates:
        return None
    preferred = [f for f in candidates if "rs" in f.name.lower() or "需求" in f.name]
    return (preferred or candidates)[0]
