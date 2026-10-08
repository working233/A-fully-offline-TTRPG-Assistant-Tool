"""备份服务：整包 zip 快照 + 轮转保留，用于跨设备迁移与误操作回滚。

策略：backup_all() 打包整个 data/campaigns；backup_campaign() 只打包单个跑团。
生成的文件名带 UTC 时间戳，按保留份数自动轮转。
"""
from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..core.errors import NotFound
from ..core.jsonio import read_json, write_json
from .base import BaseService
from .campaign_service import CampaignService

MANIFEST = "manifest.json"


class BackupService(BaseService):
    def __init__(self, paths=None, bus=None, campaigns: CampaignService | None = None,
                 keep: int = 10) -> None:
        super().__init__(paths, bus)
        self.campaigns = campaigns or CampaignService(paths, bus)
        self.keep = keep

    def _dir(self) -> Path:
        d = self.paths.backup_dir()
        d.mkdir(parents=True, exist_ok=True)
        return d

    def list(self) -> list[dict]:
        out = []
        for f in sorted(self._dir().glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True):
            size = f.stat().st_size
            meta: dict[str, Any] = {}
            try:
                with zipfile.ZipFile(f) as z:
                    if MANIFEST in z.namelist():
                        meta = json.loads(z.read(MANIFEST).decode("utf-8"))
            except zipfile.BadZipFile:
                pass
            out.append({"file": f.name, "size": size, "created_at": f.stat().st_mtime,
                        "scope": meta.get("scope", "unknown"), "campaign_id": meta.get("campaign_id", ""),
                        "app_version": meta.get("app_version", "")})
        return out

    def create(self, campaign_id: str | None = None, *, note: str = "") -> Path:
        from ..core.paths import APP_VERSION

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        if campaign_id:
            root = self.campaigns.resolve(campaign_id)
            base = root.parent
            name = f"campaign-{campaign_id}-{stamp}.zip"
            scope, cid = "campaign", campaign_id
        else:
            root = self.paths.campaigns
            base = root
            name = f"all-campaigns-{stamp}.zip"
            scope, cid = "all", ""

        dest = self._dir() / name
        files = [p for p in root.rglob("*") if p.is_file()] if root.exists() else []
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(MANIFEST, json.dumps({
                "scope": scope, "campaign_id": cid, "created_at": stamp,
                "note": note, "app_version": APP_VERSION, "files": len(files),
            }, ensure_ascii=False, indent=2))
            for f in files:
                z.write(f, f.relative_to(base))
        self.rotate()
        self.emit("backup/created", {"path": str(dest), "scope": scope})
        return dest

    def rotate(self) -> list[str]:
        files = sorted(self._dir().glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
        removed = []
        for f in files[self.keep:]:
            f.unlink(missing_ok=True)
            removed.append(f.name)
        return removed

    def restore(self, filename: str, *, overwrite: bool = False) -> dict:
        target = (self._dir() / filename).resolve()
        if not str(target).startswith(str(self._dir().resolve())) or not target.exists():
            raise NotFound(f"备份不存在：{filename}")
        return self.campaigns.import_from_archive(target, overwrite=overwrite)
