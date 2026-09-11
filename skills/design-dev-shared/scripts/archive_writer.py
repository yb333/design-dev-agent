"""archive_writer —— 资产档案两动作（目录定调 2026-09；2026-09-07 文件系统自解释强化）。

档案 = 资产当前态唯一真身（ts.json/ts.md + etl/ + dq/ + export/ + decisions.yaml），
入 git（gitignore 白名单——git 是独立的回溯备份通道，文件系统自解释为主：
MANIFEST 一眼看懂版本史，opt_{YYYYMM}/ 目录数 = 优化次数）。

两动作（子命令；住 shared——new-pipe 收尾调 adopt、opt-pipe 收口调 advance，双消费者；
目录模型 2026-09-07 终态：build=增量现场[新建全部/优化变更，开工清场]、
archive=资产档案可信基线、archive_tmp=优化进度态全量档案）：
  adopt   交付建档（new-pipe 闸口②确认后）：从增量现场 build/ **复制**本源件
          （ts/etl/dq/ddl/export + decisions）生成 {build父}/archive/ + MANIFEST 首建
          （v1 建造）——build 保留完整交付现场（全量部署内容：DDL/SQL/制品包/报告，
          人拿一个目录即可部署当前版本）。放弃分支不建档（build 留草稿，重跑覆盖）。
  advance 交付收口（opt 闸口②'确认后）：**三步全量替换**——
          mv {arc} {arc}.replaced → mv {arc_tmp} {arc} → rm -rf {arc}.replaced
          （崩在任意一步均可恢复；替换前清掉 tmp 里混入的过程产物 _internal）+ MANIFEST 追加。
          优化的中间产物（ts/etl/DDL/制品）在过程中已落位 archive_tmp（进度态随时可用），
          确认即整体上位——档案要么旧版要么新版，无中间态。
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
    # 复制不移动：build 保留完整交付现场（全量部署内容），档案独立成份（2026-09-07 定调）
    for name in ("ts.json", "ts.md", "etl", "dq", "ddl", "export"):
        src = build / name
        if src.exists():
            if src.is_dir():
                shutil.copytree(src, archive / name, dirs_exist_ok=True)
            else:
                shutil.copy2(src, archive / name)
    decisions = build / "_internal" / "design_decisions.yaml"
    if not decisions.exists():
        raise ValueError(f"建档缺设计决策: {decisions}")
    shutil.copy2(decisions, archive / "decisions.yaml")
    ts = json.loads((archive / "ts.json").read_text(encoding="utf-8"))
    f = ts.get("meta", {}).get("target", {}).get("f_table", {})
    (archive / "MANIFEST.md").write_text(
        _manifest_head(f"{f.get('schema','')}.{f.get('table','')}")
        + "| 版本 | 内容 |\n|------|------|\n| v1 | 建造（new-pipe，见 build/）|\n",
        encoding="utf-8")
    return archive


def advance(archive: Path, arc_tmp: Path, build: Path) -> Path:
    """交付收口：三步全量替换（archive_tmp 整体上位）+ MANIFEST 追加。

    替换前清掉 tmp 里混入的过程产物（_internal——诊断/计划落盘应走 build，
    此为双保险）；MANIFEST 摘自 build/_internal/change_request.json。
    """
    if not (arc_tmp / "ts.json").exists():
        raise ValueError(f"临时档案缺产物（ts.json）: {arc_tmp}——不能替换")
    if not archive.is_dir():
        raise ValueError(f"资产档案不存在: {archive}（先建档）")
    # MANIFEST 追加在替换前（对 tmp 里的 MANIFEST 写——随替换进档案）
    mf = arc_tmp / "MANIFEST.md"
    if not mf.exists():
        raise ValueError(f"临时档案缺 MANIFEST: {mf}")
    cr = {}
    try:
        import json
        cr = json.loads((build / "_internal" / "change_request.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    ver = str(cr.get("version", "")) or "本次"
    fields = ", ".join(f.get("field", "?") for f in cr.get("fields", [])[:5]) or "-"
    row = cr.get("change_log_summary") or {}
    line = f"| {ver} | 优化：+{len(cr.get('fields', []))} 字段（{fields}）"
    if row.get("desc"):
        line += f"——{row['desc'][:40]}"
    line += " |\n"
    with mf.open("a", encoding="utf-8") as fh:
        fh.write(line)
    # 清过程产物（诊断/计划等应落 build——双保险防污染档案）
    shutil.rmtree(arc_tmp / "_internal", ignore_errors=True)
    # 三步全量替换（每步失败均可恢复）
    replaced = archive.parent / (archive.name + ".replaced")
    if replaced.exists():
        shutil.rmtree(replaced)
    shutil.move(str(archive), str(replaced))
    try:
        shutil.move(str(arc_tmp), str(archive))
    except Exception:
        shutil.move(str(replaced), str(archive))  # 回滚旧档
        raise
    shutil.rmtree(replaced, ignore_errors=True)
    return archive


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="资产档案两动作：adopt 首优收档 / advance 交付收口")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_adopt = sub.add_parser("adopt", help="交付建档：从 build/ 工作区提取本源件生成 archive/（闸口②确认后）")
    p_adopt.add_argument("--build", required=True, help="建造工作区目录（new-pipe 的 {deliver}=ddlc/build）")
    p_adv = sub.add_parser("advance", help="全量替换：archive_tmp 整体上位为资产档案（闸口②'确认后）")
    p_adv.add_argument("--archive", required=True, help="archive/ 资产档案目录")
    p_adv.add_argument("--tmp", required=True, help="archive_tmp/ 临时档案目录")
    p_adv.add_argument("--build", required=True, help="build/ 增量现场（MANIFEST 数据源）")
    args = ap.parse_args(argv)

    try:
        dest = adopt(Path(args.build)) if args.cmd == "adopt" else \
            advance(Path(args.archive), Path(args.tmp), Path(args.build))
    except ValueError as e:
        print(f"ARCHIVE_ERROR: {e}", file=sys.stderr)
        return 2
    print(f"archive: {dest}")
    print("档案已更新——git 提交由人按自己的节奏做（git 为独立回溯通道，流程不内嵌 git 操作）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
