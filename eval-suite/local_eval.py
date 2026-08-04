#!/usr/bin/env python3
"""
本地评测脚本：一键跑通 preprocess → designer → assemble_ts → coder → assemble_ddl → check_sql 全流程。

不连数据库（UT 执行留内网）。目的是在开发环境验证：
1. 脚本链路（preprocess/precheck/assemble_ts/assemble_ddl/check_sql）跑通
2. AI 产出质量（designer 产 design_decisions、coder 产 SELECT）
3. 发现格式/结构问题

用法:
  python eval-suite/local_eval.py --asset dwl_con_pu_any_f
  python eval-suite/local_eval.py --asset dwl_con_pu_any_f --mapping docs/templates/mapping模板.xlsx --rs docs/templates/RS模板.md
  python eval-suite/local_eval.py --asset dwl_con_pu_any_f --skip-ai  # 只跑脚本不调AI

输出:
  - 产出文件到 10_project_deliver/{asset}/ddlc_design_dev/
  - 评测报告到 stdout（问题清单格式，适合拍照）
"""

import sys
import json
import argparse
import subprocess
from pathlib import Path
from datetime import datetime

# 项目根
ROOT = Path(__file__).resolve().parent.parent
# 全局安装的 skill 路径
DESIGN_REFS = Path.home() / ".config" / "opencode" / "skills" / "dws-design" / "references"
CODING_REFS = Path.home() / ".config" / "opencode" / "skills" / "dws-coding" / "references"


class EvalReport:
    """评测报告收集器"""
    def __init__(self, asset):
        self.asset = asset
        self.steps = []  # [{step, status, detail}]
        self.issues = []  # [{type, detail}]

    def pass_step(self, step, detail=""):
        self.steps.append({"step": step, "status": "PASS", "detail": detail})

    def fail_step(self, step, detail):
        self.steps.append({"step": step, "status": "FAIL", "detail": detail})
        self.issues.append({"type": "STEP_FAIL", "detail": f"[{step}] {detail}"})

    def warn(self, step, detail):
        self.steps.append({"step": step, "status": "WARN", "detail": detail})

    def add_issue(self, issue_type, detail):
        self.issues.append({"type": issue_type, "detail": detail})

    def print_report(self):
        print()
        print("=" * 55)
        print(f"  评测报告: {self.asset}")
        print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 55)
        print()

        # 步骤结果
        for s in self.steps:
            symbol = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️"}[s["status"]]
            detail = f" — {s['detail']}" if s["detail"] else ""
            print(f"  {symbol} {s['step']}{detail}")

        passed = sum(1 for s in self.steps if s["status"] == "PASS")
        failed = sum(1 for s in self.steps if s["status"] == "FAIL")
        warned = sum(1 for s in self.steps if s["status"] == "WARN")
        print()
        print(f"  步骤: ✅{passed}通过  ❌{failed}失败  ⚠️{warned}警告")

        # 问题清单
        if self.issues:
            print()
            print("  ⚠️ 问题清单:")
            for i, iss in enumerate(self.issues, 1):
                print(f"    {i}. [{iss['type']}] {iss['detail']}")
        else:
            print()
            print("  ✅ 无问题")

        print()
        print("=" * 55)
        return len(self.issues) == 0


def run_cmd(cmd: list[str], timeout: int = 600) -> tuple[int, str, str]:
    """运行命令，返回 (退出码, stdout, stderr)"""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(ROOT))
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"超时({timeout}s)"
    except Exception as e:
        return -1, "", str(e)


def run_python(script: str, args: list[str], timeout: int = 60) -> tuple[int, str]:
    """运行 Python 脚本"""
    code, out, err = run_cmd(["python3", script] + args, timeout)
    combined = out + ("\n" + err if err.strip() else "")
    return code, combined


def step_preprocess(report, deliver, mapping, rs, skip_rs):
    """步骤1: 预处理"""
    internal = deliver / "_internal"
    internal.mkdir(parents=True, exist_ok=True)
    rs_input = internal / "rs_input.json"

    args = ["--mapping", str(mapping), "--output", str(rs_input)]
    if not skip_rs and rs:
        args.extend(["--rs", str(rs)])

    code, out = run_python(str(DESIGN_REFS / "preprocess.py"), args)
    if code == 0:
        data = json.loads(rs_input.read_text(encoding="utf-8"))
        n_fields = len(data.get("field_mappings", []))
        n_sources = len(data.get("source_tables", []))
        report.pass_step("预处理(preprocess)", f"{n_fields}字段, {n_sources}源表")
        return True
    else:
        report.fail_step("预处理(preprocess)", out[:200])
        return False


def step_precheck(report, deliver):
    """步骤2: 预检查"""
    rs_input = deliver / "_internal" / "rs_input.json"
    code, out = run_python(str(DESIGN_REFS / "precheck.py"), ["--input", str(rs_input)])
    if code == 0:
        report.pass_step("预检查(precheck)", "全部通过")
    elif code == 1:
        report.warn("预检查(precheck)", "有警告但不阻断")
    else:
        report.fail_step("预检查(precheck)", out[:200])
    return True  # 警告不阻断


def step_designer(report, deliver, skip_ai):
    """步骤3: designer 产 design_decisions + assemble_ts 组装"""
    internal = deliver / "_internal"
    rs_input = internal / "rs_input.json"

    if skip_ai:
        report.warn("设计(designer)", "跳过AI（--skip-ai）")
        return (internal / "design_decisions.yaml").exists()

    abs_rs = str((ROOT / rs_input).resolve()) if not rs_input.is_absolute() else str(rs_input)
    abs_internal = str((ROOT / internal).resolve())
    abs_deliver = str((ROOT / deliver).resolve())

    prompt = f"读取 {abs_rs}，产出 design_decisions.yaml 到 {abs_internal}/。然后调 assemble_ts.py --rs {abs_rs} --decisions {abs_internal}/design_decisions.yaml --outdir {abs_deliver} 组装 ts.json + ts.md。"

    code, out, err = run_cmd(
        ["opencode", "run", "--agent", "dws-designer", "--format", "json", prompt],
        timeout=1800  # 大案例（264字段）可能需要30分钟
    )

    ts_json = deliver / "ts.json"
    decisions = internal / "design_decisions.yaml"

    if ts_json.exists() and decisions.exists():
        ts = json.loads(ts_json.read_text(encoding="utf-8"))
        rules = ts.get("rules", {})
        n_rules = len(rules)
        fc = ts.get("meta", {}).get("field_count", {})
        report.pass_step(
            "设计(designer+assemble)",
            f"{n_rules}规则, {fc.get('total',0)}字段, business_key={'有' if ts.get('design',{}).get('business_key') else '无'}"
        )
        return True
    else:
        report.fail_step("设计(designer)", f"产出缺失: ts.json={ts_json.exists()}, decisions={decisions.exists()}")
        return False


def step_coder(report, deliver, rule_code, skip_ai):
    """步骤4: coder 产 SELECT"""
    select_dir = deliver / "etl"
    select_dir.mkdir(exist_ok=True)

    if skip_ai:
        report.warn("编码(coder)", "跳过AI（--skip-ai）")
        return False

    abs_ts = str((ROOT / deliver / "ts.json").resolve())
    abs_select = str((ROOT / select_dir).resolve())

    prompt = f"ts.json 路径: {abs_ts}，编码规则: {rule_code}，产出 SELECT 到 {abs_select}/{rule_code}.sql"

    code, out, err = run_cmd(
        ["opencode", "run", "--agent", "dws-coder", "--format", "json", prompt],
        timeout=1800  # 大案例多规则可能需要30分钟
    )

    select_file = select_dir / f"{rule_code}.sql"
    if select_file.exists():
        content = select_file.read_text(encoding="utf-8")
        n_lines = len(content.strip().splitlines())
        report.pass_step(f"编码(coder {rule_code})", f"{n_lines}行 SELECT")
        return True
    else:
        report.fail_step(f"编码(coder {rule_code})", "SELECT 文件未生成")
        return False


def step_assemble_ddl(report, deliver):
    """步骤5: 生成 DDL"""
    ddl_dir = deliver / "ddl"
    code, out = run_python(
        str(CODING_REFS / "assemble_ddl.py"),
        ["--ts", str(deliver / "ts.json"), "--outdir", str(deliver)]
    )
    ddl_dir_real = deliver / "ddl"
    rollback_dir = deliver / "ddl_rollback"
    ddl_files = list(ddl_dir_real.glob("*.sql")) if ddl_dir_real.exists() else []
    rollback_files = list(rollback_dir.glob("*.sql")) if rollback_dir.exists() else []

    if code == 0 and ddl_files:
        report.pass_step("DDL生成(assemble_ddl)", f"{len(ddl_files)}个DDL + {len(rollback_files)}个回退")

        # DDL 内容质量检查
        # 1. I视图不能用 SELECT *
        for vf in ddl_dir_real.glob("create_view_*.sql"):
            content = vf.read_text(encoding="utf-8")
            if "SELECT *" in content and "SELECT * FROM" in content:
                report.add_issue("DDL质量", f"{vf.name} 使用了 SELECT *（应列出全部字段）")

        # 2. 每个DDL文件应有对应的回退脚本
        for df in ddl_files:
            rollback_name = f"rollback_{df.name}"
            if not (rollback_dir / rollback_name).exists():
                report.add_issue("DDL质量", f"{df.name} 缺少回退脚本 {rollback_name}")

        return True
    else:
        report.fail_step("DDL生成(assemble_ddl)", out[:200])
        return False


def step_assemble_dq(report, deliver):
    """步骤5.5: 生成 DQ 检查 SQL"""
    dq_dir = deliver / "dq"
    dq_dir.mkdir(parents=True, exist_ok=True)
    code, out = run_python(
        str(CODING_REFS / "assemble_dq.py"),
        ["--ts", str(deliver / "ts.json"), "--outdir", str(dq_dir)]
    )
    dq_files = list(dq_dir.glob("*.sql")) if dq_dir.exists() else []

    if code == 0 and dq_files:
        report.pass_step("DQ生成(assemble_dq)", f"{len(dq_files)}个DQ检查SQL")
        return True
    else:
        report.fail_step("DQ生成(assemble_dq)", out[:200])
        return False


def step_check_sql(report, deliver, rule_code):
    """步骤6: 静态对比"""
    select_file = deliver / "etl" / f"{rule_code}.sql"
    if not select_file.exists():
        report.fail_step("静态对比(check_sql)", "SELECT文件不存在")
        return False

    code, out = run_python(
        str(CODING_REFS / "check_sql.py"),
        ["--select", str(select_file), "--ts", str(deliver / "ts.json"), "--rule", rule_code]
    )
    if code == 0:
        report.pass_step("静态对比(check_sql)", "字段覆盖完整, 表引用正确")
        return True
    else:
        report.fail_step("静态对比(check_sql)", out[:200])
        return False


def step_ut(report, deliver):
    """步骤6.5: UT 预检 + 执行（需数据库；无库则跳过不报错）。

    与 new-pipe 对齐：先 check_db.py 判断有无数据源，有才跑 ut_precheck/ut_execute。
    无库时静默跳过（仅警告），不阻断流程——UT 是可选的环境依赖步骤。
    """
    # 先判断有没有数据源
    code, out = run_python(str(CODING_REFS / "check_db.py"), [], timeout=30)
    if code != 0 or "DB_OK" not in out:
        report.warn("执行验证(UT)", f"无数据源，跳过UT（{out.strip().splitlines()[-1] if out.strip() else 'check_db失败'}）")
        return True

    # 6a: UT 预检（秒级，不写数据）
    code, out = run_python(
        str(CODING_REFS / "ut_precheck.py"),
        ["--ts", str(deliver / "ts.json"),
         "--select-dir", str(deliver / "etl"),
         "--ddl-dir", str(deliver / "ddl"),
         "--result", str(deliver / "ut_precheck_result.json")],
        timeout=300,
    )
    if code != 0:
        report.fail_step("UT预检(ut_precheck)", out[:200])
        return False
    report.pass_step("UT预检(ut_precheck)", "回退+DDL+SELECT 预检通过")

    # 6b: UT 执行（分钟级，写数据）
    code, out = run_python(
        str(CODING_REFS / "ut_execute.py"),
        ["--ts", str(deliver / "ts.json"),
         "--select-dir", str(deliver / "etl"),
         "--ddl-dir", str(deliver / "ddl"),
         "--report", str(deliver / "ut_report.md")],
        timeout=1800,
    )
    if code != 0:
        report.fail_step("UT执行(ut_execute)", out[:200])
        return False
    report.pass_step("UT执行(ut_execute)", "INSERT + UT 检查通过")
    return True


def step_assemble_export(report, deliver):
    """步骤7: 生成平台制品包（与 new-pipe 对齐，UT 通过后必跑）。

    assemble_export.py 不依赖数据库，只做文件生成（Excel + manifest）。
    规则编码留空（codes_filled=false），由内网 skill 回填。
    """
    export_dir = deliver / "export"
    code, out = run_python(
        str(CODING_REFS / "assemble_export.py"),
        ["--ts", str(deliver / "ts.json"),
         "--etl-dir", str(deliver / "etl"),
         "--ddl-dir", str(deliver / "ddl"),
         "--outdir", str(deliver)],
        timeout=120,
    )
    shujia = list(export_dir.glob("shujia_*.xlsx")) if export_dir.exists() else []
    lts = list(export_dir.glob("lts_*.xlsx")) if export_dir.exists() else []
    if code == 0 and shujia and lts:
        report.pass_step("制品包(export)", f"{len(shujia)}术加 + {len(lts)}LTS")
        # manifest codes_filled 应为 false（规则编码留空）
        for mf in export_dir.glob("export_manifest_*.json"):
            try:
                m = json.loads(mf.read_text(encoding="utf-8"))
                if m.get("codes_filled") is not False:
                    report.add_issue("制品包", f"{mf.name}: codes_filled 应为 false（实际 {m.get('codes_filled')}）")
            except Exception:
                pass
        return True
    else:
        report.fail_step("制品包(export)", out[:200])
        return False


def step_validate_ts(report, deliver):
    """步骤7: ts.json 结构校验"""
    ts = json.loads((deliver / "ts.json").read_text(encoding="utf-8"))
    issues = []

    # 顶层结构
    for key in ["version", "meta", "design", "rules", "data_flow"]:
        if key not in ts:
            issues.append(f"缺顶层键: {key}")

    # business_key
    if not ts.get("design", {}).get("business_key"):
        issues.append("design.business_key 为空")

    # source_tables 补全
    for code, rule in ts.get("rules", {}).items():
        for st in rule.get("source_tables", []):
            if not st.get("table"):
                issues.append(f"{code} source_tables 有空 table（alias={st.get('alias')}）")

    # audit_fields
    audit = ts.get("design", {}).get("audit_fields", {})
    if len(audit) < 4:
        issues.append(f"audit_fields 不足4个: {list(audit.keys())}")

    # source_column 不能是中文（preprocess 映射 bug 检查）
    rs_input_path = deliver / "_internal" / "rs_input.json"
    if rs_input_path.exists():
        rs = json.loads(rs_input_path.read_text(encoding="utf-8"))
        import re
        for fm in rs.get("field_mappings", []):
            sc = fm.get("source_column", "")
            if sc and re.search(r'[\u4e00-\u9fff]', sc):
                issues.append(f"source_column 含中文: '{sc}'（应为英文字段名，检查 preprocess 列映射）")
                break  # 报一次就够

    if issues:
        for iss in issues:
            report.add_issue("TS结构", iss)
        report.fail_step("TS结构校验", f"{len(issues)}个问题")
    else:
        report.pass_step("TS结构校验", "结构完整")
    return len(issues) == 0


def main():
    parser = argparse.ArgumentParser(description="本地评测：一键跑通设计+编码全流程")
    parser.add_argument("--asset", required=True, help="资产名（如 dwl_con_pu_any_f）")
    parser.add_argument("--mapping", default="", help="mapping.xlsx 路径")
    parser.add_argument("--rs", default="", help="RS.md 路径")
    parser.add_argument("--rule", default="", help="要编码的规则号（默认第一个）")
    parser.add_argument("--all-rules", action="store_true", help="编码所有规则（默认只编第一个；多规则案例用于验证流水衔接）")
    parser.add_argument("--skip-ai", action="store_true", help="跳过 AI（只跑脚本链路）")
    parser.add_argument("--clean", action="store_true", help="清理旧产出后重跑")
    args = parser.parse_args()

    asset = args.asset
    deliver_base = ROOT / "10_project_deliver" / asset / "ddlc_design_dev"

    # 默认输入
    mapping = args.mapping or str(ROOT / "docs" / "templates" / "mapping模板.xlsx")
    rs = args.rs or str(ROOT / "docs" / "templates" / "RS模板.md")

    # 清理
    if args.clean and deliver_base.exists():
        import shutil
        shutil.rmtree(deliver_base)

    report = EvalReport(asset)

    print(f"[eval] 资产: {asset}")
    print(f"[eval] 产出目录: {deliver_base}")
    print(f"[eval] 模式: {'跳过AI' if args.skip_ai else '全流程（含AI）'}")
    print()

    # 步骤1: 预处理
    ok = step_preprocess(report, deliver_base, mapping, rs, not args.rs)
    if not ok:
        report.print_report()
        sys.exit(1)

    # 步骤2: 预检查
    step_precheck(report, deliver_base)

    # 步骤3: designer
    ok = step_designer(report, deliver_base, args.skip_ai)
    if not ok and not args.skip_ai:
        report.print_report()
        sys.exit(1)

    # 步骤3.5: TS 结构校验
    if (deliver_base / "ts.json").exists():
        step_validate_ts(report, deliver_base)

    # 步骤4: coder
    if not args.skip_ai and (deliver_base / "ts.json").exists():
        ts = json.loads((deliver_base / "ts.json").read_text(encoding="utf-8"))
        all_rules = list(ts.get("rules", {}).keys())

        # 确定要编码的规则集合
        if args.rule:
            # --rule 显式指定：只编这一个
            rules_to_encode = [args.rule]
        elif args.all_rules:
            # --all-rules：编全部
            rules_to_encode = all_rules if all_rules else ["R0001"]
        else:
            # 默认：只编第一个
            rules_to_encode = [all_rules[0]] if all_rules else ["R0001"]

        encoded_rules = []
        for rc in rules_to_encode:
            ok = step_coder(report, deliver_base, rc, args.skip_ai)
            if ok:
                encoded_rules.append(rc)

        # 未编码规则清单（多规则案例提醒）
        if len(all_rules) > 1:
            not_encoded = [r for r in all_rules if r not in encoded_rules]
            if not_encoded:
                report.add_issue("编码覆盖", f"未编码规则: {', '.join(not_encoded)}（ts.json 共 {len(all_rules)} 规则）")

        # 步骤5: DDL
        step_assemble_ddl(report, deliver_base)

        # 步骤5.5: DQ 检查 SQL
        step_assemble_dq(report, deliver_base)

        # 步骤6: 静态对比（对每个已编码规则）
        for rc in encoded_rules:
            step_check_sql(report, deliver_base, rc)

        # 步骤6.5: UT 执行验证（需数据库；无库自动跳过，与 new-pipe 对齐）
        step_ut(report, deliver_base)

        # 步骤7: 平台制品包（UT 通过后必跑，不依赖数据库）
        step_assemble_export(report, deliver_base)

    # 输出报告
    all_ok = report.print_report()

    # 产出文件清单
    print("  产出文件:")
    if deliver_base.exists():
        for f in sorted(deliver_base.rglob("*")):
            if f.is_file() and ".DS_Store" not in f.name:
                rel = f.relative_to(deliver_base)
                print(f"    {rel}")
    print()
    print("=" * 55)

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
