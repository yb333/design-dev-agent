"""运行时提示的调用说明与脚本 argparse 对账（改工具形态须同步全部调用说明）。

SKILL.md / agent.md / new-pipe.md 是 agent 消费的运行时提示，里面的 bash 调用示例
参数写错 = agent 照抄即报错（真实漂移：slice_ts 的 --compact 早已改为默认 compact +
--verbose，SKILL 还写着 --compact，coder 照抄 argparse 直接炸）。本测试静态对账：
md 代码块里每条含脚本的命令，其 --flag 必须存在于该脚本 argparse 定义。

范围：agents/ + commands/ + skills/*/SKILL.md（运行时提示）；docs/README 是维护者
文档不扫。已装机器的说明以仓库为准。
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

_SCRIPT_DIRS = [
    REPO / "skills" / "dws-design" / "scripts",
    REPO / "skills" / "dws-coding" / "scripts",
    REPO / "skills" / "design-dev-shared" / "scripts",
]

_MD_FILES = sorted(
    [p for p in (REPO / "agents").glob("*.md")]
    + [p for p in (REPO / "commands").glob("*.md")]
    + [p for p in REPO.glob("skills/*/SKILL.md")
       if "design-dev-shared" not in str(p)]
)


def _script_flags() -> dict:
    """{脚本名: argparse 定义的 --flag 集合}（从 add_argument 源码静态提取）。"""
    flags = {}
    for d in _SCRIPT_DIRS:
        for py in d.glob("*.py"):
            src = py.read_text(encoding="utf-8")
            found = set(re.findall(r'add_argument\(\s*"(--[a-z][\w-]*)"', src))
            if found:
                flags[py.stem] = found
    return flags


def _md_commands(md_path: Path) -> list:
    """md 里每个 bash 代码块按空行切成命令，返回 [(行号, 命令文本)]。"""
    text = md_path.read_text(encoding="utf-8")
    cmds = []
    for m in re.finditer(r"```[a-zA-Z]*\n(.*?)```", text, re.DOTALL):
        block = m.group(1)
        start_line = text[:m.start()].count("\n") + 2
        for para in re.split(r"\n\s*\n", block):
            para = para.strip()
            if ".py" in para:
                cmds.append((start_line, para))
    return cmds


def test_runtime_doc_flags_match_argparse():
    flags_by_script = _script_flags()
    assert flags_by_script, "脚本目录扫描为空——测试自身失效"
    problems = []
    for md in _MD_FILES:
        for line_no, cmd in _md_commands(md):
            stems = [s for s in flags_by_script if f"{s}.py" in cmd]
            if not stems:
                continue
            used = set(re.findall(r"(?<![\w-])(--[a-z][\w-]*)", cmd))
            allowed = set().union(*(flags_by_script[s] for s in stems))
            bad = used - allowed
            if bad:
                problems.append(
                    f"{md.relative_to(REPO)}:~{line_no} 命令用了未定义参数 {sorted(bad)}"
                    f"（{'+'.join(stems)} 只定义了 {sorted(allowed)}）")
    assert not problems, "\n".join(problems)


def test_coder_skill_flags_known_to_scripts():
    """coder SKILL 的三个工具调用示例逐条可解析（冒烟：文档对账机制本身在跑）。"""
    skill = REPO / "skills" / "dws-coding" / "SKILL.md"
    text = skill.read_text(encoding="utf-8")
    assert "--compact" not in text  # 已废除的参数不再出现在运行时提示
    assert "--verbose" in text      # 实际存在的完整模式参数有说明
    for flag in ("--select", "--ts", "--rule"):
        assert f"check_sql.py" in text and flag in text  # check_sql 必填三参有示例
