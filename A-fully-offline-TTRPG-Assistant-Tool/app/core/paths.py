"""路径、目录根系与全局设置。

设计约束：
1. 所有持久化数据都必须落在 Paths.root 之下，任何越界访问都会被 core.safety 拦截；
2. root 可通过环境变量 TRPG_HOME 覆盖，便于单机多份实例或迁移到移动硬盘；
3. 这里不依赖任何第三方包，仅使用 Python 标准库。
"""
from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "TRPG-Local-Assistant"
APP_VERSION = "0.1.0"

REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = REPO_ROOT / "web"


def default_root() -> Path:
    env = os.environ.get("TRPG_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return (Path.home() / APP_NAME).resolve()


class Paths:
    """目录根系。所有 Service 通过构造注入获得它，便于测试时指向临时目录。"""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root).expanduser().resolve() if root else default_root()
        self.data = self.root / "data"
        self.campaigns = self.data / "campaigns"
        self.trash = self.data / "_trash"
        self.backups = self.data / "_backups"
        self.settings_file = self.root / "settings.json"
        self.web = WEB_DIR

    def ensure(self) -> "Paths":
        for d in (self.root, self.data, self.campaigns, self.trash, self.backups):
            d.mkdir(parents=True, exist_ok=True)
        return self

    def campaign_dir(self, campaign_id: str) -> Path:
        return self.campaigns / campaign_id

    def trash_dir(self) -> Path:
        return self.trash

    def backup_dir(self) -> Path:
        return self.backups

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"<Paths root={self.root}>"


# 进程级默认实例；测试或 CLI 可替换为临时目录
paths = Paths()
