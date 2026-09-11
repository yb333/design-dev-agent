"""switch_team_branch 切分支的功能回归（本地临时 git 仓库，零网络）。

复现内网实报 bug：单分支克隆（fetch refspec 只有 master）下切其他分支，
裸 fetch origin 拉不到该分支、origin/<分支> 跟踪引用也建不出来，
checkout 报 pathspec did not match any file known to git——远端明明有。
"""
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import sync_to_team  # noqa: E402
from sync_to_team import build_parser, execute_action, switch_team_branch  # noqa: E402


def git(*args, cwd):
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )


def make_repos(tmp_path: Path, single_branch: bool):
    """origin（master + topic 两分支）+ team 克隆（可单分支）。返回 (team, origin)。"""
    origin = tmp_path / "origin"
    origin.mkdir()
    assert git("init", "-q", "-b", "master", cwd=origin).returncode == 0
    (origin / "f.txt").write_text("master", encoding="utf-8")
    git("add", "-A", cwd=origin)
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "m1", cwd=origin)
    git("checkout", "-qb", "topic", cwd=origin)
    (origin / "f.txt").write_text("topic", encoding="utf-8")
    git("add", "-A", cwd=origin)
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "t1", cwd=origin)
    git("checkout", "-q", "master", cwd=origin)

    team = tmp_path / "team"
    clone_args = ["clone", "-q"]
    if single_branch:
        clone_args += ["--single-branch", "-b", "master"]
    assert git(*clone_args, str(origin), str(team), cwd=tmp_path).returncode == 0
    return team, origin


def current_branch(repo: Path) -> str:
    r = git("symbolic-ref", "--short", "HEAD", cwd=repo)
    return r.stdout.strip()


def test_switch_single_branch_clone(tmp_path):
    """本次 bug 的回归：单分支克隆切 refspec 外的远端分支。"""
    team, origin = make_repos(tmp_path, single_branch=True)
    # 前置确认：本地确实不知道 topic（旧实现在这里必失败）
    r = git("branch", "-r", cwd=team)
    assert "origin/topic" not in r.stdout
    switch_team_branch(team, "topic")
    assert current_branch(team) == "topic"
    # 建分支起点 = 远端 topic 的真实提交，不是陈旧引用
    assert (team / "f.txt").read_text(encoding="utf-8") == "topic"
    remote_topic = git("rev-parse", "topic", cwd=origin).stdout.strip()
    assert git("rev-parse", "topic", cwd=team).stdout.strip() == remote_topic


def test_switch_normal_clone(tmp_path):
    """普通克隆切远端已有分支（DWIM 自动建跟踪分支路径）。"""
    team, _ = make_repos(tmp_path, single_branch=False)
    switch_team_branch(team, "topic")
    assert current_branch(team) == "topic"
    assert (team / "f.txt").read_text(encoding="utf-8") == "topic"


def test_switch_back_to_existing_local_branch(tmp_path):
    """切回本地已有分支（topic → master）。"""
    team, _ = make_repos(tmp_path, single_branch=False)
    switch_team_branch(team, "topic")
    switch_team_branch(team, "master")
    assert current_branch(team) == "master"


def test_switch_local_only_branch_allowed(tmp_path):
    """本地有、远端没有的分支也能切（fetch 失败只 WARN 不挡本地切换）。"""
    team, _ = make_repos(tmp_path, single_branch=False)
    git("checkout", "-qb", "localonly", cwd=team)
    (team / "g.txt").write_text("local", encoding="utf-8")
    switch_team_branch(team, "master")  # 先离开
    switch_team_branch(team, "localonly")
    assert current_branch(team) == "localonly"


def test_switch_missing_branch_fails_loud(tmp_path):
    """本地远端都没有 → SystemExit，报错指向两处都没有。"""
    team, _ = make_repos(tmp_path, single_branch=False)
    with pytest.raises(SystemExit):
        switch_team_branch(team, "nope")


def test_switch_action_is_switch_only(tmp_path):
    """--switch 动作只切换：不 mirror 不提交不推送（旧版切完直接串同步）。"""
    team, _ = make_repos(tmp_path, single_branch=True)
    cfg_file = tmp_path / "sync.conf"
    args = build_parser().parse_args(["--switch", "topic", str(team)])
    assert execute_action(args, config_path=cfg_file) == 0
    assert current_branch(team) == "topic"
    # 没串同步的证明：零领先提交（HEAD 正好在刚 fetch 的远端尖端）、无 .opencode 镜像
    assert git("rev-list", "--count", "FETCH_HEAD..HEAD", cwd=team).stdout.strip() == "0"
    assert not (team / ".opencode").exists()
    # 配置已记住新分支（后续同步/拉取按它走）
    conf = cfg_file.read_text(encoding="utf-8")
    assert "TEAM_BRANCH=topic" in conf
    assert f"TEAM_REPO={team.resolve()}" in conf


def test_menu_loop_switch_then_back_to_menu(tmp_path, monkeypatch):
    """菜单 [3] 切完回菜单（不自动同步），再选 [0] 才退出。"""
    home = tmp_path / "home"
    home.mkdir()
    repos = tmp_path / "repos"
    repos.mkdir()
    team, _ = make_repos(repos, single_branch=True)
    (home / ".design-dev-agent-sync.conf").write_text(
        f"TEAM_REPO={team.resolve()}\nSRC_BRANCH=main\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(sys, "argv", ["sync_to_team.py", "--menu"])
    answers = iter(["3", "topic", "0"])  # 切分支 → 分支名 → 回菜单后退出
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert sync_to_team.main() == 0
    assert current_branch(team) == "topic"
    assert not (team / ".opencode").exists()  # 回菜单≠偷偷同步
