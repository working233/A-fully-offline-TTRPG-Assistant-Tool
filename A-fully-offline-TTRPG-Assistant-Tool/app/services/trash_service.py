"""回收站服务：所有删除均为「移动到隐藏回收站」，可恢复、可溯源。

回收站结构：
    data/_trash/<token>/            <- 被删对象的实际内容
    data/_trash/<token>.meta.json   <- 原始路径、删除时间、所属跑团
恢复时按 meta 原路放回；彻底删除二次确认后才物理删除。
"""
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..core.errors import NotFound, Conflict
from ..core.jsonio import read_json, write_json, uid, now_iso
from .base import BaseService


class TrashService(BaseService):
    META_SUFFIX = ".meta.json"

    def _meta_path(self, token: str) -> Path:
        return self.paths.trash_dir() / f"{token}{self.META_SUFFIX}"

    def _payload_path(self, token: str) -> Path:
        return self.paths.trash_dir() / token

    def move_to_trash(self, source: Path, *, origin: str, campaign_id: str = "",
                      kind: str = "file", extra: dict | None = None) -> dict:
        source = Path(source)
        if not source.exists():
            raise NotFound(f"要删除的目标不存在：{source}")
        trash = self.paths.trash_dir()
        trash.mkdir(parents=True, exist_ok=True)

        token = uid("t")
        payload = self._payload_path(token)
        payload.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(payload))

        meta = {
            "token": token,
            "original_path": str(source),
            "relative_path": self._relative(source),
            "campaign_id": campaign_id,
            "kind": kind,
            "deleted_at": now_iso(),
            "size": _dir_size(payload) if payload.is_dir() else payload.stat().st_size,
            **(extra or {}),
        }
        write_json(self._meta_path(token), meta)
        self.emit("trash/moved", meta)
        self.log(f"已移入回收站：{origin}", kind=kind, token=token)
        return meta

    def list(self) -> list[dict]:
        trash = self.paths.trash_dir()
        if not trash.exists():
            return []
        items = []
        for meta_file in sorted(trash.glob(f"*{self.META_SUFFIX}"), key=lambda p: p.stat().st_mtime, reverse=True):
            meta = read_json(meta_file, {})
            if meta:
                items.append({**meta, "restorable": not Path(meta.get("original_path", "")).exists()})
        return items

    def get(self, token: str) -> dict:
        meta = read_json(self._meta_path(token))
        if not meta:
            raise NotFound(f"回收站条目不存在：{token}")
        return meta

    def restore(self, token: str, *, target_name: str | None = None) -> dict:
        meta = self.get(token)
        original = Path(meta["original_path"])
        if target_name:
            original = original.with_name(target_name)
        if original.exists():
            raise Conflict(f"原位置已存在同名对象：{original}，请先重命名再恢复")
        original.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(self._payload_path(token)), str(original))
        self._meta_path(token).unlink(missing_ok=True)
        self.emit("trash/restored", {"token": token, "path": str(original)})
        return {"token": token, "restored_to": str(original)}

    def purge(self, token: str) -> dict:
        meta = self.get(token)
        path = self._payload_path(token)
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
        self._meta_path(token).unlink(missing_ok=True)
        self.emit("trash/purged", {"token": token})
        return {"token": token, "purged": meta.get("original_path")}

    def empty(self) -> dict:
        removed = 0
        for item in self.list():
            self.purge(item["token"])
            removed += 1
        return {"purged": removed}

    def auto_cleanup(self, keep_days: int = 30) -> int:
        """清理超过保留期的条目，避免回收站无限膨胀。"""
        now = datetime.now(timezone.utc)
        removed = 0
        for item in self.list():
            deleted = item.get("deleted_at", "")
            try:
                when = datetime.fromisoformat(deleted)
            except ValueError:
                continue
            age = (now - when).days
            if age >= keep_days:
                self.purge(item["token"])
                removed += 1
        return removed

    def _relative(self, path: Path) -> str:
        try:
            return str(Path(path).resolve().relative_to(self.paths.root))
        except ValueError:
            return str(path)


def _dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in Path(path).rglob("*") if f.is_file())
