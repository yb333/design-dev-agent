# -*- coding: utf-8 -*-
"""分层铁律守护（AST 扫全部 import，含函数内 lazy——上翻正是靠它藏的）。

结构定调（2026-09 按消费者归位）：
  - shared = 公共设施（共用入口 preprocess/check_db/assemble_ddl/resolve_appid +
    公共库 dws_db/run_ut/sql_parse 等）——被多于一个消费者用；
  - new-pipe/scripts、opt-pipe/scripts = 各剧本自己的管线脚本（单一消费者）；
  - dws-design/scripts、dws-coding/scripts = designer/coder 的工具。

铁律单向：skill 目录（design/coding/new-pipe/opt-pipe）→ shared 合法；
  shared → 任何 skill 目录违规；pipe 之间互 import 违规（共用能力该在 shared）。
"""

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL_DIRS = {
    "dws-design": REPO / "skills" / "dws-design" / "scripts",
    "dws-coding": REPO / "skills" / "dws-coding" / "scripts",
    "new-pipe": REPO / "skills" / "new-pipe" / "scripts",
    "opt-pipe": REPO / "skills" / "opt-pipe" / "scripts",
    "design-dev-shared": REPO / "skills" / "design-dev-shared" / "scripts",
}
PIPE_DIRS = ("new-pipe", "opt-pipe")


def _module_names(dir_key: str) -> set[str]:
    """某 skill 目录下的顶层模块名。"""
    d = SKILL_DIRS[dir_key]
    return {p.stem for p in d.glob("*.py") if p.stem != "__init__"} if d.exists() else set()


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
    forbidden = set().union(*(_module_names(k) for k in SKILL_DIRS if k != "design-dev-shared"))
    assert forbidden, "skill 目录扫描为空，测试本身有问题"
    violations = []
    for py in sorted(SKILL_DIRS["design-dev-shared"].glob("*.py")):
        hit = _imported_names(py.read_text(encoding="utf-8")) & forbidden
        if hit:
            violations.append(f"{py.name} → {sorted(hit)}")
    assert not violations, (
        "shared 上翻 import skill 目录（分层铁律：箭头单向 skill→shared）：\n  "
        + "\n  ".join(violations)
        + "\n修复方式：被 shared 消费的能力下沉到 shared（整文件或抽常量），不要 lazy import 绕"
    )


def test_pipe_scripts_only_import_own_and_shared():
    """pipe 脚本只许 import 自己目录 + shared：跨 pipe/跨角色 import 都违规
    （共用能力该住 shared，2026-09 归位判据：>1 消费者 → shared）。"""
    violations = []
    for pipe in PIPE_DIRS:
        others = set().union(*(_module_names(k) for k in SKILL_DIRS
                               if k != pipe and k != "design-dev-shared"))
        own = _module_names(pipe)
        for py in sorted(SKILL_DIRS[pipe].glob("*.py")):
            hit = (_imported_names(py.read_text(encoding="utf-8")) - own) & others
            if hit:
                violations.append(f"{pipe}/{py.name} → {sorted(hit)}")
    assert not violations, (
        "pipe 脚本跨目录 import（只许自己目录 + shared）：\n  " + "\n  ".join(violations)
        + "\n修复方式：被两个 pipe 共用的脚本/库住 shared，单一消费者的进自己 pipe"
    )


def test_layering_rule_has_teeth():
    """守护测试自检：名字集合里确实包含各目录模块（防目录改名后静默失效）。"""
    assert "assemble_ts" in _module_names("dws-design")
    assert "check_sql" in _module_names("dws-coding")
    assert "ut_execute" in _module_names("new-pipe")
    assert "ut_opt" in _module_names("opt-pipe")
    assert "run_ut" in _module_names("design-dev-shared")
