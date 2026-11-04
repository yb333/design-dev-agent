# -*- coding: utf-8 -*-
"""vendor 指纹联锁（2026-10-22）：shared/sql_clean.py 是 analyzer 仓 engine.py
预处理链的 vendor 拷贝（权威在彼侧）——本测试比对三个子函数的源码指纹，权威侧
变更而本仓未 re-vendor 时 fail（漂移机器盯，不靠人记）。analyzer 仓路径不存在
时静默跳过（内网部署无彼侧源码——开关式哲学同 check_env 依赖对账）。

2026-11-04 扩展：v1 契约 schema（asset_facts.schema.json）纳入整文件指纹——
用户实测 'to_group was unexpected' 根因即彼侧加 to_group 键而我方 vendor 未跟
（schema 封闭段拒新产物），且无联锁静默漂移直到实测炸。至此 v1/v2 双方向联锁
齐：v2=彼侧 vendor 我方 schema+彼侧指纹；v1=我方 vendor 彼侧 schema+本测试。
"""
import sys
from pathlib import Path

import pytest

ANALYZER_ENGINE = Path("/Users/yuanbo/dws-analyzer-skill/dws-pipeline-analyzer/references/engine.py")
ANALYZER_SCHEMA = Path("/Users/yuanbo/dws-analyzer-skill/dws-pipeline-analyzer/schemas/asset_facts.schema.json")
SHARED_DIR = Path(__file__).resolve().parent.parent / "skills" / "design-dev-shared" / "scripts"
OUR_SCHEMA = Path(__file__).resolve().parent.parent / "skills" / "opt-pipe" / "schemas" / "asset_facts.schema.json"
VENDORED = ("_strip_sql_comments", "_strip_dws_clauses", "_replace_placeholders")


@pytest.mark.skipif(not ANALYZER_ENGINE.exists(), reason="analyzer 仓不在本机——联锁跳过（内网形态）")
def test_vendored_sql_clean_matches_analyzer():
    sys.path.insert(0, str(SHARED_DIR))
    import ast
    import sql_clean

    def _func_sources(path: Path) -> dict:
        """AST 静态提取（不执行彼侧代码）：{函数名: 源码段 strip}。"""
        tree = ast.parse(path.read_text(encoding="utf-8"))
        out = {}
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in VENDORED:
                out[node.name] = ast.get_source_segment(
                    path.read_text(encoding="utf-8"), node).strip()
        return out

    ours = _func_sources(SHARED_DIR / "sql_clean.py")
    theirs = _func_sources(ANALYZER_ENGINE)
    missing = [f for f in VENDORED if f not in theirs]
    if missing:
        pytest.skip(f"analyzer 侧缺函数 {missing}（权威侧已重构？）——人工核对 re-vendor")
    for fname in VENDORED:
        assert ours.get(fname) == theirs[fname], (
            f"vendor 漂移：{fname} 与 analyzer 权威侧不一致——彼侧预处理链已变更，"
            f"请 re-vendor（拷贝新实现+更新 sql_clean.py 头部版本锚）后重跑")


@pytest.mark.skipif(not ANALYZER_SCHEMA.exists(), reason="analyzer 仓不在本机——schema 联锁跳过（内网形态）")
def test_vendored_facts_schema_matches_analyzer():
    """v1 契约 schema 整文件指纹（2026-11-04，'to_group was unexpected' 实证后补）：
    彼侧（权威）演进契约而我方 vendor 未跟时当场 fail——re-vendor 后绿。"""
    ours = OUR_SCHEMA.read_text(encoding="utf-8").strip()
    theirs = ANALYZER_SCHEMA.read_text(encoding="utf-8").strip()
    assert ours == theirs, (
        "vendor 漂移：asset_facts.schema.json 与 analyzer 权威侧不一致——彼侧契约已"
        "演进（新增/修改字段），请 re-vendor（整文件拷贝）+ 消费侧适配新字段后重跑；"
        "封闭段(additionalProperties: false)下旧 schema 会拒收彼方新产物"
        "（实证：'to_group was unexpected'）")
