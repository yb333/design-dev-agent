"""AGENTS.md 结构登记与仓库实际对账（结构性变更须同步 AGENTS / 注册表）。

AGENTS.md 自称「当前实际结构（以此为准）」，但结构性提交漏同步它已多次发生（真实
漂移：229d718 两视图重构 commit message 写了「AGENTS 同步」实际没改；c9ad934 补
pick_targets 只改了 agent.md / tool-registry，漏了 AGENTS 的 agent 索引表；
ts_compat.py 加入后结构树与注册表双双漏登记；sync_to_team 工具在根目录存在多日
无任何登记）。参数级对账归 test_doc_sync（md 调用示例 vs argparse），本测试管
结构面，四个查：

1. 结构树 skills/*/scripts 登记 ↔ 实际 *.py **双向**一致（漏新增 / 挂错父目录都抓）；
2. agent 索引表列的工具必须真实存在（防脚本改名后表过时）；
3. tool-registry ②designer/③coder 节 ⊆ AGENTS agent 索引表对应行（注册表是工具
   唯一目录，AGENTS 表要跟上；住 shared 的能力层行不算角色入口，跳过）；
4. 根目录 tracked 脚本（py/sh/bat）必须在 AGENTS.md 全文出现过（防根目录工具隐形）。
"""

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
AGENTS_TEXT = (REPO / "AGENTS.md").read_text(encoding="utf-8")
REGISTRY_TEXT = (REPO / "docs" / "tool-registry.md").read_text(encoding="utf-8")

SCRIPT_DIRS = sorted(REPO.glob("skills/*/scripts"))


def _tree_block() -> str:
    m = re.search(r"## 当前实际结构.*?```\n(.*?)```", AGENTS_TEXT, re.DOTALL)
    assert m, "AGENTS.md 缺「当前实际结构」代码块——测试自身失效"
    return m.group(1)


def _tree_scripts() -> dict:
    """解析结构树 → {skill 目录名: {文件名.py}}。

    列 0 的 ``├── xxx/`` 定位当前 skill；含 ``scripts/`` 的节点行开启上下文并提取
    本行名字，其后**缩进的纯注释行**（``   # ...``）是同一 scripts 的续行；任何
    其他节点行或列 0 纯文本行结束上下文（防后续注释错挂——dws-dq 挂 dws-coding
    子树那类漂移靠"目录不存在"暴露）。
    """
    skills: dict = {}
    cur, in_scripts = None, False
    for line in _tree_block().splitlines():
        if "├" in line or "└" in line:  # 树节点行
            m0 = re.match(r"^[├└]── (\S+?)/", line)
            if m0:
                cur = m0.group(1)
            in_scripts = "scripts/" in line
            if in_scripts and cur is not None:
                skills.setdefault(cur, set()).update(
                    re.findall(r"([A-Za-z_]\w*\.py)", line))
        elif line.startswith((" ", "\t")) and "#" in line:  # 缩进续注释行
            if in_scripts and cur is not None:
                skills[cur].update(re.findall(r"([A-Za-z_]\w*\.py)", line))
        elif line[:1] not in ("", " "):  # 列 0 纯文本 = 新根条目，出上下文
            in_scripts = False
    return skills


def _actual_scripts() -> dict:
    return {d.parent.name: {p.name for p in d.glob("*.py")} for d in SCRIPT_DIRS}


def _agent_table_tools() -> dict:
    """AGENTS agent 索引表 → {dws-designer / dws-coder: 工具名集合}。"""
    tools = {}
    for m in re.finditer(
            r"^\| \*\*(dws-\w+)\*\* (?:\|[^|]*){2}\|([^|]*)\|", AGENTS_TEXT, re.M):
        # 工具列按 " / " 分段，每段取段首 ascii 词（括号说明里的 opt/dq 不算工具名）
        names = set()
        for part in m.group(2).split("/"):
            tm = re.match(r"\s*([a-z][a-z0-9_]*)", part)
            if tm:
                names.add(tm.group(1))
        tools[m.group(1)] = names
    return tools


def _registry_role_tools() -> dict:
    """tool-registry 按调用方分节 → {dws-designer / dws-coder: {脚本 stem}}。"""
    role_tools: dict = {}
    for chunk in re.split(r"\n## ", REGISTRY_TEXT):
        head = chunk.splitlines()[0]
        if "designer agent 调用" in head:
            role = "dws-designer"
        elif "coder agent 调用" in head:
            role = "dws-coder"
        else:
            continue
        names = role_tools.setdefault(role, set())
        for m in re.finditer(r"^\| `(\w+)\.py`([^\n]*)", chunk, re.M):
            if "design-dev-shared" in m.group(2):  # 住 shared 的能力层，非角色入口
                continue
            names.add(m.group(1))
    return role_tools


def test_tree_scripts_match_filesystem():
    tree, actual = _tree_scripts(), _actual_scripts()
    assert actual, "skills/*/scripts 扫描为空——测试自身失效"
    problems = []
    for skill in sorted(set(tree) | set(actual)):
        t, a = tree.get(skill, set()), actual.get(skill, set())
        if t and not a:
            problems.append(
                f"结构树在 skills/{skill}/ 下挂了 scripts 但该目录不存在（挂错父目录？登记：{sorted(t)}）")
            continue
        for name in sorted(a - t):
            problems.append(f"skills/{skill}/scripts/{name} 实际存在但结构树未登记")
        for name in sorted(t - a):
            problems.append(f"结构树登记了 skills/{skill}/scripts/{name} 但文件不存在")
    assert not problems, "\n".join(problems)


def test_agent_table_tools_exist():
    all_stems = {p.stem for d in SCRIPT_DIRS for p in d.glob("*.py")}
    problems = []
    for agent, names in _agent_table_tools().items():
        for n in sorted(names - all_stems):
            problems.append(f"agent 索引表 {agent} 行列了不存在的工具 {n}（脚本改名漏同步？）")
    assert not problems, "\n".join(problems)


def test_registry_role_tools_in_agent_table():
    table = _agent_table_tools()
    problems = []
    for agent, names in _registry_role_tools().items():
        missing = names - table.get(agent, set())
        if missing:
            problems.append(
                f"tool-registry {agent} 节登记了 {sorted(missing)}，AGENTS agent 索引表"
                f" {agent} 行没列（注册表是工具唯一目录，表要跟上）")
    assert not problems, "\n".join(problems)


def test_root_scripts_registered():
    try:
        out = subprocess.run(
            ["git", "ls-files"], cwd=REPO, capture_output=True, text=True,
            check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return  # 无 git 环境查不了 tracked 状态，放过（不扫未过滤的工作区）
    stems = {Path(f).stem for f in out.splitlines()
             if "/" not in f and f.endswith((".py", ".sh", ".bat"))}
    problems = [f"根目录 {s}.* 是 tracked 脚本但 AGENTS.md 全文无登记（sync_to_team 式隐形）"
                for s in sorted(stems) if f"{s}." not in AGENTS_TEXT]
    assert not problems, "\n".join(problems)
