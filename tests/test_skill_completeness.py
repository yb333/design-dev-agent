"""
pytest 测试：验证所有 6 个 ETL skills 的文件结构完整性

测试内容：
1. 每个 skill 目录存在
2. 每个 skill 有 SKILL.md 且包含 YAML frontmatter（name 和 description）
3. 带 run.py 的 skills（coder, designer, exporter, tester）有有效的 run.py
4. 每个 skill 有 references/ 目录且至少有一个 .md 文件
5. 每个 skill 的 references/*.py 文件可以导入（不报 ImportError）
6. 顶层共享文件存在（dws-run.py 和 shared/ 目录）
7. 每个 SKILL.md 的 frontmatter 中 name 字段与目录名匹配
"""

import sys
from pathlib import Path
from typing import List

import pytest
import importlib.util

# ── 路径配置 ──────────────────────────────────────────────

# 项目根目录（与 conftest.py 保持一致）
PROJECT_ROOT = Path(__file__).parent.parent

# Skills 目录
SKILLS_DIR = PROJECT_ROOT / ".opencode" / "skills"

# 所有 6 个 skills
ALL_SKILLS = [
    "dws-pipeline-code-reviewer",
    "dws-pipeline-coder",
    "dws-pipeline-designer",
    "dws-pipeline-exporter",
    "dws-pipeline-reviewer",
    "dws-pipeline-tester",
]

# 有 run.py 的 skills（4 个）
SKILLS_WITH_RUN_PY = [
    "dws-pipeline-coder",
    "dws-pipeline-designer",
    "dws-pipeline-exporter",
    "dws-pipeline-tester",
]

# 没有 run.py 的 skills（2 个）
SKILLS_WITHOUT_RUN_PY = [
    "dws-pipeline-code-reviewer",
    "dws-pipeline-reviewer",
]

# ── Fixtures ──────────────────────────────────────────────

@pytest.fixture
def skills_dir() -> Path:
    """返回 skills 目录"""
    return SKILLS_DIR


@pytest.fixture(params=ALL_SKILLS)
def skill_dir(request) -> Path:
    """参数化 fixture：返回每个 skill 的目录路径"""
    return SKILLS_DIR / request.param


@pytest.fixture(params=SKILLS_WITH_RUN_PY)
def skill_with_run_py(request) -> Path:
    """参数化 fixture：返回有 run.py 的 skill 目录"""
    return SKILLS_DIR / request.param


# ── 测试：skill 目录存在性 ──────────────────────────────────

@pytest.mark.parametrize("skill_name", ALL_SKILLS)
def test_skill_directory_exists(skill_name):
    """测试：所有 6 个 skill 目录都存在"""
    skill_path = SKILLS_DIR / skill_name
    assert skill_path.exists(), f"Skill directory not found: {skill_path}"
    assert skill_path.is_dir(), f"Path exists but is not a directory: {skill_path}"


# ── 测试：SKILL.md 文件存在性 ───────────────────────────────

def test_all_skills_have_skill_md(skill_dir: Path):
    """测试：每个 skill 都有 SKILL.md 文件"""
    skill_md = skill_dir / "SKILL.md"
    assert skill_md.exists(), f"SKILL.md not found in {skill_dir}"
    assert skill_md.is_file(), f"SKILL.md exists but is not a file in {skill_dir}"


# ── 测试：SKILL.md YAML frontmatter ─────────────────────────

def test_skill_md_has_yaml_frontmatter(skill_dir: Path):
    """测试：SKILL.md 包含 YAML frontmatter（有 name 和 description）"""
    skill_md = skill_dir / "SKILL.md"
    content = skill_md.read_text(encoding="utf-8")

    # 检查是否有 YAML 分隔符
    assert "---" in content, f"SKILL.md missing YAML frontmatter delimiter in {skill_md}"

    # 检查是否有 name: 字段
    assert "name:" in content, f"SKILL.md missing 'name:' field in frontmatter in {skill_md}"

    # 检查是否有 description: 字段
    assert "description:" in content, f"SKILL.md missing 'description:' field in frontmatter in {skill_md}"


# ── 测试：SKILL.md frontmatter name 与目录名匹配 ───────────

def test_skill_md_name_matches_directory(skill_dir: Path):
    """测试：SKILL.md frontmatter 中的 name 字段与目录名匹配"""
    skill_md = skill_dir / "SKILL.md"
    content = skill_md.read_text(encoding="utf-8")

    # 提取目录名（纯目录名，不含路径）
    expected_name = skill_dir.name

    # 检查 frontmatter 中是否有 name: <目录名>
    # 简单检查：在 YAML 块中是否有 "name: dws-pipeline-xxx"
    yaml_block_end = content.find("---", 3)  # 跳过开头的 "---"
    yaml_content = content[:yaml_block_end] if yaml_block_end != -1 else content

    assert f"name: {expected_name}" in yaml_content, \
        f"SKILL.md frontmatter name does not match directory name. Expected: {expected_name}"


# ── 测试：run.py 存在性（有 run.py 的 skills） ─────────────

def test_skills_with_run_py_have_run_file(skill_with_run_py: Path):
    """测试：有 run.py 的 skills 确实有该文件"""
    run_py = skill_with_run_py / "run.py"
    assert run_py.exists(), f"run.py not found in {skill_with_run_py}"
    assert run_py.is_file(), f"run.py exists but is not a file in {skill_with_run_py}"


# ── 测试：run.py 不存在性（没有 run.py 的 skills） ─────────

@pytest.mark.parametrize("skill_name", SKILLS_WITHOUT_RUN_PY)
def test_skills_without_run_py_do_not_have_run_file(skill_name):
    """测试：没有 run.py 的 skills 确实没有该文件"""
    skill_path = SKILLS_DIR / skill_name
    run_py = skill_path / "run.py"
    assert not run_py.exists(), f"run.py should not exist in {skill_path} but found"


# ── 测试：run.py 是有效的 Python 文件 ───────────────────────

def test_run_py_is_valid_python(skill_with_run_py: Path):
    """测试：run.py 可以被解析为有效的 Python 文件（语法正确）"""
    run_py = skill_with_run_py / "run.py"
    try:
        compile(run_py.read_text(encoding="utf-8"), str(run_py), "exec")
    except SyntaxError as e:
        pytest.fail(f"run.py has syntax error in {skill_with_run_py}: {e}")


# ── 测试：references/ 目录存在性 ─────────────────────────────

def test_all_skills_have_references_dir(skill_dir: Path):
    """测试：每个 skill 都有 references/ 目录"""
    refs_dir = skill_dir / "references"
    assert refs_dir.exists(), f"references/ directory not found in {skill_dir}"
    assert refs_dir.is_dir(), f"references/ exists but is not a directory in {skill_dir}"


# ── 测试：references/ 至少有一个参考文件（.md 或 .py） ─────

def test_references_has_reference_files(skill_dir: Path):
    """测试：references/ 目录至少有一个参考文件（.md 或 .py）"""
    refs_dir = skill_dir / "references"
    md_files = list(refs_dir.glob("*.md"))
    py_files = list(refs_dir.glob("*.py"))
    reference_files = md_files + py_files

    assert len(reference_files) > 0, \
        f"references/ directory has no .md or .py files in {skill_dir}. Found files: {list(refs_dir.iterdir())}"


# ── 测试：references/*.py 文件可以导入 ─────────────────────

def test_references_py_files_can_be_imported(skill_dir: Path):
    """测试：references/ 中的所有 .py 文件可以导入（不抛 ImportError）"""
    refs_dir = skill_dir / "references"
    py_files = list(refs_dir.glob("*.py"))

    if not py_files:
        pytest.skip(f"No .py files in {skill_dir}/references")

    for py_file in py_files:
        # 尝试导入模块
        try:
            # 使用 importlib.util 从文件路径加载模块
            spec = importlib.util.spec_from_file_location(
                f"test_module_{py_file.stem}",
                py_file
            )
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                # 注意：这里只是验证导入时不报错，不实际执行
                # Python 文件在 import 时会执行顶层代码，如果顶层代码有副作用（如导入不存在的模块）会抛 ImportError
                spec.loader.exec_module(module)
        except ImportError as e:
            pytest.fail(
                f"Failed to import {py_file} in {skill_dir}: {e}\n"
                f"This usually means the file imports a module that is not available."
            )
        except Exception as e:
            # 其他错误（如 TypeError, SyntaxError）也视为失败
            pytest.fail(
                f"Failed to import {py_file} in {skill_dir}: {e}\n"
                f"Error type: {type(e).__name__}"
            )


# ── 测试：顶层共享文件存在性 ─────────────────────────────

def test_top_level_dws_run_py_exists():
    """测试：顶层 dws-run.py 文件存在"""
    dws_run_py = SKILLS_DIR / "dws-run.py"
    assert dws_run_py.exists(), f"dws-run.py not found in {SKILLS_DIR}"
    assert dws_run_py.is_file(), f"dws-run.py exists but is not a file in {SKILLS_DIR}"


def test_top_level_shared_directory_exists():
    """测试：顶层 shared/ 目录存在"""
    shared_dir = SKILLS_DIR / "shared"
    assert shared_dir.exists(), f"shared/ directory not found in {SKILLS_DIR}"
    assert shared_dir.is_dir(), f"shared/ exists but is not a directory in {SKILLS_DIR}"


def test_shared_has_run_py():
    """测试：shared/ 目录有 run.py 文件"""
    shared_dir = SKILLS_DIR / "shared"
    shared_run_py = shared_dir / "run.py"
    assert shared_run_py.exists(), f"run.py not found in {shared_dir}"
    assert shared_run_py.is_file(), f"run.py exists but is not a file in {shared_dir}"


# ── 测试：shared/ run.py 语法正确 ─────────────────────────

def test_shared_run_py_is_valid_python():
    """测试：shared/run.py 是有效的 Python 文件"""
    shared_dir = SKILLS_DIR / "shared"
    shared_run_py = shared_dir / "run.py"
    try:
        compile(shared_run_py.read_text(encoding="utf-8"), str(shared_run_py), "exec")
    except SyntaxError as e:
        pytest.fail(f"shared/run.py has syntax error: {e}")


# ── 测试：dws-run.py 语法正确 ─────────────────────────────

def test_dws_run_py_is_valid_python():
    """测试：dws-run.py 是有效的 Python 文件"""
    dws_run_py = SKILLS_DIR / "dws-run.py"
    try:
        compile(dws_run_py.read_text(encoding="utf-8"), str(dws_run_py), "exec")
    except SyntaxError as e:
        pytest.fail(f"dws-run.py has syntax error: {e}")


# ── 测试：skill 目录完整性汇总 ─────────────────────────────

def test_total_skill_count():
    """测试：skills 目录中正好有 6 个 skill 目录（排除 shared 和文件）"""
    entries = list(SKILLS_DIR.iterdir())
    skill_dirs = [e for e in entries if e.is_dir() and not e.name.startswith(".")]

    # 排除 shared 目录
    skill_dirs = [d for d in skill_dirs if d.name != "shared"]

    assert len(skill_dirs) == 6, \
        f"Expected 6 skill directories, found {len(skill_dirs)}. Skills: {[d.name for d in skill_dirs]}"

    # 验证所有预期的 skill 都存在
    skill_names = {d.name for d in skill_dirs}
    expected_names = set(ALL_SKILLS)
    missing = expected_names - skill_names
    extra = skill_names - expected_names

    assert not missing, f"Missing expected skills: {missing}"
    assert not extra, f"Unexpected skills found: {extra}"


# ── 测试：SKILL.md 必要内容 ───────────────────────────────

def test_skill_md_has_basic_sections(skill_dir: Path):
    """测试：SKILL.md 包含基本的 Markdown 章节（至少有二级标题）"""
    skill_md = skill_dir / "SKILL.md"
    content = skill_md.read_text(encoding="utf-8")

    # 检查是否有 ## 二级标题（常见章节标题）
    has_h2 = "## " in content
    assert has_h2, f"SKILL.md should have at least one ## heading in {skill_dir}"
