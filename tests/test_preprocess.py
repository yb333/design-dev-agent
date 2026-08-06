"""
preprocess.py 核心逻辑测试。

重点测两类逻辑（build_rs_input 内部）：
1. 目标表后缀 -> f_table / i_view 推导
2. RS vs mapping 的 schema/table 校验分级（阻断 vs 告警 vs 正常）

测试数据全部用 dict 构造，不读真实 xlsx；build_rs_input 可直接 import 调用
（mapping_raw 和 rs_data 都是 dict，不依赖 ExcelMappingParser）。
"""

import pytest

# preprocess 通过 conftest.py 把 DESIGN_REFS 加入 sys.path 后可直接 import
from preprocess import build_rs_input


# ============================================================
# 工具：构造 mapping_raw / rs_data 的最小 dict
# ============================================================

def _mapping_raw(target_schema="dws", table="dwb_test_i", cn="测试表"):
    """构造 build_rs_input 第一参数 mapping_raw 的最小形态。

    build_rs_input 内部会先调 slim_mapping_data 做字段精简，但 schema/table/cn
    这几个顶层字段直接从 mapping_raw 读取，所以这里只需保证这几个字段在即可。
    """
    return {
        "target_schema": target_schema,
        "target_table": table,
        "target_table_cn": cn,
        "source_tables": [],
        "field_mappings": [],
    }


def _rs_data(schema="", table="", cn=""):
    """构造 build_rs_input 第二参数 rs_data 的最小形态。

    注意：extract_rs_data 的真实输出格式是 meta 顶层有 schema/table，
    不是嵌套在 meta.target 里。这里匹配真实格式。
    """
    return {
        "meta": {
            "schema": schema,
            "table": table,
            "cn": cn,
            "grain": "",
            "description": "",
        },
    }


def _f_table(result):
    return result["meta"]["target"]["f_table"]["table"]


def _i_view(result):
    return result["meta"]["target"]["i_view"]["table"]


# ============================================================
# 1. 目标表后缀 -> f_table / i_view 推导
# ============================================================

class TestSuffixDerivation:
    """测 build_rs_input 里 _i / _f / _d / 无后缀 的推导规则。"""

    def test_i_suffix(self):
        """_i 结尾 -> f_table=_f, i_view=_i"""
        r = build_rs_input(_mapping_raw(table="dwb_test_i"), _rs_data())
        assert _f_table(r) == "dwb_test_f"
        assert _i_view(r) == "dwb_test_i"

    def test_f_suffix(self):
        """_f 结尾 -> f_table=_f, i_view=_i"""
        r = build_rs_input(_mapping_raw(table="dwb_test_f"), _rs_data())
        assert _f_table(r) == "dwb_test_f"
        assert _i_view(r) == "dwb_test_i"

    def test_d_suffix(self):
        """_d 结尾（无标准后缀）-> f_table=原名, i_view=原名_i"""
        r = build_rs_input(_mapping_raw(table="dim_test_d"), _rs_data())
        assert _f_table(r) == "dim_test_d"
        assert _i_view(r) == "dim_test_d_i"

    def test_no_suffix(self):
        """无后缀 -> f_table=原名, i_view=原名_i"""
        r = build_rs_input(_mapping_raw(table="dim_test"), _rs_data())
        assert _f_table(r) == "dim_test"
        assert _i_view(r) == "dim_test_i"


# ============================================================
# 2. schema / table 校验分级
# ============================================================

class TestValidationGrading:
    """测 build_rs_input 里的校验分级逻辑。"""

    def test_both_no_schema_blocks(self, capsys):
        """两边都没写 schema -> 阻断（sys.exit 1）"""
        with pytest.raises(SystemExit) as exc:
            build_rs_input(
                _mapping_raw(target_schema="", table="dwb_test_i"),
                _rs_data(schema="", table="dwb_test_i"),
            )
        assert exc.value.code == 1
        # 错误信息应落到 stderr
        err = capsys.readouterr().err
        assert "schema" in err
        assert "都没写" in err

    def test_schema_mismatch_blocks(self, capsys):
        """两边 schema 不一致 -> 阻断"""
        with pytest.raises(SystemExit) as exc:
            build_rs_input(
                _mapping_raw(target_schema="dws", table="dwb_test_i"),
                _rs_data(schema="ods", table="dwb_test_i"),
            )
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "schema 不一致" in err

    def test_mapping_only_schema_warns(self, capsys):
        """mapping 有 schema、RS 没有 -> 告警但不阻断"""
        r = build_rs_input(
            _mapping_raw(target_schema="dws", table="dwb_test_i"),
            _rs_data(schema="", table="dwb_test_i"),
        )
        out = capsys.readouterr().out
        assert "告警" in out and "RS 没写 schema" in out
        # 最终 schema 取 mapping 的
        assert r["meta"]["target"]["f_table"]["schema"] == "dws"

    def test_rs_only_schema_warns(self, capsys):
        """RS 有 schema、mapping 没有 -> 告警但不阻断"""
        r = build_rs_input(
            _mapping_raw(target_schema="", table="dwb_test_i"),
            _rs_data(schema="ods", table="dwb_test_i"),
        )
        out = capsys.readouterr().out
        assert "告警" in out and "mapping 没写 schema" in out
        # 最终 schema 取 RS 的
        assert r["meta"]["target"]["f_table"]["schema"] == "ods"

    def test_schema_consistent_passes(self, capsys):
        """两边 schema 一致 -> 正常，无告警无阻断"""
        r = build_rs_input(
            _mapping_raw(target_schema="dws", table="dwb_test_i"),
            _rs_data(schema="dws", table="dwb_test_i"),
        )
        out = capsys.readouterr().out
        assert "告警" not in out
        assert r["meta"]["target"]["f_table"]["schema"] == "dws"
        assert _f_table(r) == "dwb_test_f"

    def test_both_no_table_blocks(self, capsys):
        """两边都没写表名 -> 阻断"""
        with pytest.raises(SystemExit) as exc:
            build_rs_input(
                _mapping_raw(target_schema="dws", table=""),
                _rs_data(schema="dws", table=""),
            )
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "表名" in err and "都没写" in err

    def test_table_mismatch_blocks(self, capsys):
        """两边表名不一致 -> 阻断"""
        with pytest.raises(SystemExit) as exc:
            build_rs_input(
                _mapping_raw(target_schema="dws", table="dwb_a_i"),
                _rs_data(schema="dws", table="dwb_b_i"),
            )
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "表名不一致" in err


# ============================================================
# 3. 与 conftest 工厂函数集成（确保 make_rs_input 推导一致）
# ============================================================

class TestFactoryIntegration:
    """验证 conftest.make_rs_input 的推导与 build_rs_input 行为一致。"""

    def test_factory_i_suffix_matches(self):
        from conftest import make_rs_input

        rs = make_rs_input(table="dwb_test_i")
        assert rs["meta"]["target"]["f_table"]["table"] == "dwb_test_f"
        assert rs["meta"]["target"]["i_view"]["table"] == "dwb_test_i"

    def test_factory_f_suffix_matches(self):
        from conftest import make_rs_input

        rs = make_rs_input(table="dwb_test_f")
        assert rs["meta"]["target"]["f_table"]["table"] == "dwb_test_f"
        assert rs["meta"]["target"]["i_view"]["table"] == "dwb_test_i"

    def test_factory_has_audit_fields(self):
        from conftest import make_rs_input

        rs = make_rs_input(table="dwb_test_i")
        targets = {f["target_column"] for f in rs["field_mappings"]}
        assert {"del_flag", "crt_cycle_id", "last_upd_cycle_id", "dw_last_update_date"} <= targets

    def test_factory_no_audit(self):
        from conftest import make_rs_input

        rs = make_rs_input(table="dwb_test_i", has_audit=False)
        targets = {f["target_column"] for f in rs["field_mappings"]}
        assert "del_flag" not in targets


# ============================================================
# 4. 端到端：extract_rs_data → build_rs_input（真实数据流）
# ============================================================

class TestExtractAndBuildE2E:
    """用真实的 extract_rs_data 提取 RS，传给 build_rs_input。

    这个测试防止"测试构造的数据格式和真实 extract_rs_data 输出不匹配"
    的问题（之前 _rs_data 把 schema/table 放在 meta.target 下，
    但真实输出在 meta 顶层，导致测试通过但真实场景报错）。
    """

    def test_real_rs_extraction_to_build(self):
        """extract_rs_data 提取标准 RS → build_rs_input 能正确取到 schema/table"""
        from preprocess import extract_rs_data
        from pathlib import Path

        rs_path = Path(__file__).resolve().parent.parent / "docs" / "templates" / "RS模板.md"
        rs_data = extract_rs_data(str(rs_path))

        # extract_rs_data 的输出：schema/table 在 meta 顶层
        assert rs_data["meta"]["schema"] != "", "extract_rs_data 应提取到 schema"
        assert rs_data["meta"]["table"] != "", "extract_rs_data 应提取到 table"

        # 构造配套的 mapping_raw（schema/table 和 RS 一致）
        rs_schema = rs_data["meta"]["schema"]
        rs_table = rs_data["meta"]["table"]
        mapping_raw = {
            "target_schema": rs_schema,
            "target_table": rs_table,
            "target_table_cn": "测试",
            "source_tables": [],
            "field_mappings": [],
        }

        # build_rs_input 应该能从 rs_data 正确取到 schema/table，不阻断
        result = build_rs_input(mapping_raw, rs_data)
        assert result["meta"]["target"]["f_table"]["schema"] == rs_schema
        assert result["meta"]["target"]["f_table"]["table"] != ""

    def test_real_rs_extraction_format(self):
        """验证 extract_rs_data 输出的 meta 结构（schema/table 在顶层不在 target 下）"""
        from preprocess import extract_rs_data
        from pathlib import Path

        rs_path = Path(__file__).resolve().parent.parent / "docs" / "templates" / "RS模板.md"
        rs_data = extract_rs_data(str(rs_path))
        meta = rs_data["meta"]

        # 真实格式：schema/table 在 meta 顶层
        assert "schema" in meta, "meta 顶层应有 schema"
        assert "table" in meta, "meta 顶层应有 table"
        # 不应该有嵌套的 target
        assert "target" not in meta or not isinstance(meta.get("target"), dict) or not meta["target"], \
            "extract_rs_data 不应该把 schema/table 放在 meta.target 下"


# ============================================================
# build_compact 测试：分块紧凑视图（给 designer 读）
# ============================================================

def _rs_input_with(fields, source_tables=None):
    """构造含 field_mappings 的最小 rs_input（给 build_compact 用）。"""
    if source_tables is None:
        source_tables = [{"source_schema": "ods", "source_table": "ods_test_f",
                          "source_alias": "t", "join_condition": "LEFT JOIN ON id"}]
    return {"field_mappings": fields, "source_tables": source_tables}


def _direct(source_column="id", target_column="id", source_table="ods_test_f",
            alias="t", schema="ods", target_type="bigint", remark=""):
    return {"source_schema": schema, "source_table": source_table,
            "source_column": source_column, "source_type": target_type,
            "transform_rule": "直接复制", "transform_detail": "-",
            "target_column": target_column, "target_column_cn": target_column,
            "target_type": target_type, "source_alias": alias,
            "scene_group": "default", "remark": remark}


def _assign(target_column="del_flag", target_type="nvarchar(1)", detail="'N'"):
    return {"source_schema": "", "source_table": "", "source_column": "", "source_type": "",
            "transform_rule": "赋值", "transform_detail": detail,
            "target_column": target_column, "target_column_cn": "删除标识",
            "target_type": target_type, "source_alias": "",
            "scene_group": "default", "remark": "审计字段"}


def _processed(target_column="total_amt", target_type="decimal(18,2)",
               source_table="ods_test_f", source_column="amount", alias="t",
               detail="SUM(amount)"):
    return {"source_schema": "ods", "source_table": source_table,
            "source_column": source_column, "source_type": "decimal(18,2)",
            "transform_rule": "数据加工", "transform_detail": detail,
            "target_column": target_column, "target_column_cn": "总额",
            "target_type": target_type, "source_alias": alias,
            "scene_group": "default", "remark": ""}


class TestBuildCompact:
    """build_compact：分块紧凑视图生成。"""

    def test_direct_fields_grouped_by_table(self):
        """直取字段按 (schema,table,alias) 分块，同表多字段聚一块。"""
        from preprocess import build_compact
        rs = _rs_input_with([
            _direct("id", "user_id"), _direct("name", "user_name"),
        ])
        c = build_compact(rs)
        direct = c["direct"]
        assert len(direct) == 1, "同表同别名应聚一块"
        assert direct[0]["schema"] == "ods"
        assert direct[0]["table"] == "ods_test_f"
        assert direct[0]["alias"] == "t"
        assert direct[0]["rule"] == "直接复制"
        assert len(direct[0]["fields"]) == 2
        # 块体短 key
        f0 = direct[0]["fields"][0]
        assert f0["src"] == "id"
        assert f0["tgt"] == "user_id"
        assert f0["type"] == "bigint"
        assert "note" not in f0, "无 remark 不应有 note"

    def test_assign_fields_separate_block(self):
        """赋值字段（审计字段）单独成块，val 列含赋值。"""
        from preprocess import build_compact
        rs = _rs_input_with([
            _direct("id", "user_id"),
            _assign("del_flag", "nvarchar(1)", "'N'"),
        ])
        c = build_compact(rs)
        assign_blocks = [b for b in c["direct"] if b["rule"] == "赋值"]
        assert len(assign_blocks) == 1
        f = assign_blocks[0]["fields"][0]
        assert f["tgt"] == "del_flag"
        assert f["val"] == "'N'"

    def test_processed_fields_flat_with_logic(self):
        """加工字段逐个平铺，含 logic 口径。"""
        from preprocess import build_compact
        rs = _rs_input_with([_processed("total_amt", detail="SUM(amount)")])
        c = build_compact(rs)
        assert len(c["processed"]) == 1
        p = c["processed"][0]
        assert p["tgt"] == "total_amt"
        assert p["type"] == "decimal(18,2)"
        assert p["logic"] == "SUM(amount)"
        # 单来源 sources 是单元素数组
        assert isinstance(p["sources"], list)
        assert len(p["sources"]) == 4  # [schema, table, alias, column]

    def test_multi_source_field_merged(self):
        """多表来源字段（同 target_column 多行不同表）合并成一段。"""
        from preprocess import build_compact
        rs = _rs_input_with([
            _direct("behavior_id", "behavior_id", source_table="ods_a_f", alias="a"),
            _direct("behavior_id", "behavior_id", source_table="ods_b_f", alias="b"),
            _direct("behavior_id", "behavior_id", source_table="ods_c_f", alias="c"),
        ])
        c = build_compact(rs)
        # 这 3 行同 target_column 应聚到一个 direct 块？
        # 不——它们 source_table 不同，是 3 个 direct 块。
        # 但多表来源合并主要针对 processed 段。直取的多表来源场景较少。
        # 这里验证 direct 段按表分块正确（3 块）
        assert len(c["direct"]) == 3

    def test_multi_source_processed_merged(self):
        """加工字段多表来源（同 target 不同表）合并成一段，sources 是多元素数组。"""
        from preprocess import build_compact
        rs = _rs_input_with([
            _processed("time_period", source_table="ods_a_f", source_column="create_time",
                       alias="a", detail="CASE WHEN HOUR(create_time)<6 THEN '凌晨' END"),
            _processed("time_period", source_table="ods_b_f", source_column="interaction_time",
                       alias="b", detail="CASE WHEN HOUR(interaction_time)<6 THEN '凌晨' END"),
        ])
        c = build_compact(rs)
        assert len(c["processed"]) == 1, "同 target 多行应合并一段"
        p = c["processed"][0]
        assert isinstance(p["sources"], list) and len(p["sources"]) == 2

    def test_null_assign_skipped_with_marker(self):
        """NULL 赋值字段跳过（去噪），但进 null_in_scene 标记列表。"""
        from preprocess import build_compact
        rs = _rs_input_with([
            _direct("id", "user_id"),
            _assign("unused_field", "varchar(64)", "NULL"),  # NULL 赋值
        ])
        c = build_compact(rs)
        # unused_field 不应出现在 direct 段
        all_tgts = [f["tgt"] for b in c["direct"] for f in b["fields"]]
        assert "unused_field" not in all_tgts
        # 但应在 null_in_scene 标记里
        assert "unused_field" in c.get("null_in_scene", [])

    def test_no_null_when_all_real(self):
        """没有 NULL 赋值时，compact 不含 null_in_scene 段。"""
        from preprocess import build_compact
        rs = _rs_input_with([_direct("id", "user_id")])
        c = build_compact(rs)
        assert "null_in_scene" not in c

    def test_noise_removed(self):
        """去噪：空 remark 无 note、scene_group 不出现。"""
        from preprocess import build_compact
        rs = _rs_input_with([_direct("id", "user_id", remark="主键")])
        c = build_compact(rs)
        f = c["direct"][0]["fields"][0]
        assert f.get("note") == "主键", "有 remark 应出 note"
        # scene_group 不应出现在 compact 任何地方
        import json
        assert "scene_group" not in json.dumps(c, ensure_ascii=False)

    def test_tables_section(self):
        """表级清单含表名/别名/字段数/关联条件。"""
        from preprocess import build_compact
        rs = _rs_input_with(
            [_direct("id", "id"), _direct("name", "name")],
            source_tables=[{"source_schema": "ods", "source_table": "ods_test_f",
                            "source_alias": "t", "join_condition": "LEFT JOIN ON id"}],
        )
        c = build_compact(rs)
        assert len(c["tables"]) == 1
        t = c["tables"][0]
        assert t["schema"] == "ods"
        assert t["table"] == "ods_test_f"
        assert t["fields"] == 2
        assert t["join"] == "LEFT JOIN ON id"

    def test_equivalence_all_fields_covered(self):
        """对拍：compact 覆盖的 target 集合 == field_mappings 的 target 集合（含 NULL）。"""
        from preprocess import build_compact
        rs = _rs_input_with([
            _direct("id", "user_id"),
            _assign("del_flag", "nvarchar(1)", "'N'"),
            _processed("total_amt"),
            _assign("unused", "varchar(64)", "NULL"),  # NULL 跳过但进标记
        ])
        c = build_compact(rs)
        # field_mappings 的全部 target
        fm_targets = set(fm["target_column"] for fm in rs["field_mappings"])
        # compact 的 target（direct + processed + null_in_scene）
        c_targets = set()
        for b in c["direct"]:
            for f in b["fields"]:
                c_targets.add(f["tgt"])
        for p in c["processed"]:
            c_targets.add(p["tgt"])
        c_targets |= set(c.get("null_in_scene", []))
        assert fm_targets == c_targets, f"字段丢失：{fm_targets - c_targets} 或多余：{c_targets - fm_targets}"

    def test_build_rs_input_includes_compact(self):
        """build_rs_input 产出应含 compact 块（与 field_mappings 同级）。"""
        from preprocess import build_rs_input
        mapping_raw = _mapping_raw()
        rs_data = _rs_data()
        result = build_rs_input(mapping_raw, rs_data)
        assert "compact" in result, "rs_input 应含 compact 块"
        assert "field_mappings" in result, "rs_input 仍应含 field_mappings（脚本读）"
        assert "tables" in result["compact"]
        assert "direct" in result["compact"]
        assert "processed" in result["compact"]
