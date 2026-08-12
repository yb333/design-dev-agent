"""集中 config 文件路径解析（所有 skill 脚本统一调这里）。

config 统一放 ~/.config/opencode/_references/rules/dws-design-dev/，
与其他项目隔离（rules/ 是大项目共建目录，我们在其下开自己的文件夹）。

改基址只动这里的 config_dir()，所有脚本自动跟进——避免路径散落各处漂移。
"""
from pathlib import Path

# rules/ 下我们的文件夹名（跟 skill 命名一致）
RULES_DIR_NAME = "dws-design-dev"


def config_dir() -> Path:
    """我们的 config 根目录：~/.config/opencode/_references/rules/dws-design-dev/"""
    return Path.home() / ".config" / "opencode" / "_references" / "rules" / RULES_DIR_NAME


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


def resolve_appid(schema: str, config_path: str = "") -> str:
    """按 schema 查 appid（schema_apps.json 的标准源）。

    查找优先级：schema_mappings[schema].appid → default.appid → 空串。
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
    mappings = data.get("schema_mappings", {}) or {}
    if schema in mappings and isinstance(mappings[schema], dict):
        aid = (mappings[schema].get("appid") or "").strip()
        if aid:
            return aid
    default = data.get("default", {}) or {}
    return (default.get("appid") or "").strip()
