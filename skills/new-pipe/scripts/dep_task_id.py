#!/usr/bin/env python3
"""depTaskId 三级取值器（跨集群 tskdep 依赖的平台任务组 id）。

取值顺序（docs/platform/lts-制品生成设计.md §4.2/§七）：
  1. config lts.dep_task_ids 显式表（人填，优先——语义=人工确认）
  2. 缓存（config 目录 dep_task_id_cache.json，TTL 默认 30 天）
  3. 内网脚本现场查询（lts.dep_id_resolver 契约：script/cmd_template/output/field/timeout_sec，
     脚本名称/调用方式/产出格式由我们定义，脚本本体在内网）

全落空 → RuntimeError（带三元组 + 可手跑命令）。脚本调用记录落盘 diagnose_dir（过程可视）。
平台侧该 id 按「生产集群, itemName, taskGroupName」三元组固定（451 样本规律），故缓存安全。

单测：注入 cmd_runner 假执行器 + cache_path 临时文件，不碰内网。
"""
import json
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

# shared 公共库自洽引用（skill 脚本标准 bootstrap）
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "design-dev-shared" / "scripts"))

from config_paths import dep_id_cache_path


def dep_id_key(cluster: str, item_name: str, task_group: str, task: str, job: str) -> str:
    """缓存/显式表的键：集群|调度组|任务组|任务名|job名（五段）。

    depTaskId 粒度=job 级（用户定调 2026-09-09：跨集群依赖挂远端任务下的具体 job，
    id 是那个 job 的平台 id——路径定位任务，job 名唯一定位依赖对象）。键含 job 名才唯一。
    """
    return f"{cluster}|{item_name}|{task_group}|{task}|{job}"


def _read_cache(cache_file: Path) -> dict:
    if not cache_file.exists():
        return {}
    try:
        return json.loads(cache_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_cache(cache_file: Path, cache: dict):
    """缓存写失败静默跳过（缓存是优化不是数据——config 目录只读/权限受限时降级为每次现查）。

    tmp+rename 原子写：并行会话同时刷新缓存不会写出半截 JSON。
    """
    tmp = None
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_file.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(cache_file)
    except Exception:
        try:
            if tmp is not None:
                tmp.unlink(missing_ok=True)
        except Exception:
            pass


def _run_script(cmd: str, timeout_sec: int):
    """真执行器：内网脚本调用。返回 (returncode, stdout, stderr)。"""
    proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout_sec)
    return proc.returncode, proc.stdout, proc.stderr


def _dump_diagnose(diagnose_dir: str, key: str, lines: list):
    """过程可视：脚本调用记录落盘（好坏都留），无 diagnose_dir 时跳过。"""
    if not diagnose_dir:
        return
    try:
        d = Path(diagnose_dir)
        d.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        (d / f"dep_id_query_{stamp}.txt").write_text(
            f"key: {key}\n" + "\n".join(lines) + "\n", encoding="utf-8")
    except Exception:
        pass  # 诊断落盘失败不阻断主流程


def _parse_output(stdout: str, resolver: dict):
    """按契约解析脚本产出：json 取 field 字段 / text 取首个非空行。"""
    output = (resolver.get("output") or "json").strip().lower()
    if output == "json":
        try:
            data = json.loads(stdout)
        except Exception:
            return ""
        return str(data.get(resolver.get("field", "depTaskId"), "") or "").strip()
    for line in stdout.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def resolve_dep_task_id(cluster: str, item_name: str, task_group: str, task: str, job: str,
                        lts_config: dict, cache_path: str = "", diagnose_dir: str = "",
                        now=None, cmd_runner=None) -> str:
    """三级取值，返回 depTaskId；全落空 raise RuntimeError。

    lts_config: platform_config 的 lts 块（含 dep_task_ids / dep_id_resolver）。
    task: 被依赖 job 所属的远端任务名（depTaskName，路径末段）。
    job: 被依赖的远端 job 名（depJobName/name/job名称 同值）——id 是 job 的 id，键必含。
    cache_path/diagnose_dir: 测试与调用方可注入；cache 缺省 config 目录。
    now/cmd_runner: 测试注入（时钟 / 假脚本执行器）。
    """
    key = dep_id_key(cluster, item_name, task_group, task, job)
    fail_hint = (f"depTaskId 未取得（显式表无、缓存无/过期）。键={key}。\n"
                 f"处理：platform_config lts.dep_task_ids 手工补填 "
                 f"(键 \"{key}\")，或配置 lts.dep_id_resolver 接内网查询脚本。")

    # --- 1. 显式表（人填，优先） ---
    explicit = (lts_config.get("dep_task_ids") or {}).get(key, "")
    if explicit:
        return str(explicit)

    resolver = lts_config.get("dep_id_resolver") or {}
    now = now or datetime.now()
    cache_file = Path(cache_path) if cache_path else dep_id_cache_path()
    cache = _read_cache(cache_file)
    entry = cache.get(key) or {}

    # --- 2. 缓存（TTL 内免重查；id 平台固定，过期重查只是保鲜） ---
    ttl = int(resolver.get("cache_ttl_days", 30))
    fresh = False
    cached_at = entry.get("cached_at", "")
    if cached_at and entry.get("id"):
        try:
            fresh = (now - datetime.fromisoformat(cached_at)) <= timedelta(days=ttl)
        except Exception:
            fresh = False
    if fresh:
        return str(entry["id"])

    # --- 3. 内网脚本（未配置 = 功能关闭，直接失败） ---
    script = (resolver.get("script") or "").strip()
    if not script:
        raise RuntimeError(fail_hint)

    template = resolver.get("cmd_template") or ""
    cmd = (template
           .replace("{script}", script)
           .replace("{cluster}", cluster)
           .replace("{item}", item_name)
           .replace("{group}", task_group)
           .replace("{task}", task)
           .replace("{job}", job))
    if "{script}" not in template:
        # 模板里没有 {script} 占位 = 配置不完整，按 fail-loud 处理不猜
        raise RuntimeError(f"dep_id_resolver.cmd_template 缺 {{script}} 占位符：{template!r}")

    runner = cmd_runner or _run_script
    timeout = int(resolver.get("timeout_sec", 30))
    diag = [f"cmd: {cmd}", f"timeout_sec: {timeout}"]
    try:
        code, out, err = runner(cmd, timeout)
    except subprocess.TimeoutExpired:
        _dump_diagnose(diagnose_dir, key, diag + ["result: TIMEOUT"])
        raise RuntimeError(f"depTaskId 查询脚本超时（>{timeout}s）。键={key}。\n"
                           f"可手工执行查得后填入 lts.dep_task_ids：\n  {cmd}")
    diag += [f"returncode: {code}", f"stdout: {out}", f"stderr: {err}"]

    dep_id = ""
    if code == 0:
        dep_id = _parse_output(out, resolver)
    _dump_diagnose(diagnose_dir, key, diag + [f"parsed: {dep_id or '(空)'}"])

    if not dep_id:
        raise RuntimeError(f"depTaskId 查询脚本未返回有效 id（returncode={code}）。键={key}。\n"
                           f"可手工执行查得后填入 lts.dep_task_ids：\n  {cmd}")

    cache[key] = {"id": dep_id, "cached_at": now.isoformat()}
    _write_cache(cache_file, cache)
    return dep_id
