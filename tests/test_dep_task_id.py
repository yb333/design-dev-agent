"""depTaskId 三级取值器测试（显式表 > 缓存 > 内网脚本；不碰内网——假执行器注入）。"""
import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from dep_task_id import resolve_dep_task_id, dep_id_key

LTS = {
    "dep_task_ids": {"edw_pro|ITEM|GRP|TASK": "11111"},
    "dep_id_resolver": {
        "script": "q.py",
        "cmd_template": "python {script} --cluster {cluster} --item {item} --group {group} --task {task}",
        "output": "json",
        "field": "depTaskId",
        "timeout_sec": 5,
        "cache_ttl_days": 30,
    },
}


def fake_runner(stdout='{"depTaskId": "22222"}', code=0):
    """假脚本执行器：记录调用，返回约定输出。"""
    calls = []

    def run(cmd, timeout):
        calls.append((cmd, timeout))
        return code, stdout, ""

    run.calls = calls
    return run


def test_key_format():
    assert dep_id_key("edw_pro", "ITEM", "GRP", "TASK") == "edw_pro|ITEM|GRP|TASK"


def test_explicit_table_wins(tmp_path):
    """显式表优先（人工确认源），不调脚本不读缓存。"""
    runner = fake_runner()
    assert resolve_dep_task_id("edw_pro", "ITEM", "GRP", "TASK", LTS,
                               cache_path=str(tmp_path / "c.json"),
                               cmd_runner=runner) == "11111"
    assert runner.calls == []


def test_script_query_then_cache_hit(tmp_path):
    """未命中显式表 → 调脚本 → 写缓存；二次直接命中缓存不再调脚本。"""
    runner = fake_runner()
    cp = tmp_path / "c.json"
    id1 = resolve_dep_task_id("c1", "i", "g", "t", LTS, cache_path=str(cp), cmd_runner=runner)
    assert id1 == "22222"
    assert len(runner.calls) == 1
    assert "{script}" not in runner.calls[0][0]        # 模板占位符已替换
    assert "--cluster c1" in runner.calls[0][0] and "--task t" in runner.calls[0][0]

    id2 = resolve_dep_task_id("c1", "i", "g", "t", LTS, cache_path=str(cp), cmd_runner=runner)
    assert id2 == "22222"
    assert len(runner.calls) == 1                      # 缓存命中
    cache = json.loads(cp.read_text(encoding="utf-8"))
    assert cache["c1|i|g|t"]["id"] == "22222"
    assert cache["c1|i|g|t"]["cached_at"]


def test_cache_expired_requeries(tmp_path):
    """缓存超 TTL → 重新调脚本并刷新。"""
    runner = fake_runner()
    cp = tmp_path / "c.json"
    old = (datetime.now() - timedelta(days=31)).isoformat()
    cp.write_text(json.dumps({"c1|i|g|t": {"id": "99999", "cached_at": old}}), encoding="utf-8")
    got = resolve_dep_task_id("c1", "i", "g", "t", LTS, cache_path=str(cp), cmd_runner=runner)
    assert got == "22222"
    assert len(runner.calls) == 1


def test_cache_fresh_no_query(tmp_path):
    """TTL 内直接用缓存值（即使与脚本将返回的不同）。"""
    runner = fake_runner()
    cp = tmp_path / "c.json"
    fresh = (datetime.now() - timedelta(days=1)).isoformat()
    cp.write_text(json.dumps({"c1|i|g|t": {"id": "99999", "cached_at": fresh}}), encoding="utf-8")
    got = resolve_dep_task_id("c1", "i", "g", "t", LTS, cache_path=str(cp), cmd_runner=runner)
    assert got == "99999"
    assert runner.calls == []


def test_all_miss_fail_loud(tmp_path):
    """无显式表、无缓存、未配脚本（当前常态）→ fail-loud 指引人工填 config。"""
    with pytest.raises(RuntimeError, match="dep_task_ids.*填一次永续复用"):
        resolve_dep_task_id("c1", "i", "g", "t", {}, cache_path=str(tmp_path / "c.json"))


def test_script_failure_fail_loud(tmp_path):
    runner = fake_runner(code=1)
    with pytest.raises(RuntimeError, match="未返回有效 id"):
        resolve_dep_task_id("c1", "i", "g", "t", LTS, cache_path=str(tmp_path / "c.json"),
                            cmd_runner=runner)


def test_text_output_mode(tmp_path):
    """output=text：取首个非空行。"""
    lts = json.loads(json.dumps(LTS))
    lts["dep_id_resolver"]["output"] = "text"
    lts["dep_id_resolver"].pop("field", None)
    runner = fake_runner(stdout="\n  33333  \nother\n")
    got = resolve_dep_task_id("c1", "i", "g", "t", lts, cache_path=str(tmp_path / "c.json"),
                              cmd_runner=runner)
    assert got == "33333"


def test_timeout_fail_loud_with_manual_cmd(tmp_path):
    """脚本超时 → fail-loud，提示语带可手跑的完整命令。"""
    def slow(cmd, timeout):
        raise subprocess.TimeoutExpired(cmd, timeout)

    with pytest.raises(RuntimeError, match="python q.py --cluster c1"):
        resolve_dep_task_id("c1", "i", "g", "t", LTS, cache_path=str(tmp_path / "c.json"),
                            cmd_runner=slow)


def test_cache_write_failure_degrades(tmp_path):
    """config 目录只读（权限受限场景）→ 查询成功仍返回 id，缓存写失败静默跳过不炸导出。"""
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o555)
    try:
        got = resolve_dep_task_id("c1", "i", "g", "t", LTS, cache_path=str(ro / "c.json"),
                                  cmd_runner=fake_runner())
        assert got == "22222"
    finally:
        ro.chmod(0o755)


def test_project_layout_cache_follows_skill_root(tmp_path, monkeypatch):
    """项目制安装：缓存路径跟随 skill 所在的 config 根（__file__ 推算），不串到全局。

    把 dep_task_id.py 复制进模拟项目布局 <proj>/.opencode/skills/ 后 import，
    dep_id_cache_path() 必须落在 <proj>/.opencode/_references/rules/dws-design-dev/。
    （全局制同理——同一函数，config 跟 skill 走。）
    """
    import shutil
    import sys
    monkeypatch.delenv("DWS_RULES_DIR", raising=False)  # env 覆盖优先级最高，测试项目制解析须摘掉

    proj = tmp_path / "proj"
    skill_scripts = proj / ".opencode" / "skills" / "new-pipe" / "scripts"
    shared = proj / ".opencode" / "skills" / "design-dev-shared" / "scripts"
    rules = proj / ".opencode" / "_references" / "rules" / "dws-design-dev"
    skill_scripts.mkdir(parents=True)
    shared.mkdir(parents=True)
    rules.mkdir(parents=True)
    shutil.copy(Path(__import__("dep_task_id").__file__), skill_scripts / "dep_task_id.py")
    shutil.copy(Path(__import__("config_paths").__file__), shared / "config_paths.py")

    saved_cp = sys.modules.pop("config_paths", None)  # 强制从复制的 shared 重新加载
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "dep_task_id_proj", skill_scripts / "dep_task_id.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.dep_id_cache_path() == rules / "dep_task_id_cache.json"
    finally:
        if saved_cp is not None:
            sys.modules["config_paths"] = saved_cp


def test_diagnose_dump(tmp_path):
    """过程可视：脚本调用记录（命令+输出+解析结果）落盘 diagnose 目录。"""
    d = tmp_path / "diag"
    resolve_dep_task_id("c1", "i", "g", "t", LTS, cache_path=str(tmp_path / "c.json"),
                        diagnose_dir=str(d), cmd_runner=fake_runner())
    files = list(d.glob("dep_id_query_*.txt"))
    assert len(files) == 1
    content = files[0].read_text(encoding="utf-8")
    assert "cmd: python q.py --cluster c1 --item i --group g --task t" in content
    assert "parsed: 22222" in content
