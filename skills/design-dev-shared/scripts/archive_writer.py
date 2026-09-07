"""archive_writer —— 资产档案两动作（目录定调 2026-09；2026-09-07 文件系统自解释强化）。

档案 = 资产当前态唯一真身（ts.json/ts.md + etl/ + dq/ + export/ + decisions.yaml），
入 git（gitignore 白名单——git 是独立的回溯备份通道，文件系统自解释为主：
MANIFEST 一眼看懂版本史，opt_{YYYYMM}/ 目录数 = 优化次数）。

两动作（子命令；住 shared——new-pipe 收尾调 adopt、opt-pipe 收口调 advance，双消费者）：
  adopt   交付建档（new-pipe 闸口②确认后）：从建造工作区 build/ 提取本源件
          （ts/etl/dq/export + decisions）生成 {build父}/archive/ + MANIFEST 首建；
          build/ 剩余（ddl/ut_report/_internal）就地定格为建造现场。
          new-pipe 流程中一切产出在 build/ 下（{deliver}={ddlc}/build——位置不漂移，
          确认时只发生一次提取定稿）；放弃分支不建档。
  advance 交付收口（opt 闸口②'确认后）：优化现场（opt_{version}/）推进档案当前态
          （ts/etl/制品副本/decisions）+ MANIFEST 追加；确认前档案零改动=天然回归点。
"""
import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Optional


def _manifest_head(asset: str) -> str:
    return f"# 资产演进索引 · {asset}\n\n（当前态 = archive/ 本体；此文件为版本史一眼索引，完整历史在 git）\n\n"


def _read_cr(opt_dir: Path) -> dict:
    p = opt_dir / "_internal" / "change_request.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def adopt(build: Path) -> Path:
    """交付建档：build/ 工作区 → 提取本源件生成 archive/；剩余定格建造现场；首建 MANIFEST。"""
    ddlc = build.parent
    archive = ddlc / "archive"
    if archive.exists():
        raise ValueError(f"档案已存在（无需建档）: {archive}——如为推倒重来（人发起的重建），"
                         f"档案处置由人定，本脚本不自动覆盖")
    if not (build / "ts.json").exists():
        raise ValueError(f"{build} 无产出（ts.json 缺）——不能建档")
    archive.mkdir(parents=True)
    for name in ("ts.json", "ts.md", "etl", "dq", "export"):
        src = build / name
        if src.exists():
            shutil.move(str(src), str(archive / name))
    decisions = build / "_internal" / "design_decisions.yaml"
    if not decisions.exists():
        raise ValueError(f"收档缺设计决策: {decisions}")
    shutil.copy2(decisions, archive / "decisions.yaml")
    # 本源件已 mv 走，build/ 剩余（ddl/ut_report/_internal）就地定格为建造现场
    ts = json.loads((archive / "ts.json").read_text(encoding="utf-8"))
    f = ts.get("meta", {}).get("target", {}).get("f_table", {})
    (archive / "MANIFEST.md").write_text(
        _manifest_head(f"{f.get('schema','')}.{f.get('table','')}")
        + "| 版本 | 内容 |\n|------|------|\n| v1 | 建造（new-pipe，见 build/）|\n",
        encoding="utf-8")
    return archive


def advance(opt: Path, archive: Path) -> Path:
    """交付收口：opt_{version}/ 推进档案当前态 + MANIFEST 追加。"""
    if not (opt / "ts.json").exists():
        raise ValueError(f"{opt} 无优化产出（ts.json 缺）——不能推进")
    if not archive.is_dir():
        raise ValueError(f"档案不存在: {archive}（先收档或入料建档）")
    shutil.copy2(opt / "ts.json", archive / "ts.json")
    if (opt / "ts.md").exists():
        shutil.copy2(opt / "ts.md", archive / "ts.md")
    if (opt / "etl").is_dir():
        (archive / "etl").mkdir(exist_ok=True)
        for f in (opt / "etl").glob("*.sql"):
            shutil.copy2(f, archive / "etl" / f.name)
    patched = opt / "export" / "patched"
    if patched.is_dir():
        (archive / "export").mkdir(exist_ok=True)
        for f in patched.iterdir():
            if f.is_file():
                shutil.copy2(f, archive / "export" / f.name)
    decisions = opt / "_internal" / "design_decisions_opt.yaml"
    if not decisions.exists():
        raise ValueError(f"推进缺设计决策: {decisions}")
    shutil.copy2(decisions, archive / "decisions.yaml")
    # MANIFEST 追加（确定性摘自 change_request：版本/字段数/变更记录一句话）
    cr = _read_cr(opt)
    ver = cr.get("version", opt.name.removeprefix("opt_"))
    fields = ", ".join(f.get("field", "?") for f in cr.get("fields", [])[:5]) or "-"
    row = cr.get("change_log_summary") or {}
    desc = row.get("desc", "")
    line = f"| {ver} | 优化：+{len(cr.get('fields', []))} 字段（{fields}）"
    if desc:
        line += f"——{desc[:40]}"
    line += " |\n"
    mf = archive / "MANIFEST.md"
    if not mf.exists():
        ts = json.loads((archive / "ts.json").read_text(encoding="utf-8"))
        f2 = ts.get("meta", {}).get("target", {}).get("f_table", {})
        mf.write_text(_manifest_head(f"{f2.get('schema','')}.{f2.get('table','')}")
                      + "| 版本 | 内容 |\n|------|------|\n", encoding="utf-8")
    with mf.open("a", encoding="utf-8") as fh:
        fh.write(line)
    return archive


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="资产档案两动作：adopt 首优收档 / advance 交付收口")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_adopt = sub.add_parser("adopt", help="交付建档：从 build/ 工作区提取本源件生成 archive/（闸口②确认后）")
    p_adopt.add_argument("--build", required=True, help="建造工作区目录（new-pipe 的 {deliver}=ddlc/build）")
    p_adv = sub.add_parser("advance", help="优化现场推进档案当前态（闸口②'确认后）")
    p_adv.add_argument("--opt", required=True, help="opt_{version}/ 优化现场目录")
    p_adv.add_argument("--archive", required=True, help="archive/ 档案目录")
    args = ap.parse_args(argv)

    try:
        dest = adopt(Path(args.build)) if args.cmd == "adopt" else \
            advance(Path(args.opt), Path(args.archive))
    except ValueError as e:
        print(f"ARCHIVE_ERROR: {e}", file=sys.stderr)
        return 2
    print(f"archive: {dest}")
    print("档案已更新——git 提交由人按自己的节奏做（git 为独立回溯通道，流程不内嵌 git 操作）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
