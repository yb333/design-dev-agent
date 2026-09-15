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
    import re
    _clean = lambda s: re.sub(r"[^\w\u4e00-\u9fff]+", "_", (s or "").strip())
    for i, d in enumerate(rules_in, 1):
        fname = f"dq_{i:02d}_{_clean(d.get('check_type'))}.sql"
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
        (dq_dir / "dq_01_空值检查.sql").write_text(
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
            _rule(rule_id=None, mode="", ambiguities=[{"note": "口径二义", "options": ["A", "B"]}]),
            _rule(rule_id="DQ_002", mode="compare", check_type="一致性检查",
                  rule_name="金额复核", violation_condition="t.id <> s.id（独立重算）")])
        r1, r2 = rules_out
        assert r1["idx"] == 1 and r1["sql_file"] == "dq_01_空值检查.sql"
        assert r1["rule_id"] == "DQ_001" and r1["mode"] == "assertion"
        assert r1["ambiguities"][0]["note"] == "口径二义" and r1["waived"] is False
        assert r2["idx"] == 2 and r2["sql_file"] == "dq_02_一致性检查.sql"
        assert not any(i["level"] == "hard" for i in vr.items)

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
        (dq_dir / "dq_01_空值检查.sql").write_text(
            "SELECT t.id FROM dws.dwb_test_f t WHERE t.id IS NULL", encoding="utf-8")
        rules_in = [{
            "scope": "字段级", "check_type": "空值检查", "rule_name": "id 非空",
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
        (build / "dq" / "dq_01_空值检查.sql").write_text(
            "SELECT t.id, t.prod_code FROM dws.dwb_test_f t WHERE t.prod_code IS NULL", encoding="utf-8")
        (build / "dq.json").write_text(json.dumps({"rules": [
            {"scope": "字段级", "check_type": "空值检查", "rule_name": "产品编码非空",
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
        assert dq["rules"][0]["idx"] == 1 and dq["rules"][0]["sql_file"] == "dq_01_空值检查.sql"
        assert dq["tasks"]["dq"]["task_name"] == "task_dwb_test_f_dq"
        md = (build / "dwb_test_f_ts.md").read_text(encoding="utf-8")  # 标准名被渲染
        assert "t.prod_code IS NULL" in md

    def test_main_legacy_ts_md_fallback(self, tmp_path):
        """旧档兜底：只有 ts.md（无标准名）时渲染进 ts.md。"""
        build = self._setup(tmp_path, md_name="ts.md")
        (build / "dq" / "dq_01_空值检查.sql").write_text(
            "SELECT t.id, t.prod_code FROM dws.dwb_test_f t WHERE t.prod_code IS NULL", encoding="utf-8")
        (build / "dq.json").write_text(json.dumps({"rules": [
            {"scope": "字段级", "check_type": "空值检查", "rule_name": "产品编码非空",
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
