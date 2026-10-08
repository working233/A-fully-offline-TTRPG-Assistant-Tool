"""文件管理：跑团目录内的浏览、读写、重命名、删除（进回收站）、搜索、导入。

所有路径先过 safety.ensure_inside，杜绝 `../../` 越界。
"""
from __future__ import annotations

import base64
import shutil
from pathlib import Path
from typing import Any

from ..core.errors import Conflict, NotFound, ValidationFailed
from ..core.jsonio import MAX_FILE_BYTES, READ_SUFFIX, append_jsonl, read_json, read_jsonl, read_text, write_json, write_text
from ..core.safety import ensure_inside, safe_name
from .base import BaseService
from .campaign_service import CampaignService
from .trash_service import TrashService

TEXT_SUFFIX = {".json", ".txt", ".md", ".csv", ".dot", ".log", ".jsonl", ".yml", ".yaml"}
IMAGE_SUFFIX = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}


class FileManagerService(BaseService):
    def __init__(self, paths=None, bus=None, campaigns: CampaignService | None = None,
                 trash: TrashService | None = None) -> None:
        super().__init__(paths, bus)
        self.campaigns = campaigns or CampaignService(paths, bus)
        self.trash = trash or TrashService(paths, bus)

    # ------------------------------------------------------------ 内部工具
    def _scope(self, campaign_id: str | None, rel: str = "") -> Path:
        base = self.campaigns.resolve(campaign_id)
        if not rel or rel in (".", "/"):
            return base
        target = base / rel
        return ensure_inside(base, target)

    # ------------------------------------------------------------ 浏览
    def tree(self, campaign_id: str | None = None, rel: str = "", depth: int = 4) -> dict:
        base = self._scope(campaign_id, rel)
        return {"root": str(base.relative_to(self.campaigns.resolve(campaign_id))) or ".",
                "nodes": self._walk(base, base, depth, 0)}

    def _walk(self, root: Path, curr: Path, depth: int, level: int) -> list[dict]:
        if level >= depth:
            return []
        nodes = []
        for p in sorted(curr.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            if p.name.startswith(".") or p.name.startswith("_"):
                continue
            item = {
                "name": p.name,
                "path": str(p.relative_to(root)).replace("\\", "/"),
                "type": "dir" if p.is_dir() else self._kind(p),
                "size": p.stat().st_size if p.is_file() else 0,
                "mtime": int(p.stat().st_mtime),
            }
            if p.is_dir():
                item["children"] = self._walk(root, p, depth, level + 1)
            nodes.append(item)
        return nodes

    @staticmethod
    def _kind(p: Path) -> str:
        s = p.suffix.lower()
        if s in IMAGE_SUFFIX:
            return "image"
        if s in TEXT_SUFFIX:
            return "text"
        return "binary"

    def info(self, campaign_id: str | None, rel: str) -> dict:
        p = self._scope(campaign_id, rel)
        if not p.exists():
            raise NotFound(f"文件不存在：{rel}")
        return {"name": p.name, "path": rel, "type": "dir" if p.is_dir() else self._kind(p),
                "size": p.stat().st_size, "mtime": int(p.stat().st_mtime), "is_dir": p.is_dir()}

    # ------------------------------------------------------------ 读写
    def read(self, campaign_id: str | None, rel: str) -> dict:
        p = self._scope(campaign_id, rel)
        if not p.exists():
            raise NotFound(f"文件不存在：{rel}")
        if p.is_dir():
            raise ValidationFailed("目标是目录，无法读取内容")
        if self._kind(p) == "text":
            return {"name": p.name, "path": rel, "type": "text", "content": read_text(p)}
        data = p.read_bytes()
        b64 = base64.b64encode(data).decode("ascii")
        mime = _guess_mime(p)
        return {"name": p.name, "path": rel, "type": "binary", "size": len(data),
                "mime": mime, "base64": b64}

    def write(self, campaign_id: str | None, rel: str, content: str, *, create_dirs: bool = True) -> dict:
        p = self._scope(campaign_id, rel)
        if p.exists() and p.is_dir():
            raise ValidationFailed("目标是目录，无法写入文件内容")
        if not create_dirs and not p.parent.exists():
            raise NotFound(f"目录不存在：{p.parent}")
        p.parent.mkdir(parents=True, exist_ok=True)
        write_text(p, content)
        self.emit("file/written", {"campaign_id": campaign_id, "path": rel})
        return {"path": rel, "size": len(content), "updated_at": int(p.stat().st_mtime)}

    def write_json_doc(self, campaign_id: str | None, rel: str, data: Any) -> dict:
        p = self._scope(campaign_id, rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        write_json(p, data)
        self.emit("file/written", {"campaign_id": campaign_id, "path": rel})
        return {"path": rel}

    def mkdir(self, campaign_id: str | None, rel: str) -> dict:
        p = self._scope(campaign_id, rel)
        if p.exists():
            raise Conflict(f"目录已存在：{rel}")
        parts = [safe_name(x) for x in Path(rel).parts]
        p = self._scope(campaign_id, "/".join(parts))
        p.mkdir(parents=True, exist_ok=True)
        self.emit("file/created", {"path": rel, "type": "dir"})
        return {"path": rel}

    def rename(self, campaign_id: str | None, rel: str, new_name: str) -> dict:
        p = self._scope(campaign_id, rel)
        if not p.exists():
            raise NotFound(f"目标不存在：{rel}")
        target = p.with_name(safe_name(new_name))
        ensure_inside(self.campaigns.resolve(campaign_id), target)
        if target.exists():
            raise Conflict(f"已存在同名对象：{new_name}")
        p.rename(target)
        rel_new = str(target.relative_to(self.campaigns.resolve(campaign_id))).replace("\\", "/")
        self.emit("file/renamed", {"from": rel, "to": rel_new})
        return {"from": rel, "to": rel_new}

    def move(self, campaign_id: str | None, rel: str, dest_folder: str) -> dict:
        base = self.campaigns.resolve(campaign_id)
        p = self._scope(campaign_id, rel)
        folder = self._scope(campaign_id, dest_folder)
        if not folder.is_dir():
            raise NotFound(f"目标目录不存在：{dest_folder}")
        target = ensure_inside(base, folder / p.name)
        if target.exists():
            raise Conflict(f"目标位置已存在同名文件：{p.name}")
        shutil.move(str(p), str(target))
        self.emit("file/moved", {"from": rel, "to": str(target.relative_to(base))})
        return {"from": rel, "to": str(target.relative_to(base)).replace("\\", "/")}

    def delete(self, campaign_id: str | None, rel: str) -> dict:
        p = self._scope(campaign_id, rel)
        if not p.exists():
            raise NotFound(f"目标不存在：{rel}")
        cid = campaign_id or self.campaigns.active_id()
        return self.trash.move_to_trash(p, origin=rel, campaign_id=cid, kind="file",
                                        extra={"relative_path": rel})

    # ------------------------------------------------------------ 搜索 / 导入
    def search(self, campaign_id: str | None, query: str, *, limit: int = 50) -> list[dict]:
        base = self.campaigns.resolve(campaign_id)
        q = (query or "").strip().lower()
        if not q:
            return []
        hits = []
        for p in base.rglob("*"):
            if not p.is_file() or p.name.startswith("_"):
                continue
            if q and q in p.name.lower():
                hits.append({"path": str(p.relative_to(base)).replace("\\", "/"), "match": "name"})
            elif p.suffix.lower() in TEXT_SUFFIX and p.stat().st_size <= MAX_FILE_BYTES:
                try:
                    text = read_text(p)
                except Exception:
                    continue
                for i, line in enumerate(text.splitlines(), 1):
                    if q in line.lower():
                        hits.append({"path": str(p.relative_to(base)).replace("\\", "/"),
                                     "match": "content", "line": i, "preview": line.strip()[:160]})
                        break
            if len(hits) >= limit:
                break
        return hits

    def import_bytes(self, campaign_id: str | None, folder: str, filename: str,
                     data_base64: str | None = None, source_path: str | None = None) -> dict:
        """把图片/资源放进跑团目录。binary 内容走 base64，或直接给本机绝对路径复制。"""
        target_dir = self._scope(campaign_id, folder or "assets")
        target_dir.mkdir(parents=True, exist_ok=True)
        target = ensure_inside(self.campaigns.resolve(campaign_id), target_dir / safe_name(filename))
        if target.exists():
            raise Conflict(f"文件已存在：{filename}")
        if source_path:
            shutil.copyfile(str(Path(source_path)), str(target))
        elif data_base64:
            target.write_bytes(base64.b64decode(data_base64))
        else:
            raise ValidationFailed("需要提供 base64 内容或本机文件路径")
        self.emit("file/imported", {"path": str(target.relative_to(self.campaigns.resolve(campaign_id)))})
        return {"path": str(target.relative_to(self.campaigns.resolve(campaign_id))).replace("\\", "/"),
                "size": target.stat().st_size}


def _guess_mime(p: Path) -> str:
    return {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
        ".bmp": "image/bmp",
    }.get(p.suffix.lower(), "application/octet-stream")
