"""资产名归一口径（唯一源）——norm_asset。

v1 契约校验器已随 v1 入料路径退役（2026-11-04 一波换彻底）；本模块仅存
norm_asset（I/F 镜像归一资产名——audit_ingest/assemble_ts_baseline/
preprocess_opt 多消费方），职责单一不再挂契约名。
"""
from pathlib import Path
import json
from typing import Dict, List, Optional


def norm_asset(name: str) -> str:
    """资产名镜像归一（资产对账口径，唯一源——镜像语义只在 _f↔_i 之间，用户裁定）：
    剥 schema 前缀 + 去 _f/_i 尾（I 视图与 F 表互为镜像）。**_d 不剥**——dwb 层表的 _d
    是层命名不是镜像尾缀（dwb_cust_asset_d 的资产名就是原名，它的镜像写法不存在）。"""
    n = (name or "").strip()
    if "." in n:
        n = n.rsplit(".", 1)[-1]
    import re as _re
    return _re.sub(r"_[fi]$", "", n.lower())


