# -*- coding: utf-8 -*-
"""分层铁律守护：design-dev-shared 绝不 import dws-design/dws-coding。

背景（2026-08 函数库下沉）：脚本归位后曾出现 shared→skill 的上翻依赖
（precheck→assemble_ts→config_paths 成环），靠函数内 lazy import + sys.path
bootstrap 掩盖，运行时不报错但分层已破。本测试用 AST 扫描 shared 全部脚本的
import（含函数内 lazy import——上翻正是靠它藏的），出现即 fail。

铁律单向：design/coding → shared 合法；shared → design/coding 违规。
"""

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SHARED = REPO / "skills" / "design-dev-shared" / "scripts"


def _skill_module_names() -> set[str]:
    """design/coding 两个 skill 目录下的顶层模块名（= 禁止 shared import 的名字）。"""
    names = set()
    for skill in ("dws-design", "dws-coding"):
        d = REPO / "skills" / skill / "scripts"
        if d.exists():
            names.update(p.stem for p in d.glob("*.py") if p.stem != "__init__")
    return names


def _imported_names(source: str) -> set[str]:
    """AST 提取全部 import 名字（顶层 + 函数内 lazy，全算）。"""
    tree = ast.parse(source)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                names.add(node.module.split(".")[0])
    return names


def test_shared_never_imports_skill_dirs():
    forbidden = _skill_module_names()
    assert forbidden, "skill 目录扫描为空，测试本身有问题"
    violations = []
    for py in sorted(SHARED.glob("*.py")):
        names = _imported_names(py.read_text(encoding="utf-8"))
        hit = names & forbidden
        if hit:
            violations.append(f"{py.name} → {sorted(hit)}")
    assert not violations, (
        "shared 上翻 import skill 目录（分层铁律：箭头单向 skill→shared）：\n  "
        + "\n  ".join(violations)
        + "\n修复方式：被 shared 消费的能力下沉到 shared（整文件或抽常量），不要 lazy import 绕"
    )


def test_layering_rule_has_teeth():
    """守护测试自检：名字集合里确实包含 skill 侧模块（防目录改名后静默失效）。"""
    forbidden = _skill_module_names()
    assert "assemble_ts" in forbidden
    assert "check_sql" in forbidden
