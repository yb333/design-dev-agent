"""
pytest 共享 fixtures 和路径配置。

将 skill references 目录加入 sys.path，使测试可以直接 import 被测模块。
"""
import sys
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent

# 将各 skill 的 references 目录加入 Python 路径
SKILL_PATHS = [
    PROJECT_ROOT / ".opencode" / "skills" / "dws-pipeline-coder" / "references",
    PROJECT_ROOT / ".opencode" / "skills" / "dws-pipeline-designer" / "references",
    PROJECT_ROOT / ".opencode" / "skills" / "dws-pipeline-tester" / "references",
    PROJECT_ROOT / ".opencode" / "skills" / "dws-pipeline-exporter" / "references",
    PROJECT_ROOT / ".opencode" / "skills" / "dws-pipeline-reviewer" / "references",
    PROJECT_ROOT / ".opencode" / "skills" / "dws-pipeline-code-reviewer" / "references",
]

for p in SKILL_PATHS:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


# ── Fixtures ──────────────────────────────────────────────

import pytest


@pytest.fixture
def fixtures_dir() -> Path:
    """返回测试数据 fixtures 目录。"""
    return PROJECT_ROOT / "tests" / "fixtures"


@pytest.fixture
def sample_ddl_sql(fixtures_dir: Path) -> str:
    """返回示例 DDL SQL 内容。"""
    return (fixtures_dir / "sample_ddl.sql").read_text(encoding="utf-8")


@pytest.fixture
def sample_etl_sql(fixtures_dir: Path) -> str:
    """返回示例 ETL SQL 内容。"""
    return (fixtures_dir / "sample_etl.sql").read_text(encoding="utf-8")


@pytest.fixture
def sample_mapping_json(fixtures_dir: Path) -> dict:
    """返回示例 mapping.json 字典。"""
    import json
    with open(fixtures_dir / "sample_mapping.json", "r", encoding="utf-8") as f:
        return json.load(f)
