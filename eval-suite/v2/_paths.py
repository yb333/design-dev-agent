"""v2 公共路径工具：定位产出文件，兼容 new-pipe 新格式与历史老格式。

new-pipe 流程产出（真实案例）：
- SELECT: etl/{rule}.sql
- ts.md : {资产}_ts.md

历史格式（002 等虚拟案例、v2 测试 fixture）：
- SELECT: select/{rule}_select.sql
- ts.md : ts.md

本模块统一封装定位逻辑：优先新格式，回退老格式。所有"找 SELECT / 找 ts.md"
的调用方（assert_artifacts / assert_sql / seed）都走这里，避免散落的硬编码。
"""

from __future__ import annotations

from pathlib import Path


def find_select_file(output_dir: Path, code: str) -> Path | None:
    """定位某规则的 SELECT 文件。

    new-pipe 的 ETL 命名有两种合法形态（assemble_export.py 同款处理）：
    - 规范：etl/{code}.sql
    - 带后缀：etl/{code}_{table}_{load_mode}.sql（如 R0001_shop_truncate_table.sql）

    优先级：
    1. etl/{code}.sql（精确，最规范）
    2. etl/{code}_*.sql（前缀匹配，覆盖带后缀命名；用 startswith 不用 glob，
       sorted 保证多候选时确定性）
    3. select/{code}_select.sql（历史老格式）
    """
    # 1. 精确 etl/{code}.sql
    new_fmt = output_dir / "etl" / f"{code}.sql"
    if new_fmt.exists():
        return new_fmt
    # 2. etl/{code}_*.sql（new-pipe 带后缀命名）
    etl_dir = output_dir / "etl"
    if etl_dir.exists():
        for f in sorted(etl_dir.iterdir()):
            if f.is_file() and f.suffix == ".sql" and f.name.startswith(f"{code}_"):
                return f
    # 3. 老格式 select/{code}_select.sql
    old_fmt = output_dir / "select" / f"{code}_select.sql"
    if old_fmt.exists():
        return old_fmt
    return None


def list_select_rules(output_dir: Path) -> list[str]:
    """枚举产出里所有规则的 code（合并 etl/ 和 select/，去重排序）。

    etl/{code}.sql            → code
    etl/{code}_{后缀}.sql     → code（取首个 _ 之前；规则 code 一般无下划线）
    select/{code}_select.sql  → code
    """
    codes: set[str] = set()
    etl_dir = output_dir / "etl"
    if etl_dir.exists():
        for f in etl_dir.iterdir():
            if f.is_file() and f.suffix == ".sql":
                # R0001.sql → R0001；R0001_shop_truncate_table.sql → R0001
                codes.add(f.stem.split("_")[0])
    select_dir = output_dir / "select"
    if select_dir.exists():
        for f in select_dir.iterdir():
            if f.is_file() and f.name.endswith("_select.sql"):
                codes.add(f.name[: -len("_select.sql")])
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
