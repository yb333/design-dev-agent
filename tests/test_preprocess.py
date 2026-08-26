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
# 任务二：大小写不敏感 + RS 降级容错
# ============================================================

class TestCaseInsensitiveAndDegraded:
    """validate_target_table 大小写不敏感（仅大小写差异→warning）；RS 降级容错。"""

    def test_schema_case_only_difference_warns_not_blocks(self, capsys):
        """schema 仅大小写不同（Ods vs ods）→ warning，不算不一致、不阻断。"""
        from preprocess import validate_target_table
        final_schema, final_table, errors, warnings = validate_target_table(
            "Ods", "dwb_test_i", "ods", "dwb_test_i"
        )
        assert errors == [], f"仅大小写差异不应阻断: {errors}"
        case_warns = [w for w in warnings if "大小写" in w]
        assert case_warns, f"仅大小写差异应给规范化 warning: {warnings}"
        # 大小写一致时取 RS 为准
        assert final_schema == "Ods"

    def test_table_case_only_difference_warns_not_blocks(self, capsys):
        """表名仅大小写不同 → warning，不阻断。"""
        from preprocess import validate_target_table
        _, final_table, errors, warnings = validate_target_table(
            "dws", "DWB_TEST_I", "dws", "dwb_test_i"
        )
        assert errors == [], f"仅大小写差异不应阻断: {errors}"
        case_warns = [w for w in warnings if "大小写" in w]
        assert case_warns, f"表名仅大小写差异应给 warning: {warnings}"
        assert final_table == "DWB_TEST_I"

    def test_schema_real_mismatch_still_blocks(self):
        """schema 真不一致（dws vs ods）→ 仍阻断（大小写归一后仍不同）。"""
        from preprocess import validate_target_table
        _, _, errors, _ = validate_target_table(
            "dws", "dwb_test_i", "ods", "dwb_test_i"
        )
        assert errors, "真不一致仍应阻断"

    def test_rs_degraded_marker_when_target_missing(self, capsys):
        """RS 非空但 schema/table 都没解析出（L1.1 缺失）→ 不 exit，标 _rs_degraded，mapping 兜底。"""
        r = build_rs_input(
            _mapping_raw(target_schema="dws", table="dwb_test_i"),
            _rs_data(schema="", table=""),  # RS 有内容但目标表没解析出
        )
        # 不应 exit（到这就说明没 sys.exit）
        assert r["_rs_degraded"] is True
        # mapping 兜底：目标表来自 mapping
        assert r["meta"]["target"]["f_table"]["schema"] == "dws"
        assert _f_table(r) == "dwb_test_f"

    def test_rs_degraded_not_set_when_table_present(self, capsys):
        """RS 有 table（哪怕 schema 空）→ 不算降级（_rs_degraded 不设）。"""
        r = build_rs_input(
            _mapping_raw(target_schema="dws", table="dwb_test_i"),
            _rs_data(schema="", table="dwb_test_i"),
        )
        assert "_rs_degraded" not in r
        assert "_no_rs_mode" not in r


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

class TestExtractErrorReporting:
    """RS 解析错误必须被收集到 _extract_errors（之前 main 静默吞掉）。

    回归：extract_rs_data 把 errors 收集到 _extract_errors/_extract_warnings，
    但 main 没读它们。现在 main 会打印+exit(1)，前提是 errors 被正确收集。
    """

    def test_missing_asset_section_reports_error(self, tmp_path):
        """缺必填的资产基本信息段 → _extract_errors 非空。"""
        from preprocess import extract_rs_data
        # 一个几乎空的 RS，没有任何标准段
        rs_file = tmp_path / "bad_rs.md"
        rs_file.write_text("# 某文档\n\n一些无关内容\n", encoding="utf-8")
        rs_data = extract_rs_data(str(rs_file))
        errors = rs_data.get("_extract_errors", [])
        assert errors, f"缺必填段应收集到 errors: {errors}"
        assert any("资产基本信息" in e for e in errors)

    def test_missing_optional_section_warns_not_errors(self, tmp_path):
        """缺非必填段（调度/DQ）→ _extract_warnings，不是 errors。"""
        from preprocess import extract_rs_data
        rs_file = tmp_path / "min_rs.md"
        # 只有资产基本信息段（真实格式：### 标题 + 属性/内容表头），其他都缺
        rs_file.write_text(
            "### 1.1 资产基本信息\n\n"
            "| 属性 | 内容 |\n|------|------|\n"
            "| 业务对象 | 订单 |\n"
            "| 资产 SCHEMA.接口视图 | dws.dwb_test_i |\n"
            "| 资产描述 | 测试表 |\n\n",
            encoding="utf-8")
        rs_data = extract_rs_data(str(rs_file))
        errors = rs_data.get("_extract_errors", [])
        warnings = rs_data.get("_extract_warnings", [])
        # 资产段有了，不应有"资产基本信息"相关的 error
        assert not any("资产基本信息" in e for e in errors), f"资产段有不应报错: {errors}"
        # 调度/DQ 缺失应是 warning
        assert warnings, f"缺非必填段应有 warnings: {warnings}"

    def test_valid_rs_no_errors(self, tmp_path):
        """标准 RS → _extract_errors 为空。"""
        from preprocess import extract_rs_data
        from pathlib import Path
        rs_path = Path(__file__).resolve().parent.parent / "docs" / "templates" / "RS模板.md"
        rs_data = extract_rs_data(str(rs_path))
        errors = rs_data.get("_extract_errors", [])
        assert not errors, f"标准 RS 不应有解析错误: {errors}"

    def test_asset_section_found_but_schema_missing_reports(self, tmp_path):
        """★ 段在但核心字段（schema/table）没解析到 → error。

        回归场景：源端把'资产 SCHEMA.接口视图'写成了别的措辞，
        段找到了、其他字段也解析了，但 schema/table 丢了。
        """
        from preprocess import extract_rs_data
        rs_file = tmp_path / "bad_schema.md"
        rs_file.write_text(
            "### 1.1 资产基本信息\n\n"
            "| 属性 | 内容 |\n|------|------|\n"
            "| 业务对象 | 订单 |\n"
            "| 资产描述 | 测试表 |\n"  # 没有 SCHEMA.接口视图 行
            "\n### L07 初始化及调度设计\n\n"
            "| 配置项 | 内容 |\n|------|------|\n"
            "| 调度方案 | 全量调度 |\n\n",
            encoding="utf-8")
        rs_data = extract_rs_data(str(rs_file))
        errors = rs_data.get("_extract_errors", [])
        schema_errors = [e for e in errors if "schema" in e.lower() or "未提取到" in e]
        assert schema_errors, f"段在但 schema 没解析到应报 error: {errors}"

    def test_asset_section_found_but_table_garbled_reports(self, tmp_path):
        """段在但表格格式完全不对（没解析出任何字段）→ error。"""
        from preprocess import extract_rs_data
        rs_file = tmp_path / "garbled.md"
        rs_file.write_text(
            "### 1.1 资产基本信息\n\n"
            "这里没有表格，只有一段文字描述\n",
            encoding="utf-8")
        rs_data = extract_rs_data(str(rs_file))
        errors = rs_data.get("_extract_errors", [])
        garbled_errors = [e for e in errors if "未解析" in e or "未找到" in e]
        assert garbled_errors, f"段在但表格没解析出应报 error: {errors}"

    def test_sched_section_found_but_unparseable_warns(self, tmp_path):
        """调度段在但表头写法不标准 → warning（非必填不报 error）。"""
        from preprocess import extract_rs_data
        rs_file = tmp_path / "bad_sched.md"
        rs_file.write_text(
            "### 1.1 资产基本信息\n\n"
            "| 属性 | 内容 |\n|------|------|\n"
            "| 业务对象 | 订单 |\n"
            "| 资产 SCHEMA.接口视图 | dws.dwb_test_i |\n\n"
            "### L07 初始化及调度设计\n\n"
            "调度方案是每天跑一次\n",  # 段在但没有标准表格
            encoding="utf-8")
        rs_data = extract_rs_data(str(rs_file))
        warnings = rs_data.get("_extract_warnings", [])
        sched_warns = [w for w in warnings if "调度配置" in w and "未解析" in w]
        assert sched_warns, f"调度段在但没解析出应 warn: {warnings}"


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
# 5. 增量表及增量字段解析（RS L07 子段）
# ============================================================

# 一个最小但结构完整的 RS L07 段（含调度配置 + 增量表 + 湖表调度），
# 用来测增量表解析的多种场景。包在资产信息 + L07 + L08 之间，
# 让 _find_section 能正确切出 L07 段。
def _rs_with_incremental(incr_rows_md: str) -> str:
    """构造含 L07 段的 RS 文本。incr_rows_md 是增量表的数据行 markdown。"""
    return f"""# RS

**资产基本信息**

| SCHEMA | 资产描述 |
|--------|----------|
| dws.dwb_test_f | 测试资产 |

**L07 初始化及调度设计**

| 配置项 | 内容 |
|--------|------|
| 调度方案 | 增量调度|
| 初始化时间范围 | ALL |
| 调度频率 | T+1调度，一天一调|
| 调度完成时间要求 | SLA：3:30|
| 增量识别方式 | update_time|

**增量表及增量字段**
|来源表|增量字段|
|-----|-----|
{incr_rows_md}

**湖表调度信息**：

| 湖表 | 任务名 | 环境 | 应用 | 项目 | 任务组 |
|------|--------|------|------|------|--------|
| ods.ods_a | task_a | dev | app1 | P1 | G1 |

**L08 数据保留周期及清理规则**
"""


class TestIncrementalTablesParse:
    """extract_rs_data 解析 L07 的"增量表及增量字段"子段。"""

    def test_parses_incremental_rows(self, tmp_path):
        """有真实增量行 -> 解析成 incremental_tables 列表。"""
        from preprocess import extract_rs_data
        rs = _rs_with_incremental(
            "|ods.ods_order_f|update_time|\n|ods.ods_payment_f|dt|\n"
        )
        p = tmp_path / "rs.md"
        p.write_text(rs, encoding="utf-8")
        rs_data = extract_rs_data(str(p))
        assert rs_data["schedule"]["incremental_tables"] == [
            {"source_table": "ods.ods_order_f", "incremental_key": "update_time"},
            {"source_table": "ods.ods_payment_f", "incremental_key": "dt"},
        ]

    def test_filters_template_placeholder(self, tmp_path):
        """RS 模板占位行（xxxx.xxxx | xxxx）被过滤掉。"""
        from preprocess import extract_rs_data
        rs = _rs_with_incremental("|xxxx.xxxx|xxxx|\n")
        p = tmp_path / "rs.md"
        p.write_text(rs, encoding="utf-8")
        rs_data = extract_rs_data(str(p))
        assert rs_data["schedule"]["incremental_tables"] == []

    def test_full_load_no_section(self, tmp_path):
        """全量资产 RS 没有增量表子段 -> incremental_tables 为空列表不报错。"""
        from preprocess import extract_rs_data
        # 把增量表子段整个删掉（模拟全量资产）
        rs = _rs_with_incremental("").replace("**增量表及增量字段**\n", "")
        p = tmp_path / "rs.md"
        p.write_text(rs, encoding="utf-8")
        rs_data = extract_rs_data(str(p))
        assert rs_data["schedule"]["incremental_tables"] == []

    def test_old_rs_without_label_compat(self, tmp_path):
        """旧 RS（完全没有增量表段）正常解析，incremental_tables 为空。"""
        from preprocess import extract_rs_data
        rs = """# RS
**资产基本信息**

| SCHEMA | 资产描述 |
|--------|----------|
| dws.dwb_old_f | 旧资产 |

**L07 初始化及调度设计**

| 配置项 | 内容 |
|--------|------|
| 调度方案 | 全量调度|

**L08 数据保留周期及清理规则**
"""
        p = tmp_path / "rs.md"
        p.write_text(rs, encoding="utf-8")
        rs_data = extract_rs_data(str(p))
        assert rs_data["schedule"]["incremental_tables"] == []

    def test_partial_row_skipped(self, tmp_path):
        """缺列/空行的行被跳过，不报错。"""
        from preprocess import extract_rs_data
        rs = _rs_with_incremental(
            "|ods.ods_order_f|update_time|\n"   # 完整
            "|ods.ods_payment_f|\n"            # 缺增量字段 -> 跳过
            "||\n"                              # 空行 -> 跳过
            "|ods.ods_log_f|create_time|\n"    # 完整
        )
        p = tmp_path / "rs.md"
        p.write_text(rs, encoding="utf-8")
        rs_data = extract_rs_data(str(p))
        assert rs_data["schedule"]["incremental_tables"] == [
            {"source_table": "ods.ods_order_f", "incremental_key": "update_time"},
            {"source_table": "ods.ods_log_f", "incremental_key": "create_time"},
        ]

    def test_upstream_not_polluted(self, tmp_path):
        """增量表子段解析到下一个加粗标签止，不吞湖表调度的行（子段边界正确）。"""
        from preprocess import extract_rs_data
        rs = _rs_with_incremental("|ods.ods_order_f|update_time|\n")
        p = tmp_path / "rs.md"
        p.write_text(rs, encoding="utf-8")
        rs_data = extract_rs_data(str(p))
        # incremental_tables 只含增量表那行，不含湖表调度行（task_a 等）
        incr = rs_data["schedule"]["incremental_tables"]
        assert incr == [{"source_table": "ods.ods_order_f",
                         "incremental_key": "update_time"}]
        # 验证子段边界：湖表那行的任何值都没渗进 incremental_tables
        all_vals = " ".join(
            f"{it.get('source_table','')}{it.get('incremental_key','')}" for it in incr
        )
        assert "task_a" not in all_vals
        assert "湖表" not in all_vals


class TestIncrementalTablesBuild:
    """build_rs_input 把 incremental_tables 搬进 schedule 段。"""

    def test_build_carries_incremental_tables(self):
        """build_rs_input 的 schedule 段含 incremental_tables。"""
        rs_data = {
            "meta": {"schema": "dws", "table": "dwb_test_i", "cn": "", "grain": ""},
            "schedule": {
                "strategy": "增量调度", "frequency": "T+1", "incremental_key": "update_time",
                "incremental_tables": [
                    {"source_table": "ods.ods_order_f", "incremental_key": "update_time"},
                ],
                "upstream": [],
            },
        }
        result = build_rs_input(_mapping_raw(), rs_data)
        assert result["schedule"]["incremental_tables"] == [
            {"source_table": "ods.ods_order_f", "incremental_key": "update_time"},
        ]

    def test_build_empty_when_absent(self):
        """rs_data 没有 incremental_tables -> schedule 里也没有，不报错。"""
        rs_data = _rs_data(schema="dws", table="dwb_test_i")
        rs_data["schedule"] = {"strategy": "全量调度"}
        result = build_rs_input(_mapping_raw(), rs_data)
        # schedule 原样搬过来，没有 incremental_tables 键也不报错
        assert result["schedule"]["strategy"] == "全量调度"


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

    def test_build_rs_input_excludes_compact(self):
        """build_rs_input 产出不含 compact（compact 是独立 view 文件，由 main 写出）。"""
        from preprocess import build_rs_input
        mapping_raw = _mapping_raw()
        rs_data = _rs_data()
        result = build_rs_input(mapping_raw, rs_data)
        # rs_input.json 是纯真相源（field_mappings 给脚本），不含 compact
        assert "compact" not in result, "rs_input 不应含 compact（独立 view 文件）"
        assert "field_mappings" in result
        # compact 可从 rs_input 独立派生
        from preprocess import build_compact
        c = build_compact(result)
        assert "tables" in c
        assert "direct" in c
        assert "processed" in c

    def test_compact_includes_incremental_tables(self):
        """incremental_tables 非空时 compact 置顶横幅（designer 读 view 第一眼看到）。"""
        from preprocess import build_compact
        rs = _rs_input_with([_direct("id", "id")])
        rs["schedule"] = {"incremental_tables": [
            {"source_table": "ods.ods_order_f", "incremental_key": "update_time"},
        ]}
        c = build_compact(rs)
        banner = c["增量资产提示"]
        assert banner["incremental_tables"] == [
            {"source_table": "ods.ods_order_f", "incremental_key": "update_time"},
        ]
        assert "增量管道" in banner["说明"]
        assert "至少两个规则" in banner["说明"]
        assert list(c.keys())[0] == "增量资产提示"  # 置顶

    def test_compact_no_incremental_when_empty(self):
        """incremental_tables 为空时 compact 不含该键（全量资产）。"""
        from preprocess import build_compact
        rs = _rs_input_with([_direct("id", "id")])
        rs["schedule"] = {}
        c = build_compact(rs)
        assert "incremental_tables" not in c

    def test_compact_dq_section_with_requirements(self):
        """RS 有 DQ 需求时 compact.dq 展示需求内容 + 翻译说明（designer 必须翻译产 dq_rules）。"""
        from preprocess import build_compact
        rs = _rs_input_with([_direct("id", "id")])
        rs["dq_requirements"] = [
            {"scope": "字段级", "check_type": "空值检查", "rule_name": "金额非空",
             "rule_desc": "订单金额不能为空"},
        ]
        c = build_compact(rs)
        assert "dq" in c
        assert c["dq"]["requirements"] == rs["dq_requirements"]
        assert "翻译" in c["dq"]["说明"], "应告知 designer 翻译职责"

    def test_compact_dq_section_empty(self):
        """RS 无 DQ 需求时 compact.dq 标注留空（designer 不产 DQ）。"""
        from preprocess import build_compact
        rs = _rs_input_with([_direct("id", "id")])
        rs["dq_requirements"] = []
        c = build_compact(rs)
        assert "dq" in c
        assert c["dq"]["requirements"] == []
        assert "留空" in c["dq"]["说明"], "应明确告知 dq_rules 留空"


class TestNoRsMode:
    """无RS模式：mapping 独立驱动，schedule 用默认值兜底。

    场景：RS 不稳定是已知痛点，正式支持无RS模式——mapping 能独立跑通
    核心 链路（设计+编码+UT），缺的调度/增量/DQ 用默认值兜底。
    """

    def test_build_rs_input_no_rs_has_defaults(self):
        """★ 无RS（rs_data={}）→ schedule 有默认值，不崩。"""
        from preprocess import build_rs_input
        mapping_raw = _mapping_raw()
        result = build_rs_input(mapping_raw, {})  # 空 rs_data = 无RS
        sched = result["schedule"]
        assert sched["strategy"] == "全量调度"
        assert sched["frequency"] == "T+1"
        assert sched["incremental_key"] == "不涉及"
        assert sched["incremental_tables"] == []
        assert "_no_rs_mode" in result, "应有无RS模式标记"

    def test_build_rs_input_with_rs_overrides_defaults(self):
        """有RS时 RS 的值覆盖默认（不丢失RS提供的信息）。"""
        from preprocess import build_rs_input
        mapping_raw = _mapping_raw()
        rs_data = _rs_data()
        rs_data["schedule"] = {"strategy": "增量调度", "frequency": "小时调度"}
        result = build_rs_input(mapping_raw, rs_data)
        assert result["schedule"]["strategy"] == "增量调度"
        assert result["schedule"]["frequency"] == "小时调度"
        assert "_no_rs_mode" not in result

    def test_no_rs_field_mappings_intact(self):
        """★ 无RS时 field_mappings（核心数据）完整不丢。"""
        from preprocess import build_rs_input
        mapping_raw = _mapping_raw()
        mapping_raw["field_mappings"] = [
            {"source_column": "id", "target_column": "id", "target_type": "bigint",
             "transform_rule": "直接复制", "source_alias": "t"}]
        mapping_raw["source_tables"] = [
            {"source_schema": "ods", "source_table": "ods_test_f", "source_alias": "t"}]
        result = build_rs_input(mapping_raw, {})
        assert len(result["field_mappings"]) > 0, "无RS不应影响字段映射"
        assert len(result["source_tables"]) > 0, "无RS不应影响源表"

    def test_no_rs_precheck_warns_not_blocks(self, monkeypatch):
        """★ 无RS模式 precheck 给 warn 不阻断（核心链路可继续）。"""
        from precheck import precheck
        # mock 掉连库（测试环境无 DB）
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": (_ for _ in ()).throw(ImportError("skip db")))
        # 构造无RS模式的 rs_input
        rs = {
            "meta": {"target": {"f_table": {"schema": "dws", "table": "dwb_test_f", "cn": "测试"},
                                "i_view": {"schema": "dws", "table": "dwb_test_i", "cn": "测试"}}},
            "source_tables": [{"source_schema": "ods", "source_table": "ods_test_f",
                               "source_alias": "t", "source_table_cn": "测试"}],
            "field_mappings": [{"source_schema": "ods", "source_table": "ods_test_f",
                                 "source_column": "id", "source_type": "bigint",
                                 "transform_rule": "直接复制", "transform_detail": "-",
                                 "target_column": "id", "target_column_cn": "ID",
                                 "target_type": "bigint", "source_alias": "t"}],
            "schedule": {"strategy": "全量调度", "frequency": "T+1",
                         "incremental_key": "不涉及", "incremental_tables": [], "upstream": []},
            "_no_rs_mode": True,
        }
        result = precheck(rs)
        # 无RS模式应该是 warning 不阻断（return_code ≤ 1）
        assert result.return_code <= 1, f"无RS模式不应阻断: {result.errors}"
        no_rs_warns = [w for w in result.warnings if "无RS" in w]
        assert no_rs_warns, f"应有无RS模式提示: {result.warnings}"

    def test_schedule_with_defaults_function(self):
        """_schedule_with_defaults：RS提供的不覆盖，缺的补默认。"""
        from preprocess import _schedule_with_defaults
        # RS 提供了 strategy，缺 frequency
        sched = _schedule_with_defaults({"strategy": "增量调度"})
        assert sched["strategy"] == "增量调度"  # RS 提供的保留
        assert sched["frequency"] == "T+1"      # 缺的补默认
        assert sched["incremental_key"] == "不涉及"


class TestColumnMatch:
    """列名校验：缺任一标准列 → column_missing（不再只查 required）。"""

    def _make_parser(self):
        """构造不读文件的 parser 实例。"""
        from preprocess import ExcelMappingParser
        return ExcelMappingParser("dummy.xlsx")

    def test_missing_standard_column_reports(self):
        """缺标准列（如 source_alias）→ 报 column_missing。"""
        import pandas as pd
        parser = self._make_parser()
        # 实体级缺 '源表别名'（source_alias）
        cols = ['源表schema', '源表物理表名', '源表中文名', '目标表逻辑schema',
                '目标表中文名', '目标表物理名称', '关联&限定条件', '备注', '分组']
        df = pd.DataFrame(columns=cols)
        parser._check_column_match(df, parser.ENTITY_COLUMN_MAP, '实体级',
                                   optional=['remark', 'scene_group', 'join_condition'])
        missing = [d for d in parser.diagnostics if d['type'] == 'column_missing']
        assert missing, f"缺 source_alias 列应报 column_missing: {parser.diagnostics}"
        assert any('源表别名' in d['message'] for d in missing), \
            f"报错应提到期望列名 '源表别名': {missing}"

    def test_missing_optional_column_no_report(self):
        """可选列（备注/分组/关联条件）缺失 → 不报。"""
        import pandas as pd
        parser = self._make_parser()
        cols = ['源表schema', '源表物理表名', '源表中文名', '源表别名',
                '目标表逻辑schema', '目标表中文名', '目标表物理名称']
        df = pd.DataFrame(columns=cols)
        parser._check_column_match(df, parser.ENTITY_COLUMN_MAP, '实体级',
                                   optional=['remark', 'scene_group', 'join_condition'])
        missing = [d for d in parser.diagnostics if d['type'] == 'column_missing']
        assert missing == [], f"可选列缺失不该报: {missing}"

    def test_all_columns_present_no_report(self):
        """所有标准列都齐 → 不报。"""
        import pandas as pd
        parser = self._make_parser()
        cols = list(parser.ENTITY_COLUMN_MAP.keys())
        df = pd.DataFrame(columns=cols)
        parser._check_column_match(df, parser.ENTITY_COLUMN_MAP, '实体级',
                                   optional=['remark', 'scene_group', 'join_condition'])
        missing = [d for d in parser.diagnostics if d['type'] == 'column_missing']
        assert missing == [], f"列都齐不该报: {missing}"

    def test_attribute_missing_source_alias_reports(self):
        """属性级缺 '源表别名' → 报（用户遇到的根因场景）。"""
        import pandas as pd
        parser = self._make_parser()
        # 属性级缺 '源表别名'（BA 可能写成 '源表别名'）
        cols = ['源schema', '源表物理表名', '源表字段名', '源表字段中文名', '源表字段类型',
                '映射规则', '映射表达式', '目标字段名', '目标字段中文名', '目标字段类型']
        df = pd.DataFrame(columns=cols)
        parser._check_column_match(df, parser.ATTRIBUTE_COLUMN_MAP, '属性级',
                                   optional=['remark', 'scene_group', 'source_column_cn'])
        missing = [d for d in parser.diagnostics if d['type'] == 'column_missing']
        assert missing, f"属性级缺 source_alias 应报: {parser.diagnostics}"
        assert any('源表别名' in d['message'] for d in missing), \
            f"报错应提到 '源表别名': {missing}"


def _build_xlsx_with_assign_null(path, assign_expr='NULL'):
    """构造最小 mapping xlsx（实体级 + 属性级，属性级含一行"赋值"字段）。

    assign_expr 控制赋值行的映射表达式：默认 'NULL'（验证不被吞），
    传 None 模拟真没填的空单元格（验证区分能力）。
    """
    import openpyxl
    wb = openpyxl.Workbook()
    # 实体级（完整列名，过 _check_column_match）
    ws_e = wb.active
    ws_e.title = "实体级"
    ws_e.append(['源表schema', '源表物理表名', '源表中文名', '源表别名',
                 '目标表逻辑schema', '目标表中文名', '目标表物理名称',
                 '关联&限定条件', '备注', '分组'])
    ws_e.append(['ods', 'ods_test_f', '测试源表', 't', 'dws', '测试表',
                 'dwb_test_f', 'LEFT JOIN ON id', '', 'default'])
    # 属性级（完整列名 + 一行赋值 NULL）
    ws_a = wb.create_sheet("属性级")
    ws_a.append(['源schema', '源表物理表名', '源表别名', '源表字段名',
                 '源表字段中文名', '源表字段类型', '映射规则', '映射表达式',
                 '目标字段名', '目标字段中文名', '目标字段类型', '备注', '分组'])
    ws_a.append(['ods', 'ods_test_f', 't', 'id', 'ID', 'bigint',
                 '直接复制', '-', 'id', 'ID', 'bigint', '主键', 'default'])
    ws_a.append(['', '', '', '', '', '',
                 '赋值', assign_expr, 'del_flag', '删除标识', 'NVARCHAR(1)', '', 'default'])
    wb.save(path)


class TestNullPreservation:
    """赋值 NULL 场景：pandas.read_excel 不应把 NULL/NA 吞成 NaN。

    回归背景：read_excel 默认 keep_default_na=True，把 "NULL"/"NA"/"N/A" 都读成 NaN。
    _safe_str 再把 NaN 转 ''，导致"赋值 NULL"字段的映射表达式变空 → precheck 报
    "赋值字段映射表达式为空"。修复：read_excel 加 keep_default_na=False，保留原文。
    """

    def test_assign_null_preserved_not_swallowed(self, tmp_path):
        """赋值字段的映射表达式填 NULL → 保留原文 'NULL'，不被 pandas 吞成空。"""
        from preprocess import parse_mapping
        xlsx = tmp_path / "test_null.xlsx"
        _build_xlsx_with_assign_null(xlsx)
        result = parse_mapping(str(xlsx))
        fms = result.get("field_mappings", [])
        assign_fms = [fm for fm in fms
                      if (fm.get("transform_rule") or fm.get("mapping_rule")) == "赋值"]
        assert len(assign_fms) == 1, f"应解析出 1 个赋值字段，实际 {len(assign_fms)}"
        expr = assign_fms[0].get("transform_detail") or assign_fms[0].get("mapping_expression")
        # ★ NULL 必须保留原文，不是空（这是 bug 的核心断言）
        assert expr == "NULL", f"赋值 NULL 应保留原文 'NULL'，实际被吞成: {repr(expr)}"

    def test_empty_cell_still_empty(self, tmp_path):
        """真没填的空单元格（赋值字段映射表达式空着）→ 仍是空串，和"填NULL"区分开。"""
        from preprocess import parse_mapping
        xlsx = tmp_path / "test_empty.xlsx"
        _build_xlsx_with_assign_null(xlsx, assign_expr=None)  # None = 空单元格（真没填）
        result = parse_mapping(str(xlsx))
        fms = result.get("field_mappings", [])
        assign_fms = [fm for fm in fms
                      if (fm.get("transform_rule") or fm.get("mapping_rule")) == "赋值"]
        expr = assign_fms[0].get("transform_detail") or assign_fms[0].get("mapping_expression")
        assert expr == "", f"真没填应是空串，实际: {repr(expr)}"


class TestCompactConditionIssues:
    """precheck 入口闸检出 → view 的 tables 块 ⚠ 标记（designer 第一眼处理）。"""

    def test_issue_marked_on_table_entry(self):
        from preprocess import build_compact
        rs = _rs_input_with([_direct("id", "id")])
        rs["source_tables"][0]["join_condition"] = "t.id = m.mid and m.rn = 1"
        rs["_condition_issues"] = [{
            "table": "ods.ods_test_f", "field": "rn", "level": "error",
            "issue": "无出处（不在表结构，无产生逻辑记载）"}]
        c = build_compact(rs)
        entry = next(e for e in c["tables"] if e.get("alias") == "t")
        assert "⚠ rn" in entry["输入存疑"]

    def test_no_marker_without_issues(self):
        from preprocess import build_compact
        rs = _rs_input_with([_direct("id", "id")])
        c = build_compact(rs)
        assert all("输入存疑" not in e for e in c["tables"])


class TestAssignFaithfulPassthrough:
    """preprocess 如实反映：任何 detail 都不改 transform_rule。

    回归背景（187a92a 不完整修复的回声）：preprocess 曾把非平凡赋值改判"数据加工"——
    只改类型改不了 source_alias，撞 precheck 步骤6"数据加工必须填别名"，把合法的
    审计/传参字段全爆错。自然语言在输入层判不了（"传参"是描述不是错标），错标识别
    后置到 designer 翻译之后（assemble_ts N35 过程校验）。"""

    def test_any_detail_never_rewrites_rule(self):
        from preprocess import slim_mapping_data
        raw = {"source_tables": [], "field_mappings": [
            {"target_column": "flag", "mapping_rule": "赋值",
             "mapping_expression": "CASE WHEN x=1 THEN 'Y' ELSE 'N' END"},  # 真错标也不动
            {"target_column": "biz_flag", "mapping_rule": "赋值", "mapping_expression": "传参"},
            {"target_column": "del_flag", "mapping_rule": "赋值", "mapping_expression": "'N'"},
        ]}
        slim = slim_mapping_data(raw)
        assert all(f["transform_rule"] == "赋值" for f in slim["field_mappings"])

    def test_trivial_forms_all_kept(self):
        from preprocess import slim_mapping_data
        trivials = ["'N'", "0", "${P_CYCLE_ID}", "CURRENT_TIMESTAMP", "-", ""]
        raw = {"source_tables": [], "field_mappings": [
            {"target_column": f"c{i}", "mapping_rule": "赋值", "mapping_expression": d}
            for i, d in enumerate(trivials)]}
        slim = slim_mapping_data(raw)
        assert all(f["transform_rule"] == "赋值" for f in slim["field_mappings"])


class TestCompactAssignWarn:
    """view 对非标准字面量赋值标 ⚠（designer 第一眼翻译）；标准审计/平凡豁免。"""

    def test_marks_nontrivial_non_audit_only(self):
        from preprocess import build_compact
        rs = {"field_mappings": [
            {"transform_rule": "赋值", "transform_detail": "传参", "target_column": "biz_flag"},
            {"transform_rule": "赋值", "transform_detail": "'N'", "target_column": "del_flag"},
            {"transform_rule": "赋值", "transform_detail": "新增时间戳",
             "target_column": "dw_last_update_date"},
        ], "source_tables": []}
        view = build_compact(rs)
        marks = {}
        for blk in view.get("direct", []):
            for row in blk.get("fields", []):
                marks[row["tgt"]] = "⚠" in row
        assert marks == {"biz_flag": True, "del_flag": False, "dw_last_update_date": False}


class TestAssignSeamNoFalseAliasError:
    """接缝回归（187a92a 教训：两个模块各自对、组合错）：preprocess 输出喂 precheck——
    赋值字段（含非标准写法）不因类型被改判而撞"数据加工必须填 source_alias"。"""

    def test_full_forms_pass_precheck(self, monkeypatch):
        from preprocess import slim_mapping_data
        from precheck import precheck
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": (_ for _ in ()).throw(ImportError("skip db")))
        slim = slim_mapping_data({"source_tables": [
            {"source_schema": "ods", "source_table": "ods_t", "source_alias": "t",
             "source_table_cn": "测试"}],
            "field_mappings": [
                {"source_schema": "ods", "source_table": "ods_t", "source_alias": "t",
                 "source_column": "id", "transform_rule": "直接复制", "transform_detail": "-",
                 "target_column": "id", "target_column_cn": "ID", "target_type": "bigint"},
                {"transform_rule": "赋值", "transform_detail": "传参",
                 "target_column": "crt_cycle_id", "target_column_cn": "创建周期",
                 "target_type": "bigint"},
                {"transform_rule": "赋值",
                 "transform_detail": "CASE WHEN t.id=1 THEN 'Y' ELSE 'N' END",
                 "target_column": "flag", "target_column_cn": "标记",
                 "target_type": "nvarchar(1)"},
            ]})
        rs = {"meta": {"target": {"f_table": {"schema": "dws", "table": "dwb_test_f", "cn": "测试"},
                                  "i_view": {"schema": "dws", "table": "dwb_test_i", "cn": "测试"}}},
              "source_tables": slim["source_tables"],
              "field_mappings": slim["field_mappings"],
              "schedule": {"strategy": "全量调度", "frequency": "T+1",
                           "incremental_key": "不涉及", "incremental_tables": [], "upstream": []},
              "_no_rs_mode": True}
        result = precheck(rs)
        alias_errs = [e for e in result.errors if "source_alias" in e or "来源别名" in e]
        assert not alias_errs, alias_errs

