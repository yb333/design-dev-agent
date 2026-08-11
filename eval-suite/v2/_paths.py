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
