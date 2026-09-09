#!/usr/bin/env python3
"""depTaskId 取值器（跨集群 tskdep 依赖的平台任务 id，task 级粒度）。

id 定位：键=「集群|调度组|任务组|任务名」四段（2026-09-09 用户终稿：id 与 task 同粒度）。

取值顺序（docs/platform/lts-制品生成设计.md §4.2/§七）：
  1. config lts.dep_task_ids 显式表（人上平台查得后填入——**当前唯一常态来源**；
     人工逐条查或请平台导全量表灌入，同一结构。id 稳定，填一次永续复用）
  2. 缓存（config 目录 dep_task_id_cache.json，TTL 30 天——仅脚本来源启用后才会写入）
  3. 脚本现场查询（lts.dep_id_resolver 契约——**预留口子，默认关闭**（script 空）：
     内网脚本仅开发环境可跑而制品对齐生产，生产 id 拿不到（2026-09-09 定调搁置）；
     哪天平台开放接口，配 script 即启用，代码零改动）

全落空 → RuntimeError（带键 + 补填指引）。脚本调用记录落盘 diagnose_dir（过程可视）。

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


def dep_id_key(cluster: str, item_name: str, task_group: str, task: str) -> str:
    """缓存/显式表的键：集群|调度组|任务组|任务名（四段，task 级粒度——用户终稿）。

    depTaskId 与被依赖任务同粒度（upstream.job 只是引用名/显示名，不参与 id 定位）。
    """
    return f"{cluster}|{item_name}|{task_group}|{task}"


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


def resolve_dep_task_id(cluster: str, item_name: str, task_group: str, task: str,
                        lts_config: dict, cache_path: str = "", diagnose_dir: str = "",
                        now=None, cmd_runner=None) -> str:
    """三级取值，返回 depTaskId；全落空 raise RuntimeError。

    lts_config: platform_config 的 lts 块（含 dep_task_ids / dep_id_resolver）。
    task: 被依赖的远端任务名（depTaskName，路径末段）——id 与 task 同粒度。
    cache_path/diagnose_dir: 测试与调用方可注入；cache 缺省 config 目录。
    now/cmd_runner: 测试注入（时钟 / 假脚本执行器）。
    """
    key = dep_id_key(cluster, item_name, task_group, task)
    fail_hint = (f"depTaskId 未取得（config 显式表无此键）。键=\"{key}\"。\n"
                 f"处理：上平台查得该任务的 id 后，填入 platform_config "
                 f"lts.dep_task_ids（键 \"{key}\"，值=id）——id 稳定，填一次永续复用。")

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

    # --- 3. 脚本查询（预留口子，script 未配置 = 关闭，直接走失败提示） ---
    script = (resolver.get("script") or "").strip()
    if not script:
        raise RuntimeError(fail_hint)

    template = resolver.get("cmd_template") or ""
    cmd = (template
           .replace("{script}", script)
           .replace("{cluster}", cluster)
           .replace("{item}", item_name)
           .replace("{group}", task_group)
           .replace("{task}", task))
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
                           f"可手工查得后填入 lts.dep_task_ids：\n  （参考命令）{cmd}")
    diag += [f"returncode: {code}", f"stdout: {out}", f"stderr: {err}"]

    dep_id = ""
    if code == 0:
        dep_id = _parse_output(out, resolver)
    _dump_diagnose(diagnose_dir, key, diag + [f"parsed: {dep_id or '(空)'}"])

    if not dep_id:
        raise RuntimeError(f"depTaskId 查询脚本未返回有效 id（returncode={code}）。键={key}。\n"
                           f"可手工查得后填入 lts.dep_task_ids：\n  （参考命令）{cmd}")

    cache[key] = {"id": dep_id, "cached_at": now.isoformat()}
    _write_cache(cache_file, cache)
    return dep_id
