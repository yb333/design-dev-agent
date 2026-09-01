"""archive_writer —— 交付写回档案（docs/specs/opt/02 §〇 档案模型；v1.7 循环链闭合）。

档案 = 唯一锚点（ts + etl SQL + ddl 全量 + decisions/change），文本小件入 git。
archives/{appid}/{schema}/{资产}/{NNN_日期}/，NNN 顺延既有目录（不 glob——目录枚举）。
xlsx 大件不进档案（运行时产物可再生）。new-pipe 与 opt-pipe 共用（new-pipe 交付即建档）。
"""
import argparse
import json
import shutil
import sys
from datetime import date
from pathlib import Path
from typing import Optional


def next_seq(asset_dir: Path) -> int:
    if not asset_dir.exists():
        return 1
    seqs = []
    for d in asset_dir.iterdir():
        if d.is_dir() and d.name[:3].isdigit():
            seqs.append(int(d.name[:3]))
    return (max(seqs) + 1) if seqs else 1


def write_archive(archives_root: Path, schema: str, asset: str,
                  ts_path: Path, etl_dir: Path, ddl_dir: Path,
                  decisions_path: Optional[Path] = None) -> Path:
    asset_dir = archives_root / schema / asset
    dest = asset_dir / f"{next_seq(asset_dir):03d}_{date.today():%Y%m%d}"
    dest.mkdir(parents=True, exist_ok=False)
    shutil.copy2(ts_path, dest / ts_path.name)
    if etl_dir.is_dir():
        shutil.copytree(etl_dir, dest / "etl", dirs_exist_ok=True)
    if ddl_dir.is_dir():
        shutil.copytree(ddl_dir, dest / "ddl", dirs_exist_ok=True)
    if decisions_path and Path(decisions_path).exists():
        shutil.copy2(decisions_path, dest / Path(decisions_path).name)
    return dest


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="交付写回档案（ts + etl + ddl 全量 + decisions）")
    ap.add_argument("--ts", required=True, help="ts.json（new-pipe 产物或 ts_v2.json）")
    ap.add_argument("--etl-dir", required=True)
    ap.add_argument("--ddl-dir", required=True, help="全量 DDL 目录（opt: ddl_full/；new-pipe: ddl/）")
    ap.add_argument("--decisions", default="", help="decisions 文件（opt 增量 or new-pipe 全量）")
    ap.add_argument("--archives-root", default="archives", help="档案根目录")
    args = ap.parse_args(argv)

    ts = json.loads(Path(args.ts).read_text(encoding="utf-8"))
    f_table = ts.get("meta", {}).get("target", {}).get("f_table", {})
    schema, asset = f_table.get("schema", ""), f_table.get("table", "")
    if not schema or not asset:
        print("ARCHIVE_ERROR: ts 缺 meta.target.f_table.schema/table", file=sys.stderr)
        return 2
    try:
        dest = write_archive(Path(args.archives_root), schema, asset,
                             Path(args.ts), Path(args.etl_dir), Path(args.ddl_dir),
                             Path(args.decisions) if args.decisions else None)
    except Exception as e:
        print(f"ARCHIVE_ERROR: {e}", file=sys.stderr)
        return 2
    print(f"archive: {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
