# -*- coding: utf-8 -*-
"""agent 定义 frontmatter 结构守护。

实证事故（2026-09-03，内网）：往 permission 块中间插 tools: 块，把 permission
劈成两半——edit/write/skill 变顶层键，designer/coder 在内网无法被识别（tests
套件当时全绿——frontmatter 结构不在测试覆盖内，靠内网才发现）。本测试补这个盲区：
①三个 agent 的 frontmatter 可被 YAML 解析；②permission 是嵌套 dict 且关键子键
（bash/edit/write/skill）在其中而非顶层；③顶层键在已知集合内（未知顶层键=插错位置
的强信号）。
"""

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
AGENTS = ["dws-engineer.md", "dws-designer.md", "dws-coder.md"]
# opencode agent frontmatter 的已知顶层键（本仓使用的）
KNOWN_TOP_KEYS = {"description", "mode", "hidden", "permission", "temperature", "model",
                  "tools", "discovery"}


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert m, f"{path.name} 缺 frontmatter（--- 闭合）"
    return yaml.safe_load(m.group(1))


@pytest.mark.parametrize("name", AGENTS)
def test_frontmatter_parsable_and_known_keys(name):
    fm = _frontmatter(REPO / "agents" / name)
    assert isinstance(fm, dict) and fm.get("description"), f"{name} description 缺失"
    unknown = set(fm) - KNOWN_TOP_KEYS
    assert not unknown, f"{name} 出现未知顶层键 {unknown}——很可能插错了位置（子键逃逸出 permission）"


@pytest.mark.parametrize("name", AGENTS)
def test_permission_keys_nested_not_top_level(name):
    """关键权限子键必须在 permission 内——插块在 permission 中间会把这些键顶到顶层。"""
    fm = _frontmatter(REPO / "agents" / name)
    perm = fm.get("permission")
    assert isinstance(perm, dict), f"{name} permission 缺失或不是嵌套 dict"
    for key in ("bash", "skill"):
        assert key in perm, f"{name} permission.{key} 缺失"
    # designer/coder/engineer 都有 edit/write 白名单
    for key in ("edit", "write"):
        assert key in perm, f"{key} 逃逸出 permission（在顶层={('edit' in fm) or ('write' in fm)}）——检查 permission 块是否被中途截断"


def test_mcp_deny_in_all_three():
    """MCP 尽力层：三个 agent 的 permission 均含 mcp_* deny（部署面+提示词之外的兜底）。"""
    for name in AGENTS:
        perm = _frontmatter(REPO / "agents" / name)["permission"]
        assert perm.get("mcp_*") == "deny", f"{name} permission.mcp_* != deny"
