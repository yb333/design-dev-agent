"""precheck_opt 测试：只检新增子集（命名规范/存在性对账/类型风险决策回写/新来源 JOIN 对账）。
不连库——连库单元用 fake tables dict；main 的无库路径走降级 warn。"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "skills" / "opt-pipe" / "scripts"))
sys.path.insert(0, str(REPO / "skills" / "design-dev-shared" / "scripts"))

from precheck_opt import (
    main, _check_existence_and_types, _check_type_risks, _check_join_risks,
)
from risk_checks import PrecheckResult


def mk_cr(fields):
    return {"change_type": "add_field", "version": "202608", "fields": fields,
            "asset": "dws.dwb_x_d"}


def mk_field(name="channel_name", stype="varchar(64)", ttype="varchar(64)",
             table="dim_channel", alias="c", join="a.shop_id=c.shop_id",
             new_source=True, rule="直取"):
    return {"field": name, "cn": name, "type": ttype,
            "source": {"schema": "dim", "table": table, "alias": alias, "field": name,
                       "source_type": stype, "rule": rule, "expr": "-",
                       "join_condition": join},
            "new_source_table": new_source}


def mk_ts():
    return {"meta": {"target": {"f_table": {"schema": "dws", "table": "dwb_x_d"}}},
            "rules": {"R0001": {"source_tables": [
                {"schema": "ods", "table": "ods_order", "alias": "a"}]}}}


TABLES = {"dim.dim_channel": {"channel_name": "varchar(64)", "shop_id": "numeric(10)"},
          "ods.ods_order": {"shop_id": "numeric(10)"}}


class TestNaming:
    def test_bad_name_blocked(self, tmp_path):
        cr_path = tmp_path / "cr.json"
        cr_path.write_text(json.dumps(
            mk_cr([mk_field(name="Channel-Name")]), ensure_ascii=False), encoding="utf-8")
        ts_path = tmp_path / "ts.json"
        ts_path.write_text(json.dumps(mk_ts()), encoding="utf-8")
        rc = main(["--change-request", str(cr_path), "--ts-baseline", str(ts_path),
                   "--outdir", str(tmp_path)])
        assert rc == 2 or rc == 1  # 无库 warn + 命名 error → error 优先 exit 2
        cr = json.loads(cr_path.read_text(encoding="utf-8"))
        # 命名 error 在（无库路径照样跑离线检查）

    def test_good_name_passes_offline(self, tmp_path):
        cr_path = tmp_path / "cr.json"
        cr_path.write_text(json.dumps(mk_cr([mk_field()])), encoding="utf-8")
        ts_path = tmp_path / "ts.json"
        ts_path.write_text(json.dumps(mk_ts()), encoding="utf-8")
        rc = main(["--change-request", str(cr_path), "--ts-baseline", str(ts_path),
                   "--outdir", str(tmp_path)])
        assert rc == 1  # 无库降 warn（存在性+值域各一条），无 error


class TestExistence:
    def test_missing_column_error(self):
        result = PrecheckResult()
        cr = mk_cr([mk_field(name="nope", stype="varchar(10)")])
        _check_existence_and_types(cr, mk_ts(), TABLES, result)
        assert any("源字段不存在" in e for e in result.errors)

    def test_declared_type_mismatch_warns_and_backfills(self):
        result = PrecheckResult()
        cr = mk_cr([mk_field(stype="varchar(200)")])  # 库里实际 varchar(64)
        _check_existence_and_types(cr, mk_ts(), TABLES, result)
        assert any("以库为准" in w for w in result.warnings)
        assert cr["fields"][0]["source"]["source_type"] == "varchar(64)"

    def test_exact_match_silent(self):
        result = PrecheckResult()
        cr = mk_cr([mk_field(stype="varchar(64)")])
        _check_existence_and_types(cr, mk_ts(), TABLES, result)
        assert not result.errors and not result.warnings


class TestTypeRiskDecision:
    def _cr_cross(self):
        # 库类型回填后跨大类：varchar 源 → date 目标
        return mk_cr([mk_field(name="biz_date", stype="varchar(20)", ttype="date")])

    def test_pending_then_decision_written_back(self, tmp_path):
        from risk_checks import _detect_type_risks as detect_type_risks, _generate_type_risk_skeleton as generate_type_risk_skeleton
        cr = self._cr_cross()
        fm = [{"target_column": f["field"], "source_type": f["source"]["source_type"],
               "target_type": f["type"], "transform_rule": "直接复制"} for f in cr["fields"]]
        batch, individual = detect_type_risks({"field_mappings": fm})
        assert individual, "varchar→date 应检出跨大类"
        decision = tmp_path / "type_risk_decision.yaml"
        generate_type_risk_skeleton(decision, batch, individual)
        import yaml
        dec = yaml.safe_load(decision.read_text(encoding="utf-8"))
        for it in dec.get("跨大类风险字段", []):
            it["处置"] = "转换"
        decision.write_text(yaml.dump(dec, allow_unicode=True), encoding="utf-8")

        result = PrecheckResult()
        _check_type_risks(cr, tmp_path, result)
        assert not result.errors
        assert "decision" in cr["fields"][0]
        assert "原始输入='直接复制'" in cr["fields"][0]["decision"]
        assert "勿推翻方向" in cr["fields"][0]["decision"]

    def test_return_source_blocks(self, tmp_path):
        from risk_checks import _detect_type_risks as detect_type_risks, _generate_type_risk_skeleton as generate_type_risk_skeleton
        cr = self._cr_cross()
        fm = [{"target_column": f["field"], "source_type": f["source"]["source_type"],
               "target_type": f["type"], "transform_rule": "直接复制"} for f in cr["fields"]]
        batch, individual = detect_type_risks({"field_mappings": fm})
        decision = tmp_path / "type_risk_decision.yaml"
        generate_type_risk_skeleton(decision, batch, individual)
        import yaml
        dec = yaml.safe_load(decision.read_text(encoding="utf-8"))
        for it in dec.get("跨大类风险字段", []):
            it["处置"], it["原因"] = "返源端", "源端应提供 date"
        decision.write_text(yaml.dump(dec, allow_unicode=True), encoding="utf-8")
        result = PrecheckResult()
        _check_type_risks(cr, tmp_path, result)
        assert any("返源端" in e for e in result.errors), "返源端本轮终止（对齐 new-pipe）"
        assert "decision" not in cr["fields"][0]

    def test_no_pending_stdout_when_clean(self, tmp_path, capsys):
        cr = mk_cr([mk_field(stype="varchar(64)", ttype="varchar(200)")])  # 放宽无风险
        result = PrecheckResult()
        _check_type_risks(cr, tmp_path, result)
        assert "TYPE_RISK_PENDING" not in capsys.readouterr().out


class TestJoinRisk:
    def test_cross_category_detected_and_decision_written(self, tmp_path):
        cr = mk_cr([mk_field(name="channel_name", stype="varchar(64)",
                             join="a.shop_code=c.shop_code")])
        tables = {"dim.dim_channel": {"channel_name": "varchar(64)", "shop_code": "varchar(20)"},
                  "ods.ods_order": {"shop_id": "numeric(10)", "shop_code": "numeric(10)"}}
        result = PrecheckResult()
        _check_join_risks(cr, mk_ts(), tables, tmp_path, tmp_path / "cr.json", result)
        assert any("跨大类" in e for e in result.errors)
        dec_path = tmp_path / "join_type_decision.yaml"
        assert dec_path.exists(), "骨架已生成"

        import yaml
        dec = yaml.safe_load(dec_path.read_text(encoding="utf-8"))
        for it in dec.get("关联风险对", []):
            it["处置"] = "转换"
        dec_path.write_text(yaml.dump(dec, allow_unicode=True), encoding="utf-8")
        result2 = PrecheckResult()
        _check_join_risks(cr, mk_ts(), tables, tmp_path, tmp_path / "cr.json", result2)
        assert not result2.errors
        assert cr["join_type_decisions"][0]["decision"] == "转换"

    def test_same_type_no_risk(self, tmp_path):
        cr = mk_cr([mk_field(join="a.shop_id=c.shop_id")])  # 两侧 numeric 同族
        result = PrecheckResult()
        _check_join_risks(cr, mk_ts(), TABLES, tmp_path, tmp_path / "cr.json", result)
        assert not result.errors and not (tmp_path / "join_type_decision.yaml").exists()

    def test_key_change_blocks(self, tmp_path):
        cr = mk_cr([mk_field(name="channel_name", stype="varchar(64)",
                             join="a.shop_code=c.shop_code")])
        tables = {"dim.dim_channel": {"channel_name": "varchar(64)", "shop_code": "varchar(20)"},
                  "ods.ods_order": {"shop_id": "numeric(10)", "shop_code": "numeric(10)"}}
        result = PrecheckResult()
        _check_join_risks(cr, mk_ts(), tables, tmp_path, tmp_path / "cr.json", result)
        import yaml
        dec = yaml.safe_load((tmp_path / "join_type_decision.yaml").read_text(encoding="utf-8"))
        for it in dec.get("关联风险对", []):
            it["处置"] = "改关联键"
        (tmp_path / "join_type_decision.yaml").write_text(
            yaml.dump(dec, allow_unicode=True), encoding="utf-8")
        result2 = PrecheckResult()
        _check_join_risks(cr, mk_ts(), tables, tmp_path, tmp_path / "cr.json", result2)
        assert any("改关联键" in e for e in result2.errors)


class TestModifyTypeDecision:
    """场景 B 类型修改方向决策：扩容放行 / 收窄·跨大类
    PENDING 人决策三选（确认转换/重选兼容类型/放弃该条变更）回写。"""

    def _cr(self, old="varchar(64)", new="varchar(128)"):
        cr = mk_cr([])
        cr["modify_type_fields"] = [{"field": "order_id", "old_type": old,
                                     "new_type": new, "change_entry": {}}]
        return cr

    def test_widening_passes_silent(self, tmp_path, capsys):
        from precheck_opt import _check_modify_type_risks
        cr = self._cr()
        result = PrecheckResult()
        _check_modify_type_risks(cr, tmp_path, result)
        assert not result.errors
        assert cr["modify_type_fields"][0]["decision"]
        assert "TYPE_MODIFY_RISK_PENDING" not in capsys.readouterr().out

    def test_cross_category_pending_then_confirm_written_back(self, tmp_path):
        from precheck_opt import _check_modify_type_risks
        cr = self._cr(old="varchar(32)", new="int")  # 跨大类（塞不进去方向：存量 varchar 值未必是数字）
        result = PrecheckResult()
        _check_modify_type_risks(cr, tmp_path, result)
        assert any("待人工决策" in e for e in result.errors)
        assert (tmp_path / "modify_type_decision.yaml").exists()

        import yaml
        decision = tmp_path / "modify_type_decision.yaml"
        dec = yaml.safe_load(decision.read_text(encoding="utf-8"))
        for it in dec.get("类型修改风险字段", []):
            it["处置"] = "确认转换"
        decision.write_text(yaml.dump(dec, allow_unicode=True), encoding="utf-8")
        result2 = PrecheckResult()
        _check_modify_type_risks(cr, tmp_path, result2)
        assert not result2.errors
        assert "确认" in cr["modify_type_fields"][0]["decision"]
        assert "勿推翻" in cr["modify_type_fields"][0]["decision"]

    def test_drop_decision_routes_back_to_input(self, tmp_path):
        from precheck_opt import _check_modify_type_risks
        cr = self._cr(old="varchar(32)", new="int")
        result = PrecheckResult()
        _check_modify_type_risks(cr, tmp_path, result)
        import yaml
        decision = tmp_path / "modify_type_decision.yaml"
        dec = yaml.safe_load(decision.read_text(encoding="utf-8"))
        for it in dec.get("类型修改风险字段", []):
            it["处置"] = "放弃该条变更"
        decision.write_text(yaml.dump(dec, allow_unicode=True), encoding="utf-8")
        result2 = PrecheckResult()
        _check_modify_type_risks(cr, tmp_path, result2)
        assert any("放弃" in e and "重跑" in e for e in result2.errors)


class _FakeEx:
    """fake executor：mimic _fetch_tables_schema_batch 的 UNION ALL 返回。"""

    def __init__(self, tables_rows):
        self._rows = tables_rows  # [{nsp, rel, col, col_type}]
        self.calls = []

    def execute(self, sql):
        self.calls.append(sql)
        return type("R", (), {"success": True, "rows": self._rows, "error": ""})()

    def close(self):
        pass


class TestSchemaCacheChain:
    """三点一线契约（2026-11-10 实报收口）：_fetch tuple 键 → 落盘字符串键 →
    消费者字符串查。此前 _get_schema_types 零覆盖，tuple 键裸塞 json 炸被吞、
    静默不落盘的病根正是无链路测试。"""

    def _run_main(self, tmp_path, monkeypatch, rows):
        import dws_db
        ex = _FakeEx(rows)
        monkeypatch.setattr(dws_db, "create_executor_for_schema",
                            lambda *a, **k: ex)
        cr_path = tmp_path / "cr.json"
        cr_path.write_text(json.dumps(mk_cr([mk_field()])), encoding="utf-8")
        ts_path = tmp_path / "ts.json"
        ts_path.write_text(json.dumps(mk_ts()), encoding="utf-8")
        rc = main(["--change-request", str(cr_path), "--ts-baseline", str(ts_path),
                   "--outdir", str(tmp_path)])
        return rc, ex

    def test_fetch_writes_string_key_cache(self, tmp_path, monkeypatch):
        """连库 → _internal/schema_cache.json 落盘且键=字符串 schema.table。"""
        rows = [{"nsp": "dim", "rel": "dim_channel", "col": "channel_name",
                 "col_type": "character varying(64)"},
                {"nsp": "ods", "rel": "ods_order", "col": "shop_id",
                 "col_type": "numeric(10,0)"}]
        rc, _ = self._run_main(tmp_path, monkeypatch, rows)
        assert rc == 1  # 无 error（warn 属值域类）
        cache_file = tmp_path / "schema_cache.json"
        assert cache_file.exists(), "cache 必须落盘（实报：tuple 键 json 炸被吞静默失败）"
        tables = json.loads(cache_file.read_text(encoding="utf-8"))["tables"]
        assert "dim.dim_channel" in tables and "(dim" not in str(list(tables))
        assert tables["dim.dim_channel"]["channel_name"] == "character varying(64)"

    def test_second_run_hits_cache_no_refetch(self, tmp_path, monkeypatch):
        """二轮全命中且新鲜 → 不连库、不误报源字段不存在（读回键错位实报点）。"""
        rows = [{"nsp": "dim", "rel": "dim_channel", "col": "channel_name",
                 "col_type": "varchar(64)"},
                {"nsp": "ods", "rel": "ods_order", "col": "shop_id",
                 "col_type": "numeric(10,0)"}]
        rc, ex = self._run_main(tmp_path, monkeypatch, rows)
        n_first = len(ex.calls)
        assert n_first == 1
        rc2, ex2 = self._run_main(tmp_path, monkeypatch, rows)
        assert len(ex2.calls) == 0, "缓存新鲜且全命中不应重查"

    def test_fresh_cache_missing_table_refetches(self, tmp_path, monkeypatch):
        """缓存新鲜但缺表 → 连库补缺（缺表不当命中——对齐 new-pipe 语义，
        防「缓存没这张表」误判成「库里没这列」）。"""
        rows = [{"nsp": "dim", "rel": "dim_channel", "col": "channel_name",
                 "col_type": "varchar(64)"},
                {"nsp": "ods", "rel": "ods_order", "col": "shop_id",
                 "col_type": "numeric(10,0)"}]
        rc, _ = self._run_main(tmp_path, monkeypatch, rows)
        # 手动从缓存删掉一张表（模拟扩围前旧缓存）
        cache_file = tmp_path / "schema_cache.json"
        cache = json.loads(cache_file.read_text(encoding="utf-8"))
        del cache["tables"]["ods.ods_order"]
        cache_file.write_text(json.dumps(cache), encoding="utf-8")
        rc2, ex2 = self._run_main(tmp_path, monkeypatch, rows)
        assert len(ex2.calls) == 1, "缺表应连库补查"

    def test_save_failure_warns_not_silent(self, tmp_path, monkeypatch, capsys):
        """写盘炸 → stderr WARN 留痕不阻断（吞异常静默是实报放大器）。"""
        rows = [{"nsp": "dim", "rel": "dim_channel", "col": "channel_name",
                 "col_type": "varchar(64)"},
                {"nsp": "ods", "rel": "ods_order", "col": "shop_id",
                 "col_type": "numeric(10,0)"}]
        import dws_db
        ex = _FakeEx(rows)
        monkeypatch.setattr(dws_db, "create_executor_for_schema",
                            lambda *a, **k: ex)
        real_write = Path.write_text
        monkeypatch.setattr(Path, "write_text",
                            lambda self, *a, **k: (_ for _ in ()).throw(IOError("disk full"))
                            if self.name == "schema_cache.json" else real_write(self, *a, **k))
        cr_path = tmp_path / "cr.json"
        cr_path.write_text(json.dumps(mk_cr([mk_field()])), encoding="utf-8")
        ts_path = tmp_path / "ts.json"
        ts_path.write_text(json.dumps(mk_ts()), encoding="utf-8")
        rc = main(["--change-request", str(cr_path), "--ts-baseline", str(ts_path),
                   "--outdir", str(tmp_path)])
        captured = capsys.readouterr()
        assert "schema_cache 写盘失败" in captured.err
        assert rc == 0  # 校验照常完成（内存态在，不阻断）

    def test_cache_file_feeds_assemble_ts_opt(self, tmp_path, monkeypatch):
        """三点一线终点：precheck_opt 落的文件 → assemble_ts_opt 读 →
        N38 等价幻觉列真被拦（此前字符串键 cache 喂 tuple 查询全静默哑火）。"""
        import yaml
        from assemble_ts_opt import validate_decisions
        rows = [{"nsp": "dim", "rel": "dim_channel", "col": "channel_name",
                 "col_type": "varchar(64)"},
                {"nsp": "ods", "rel": "ods_order", "col": "shop_id",
                 "col_type": "numeric(10,0)"}]
        self._run_main(tmp_path, monkeypatch, rows)
        baseline = {"meta": {"target": {"f_table": {"schema": "dws", "table": "dwb_x_d"}}},
                    "tables": {"dwb_x_d": {"fields": [{"target_field": "etl_time"}]}},
                    "rules": {"R0001": {"source_tables": [
                        {"schema": "ods", "table": "ods_order", "alias": "a"}],
                        "target_table": "dws.dwb_x_d"}}}
        good = {"change_type": "add_field",
                "backfill": "no",
                "baseline_design": {"grain": "g", "keys": "k", "topology": "t"},
                "fields": [{"field": "channel_name", "target_table": "dwb_x_d",
                            "placed_rules": ["R0001"], "intermediate_tables": [],
                            "field_type": "varchar(64)", "field_comment": "渠道",
                            "design_logic": "c.channel_name 直取",
                            "transform_type": "direct",
                            "source": {"schema": "dim", "table": "dim_channel",
                                       "alias": "c", "field": "channel_name"},
                            "new_joins": [{"rule": "R0001", "schema": "dim",
                                           "table": "dim_channel", "alias": "c",
                                           "join_type": "LEFT",
                                           "join_on": "a.shop_id = c.shop_id",
                                           "join_safety": {"join_key_unique": True,
                                                           "strategy": "直接关联",
                                                           "join_filter": "",
                                                           "reason": "实测 count=distinct"}}]}]}
        p = tmp_path / "dec.yaml"
        p.write_text(yaml.dump(good, allow_unicode=True), encoding="utf-8")
        # 好 decisions + 真文件 cache：通过（JOIN 类型比对真实吃到 numeric 两侧一致）
        from schema_cache import load_cache_tables
        cache = load_cache_tables(tmp_path / "schema_cache.json")
        validate_decisions(good, baseline, cache)
        # 幻觉列：源表没有该列 → 源表侧拦截（cache 命中才拦得住——哑火实报点）
        bad = yaml.safe_load(yaml.dump(good, allow_unicode=True))
        bad["fields"][0]["design_logic"] = "c.ghost_col 直取"
        with pytest.raises(SystemExit):
            validate_decisions(bad, baseline, cache)
