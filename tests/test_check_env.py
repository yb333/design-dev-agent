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


# ---------------------------------------------------------------------------
# 接口 canary / 双源混装检测（2026-11-05 内网实报：ut_opt↔run_ut 漂移致 UT 失败）
# ---------------------------------------------------------------------------
import sys as _sys
for _d in ("new-pipe/scripts", "design-dev-shared/scripts"):
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / _d))
import check_env  # noqa: E402

REPO2 = Path(__file__).resolve().parent.parent


def _mini_tree(root: Path, gut_run_ut: bool) -> Path:
    """最小技能树：shared+opt-pipe 整目录真件（run_ut 可选掏空=模拟新旧混装）。"""
    import shutil
    sk = root / "skills"
    (sk / "new-pipe").mkdir(parents=True)
    (sk / "new-pipe" / "SKILL.md").write_text("x", encoding="utf-8")
    shutil.copytree(REPO2 / "skills" / "design-dev-shared", sk / "design-dev-shared",
                    ignore=shutil.ignore_patterns("__pycache__"))
    if gut_run_ut:
        (sk / "design-dev-shared" / "scripts" / "run_ut.py").write_text(
            "def wrap_write(): pass\n", encoding="utf-8")
    for d in ("dws-design/scripts", "dws-coding/scripts"):
        (sk / d).mkdir(parents=True)
    (sk / "dws-design" / "scripts" / "assemble_ts.py").write_text("x=1", encoding="utf-8")
    (sk / "dws-coding" / "scripts" / "slice_ts.py").write_text("x=1", encoding="utf-8")
    shutil.copytree(REPO2 / "skills" / "opt-pipe", sk / "opt-pipe",
                    ignore=shutil.ignore_patterns("__pycache__"))
    return root


class TestInterfaceCanary:
    def test_mixed_tree_caught_at_step0(self, tmp_path, monkeypatch):
        """旧 run_ut（缺符号）+ 新 ut_opt 混装 → canary 在步骤 0 报清（非跑到 UT 才爆）。"""
        monkeypatch.setattr("check_env.Path.home", lambda: tmp_path / "home")
        tree = _mini_tree(tmp_path, gut_run_ut=True)
        problems = check_env.check(str(tree / "skills"))
        assert any("接口 canary" in p and "run_ut" in p for p in problems), problems

    def test_broken_ut_opt_caught_via_subprocess(self, tmp_path, monkeypatch):
        """opt-pipe/ut_opt 顶层 import 炸 → 子进程探测报清（pipe 间禁互 import 的合规形态）。"""
        monkeypatch.setattr("check_env.Path.home", lambda: tmp_path / "home")
        tree = _mini_tree(tmp_path, gut_run_ut=False)
        uo = tree / "skills" / "opt-pipe" / "scripts" / "ut_opt.py"
        uo.write_text("import sys\nsys.path.insert(0, r'%s')\nfrom run_ut import not_exist\n"
                      % (tree / "skills" / "design-dev-shared" / "scripts"), encoding="utf-8")
        problems = check_env.check(str(tree / "skills"))
        assert any("接口 canary" in p and "ut_opt" in p for p in problems), problems

    def test_consistent_tree_passes_canary(self, tmp_path, monkeypatch):
        monkeypatch.setattr("check_env.Path.home", lambda: tmp_path / "home")
        tree = _mini_tree(tmp_path, gut_run_ut=False)
        problems = [p for p in check_env.check(str(tree / "skills"))
                    if "接口 canary" in p]
        assert problems == []


class TestDualSourceDetection:
    def test_dual_installation_flagged(self, tmp_path, monkeypatch):
        """同名 skill 同时在项目 .opencode/skills 与全局 ~/.config → 双源报错。"""
        for side in (".opencode/skills/opt-pipe", "home/.config/opencode/skills/opt-pipe"):
            d = tmp_path / side
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text("x", encoding="utf-8")
        monkeypatch.setattr("check_env.Path.home", lambda: tmp_path / "home")
        monkeypatch.setattr("check_env.Path.cwd", lambda: tmp_path)
        problems = check_env.check("")
        assert any("双源混装" in p for p in problems), problems
