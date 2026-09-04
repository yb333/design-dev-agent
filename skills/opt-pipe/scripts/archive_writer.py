"""archive_writer —— 资产档案两动作（2026-08-31 目录定调：档案=ddlc_design_dev/archive/ 单目录当前态）。

档案 = 资产当前态唯一真身（ts.json/ts.md + etl/ + ddl/ + dq/ + decisions.yaml），
入 git（gitignore 白名单），演进史 = git 提交历史（每次交付覆盖 + 一次 commit）。

两动作（子命令；调用方都是 opt-pipe 步骤——new-pipe 零改动，收档是首优时才付的成本）：
  adopt   首优收档：new-pipe 平铺产出原地收纳进 archive/（一次性；此后交付即有档）
  advance 交付收口：优化现场（opt/）推进档案（闸口②'确认后调；确认前档案零改动=天然回归点）
"""
import argparse
import shutil
import sys
from pathlib import Path
from typing import Optional


def adopt(ddlc: Path) -> Path:
    """首优收档：ddlc_design_dev 平铺的 new-pipe 产出 → archive/。

    mv ts.json/ts.md/etl//dq/（dq 可缺）→ archive/；cp _internal/design_decisions.yaml
    → archive/decisions.yaml。ddl/ 不入档（DDL 是 ts 的可再生投影——档案=本源集合，
    2026-09-04 裁决）；export//ut_report.md/_internal/ 留原位（new-pipe 交付现场）。
    """
    archive = ddlc / "archive"
    if archive.exists():
        raise ValueError(f"档案已存在（无需收档）: {archive}")
    if not (ddlc / "ts.json").exists():
        raise ValueError(f"{ddlc} 无 new-pipe 产出（ts.json 缺）——不能收档")
    archive.mkdir(parents=True)
    for name in ("ts.json", "ts.md", "etl", "dq"):
        src = ddlc / name
        if src.exists():
            shutil.move(str(src), str(archive / name))
    decisions = ddlc / "_internal" / "design_decisions.yaml"
    if not decisions.exists():
        raise ValueError(f"收档缺设计决策: {decisions}")
    shutil.copy2(decisions, archive / "decisions.yaml")
    return archive


def advance(opt: Path, archive: Path) -> Path:
    """交付收口：优化现场（opt/）推进档案当前态。

    ts_v2.json→ts.json、ts.md→ts.md、etl/*.sql→etl/（{rule_code}.sql 同名覆盖=该规则当前版）、
    _internal/design_decisions_opt.yaml→decisions.yaml。（DDL 不入档案——ts 的可再生投影。）
    opt/ 现场保留（最近一次优化的交付物：ALTER 单/patch 副本，人取用），下次优化开工重建。
    """
    if not (opt / "ts_v2.json").exists():
        raise ValueError(f"{opt} 无优化产出（ts_v2.json 缺）——不能推进")
    if not archive.is_dir():
        raise ValueError(f"档案不存在: {archive}（先收档或入料建档）")
    shutil.copy2(opt / "ts_v2.json", archive / "ts.json")
    if (opt / "ts.md").exists():
        shutil.copy2(opt / "ts.md", archive / "ts.md")
    if (opt / "etl").is_dir():
        (archive / "etl").mkdir(exist_ok=True)
        for f in (opt / "etl").glob("*.sql"):
            shutil.copy2(f, archive / "etl" / f.name)
    decisions = opt / "_internal" / "design_decisions_opt.yaml"
    if not decisions.exists():
        raise ValueError(f"推进缺设计决策: {decisions}")
    shutil.copy2(decisions, archive / "decisions.yaml")
    return archive


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="资产档案两动作：adopt 首优收档 / advance 交付收口")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_adopt = sub.add_parser("adopt", help="new-pipe 平铺产出收档进 archive/")
    p_adopt.add_argument("--ddlc", required=True, help="ddlc_design_dev 目录（平铺产出所在）")
    p_adv = sub.add_parser("advance", help="优化现场推进档案当前态（闸口②'确认后）")
    p_adv.add_argument("--opt", required=True, help="opt/ 优化现场目录")
    p_adv.add_argument("--archive", required=True, help="archive/ 档案目录")
    args = ap.parse_args(argv)

    try:
        dest = adopt(Path(args.ddlc)) if args.cmd == "adopt" else \
            advance(Path(args.opt), Path(args.archive))
    except ValueError as e:
        print(f"ARCHIVE_ERROR: {e}", file=sys.stderr)
        return 2
    print(f"archive: {dest}")
    print("档案已更新——git 提交由人按自己的节奏做（演进史 = git 提交历史，流程不内嵌 git 操作）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
