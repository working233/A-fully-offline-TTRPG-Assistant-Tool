"""跑团（Campaign）服务：跑团的创建、切换、删除、导入导出。

每个跑团是一份自包含的目录，可整包复制、压缩迁移，不依赖任何外部数据库：
    campaigns/<slug-id>/
        campaign.json     元信息
        characters/       角色卡 JSON
        monsters/         怪物卡 JSON
        maps/             地图图片 + 网格/迷雾配置（<图名>.map.json）
        notes/            文本笔记（.txt / .md）
        stories/          结构化剧情（.json）
        logs/             跑团记录（.jsonl）
        assets/           杂项资源
"""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Any

from ..core.errors import Conflict, NotFound, ValidationFailed
from ..core.jsonio import read_json, write_json, now_iso, slugify, uid
from ..core.safety import ensure_inside, safe_name
from .base import BaseService
from .trash_service import TrashService

# 目录骨架版本：将来结构调整时用于自动迁移
FOLDER_VERSION = 1
SUBFOLDERS = ("characters", "monsters", "maps", "notes", "stories", "logs", "assets")
FOLDER_HINTS = {
    "characters": "角色卡（.json），一张卡一个文件",
    "monsters": "怪物卡 / NPC 卡（.json）",
    "maps": "地图图片及其同名 .map.json（网格、迷雾、光源配置）",
    "notes": "文本笔记（.txt / .md）",
    "stories": "结构化剧情（.json），支持分支与条件跳转",
    "logs": "跑团记录（.jsonl 追加写入，一行一条）",
    "assets": "立绘、音频等杂项资源",
}


class CampaignService(BaseService):
    def __init__(self, paths=None, bus=None, trash: TrashService | None = None) -> None:
        super().__init__(paths, bus)
        self.trash = trash or TrashService(paths, bus)

    # ------------------------------------------------------------ 全局设置
    def _settings(self) -> dict:
        return read_json(self.paths.settings_file, {"active_campaign": "", "version": 1}) or {}

    def _save_settings(self, data: dict) -> None:
        write_json(self.paths.settings_file, data)

    def active_id(self) -> str:
        return self._settings().get("active_campaign", "") or ""

    def list(self) -> list[dict]:
        root = self.paths.campaigns
        if not root.exists():
            return []
        out = []
        active = self.active_id()
        for d in sorted(root.iterdir()):
            if not d.is_dir() or d.name.startswith("_"):
                continue
            meta = read_json(d / "campaign.json", {}) or {}
            if not meta:
                continue
            out.append({**meta, "is_active": meta.get("id") == active})
        return out

    def get(self, campaign_id: str) -> dict:
        meta = read_json(self.campaign_dir(campaign_id) / "campaign.json")
        if not meta:
            raise NotFound(f"跑团不存在：{campaign_id}")
        meta["counts"] = self.summary_counts(campaign_id)
        return meta

    def campaign_dir(self, campaign_id: str) -> Path:
        return ensure_inside(self.paths.campaigns, self.paths.campaigns / safe_name(campaign_id))

    def resolve(self, campaign_id: str | None = None) -> Path:
        cid = campaign_id or self.active_id()
        if not cid:
            raise ValidationFailed("尚未选择跑团，请先创建或切换跑团")
        d = self.campaign_dir(cid)
        if not d.exists():
            raise NotFound(f"跑团不存在：{cid}")
        return d

    def summary_counts(self, campaign_id: str) -> dict:
        d = self.campaign_dir(campaign_id)
        return {
            "characters": _count(d / "characters", "*.json"),
            "monsters": _count(d / "monsters", "*.json"),
            "maps": _count(d / "maps", "*.map.json"),
            "notes": _count(d / "notes", "*.txt"),
            "stories": _count(d / "stories", "*.json"),
            "log_lines": _log_lines(d / "logs"),
        }

    # ------------------------------------------------------------ 生命周期
    def create(self, name: str, system: str = "DND 5e", description: str = "",
               dm: str = "", *, template: str = "standard") -> dict:
        name = (name or "").strip()
        if not name:
            raise ValidationFailed("跑团名称不能为空")
        slug = slugify(name, fallback="campaign")
        candidate = slug
        n = 2
        while (self.paths.campaigns / candidate).exists():
            candidate = f"{slug}-{n}"
            n += 1
        campaign_id = candidate
        root = self.paths.campaigns / campaign_id
        root.mkdir(parents=True, exist_ok=True)

        for folder in SUBFOLDERS:
            sub = root / folder
            sub.mkdir(parents=True, exist_ok=True)
            (sub / "_README.txt").write_text(
                f"{FOLDER_HINTS[folder]}\n", encoding="utf-8")

        meta = {
            "id": campaign_id,
            "name": name,
            "system": system,
            "description": description,
            "dm": dm,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "folder_version": FOLDER_VERSION,
            "players": [],
            "settings": {"dice_history_limit": 500, "auto_backup": True},
        }
        write_json(root / "campaign.json", meta)
        self.set_active(campaign_id)
        self.log(f"创建跑团：{name}", campaign_id=campaign_id)
        self.emit("campaign/created", meta)
        return meta

    def update(self, campaign_id: str, patch: dict) -> dict:
        root = self.resolve(campaign_id)
        meta = read_json(root / "campaign.json", {})
        if not meta:
            raise NotFound(f"跑团不存在：{campaign_id}")
        protected = {"id", "created_at"}
        for k, v in (patch or {}).items():
            if k in protected:
                continue
            meta[k] = v
        meta["updated_at"] = now_iso()
        write_json(root / "campaign.json", meta)
        self.emit("campaign/updated", meta)
        return meta

    def set_active(self, campaign_id: str) -> dict:
        if not (self.paths.campaigns / safe_name(campaign_id)).exists():
            raise NotFound(f"跑团不存在：{campaign_id}")
        data = self._settings()
        data["active_campaign"] = campaign_id
        self._save_settings(data)
        self.emit("campaign/activated", {"id": campaign_id})
        return {"active_campaign": campaign_id}

    def delete(self, campaign_id: str) -> dict:
        root = self.resolve(campaign_id)
        meta = read_json(root / "campaign.json", {}) or {}
        result = self.trash.move_to_trash(root, campaign_id=campaign_id, kind="campaign",
                                          origin=meta.get("name", campaign_id))
        settings = self._settings()
        if settings.get("active_campaign") == campaign_id:
            settings["active_campaign"] = ""
            self._save_settings(settings)
        self.emit("campaign/deleted", {"id": campaign_id})
        return result

    # ------------------------------------------------------------ 迁移
    def export(self, campaign_id: str, dest: Path | str | None = None) -> Path:
        root = self.resolve(campaign_id)
        dest = Path(dest) if dest else self.paths.backup_dir() / f"{campaign_id}-export-{uid()}.zip"
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
            for f in root.rglob("*"):
                if f.is_file():
                    z.write(f, f.relative_to(root.parent))
        self.emit("campaign/exported", {"path": str(dest)})
        return dest

    def import_from_archive(self, archive: Path | str, *, overwrite: bool = False) -> dict:
        archive = Path(archive)
        if not archive.exists():
            raise NotFound(f"压缩包不存在：{archive}")
        with zipfile.ZipFile(archive) as z:
            top = {Path(n).parts[0] for n in z.namelist() if n.strip()}
            if len(top) != 1:
                raise ValidationFailed("压缩包结构异常：应只包含一个跑团根目录")
            target_name = top.pop()
            target = ensure_inside(self.paths.campaigns, self.paths.campaigns / target_name)
            if target.exists() and not overwrite:
                raise Conflict(f"已存在同名跑团：{target_name}，请先删除或使用 overwrite=True")
            z.extractall(self.paths.campaigns)
        meta = read_json(target / "campaign.json", {})
        self.emit("campaign/imported", meta or {"id": target_name})
        return meta or {"id": target_name}


def _count(folder: Path, pattern: str) -> int:
    return len(list(folder.glob(pattern))) if folder.exists() else 0


def _log_lines(folder: Path) -> int:
    if not folder.exists():
        return 0
    lines = 0
    for f in folder.glob("*.jsonl"):
        with open(f, "r", encoding="utf-8", errors="replace") as fh:
            lines += sum(1 for _ in fh)
    return lines
