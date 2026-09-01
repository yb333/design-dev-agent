"""check_env 探针测试：dws-engineer 步骤 0 的环境自检（安装指纹/关键文件/python 版本）。"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "skills" / "new-pipe" / "scripts"))

from check_env import check, check_requirements


def test_local_repo_layout_passes():
    """本地仓布局（--skill-root 指向仓内 skills）：文件齐全 → 无问题。"""
    assert check(str(REPO / "skills")) == []


def test_missing_layout_reported(tmp_path):
    """空目录当 skills 根：缺 SKILL/管线脚本/agent/指纹 → 逐项报出。"""
    problems = check(str(tmp_path))
    assert any("缺文件" in p and "SKILL.md" in p for p in problems)
    assert any("preprocess.py" in p for p in problems)
    assert any("dws-engineer.md" in p for p in problems)
    assert any("_install_meta.json" in p for p in problems)


def test_stale_repo_meta_flagged(tmp_path, monkeypatch):
    """仓布局下安装指纹与当前 commit 不一致 → 报过时（重跑 install 指引）。"""
    skills_root = tmp_path / "skills"
    for rel in ["new-pipe/SKILL.md",
                "design-dev-shared/scripts/preprocess.py",
                "dws-design/scripts/assemble_ts.py",
                "dws-coding/scripts/slice_ts.py"]:
        f = skills_root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x", encoding="utf-8")
    (tmp_path / "agents" / "dws-engineer.md").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "agents" / "dws-engineer.md").write_text("x", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / "_install_meta.json").write_text(
        '{"commit": "oldone", "install_scope": "repo", "installed_at": "2026-08-01T00:00:00"}',
        encoding="utf-8")
    monkeypatch.setattr("check_env._git_commit", lambda root: "newone")
    problems = check(str(skills_root))
    assert any("安装指纹过时" in p for p in problems)


class TestCheckRequirements:
    """运行时依赖对账（check_requirements）：当前解释器逐包查 requirements 文本。"""

    def test_satisfied_requirement_passes(self):
        assert check_requirements("pytest>=1.0\n# 注释行跳过\n\n") == []

    def test_version_below_floor_reported_with_fix_command(self):
        """版本不满足（用不可能的高版本制造）→ problem 带已装版本与修复命令。"""
        problems = check_requirements("pytest>=999.0")
        assert len(problems) == 1 and "pytest" in problems[0] and "pip install --upgrade pytest" in problems[0]

    def test_missing_package_reported(self):
        problems = check_requirements("definitely-not-a-dist-xyz>=1.0")
        assert len(problems) == 1 and "缺依赖包" in problems[0] and "definitely-not-a-dist-xyz" in problems[0]

    def test_unknown_constraint_form_skipped(self):
        """非 >= 约束形态不判（宁放过——requirements 现状全为 >=）。"""
        assert check_requirements("pytest~=9.0") == []

    def test_real_repo_requirements_all_satisfied(self):
        """本机全量对账（开发机装了 requirements 全家——探针对真解释器零歧义）。"""
        req = (REPO / "requirements.txt").read_text(encoding="utf-8")
        assert check_requirements(req) == []
