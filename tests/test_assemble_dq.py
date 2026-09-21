"""assemble_dq（DQ 校验渲染器）测试——2026-09-14 DQ 拆分 + 2026-09-15 两跳并一跳精简。

精简后形态：producer 直接产 dq.json（最薄 rules）+ SQL，assemble_dq 只做
校验（N_DQ1/4/5/9/10）+补全（idx/sql_file/mode 缺省/meta）+渲染 ts.md 表格。
锚定声明/compare_sources/N_DQ6-8 已随精简退役。
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, "skills/new-pipe/scripts")

from assemble_dq import (  # noqa: E402
    validate_and_build, build_dq_task, patch_ts_md, render_dq_section, DqResult,
)

F_FIELDS = ["id", "prod_code", "del_flag", "crt_cycle_id", "last_upd_cycle_id", "dw_last_update_date"]


def _ts(with_view=True, with_tmp=False):
    """fields 条目对齐 build_tables 真实产出键（target_field——build_field 的产物形态）。"""
    rules = {
        "R0001": {"target_table": "dws.dwb_test_f", "target_role": "target",
                  "source_tables": [{"schema": "ods", "table": "ods_test_f", "alias": "s"}]},
    }
    if with_tmp:
        rules["R0000"] = {"target_table": "dws.dwb_test_f_tmp1", "target_role": "intermediate",
                          "source_tables": [{"schema": "ods", "table": "ods_test_f", "alias": "s"}]}
    tasks = {"f": {"task_name": "task_dwb_test_f", "cron": "0 0 1 * * ?"},
             "view": {"task_name": "task_dwb_test_i"}}
    if not with_view:
        tasks.pop("view")
    return {
        "meta": {"target": {"f_table": {"schema": "dws", "table": "dwb_test_f", "cn": "测试"}}},
        "design": {"business_key": ["id"]},
        "tables": {"dwb_test_f": {"fields": [
            {"target_field": f, "field_type": "varchar(50)", "field_comment": f}
            for f in F_FIELDS]}},
        "rules": rules,
        "tasks": tasks,
    }


def _rs(dq_needs=None):
    return {
        "meta": {"target": {"f_table": {"schema": "dws", "table": "dwb_test_f"}}},
        "source_tables": [{"source_schema": "ods", "source_table": "ods_test_f", "source_alias": "s"}],
        "dq_requirements": dq_needs if dq_needs is not None else [
            {"scope": "字段级", "check_type": "空值检查", "rule_name": "产品编码非空",
             "rule_desc": "产品编码不能为空"},
        ],
    }


def _rule(**kw):
    base = {"rule_id": "DQ_001", "scope": "字段级", "check_type": "空值检查",
            "rule_name": "产品编码非空", "mode": "assertion",
            "violation_condition": "t.prod_code IS NULL",
            "rule_desc": "违规=prod_code 为空"}
    base.update(kw)
    return base


def _run(tmp_path, rules_in, ts=None, rs=None, cache_tables=None, sqls=None):
    """便捷：落 SQL 文件（默认按规则序写合法 SQL）→ 跑校验。返回 (rules_out, vr)。"""
    ts = ts or _ts()
    rs = rs or _rs()
    dq_dir = tmp_path / "dq"
    dq_dir.mkdir(exist_ok=True)
    from run_ut import dq_rule_filename
    for i, d in enumerate(rules_in, 1):
        rid = (d.get("rule_id") or "").strip()
        fname = dq_rule_filename(rid, d.get("rule_name") or d.get("check_type")) if rid \
            else f"dq_{i:02d}_{d.get('check_type')}.sql"
        content = (sqls or {}).get(i) or (
            f"/* DQ */\nSELECT t.id, t.prod_code FROM dws.dwb_test_f t WHERE {d.get('violation_condition', '1=1')}")
        (dq_dir / fname).write_text(content, encoding="utf-8")
    cache_path = ""
    if cache_tables is not None:
        cache_path = str(tmp_path / "schema_cache.json")
        Path(cache_path).write_text(json.dumps({"tables": cache_tables}), encoding="utf-8")
    return validate_and_build(rs, ts, rules_in, dq_dir, cache_path)


def _codes(vr):
    return [i["code"] for i in vr.items]


# ============================================================
# N_DQ1-N_DQ3：与 RS 对照
# ============================================================

class TestRsContract:
    def test_dq1_rs_has_needs_but_empty_hard(self, tmp_path):
        rules_out, vr = _run(tmp_path, [])
        assert "N_DQ1" in _codes(vr)
        assert any(i["code"] == "N_DQ1" and i["level"] == "hard" for i in vr.items)

    def test_dq2_partial_warns(self, tmp_path):
        rules_out, vr = _run(tmp_path, [_rule()], rs=_rs(dq_needs=[
            {"scope": "字段级", "check_type": "空值检查", "rule_name": "a", "rule_desc": "x"},
            {"scope": "表级", "check_type": "重复检查", "rule_name": "b", "rule_desc": "y"},
        ]))
        assert any(i["code"] == "N_DQ2" and i["level"] == "warn" for i in vr.items)

    def test_dq3_rs_none_but_added_warns(self, tmp_path):
        rules_out, vr = _run(tmp_path, [_rule()], rs=_rs(dq_needs=[]))
        assert any(i["code"] == "N_DQ3" and i["level"] == "warn" for i in vr.items)

    def test_full_match_passes(self, tmp_path):
        rules_out, vr = _run(tmp_path, [_rule()])
        assert not any(i["level"] == "hard" for i in vr.items)


# ============================================================
# N_DQ4/N_DQ5：violation_condition 与 mode
# ============================================================

class TestViolationCondition:
    def test_dq4_missing_hard(self, tmp_path):
        rules_out, vr = _run(tmp_path, [_rule(violation_condition="")])
        assert any(i["code"] == "N_DQ4" and i["level"] == "hard" for i in vr.items)

    def test_mode_bad_value_hard(self, tmp_path):
        rules_out, vr = _run(tmp_path, [_rule(mode="wild")])
        assert any(i["code"] == "N_DQ4" and "mode" in i["msg"] for i in vr.items)

    def test_mode_missing_defaults_assertion(self, tmp_path):
        """mode 缺省补全为 assertion（精简后：不是重契约，是补全）。"""
        rules_out, vr = _run(tmp_path, [_rule(mode="")])
        assert rules_out[0]["mode"] == "assertion"

    def test_dq5_unknown_field_hard_with_cache(self, tmp_path):
        rules_out, vr = _run(tmp_path, [_rule(violation_condition="t.order_amount IS NULL")],
                             cache_tables={"ods.ods_test_f": {"id": "bigint"}})
        hits = [i for i in vr.items if i["code"] == "N_DQ5" and i["level"] == "hard"]
        assert hits and "order_amount" in hits[0]["msg"]

    def test_dq5_three_part_hard_without_cache(self, tmp_path):
        rules_out, vr = _run(tmp_path, [_rule(
            violation_condition="dws.dwb_test_f.prod_code IS NULL")])
        hits = [i for i in vr.items if i["code"] == "N_DQ5" and "三段式" in i["msg"]]
        assert hits and hits[0]["level"] == "hard"

    def test_dq5_unknown_table_hard_without_cache(self, tmp_path):
        rules_out, vr = _run(tmp_path, [_rule(
            violation_condition="(select count(1) from ods.ods_nosuch_f) <> 100",
            mode="compare")])
        hits = [i for i in vr.items if i["code"] == "N_DQ5" and i["level"] == "hard"]
        assert hits and "ods_nosuch_f" in hits[0]["msg"]

    def test_dq5_cross_table_no_cache_downgrades_warn(self, tmp_path):
        rules_out, vr = _run(tmp_path, [_rule(
            violation_condition="(select count(1) from ods.ods_test_f s) - (select count(1) from dws.dwb_test_f t) <> 0 or s.src_cnt is null",
            mode="compare")])
        assert not any(i["code"] == "N_DQ5" and i["level"] == "hard" for i in vr.items)
        assert any(i["code"] == "N_DQ5" and i["level"] == "warn" for i in vr.items)

    def test_dq5_tmp_forbidden_hard(self, tmp_path):
        """独立重算禁碰中间表：vc 引用 tmp 表 → hard。"""
        rules_out, vr = _run(tmp_path, [_rule(
            violation_condition="exists (select 1 from dws.dwb_test_f_tmp1 m where m.id = t.id)",
            mode="compare")],
            ts=_ts(with_tmp=True))
        hits = [i for i in vr.items if i["code"] == "N_DQ5" and i["level"] == "hard"
                and "中间表" in i["msg"]]
        assert hits


# ============================================================
# N_DQ9/N_DQ10：SQL 文件与文本对账（含 2026-09-15 吸收的 check_sql --dq 检查项）
# ============================================================

class TestSqlChecks:
    def test_dq9_file_missing_hard(self, tmp_path):
        ts = _ts()
        rs = _rs()
        rules_out, vr = validate_and_build(rs, ts, [_rule()], tmp_path / "dq")
        assert any(i["code"] == "N_DQ9" and i["level"] == "hard" for i in vr.items)

    def test_dq10_hallucinated_column_hard(self, tmp_path):
        """SQL 里目标表别名引用了目标表没有的列（幻觉列）→ hard。"""
        rules_out, vr = _run(tmp_path, [_rule()], sqls={
            1: "SELECT t.id, t.ordr_amont FROM dws.dwb_test_f t WHERE t.prod_code IS NULL"})
        hits = [i for i in vr.items if i["code"] == "N_DQ10" and "幻觉列" in i["msg"]]
        assert hits and "ordr_amont" in hits[0]["msg"]

    def test_dq10_missing_business_key_output_hard(self, tmp_path):
        """输出列缺业务键 → hard（违规行要能回溯到业务对象；2026-09-15 自 check_sql 吸收）。"""
        rules_out, vr = _run(tmp_path, [_rule()], sqls={
            1: "SELECT t.prod_code FROM dws.dwb_test_f t WHERE t.prod_code IS NULL"})
        hits = [i for i in vr.items if i["code"] == "N_DQ10" and "业务键" in i["msg"]]
        assert hits and "id" in hits[0]["msg"]

    def test_dq10_bare_table_hard(self, tmp_path):
        """FROM 裸表名（无 schema 前缀）→ hard（2026-09-15 自 check_sql 吸收）。"""
        rules_out, vr = _run(tmp_path, [_rule()], sqls={
            1: "SELECT t.id, t.prod_code FROM dwb_test_f t WHERE t.prod_code IS NULL"})
        assert any(i["code"] == "N_DQ10" and "schema 前缀" in i["msg"] for i in vr.items)

    def test_dq10_select_star_hard(self, tmp_path):
        rules_out, vr = _run(tmp_path, [_rule()], sqls={
            1: "SELECT * FROM dws.dwb_test_f t WHERE t.prod_code IS NULL"})
        assert any(i["code"] == "N_DQ10" and "SELECT *" in i["msg"] for i in vr.items)

    def test_dq10_cross_table_asset_sources_ok(self, tmp_path):
        """跨表检查：资产内源表合法引用（源表来自 rs_input source_tables）。"""
        rules_out, vr = _run(tmp_path, [_rule(
            violation_condition="t.prod_code IS NULL AND s.id IS NULL", mode="compare")], sqls={
            1: "SELECT t.id, t.prod_code FROM dws.dwb_test_f t "
               "JOIN ods.ods_test_f s ON s.id = t.id WHERE t.prod_code IS NULL AND s.id IS NULL"})
        assert not any(i["level"] == "hard" for i in vr.items), vr.report_lines()

    def test_dq10_sql_tmp_forbidden_hard(self, tmp_path):
        rules_out, vr = _run(tmp_path, [_rule(
            mode="compare",
            violation_condition="t.id <> m.id（与 tmp 重算比对）")],
            ts=_ts(with_tmp=True), sqls={
            1: "SELECT t.id, t.prod_code FROM dws.dwb_test_f t "
               "JOIN dws.dwb_test_f_tmp1 m ON m.id = t.id WHERE t.id <> m.id"})
        assert any(i["code"] == "N_DQ10" and "中间表" in i["msg"] for i in vr.items)

    def test_dq10_sql_foreign_table_hard(self, tmp_path):
        rules_out, vr = _run(tmp_path, [_rule()], sqls={
            1: "SELECT t.id FROM dws.dwb_test_f t JOIN ods.ods_other_f o ON o.id = t.id "
               "WHERE t.prod_code IS NULL"})
        assert any(i["code"] == "N_DQ10" and "资产外" in i["msg"] for i in vr.items)

    def test_sql_three_part_hard(self, tmp_path):
        rules_out, vr = _run(tmp_path, [_rule()], sqls={
            1: "SELECT t.id FROM dws.dwb_test_f t WHERE dws.dwb_test_f.prod_code IS NULL"})
        assert any(i["code"] == "N_DQ10" and "三段式" in i["msg"] for i in vr.items)


# ============================================================
# declined：producer 必要性甄别（结构类 DQ 建议不做——人拍板）
# ============================================================

class TestDeclined:
    def test_declined_counts_toward_rs_coverage(self, tmp_path):
        """declined 计入 RS 覆盖：RS 2 条=1 做+1 declined → 不触发 N_DQ2 漏翻译 warn。"""
        rules_out, vr = _run(tmp_path, [_rule()], rs=_rs(dq_needs=[
            {"scope": "字段级", "check_type": "空值检查", "rule_name": "a", "rule_desc": "x"},
            {"scope": "表级", "check_type": "结构检查", "rule_name": "落地类型一致", "rule_desc": "y"},
        ]))
        # _run 不传 declined——直接调 validate_and_build 带 declined
        ts = _ts()
        rs2 = _rs(dq_needs=[
            {"scope": "字段级", "check_type": "空值检查", "rule_name": "a", "rule_desc": "x"},
            {"scope": "表级", "check_type": "结构检查", "rule_name": "落地类型一致", "rule_desc": "y"},
        ])
        import re as _re
        dq_dir = tmp_path / "dq2"
        dq_dir.mkdir()
        (dq_dir / "DQ_001_产品编码非空.sql").write_text(
            "SELECT t.id, t.prod_code FROM dws.dwb_test_f t WHERE t.prod_code IS NULL", encoding="utf-8")
        rules_out, vr = validate_and_build(
            rs2, ts, [_rule()], dq_dir,
            declined=[{"rs_rule_name": "落地类型一致", "reason": "结构类：precheck 已覆盖"}])
        assert not any(i["code"] == "N_DQ2" for i in vr.items)

    def test_render_declined_section(self):
        dq = {"rules": [], "declined": [
            {"rs_rule_name": "落地类型一致性检查", "reason": "类型对齐已被 precheck 覆盖"}]}
        text = render_dq_section(dq, [])
        assert "建议不做" in text and "落地类型一致性检查" in text and "precheck" in text


# ============================================================
# 补全产物 + ts.md 追加 + dq 任务
# ============================================================

class TestAssembly:
    def test_rules_out_shape_and_completion(self, tmp_path):
        """补全：idx/sql_file 派生/mode 缺省；ambiguities 透传（对比式不再要求锚定/来源声明）。"""
        rules_out, vr = _run(tmp_path, [
            _rule(rule_id="DQ_001", mode="", ambiguities=[{"note": "口径二义", "options": ["A", "B"]}]),
            _rule(rule_id="DQ_002", mode="compare", check_type="一致性检查",
                  rule_name="金额一致性", violation_condition="t.id <> s.id（独立重算）")])
        r1, r2 = rules_out
        assert r1["idx"] == 1 and r1["sql_file"] == "DQ_001_产品编码非空.sql"
        assert r1["rule_id"] == "DQ_001" and r1["mode"] == "assertion"
        assert r1["ambiguities"][0]["note"] == "口径二义" and r1["waived"] is False
        assert r2["idx"] == 2 and r2["sql_file"] == "DQ_002_金额一致性.sql"
        assert not any(i["level"] == "hard" for i in vr.items)

    def test_rule_id_missing_and_duplicate_hard(self, tmp_path):
        """rule_id=机器键（2026-09-18 文件名锚定）：缺失/重复都硬拦。"""
        _, vr = _run(tmp_path, [_rule(rule_id=None)])
        assert any(i["code"] == "N_DQ4" and "缺 rule_id" in i["msg"] for i in vr.items)
        _, vr2 = _run(tmp_path, [_rule(), _rule(rule_name="产品编码非空2")])
        assert any(i["code"] == "N_DQ4" and "重复" in i["msg"] for i in vr2.items)

    def test_sql_file_declaration_ignored_and_overwritten(self, tmp_path):
        """（2026-09-21 通道收口）sql_file 声明不再参与文件定位/前缀对账——文件按
        {rule_id}.sql 或标准名在位即可，装配回写标准名真值（旧"前缀对账硬拦"退役）。"""
        dq_dir = tmp_path / "dq"
        dq_dir.mkdir()
        (dq_dir / "DQ_001.sql").write_text(
            "SELECT t.id, t.prod_code FROM dws.dwb_test_f t WHERE t.prod_code IS NULL",
            encoding="utf-8")
        rules_out, vr = validate_and_build(_rs(), _ts(), [_rule(sql_file="别的名字.sql")], dq_dir)
        assert not any(i["code"] == "N_DQ9" for i in vr.items)
        assert rules_out[0]["sql_file"].startswith("DQ_001_")   # 声明被标准名覆盖

    def test_fused_coverage_and_render(self, tmp_path):
        """fused 申报（2026-09-18）：覆盖计数入 N_DQ2；rule_id/RS 名对账；ts.md 融合注记。"""
        rs2 = _rs(dq_needs=[
            {"scope": "字段级", "check_type": "空值检查", "rule_name": "产品编码非空",
             "rule_desc": "产品编码不能为空"},
            {"scope": "字段级", "check_type": "空值检查", "rule_name": "编码不可为空值",
             "rule_desc": "编码为空就是违规"}])
        rules_out, vr = _run(tmp_path, [_rule()], rs=rs2)
        assert any(i["code"] == "N_DQ2" for i in vr.items)  # 未申报融合→覆盖不足 warn
        rules_out, vr = _run(tmp_path, [_rule()], rs=rs2,
                             fused=[{"rule_id": "DQ_001", "covered_rs": ["编码不可为空值"],
                                     "note": "同一检查不同措辞"}]) if False else (None, None)
        # _run 不传 fused——直接调 validate_and_build 带 fused
        from run_ut import dq_rule_filename
        dq_dir = tmp_path / "dqf"
        dq_dir.mkdir()
        (dq_dir / dq_rule_filename("DQ_001", "产品编码非空")).write_text(
            "SELECT t.id, t.prod_code FROM dws.dwb_test_f t WHERE t.prod_code IS NULL",
            encoding="utf-8")
        rules_out, vr = validate_and_build(
            rs2, _ts(), [_rule()], dq_dir,
            fused=[{"rule_id": "DQ_001", "covered_rs": ["编码不可为空值"], "note": "同一检查不同措辞"}])
        assert not any(i["code"] == "N_DQ2" for i in vr.items)  # 融合覆盖计入→契约齐
        # 对账两硬拦
        _, vrx = validate_and_build(rs2, _ts(), [_rule()], dq_dir,
                                    fused=[{"rule_id": "DQ_099", "covered_rs": ["编码不可为空值"]}])
        assert any("rule_id 'DQ_099' 不存在" in i["msg"] for i in vrx.items)
        _, vry = validate_and_build(rs2, _ts(), [_rule()], dq_dir,
                                    fused=[{"rule_id": "DQ_001", "covered_rs": ["不存在的需求"]}])
        assert any("RS 需求名 '不存在的需求' 不存在" in i["msg"] for i in vry.items)
        from assemble_dq import render_dq_section
        text = render_dq_section({"rules": rules_out,
                                  "fused": [{"rule_id": "DQ_001", "covered_rs": ["编码不可为空值"],
                                             "note": "同一检查不同措辞"}]}, rs2["dq_requirements"])
        assert "融合申报" in text and "编码不可为空值" in text and "DQ_001" in text

    def test_patch_ts_md_keeps_mainline_bytes(self, tmp_path):
        md = tmp_path / "ts.md"
        mainline = ("# ETL 技术规格(TS)\n\n主线章节内容\n\n---\n\n"
                    "## 6. 调度\n\n主线任务\n\n---\n\n"
                    "## 7. 数据质量检查(DQ)\n\n"
                    "*(DQ 章节由 dws-dq-producer 独立设计后经 assemble_dq 追加；RS 无 DQ 需求则本资产无 DQ)*\n\n"
                    "---\n\n## 8. 增量设计\n\n增量内容\n")
        md.write_text(mainline, encoding="utf-8")
        dq = {"rules": [{"idx": 1, "rule_name": "产品编码非空", "check_type": "空值检查",
                         "scope": "字段级", "mode": "assertion",
                         "violation_condition": "t.prod_code IS NULL", "rule_desc": "违规=空",
                         "ambiguities": [], "waived": False}]}
        patch_ts_md(md, dq, [])
        after = md.read_text(encoding="utf-8")
        assert after.startswith("# ETL 技术规格(TS)\n\n主线章节内容")  # 主线开头字节不动
        assert "## 6. 调度\n\n主线任务" in after  # §6 不动
        assert "## 8. 增量设计\n\n增量内容" in after  # §8 不动
        assert "占位" not in after  # 占位被替换
        assert "dws-dq-producer 独立设计实现" in after and "t.prod_code IS NULL" in after

    def test_render_section_ambiguity_inline(self):
        dq = {"rules": [
            {"idx": 1, "rule_name": "断言1", "check_type": "空值检查", "scope": "字段级",
             "mode": "assertion", "violation_condition": "t.a IS NULL", "rule_desc": "r",
             "ambiguities": [{"note": "二义", "options": ["A"]}], "waived": False},
            {"idx": 2, "rule_name": "对比1", "check_type": "一致性检查", "scope": "记录级",
             "mode": "compare", "violation_condition": "t.a <> s.a", "rule_desc": "独立重算",
             "ambiguities": [], "waived": True, "waive_reason": "数据真脏"},
        ]}
        text = render_dq_section(dq, [])
        assert "⚠️歧义" in text          # 表格行内歧义标记
        assert "歧义标注" in text and "二义" in text  # 表格后歧义清单
        assert "（已豁免）" in text       # 豁免标记行内呈现

    def test_build_dq_task_hangs_under_view(self, monkeypatch):
        import assemble_dq
        monkeypatch.setattr(assemble_dq, "load_schedule_config",
                            lambda: {"default": {"project_name": "SRP", "task_group": "G",
                                                 "dq": {"project_name": "DQ_P", "task_group": "DQ_G"}}})
        task = build_dq_task(_ts(), {})
        assert task["task_name"] == "task_dwb_test_f_dq"
        assert task["project_name"] == "DQ_P" and task["task_group"] == "DQ_G"  # dq 子键
        assert task["upstream"][0]["task"] == "task_dwb_test_i"  # 挂 view 下游

    def test_build_dq_task_designer_override_wins(self, monkeypatch):
        import assemble_dq
        monkeypatch.setattr(assemble_dq, "load_schedule_config",
                            lambda: {"default": {"project_name": "SRP", "task_group": "G"}})
        dd = {"schedule": {"task_project_override": {"dq": {"project_name": "CUSTOM", "task_group": "CG"}}}}
        task = build_dq_task(_ts(), dd)
        assert task["project_name"] == "CUSTOM" and task["task_group"] == "CG"

    def test_build_dq_task_no_view_no_task(self):
        assert build_dq_task(_ts(with_view=False), {}) == {}


# ============================================================
# 真实装配链路（do_assemble 产的 ts 喂 DQ 校验——fixture 手写形态与真实产出脱节
# 曾漏掉 target_field 键不认的 bug，此测试锚定真实链路）
# ============================================================

class TestRealChain:
    def test_f_fields_from_real_assemble(self, tmp_path):
        """do_assemble 产出（fields=target_field 形态）→ _f_table_info 取到字段集。"""
        from conftest import make_rs_input, make_design_decisions
        from assemble_ts import assemble_ts as do_assemble
        from assemble_dq import _f_table_info
        rs = make_rs_input()
        rs["dq_requirements"] = [
            {"scope": "字段级", "check_type": "空值检查", "rule_name": "id 非空", "rule_desc": "x"}]
        dd = make_design_decisions()
        ts, _, _ = do_assemble(rs, dd)
        _schema, short, fields = _f_table_info(ts)
        assert short == "dwb_test_f"
        assert {"id", "del_flag", "crt_cycle_id"} <= fields  # 真实 target_field 键被识别
        # 端到端：断言式 DQ 在真实 ts 上校验通过（精简形态：无锚定声明要求）
        dq_dir = tmp_path / "dq"
        dq_dir.mkdir()
        (dq_dir / "DQ_001_id_非空.sql").write_text(
            "SELECT t.id FROM dws.dwb_test_f t WHERE t.id IS NULL", encoding="utf-8")
        rules_in = [{
            "rule_id": "DQ_001", "scope": "字段级", "check_type": "空值检查", "rule_name": "id 非空",
            "mode": "assertion", "violation_condition": "t.id IS NULL", "rule_desc": "违规=id 空"}]
        rules_out, vr = validate_and_build(rs, ts, rules_in, dq_dir)
        assert not any(i["level"] == "hard" for i in vr.items), vr.report_lines()


# ============================================================
# CLI 端到端
# ============================================================

class TestMain:
    def _setup(self, tmp_path, md_name="dwb_test_f_ts.md"):
        build = tmp_path / "build"
        (build / "_internal").mkdir(parents=True)
        (build / "dq").mkdir()
        (build / "ts.json").write_text(json.dumps(_ts(), ensure_ascii=False), encoding="utf-8")
        (build / "_internal" / "rs_input.json").write_text(
            json.dumps(_rs(), ensure_ascii=False), encoding="utf-8")
        # 产出标准：md 带 f_table 短名前缀（3322a75；_locate_ts_md 按标准寻址>ts.md 兜底）
        (build / md_name).write_text(
            "## 7. 数据质量检查(DQ)\n\n*(占位)*\n\n---\n\n## 8. 增量设计\n", encoding="utf-8")
        return build

    def test_main_success(self, tmp_path):
        build = self._setup(tmp_path)
        (build / "dq" / "DQ_001_产品编码非空.sql").write_text(
            "SELECT t.id, t.prod_code FROM dws.dwb_test_f t WHERE t.prod_code IS NULL", encoding="utf-8")
        (build / "dq.json").write_text(json.dumps({"rules": [
            {"rule_id": "DQ_001", "scope": "字段级", "check_type": "空值检查",
             "rule_name": "产品编码非空",
             "mode": "assertion", "violation_condition": "t.prod_code IS NULL",
             "rule_desc": "违规=空"}]}, ensure_ascii=False), encoding="utf-8")
        import assemble_dq
        import sys as _sys
        old_argv = _sys.argv
        _sys.argv = ["assemble_dq.py", "--ts", str(build / "ts.json"),
                     "--dq-src", str(build / "dq.json"),
                     "--rs", str(build / "_internal" / "rs_input.json")]
        try:
            with pytest.raises(SystemExit) as ei:
                assemble_dq.main()
        finally:
            _sys.argv = old_argv
        assert ei.value.code == 0
        dq = json.loads((build / "dq.json").read_text(encoding="utf-8"))
        assert dq["rules"][0]["mode"] == "assertion"
        assert dq["rules"][0]["idx"] == 1 and dq["rules"][0]["sql_file"] == "DQ_001_产品编码非空.sql"
        assert dq["tasks"]["dq"]["task_name"] == "task_dwb_test_f_dq"
        md = (build / "dwb_test_f_ts.md").read_text(encoding="utf-8")  # 标准名被渲染
        assert "t.prod_code IS NULL" in md

    def test_main_legacy_ts_md_fallback(self, tmp_path):
        """旧档兜底：只有 ts.md（无标准名）时渲染进 ts.md。"""
        build = self._setup(tmp_path, md_name="ts.md")
        (build / "dq" / "DQ_001_产品编码非空.sql").write_text(
            "SELECT t.id, t.prod_code FROM dws.dwb_test_f t WHERE t.prod_code IS NULL", encoding="utf-8")
        (build / "dq.json").write_text(json.dumps({"rules": [
            {"rule_id": "DQ_001", "scope": "字段级", "check_type": "空值检查",
             "rule_name": "产品编码非空",
             "mode": "assertion", "violation_condition": "t.prod_code IS NULL",
             "rule_desc": "违规=空"}]}, ensure_ascii=False), encoding="utf-8")
        import assemble_dq
        import sys as _sys
        old_argv = _sys.argv
        _sys.argv = ["assemble_dq.py", "--ts", str(build / "ts.json"),
                     "--dq-src", str(build / "dq.json"),
                     "--rs", str(build / "_internal" / "rs_input.json")]
        try:
            with pytest.raises(SystemExit) as ei:
                assemble_dq.main()
        finally:
            _sys.argv = old_argv
        assert ei.value.code == 0
        assert "t.prod_code IS NULL" in (build / "ts.md").read_text(encoding="utf-8")

    def test_main_hard_exit_1(self, tmp_path):
        build = self._setup(tmp_path)
        (build / "dq.json").write_text(json.dumps({"rules": []}, ensure_ascii=False), encoding="utf-8")
        import assemble_dq
        import sys as _sys
        old_argv = _sys.argv
        _sys.argv = ["assemble_dq.py", "--ts", str(build / "ts.json"),
                     "--dq-src", str(build / "dq.json"),
                     "--rs", str(build / "_internal" / "rs_input.json")]
        try:
            with pytest.raises(SystemExit) as ei:
                assemble_dq.main()
        finally:
            _sys.argv = old_argv
        assert ei.value.code == 1


class TestGroupByPerScope:
    """聚合语法逐作用域（2026-09-18 内网实证：聚合错在 CTE 里被旧版只扫主查询体漏检；
    WHERE 标量子查询聚合合法，旧版整段正则误拦——两个方向一起修）。"""

    def _sql_run(self, tmp_path, sql, rid="DQ_001", rn="金额一致性"):
        from run_ut import dq_rule_filename
        dq_dir = tmp_path / ("dq" + rid)
        dq_dir.mkdir(exist_ok=True)
        (dq_dir / dq_rule_filename(rid, rn)).write_text(sql, encoding="utf-8")
        return validate_and_build(_rs(), _ts(), [
            _rule(rule_id=rid, rule_name=rn, check_type="一致性检查", mode="compare",
                  violation_condition="t.id <> s.id")], dq_dir)

    def test_cte_agg_missing_groupby_caught(self, tmp_path):
        """CTE 内聚合无 GROUP BY——旧版漏检（返回任意行比主查询错更隐蔽），必须拦。"""
        sql = ("WITH s AS (SELECT b.id, SUM(b.amt) AS total FROM ods.ods_test_f b) "
               "SELECT t.id, s.total FROM dws.dwb_test_f t JOIN s ON s.id = t.id")
        _, vr = self._sql_run(tmp_path, sql)
        assert any("CTE" in i["msg"] and "GROUP BY" in i["msg"] for i in vr.items)

    def test_cte_agg_with_groupby_ok(self, tmp_path):
        sql = ("WITH s AS (SELECT b.id, SUM(b.amt) AS total FROM ods.ods_test_f b GROUP BY b.id) "
               "SELECT t.id, s.total FROM dws.dwb_test_f t JOIN s ON s.id = t.id")
        _, vr = self._sql_run(tmp_path, sql)
        assert not any("GROUP BY" in i["msg"] for i in vr.items)

    def test_where_scalar_subquery_not_flagged(self, tmp_path):
        """WHERE 标量子查询聚合（合法，不强制外层分组）——不得误拦。"""
        sql = ("SELECT t.id, t.prod_code FROM dws.dwb_test_f t "
               "WHERE t.amt <> (SELECT SUM(b.amt) FROM ods.ods_test_f b WHERE b.id = t.id)")
        _, vr = self._sql_run(tmp_path, sql)
        assert not any("GROUP BY" in i["msg"] for i in vr.items)

    def test_fix_loop_fusion_stability(self, tmp_path):
        """修回路稳定性：融合（删中间规则）后其余规则的文件名/sql_file 零变化、零 N_DQ9。"""
        from run_ut import dq_rule_filename
        dq_dir = tmp_path / "dqz"
        dq_dir.mkdir()
        rules = [_rule(rule_id="DQ_001"),
                 _rule(rule_id="DQ_002", rule_name="编码不可为空值"),
                 _rule(rule_id="DQ_003", mode="compare", check_type="一致性检查",
                       rule_name="金额一致性", violation_condition="t.id <> s.id")]
        for d in rules:
            rid, rn = d["rule_id"], d["rule_name"]
            (dq_dir / dq_rule_filename(rid, rn)).write_text(
                f"SELECT t.id, t.prod_code FROM dws.dwb_test_f t WHERE t.prod_code IS NULL",
                encoding="utf-8")
        rules_out, vr = validate_and_build(_rs(), _ts(), rules, dq_dir)
        assert not any(i["level"] == "hard" for i in vr.items)
        # 融合 DQ_002 并入 DQ_001（删 002）——其余规则零感知
        fused_rules = [rules[0], rules[2]]
        rules_out2, vr2 = validate_and_build(
            _rs(dq_needs=[
                {"scope": "字段级", "check_type": "空值检查", "rule_name": "产品编码非空", "rule_desc": "x"},
                {"scope": "字段级", "check_type": "空值检查", "rule_name": "编码不可为空值", "rule_desc": "y"}]),
            _ts(), fused_rules, dq_dir,
            fused=[{"rule_id": "DQ_001", "covered_rs": ["编码不可为空值"], "note": "同义融合"}])
        assert not any(i["code"] == "N_DQ9" for i in vr2.items)      # 零文件错位
        by_id = {r["rule_id"]: r for r in rules_out2}
        assert by_id["DQ_003"]["sql_file"] == "DQ_003_金额一致性.sql"  # 文件名零变化
        assert by_id["DQ_001"]["sql_file"] == "DQ_001_产品编码非空.sql"


# ============================================================
# output_form 分级 + 文件名通道收口（2026-09-21 内网实报两问题）
# ============================================================
_COUNT_SQL = """/* DQ-数量一致性: 目标行数与源表一致 —— 违规=两侧行数不等 */
SELECT
    'row_count' AS check_item,
    t.cnt AS target_rows,
    s.cnt AS source_rows
FROM (SELECT COUNT(1) AS cnt FROM dws.dwb_test_f) t,
     (SELECT COUNT(1) AS cnt FROM ods.ods_test_f) s
WHERE t.cnt <> s.cnt"""


def _count_rule():
    return _rule(rule_id="DQ_003", scope="表级", check_type="数量一致性检查",
                 rule_name="目标行数与源表一致", mode="compare", output_form="set",
                 violation_condition="目标表行数 <> 源表行数（两侧不等即违规）",
                 rule_desc="违规=目标行数与源表行数不等")


def _count_rs():
    return _rs([{"scope": "表级", "check_type": "数量一致性检查",
                 "rule_name": "目标行数与源表一致", "rule_desc": "目标表行数与源表一致"}])


class TestOutputForm:
    """集合级检查（数量一致性模板形态——内网实测报的数据形态）无业务键不拦。"""

    def test_set_form_count_check_passes_without_business_key(self, tmp_path):
        rules_out, vr = _run(tmp_path, [_count_rule()], rs=_count_rs(), sqls={1: _COUNT_SQL})
        assert "N_DQ10" not in _codes(vr)
        assert rules_out[0]["output_form"] == "set"

    def test_row_default_missing_business_key_still_flags(self, tmp_path):
        """缺省 row 形态输出列无业务键 → 照拦（回归）。"""
        rules_out, vr = _run(tmp_path, [_rule(rule_id="DQ_009", rule_name="行数裸查")],
                             sqls={1: "/* DQ */\nSELECT t.prod_code FROM dws.dwb_test_f t "
                                      "WHERE t.prod_code IS NULL"})
        assert any("缺业务键" in i["msg"] for i in vr.items if i["code"] == "N_DQ10")

    def test_set_form_declared_but_row_sql_flags(self, tmp_path):
        """set 条目走行级 SQL 不误拦（set 放宽是单向的——形态声明信任 producer）。"""
        rules_out, vr = _run(tmp_path, [_count_rule()], rs=_count_rs())
        assert "N_DQ10" not in _codes(vr)   # _run 默认 SQL 含业务键 id，本就用例验证不炸

    def test_illegal_output_form_value_flags(self, tmp_path):
        rule = _count_rule()
        rule["output_form"] = "aggregate"
        _, vr = _run(tmp_path, [rule], rs=_count_rs(), sqls={1: _COUNT_SQL})
        assert any("output_form" in i["msg"] and "非法" in i["msg"] for i in vr.items)


class TestFilenameChannel:
    """producer 落盘纯 {rule_id}.sql → 装配器 rename 标准装饰名+回写 sql_file 真值。"""

    def test_plain_id_file_renamed_to_canonical(self, tmp_path):
        ts, rs = _ts(), _rs()
        dq_dir = tmp_path / "dq"
        dq_dir.mkdir()
        (dq_dir / "DQ_001.sql").write_text(
            "/* DQ */\nSELECT t.id, t.prod_code FROM dws.dwb_test_f t WHERE t.prod_code IS NULL",
            encoding="utf-8")
        rules_out, vr = validate_and_build(rs, ts, [_rule()], dq_dir, "")
        from run_ut import dq_rule_filename
        canonical = dq_rule_filename("DQ_001", "产品编码非空")
        assert (dq_dir / canonical).exists()          # rename 落位
        assert not (dq_dir / "DQ_001.sql").exists()   # 原纯 id 名已不存在
        assert rules_out[0]["sql_file"] == canonical  # 真值回写
        assert "N_DQ9" not in _codes(vr)

    def test_canonical_name_still_accepted(self, tmp_path):
        """直接落标准装饰名照常（兼容路径，不发生 rename）。"""
        rules_out, vr = _run(tmp_path, [_rule()])
        assert rules_out[0]["sql_file"].startswith("DQ_001_")
        assert "N_DQ9" not in _codes(vr)

    def test_both_forms_missing_flags(self, tmp_path):
        ts, rs = _ts(), _rs()
        dq_dir = tmp_path / "dq"
        dq_dir.mkdir()
        _, vr = validate_and_build(rs, ts, [_rule()], dq_dir, "")
        assert any(i["code"] == "N_DQ9" and "缺失" in i["msg"] for i in vr.items)


class TestSkillDocContract:
    """文档契约：SKILL 与模板的文件名通道/output_form/无删除权条款与实现一致。"""

    def test_skill_carries_new_channel_terms(self):
        skill = (Path(__file__).resolve().parent.parent / "skills" / "dws-dq" / "SKILL.md"
                 ).read_text(encoding="utf-8")
        assert "{build}/dq/{rule_id}.sql" in skill       # 纯 id 落盘契约
        assert "output_form" in skill                    # 形态声明
        assert "不可自行删除" in skill                    # 无删除权纪律

    def test_template_carries_new_channel_terms(self):
        tpl = (Path(__file__).resolve().parent.parent / "skills" / "dws-dq" / "assets"
               / "dq-template.json").read_text(encoding="utf-8")
        assert "{rule_id}.sql" in tpl and "output_form" in tpl
