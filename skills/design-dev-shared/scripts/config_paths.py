"""集中 config 文件路径解析（所有 skill 脚本统一调这里）。

config 跟随 skill 安装位置（用户级 ~/.config/opencode 或项目级 <proj>/.opencode），
落在 <opencode_root>/_references/rules/dws-design-dev/，与其他项目隔离。

定位策略（config_dir 优先用环境变量，否则从 opencode_root 推算）：
- 环境变量 DWS_RULES_DIR：直接指向 rules 目录（部署/CI/测试强制覆盖，不碰真实 config）
- opencode_root()：__file__ 推算（config 跟 skill 走）→ 全局 → 项目级 .opencode → 回全局

改基址只动这里，所有脚本自动跟进——避免路径散落各处漂移。
"""
import os
from pathlib import Path

# rules/ 下我们的文件夹名（跟 skill 命名一致）
RULES_DIR_NAME = "dws-design-dev"

# config 目录标记（探测 opencode 根用：根下有这个相对路径说明 config 装在这）
_RULES_MARKER = Path("_references") / "rules" / RULES_DIR_NAME


def opencode_root() -> Path:
    """定位 opencode 配置根（skill + config 共同的父目录）。

    优先级：
      1. ``__file__`` 推算：本文件在 <root>/skills/design-dev-shared/scripts/，
         parents[3] = <root>。该根下有 _references/rules/dws-design-dev/ → 命中
         （config 自动跟随 skill，用户级 / 项目级安装都自动对齐）
      2. 全局：~/.config/opencode（向后兼容老的纯全局安装）
      3. 项目级：cwd 向上找 .opencode（install.py --local 的落点）
      4. 全 miss：回全局路径（友好报错，不比固定 Path.home 差）

    幂等：纯路径推算 + exists 检查，无副作用，assemble_ts main 校验阶段重复调安全。
    """
    # 1. __file__ 推算（最可靠：脚本知道自己在哪，跟 skill 走）
    inferred = Path(__file__).resolve().parents[3]
    if (inferred / _RULES_MARKER).exists():
        return inferred
    # 2. 全局安装
    home = Path.home() / ".config" / "opencode"
    if (home / _RULES_MARKER).exists():
        return home
    # 3. 项目级安装：cwd 向上找 .opencode
    cwd = Path.cwd()
    for d in [cwd, *cwd.parents]:
        cand = d / ".opencode"
        if (cand / _RULES_MARKER).exists():
            return cand
    # 4. 全 miss：回全局（友好报错，保留旧行为）
    return home


def config_dir() -> Path:
    """我们的 config 根目录（db-sources / platform_config / schedule_config / schema_apps 所在）。

    优先用环境变量 DWS_RULES_DIR（直接指向 rules 目录，部署/CI/测试隔离用）；
    否则从 opencode_root() 推算 = <opencode_root>/_references/rules/dws-design-dev/。
    """
    env = os.environ.get("DWS_RULES_DIR")
    if env:
        return Path(env)
    return opencode_root() / "_references" / "rules" / RULES_DIR_NAME


def db_sources_path() -> Path:
    """db-sources.json（DB 连接配置，dws_db 用）"""
    return config_dir() / "db-sources.json"


def platform_config_path() -> Path:
    """platform_config.json（术加/LTS 部署配置，assemble_export 用；已不含 appid）"""
    return config_dir() / "platform_config.json"


def schedule_config_path() -> Path:
    """schedule_config.json（调度项目/任务组，assemble_ts 用）"""
    return config_dir() / "schedule_config.json"


def schema_apps_path() -> Path:
    """schema_apps.json（schema↔appid 标准源，Task 1）。deliver 目录层 + export job 参数都从这读。"""
    return config_dir() / "schema_apps.json"


def requirements_path() -> Path:
    """requirements.txt（check_env 依赖对账清单，与其他 config 同目录）。

    开关式：此文件存在 check_env 才做逐包对账，不存在静默跳过。自测由
    install.py 从仓根拷入；内网默认不放（环境依赖部署侧统一管），想开启
    查证放一个文件即开。
    """
    return config_dir() / "requirements.txt"


def resolve_appid(schema: str, config_path: str = "") -> str:
    """按 schema 反查所属 appid（schema_apps.json 标准源）。

    schema_apps.json 以 appid 打头：apps: appid → {schemas:[...]}（一个 appid 下多个 schema）。
    本函数扫描 apps，找到 schema 所属的 appid；找不到用 default_appid；都没有返回空串。
    config_path 不传则用 schema_apps_path()。文件不存在返回空串（不阻断，调用方决定）。
    """
    import json
    p = Path(config_path) if config_path else schema_apps_path()
    if not p.exists():
        return ""
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return ""
    schema = (schema or "").strip()
    apps = data.get("apps", {}) or {}
    for appid, info in apps.items():
        schemas = ((info or {}).get("schemas")) or []
        if schema in schemas:
            return appid
    return (data.get("default_appid") or "").strip()
