"""人物卡 / 怪物卡实体服务：模板生成、校验、增删改查。

数据就是一个 JSON 文件，Schema 只做「最小约束 + 表单描述」，
新增规则不必改代码 —— 自定义规则直接把 system 写成自定义名即可。
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Literal

from ..core.errors import Conflict, NotFound, ValidationFailed
from ..core.jsonio import read_json, slugify, uid, write_json, now_iso
from ..core.safety import ensure_inside, safe_name
from ..core.validate import CHARACTER_SCHEMA, MONSTER_SCHEMA, RULE_SYSTEMS, validate_document
from .base import BaseService
from .campaign_service import CampaignService
from .trash_service import TrashService

Kind = Literal["character", "monster"]
FOLDERS: dict[str, str] = {"character": "characters", "monster": "monsters"}
SCHEMAS: dict[str, dict] = {"character": CHARACTER_SCHEMA, "monster": MONSTER_SCHEMA}


class EntityService(BaseService):
    def __init__(self, paths=None, bus=None, campaigns: CampaignService | None = None,
                 trash: TrashService | None = None) -> None:
        super().__init__(paths, bus)
        self.campaigns = campaigns or CampaignService(paths, bus)
        self.trash = trash or TrashService(paths, bus)

    # ------------------------------------------------------------ 路径
    def _folder(self, campaign_id: str | None, kind: Kind) -> Path:
        if kind not in FOLDERS:
            raise ValidationFailed(f"未知实体类型：{kind}")
        root = self.campaigns.resolve(campaign_id)
        return ensure_inside(root, root / FOLDERS[kind])

    def _file(self, campaign_id: str | None, kind: Kind, slug: str) -> Path:
        folder = self._folder(campaign_id, kind)
        target = folder / f"{safe_name(slug)}.json"
        return ensure_inside(folder, target)

    # ------------------------------------------------------------ 模板
    def template(self, kind: Kind, system: str = "DND 5e") -> dict:
        if kind not in SCHEMAS:
            raise ValidationFailed(f"未知实体类型：{kind}")
        if kind == "character":
            base: dict[str, Any] = {
                "id": uid("pc"),
                "system": system,
                "name": "新角色",
                "player": "",
                "race": "",
                "klass": "",
                "level": 1,
                "hp": {"current": 10, "max": 10, "temp": 0},
                "ac": 10,
                "speed": "30尺",
                "attributes": {},
                "skills": {},
                "saves": {},
                "equipment": [],
                "features": [],
                "background": "",
                "notes": "",
                "portrait": "",
                "created_at": now_iso(),
                "updated_at": now_iso(),
            }
            if system == "COC 7th":
                base.update({
                    "attributes": {"STR": 50, "CON": 50, "SIZ": 50, "DEX": 50, "APP": 50,
                                   "INT": 50, "POW": 50, "EDU": 50},
                    "skills": {"侦查": 25, "聆听": 25, "图书馆使用": 25, "心理学": 10},
                    "derived": {"SAN": 50, "LUCK": 50, "MP": 10, "MOV": 8, "DB": "0", "BUILD": 0},
                })
                base["hp"] = {"current": 10, "max": 10}
            elif system == "DND 5e":
                base.update({
                    "attributes": {"STR": 10, "DEX": 10, "CON": 10, "INT": 10, "WIS": 10, "CHA": 10},
                    "skills": {"威吓": 2, "洞察": 2, "运动": 2},
                    "saves": {"STR": 0, "DEX": 2, "CON": 2, "INT": 0, "WIS": 0, "CHA": 0},
                    "proficiency": 2,
                    "hit_dice": "1d8",
                })
        else:
            base = {
                "id": uid("mn"),
                "system": system,
                "name": "新怪物",
                "type": "中型 异怪",
                "alignment": "中立邪恶",
                "cr": "1/4",
                "hp": {"current": 11, "max": 11},
                "ac": 11,
                "speed": "30尺",
                "attributes": {"STR": 10, "DEX": 10, "CON": 10, "INT": 10, "WIS": 10, "CHA": 10},
                "skills": {},
                "resistances": [],
                "immunities": [],
                "vulnerabilities": [],
                "attacks": [{"name": "爪击", "attack": "+3", "damage": "1d4+1", "type": "挥砍", "note": ""}],
                "abilities": [],
                "description": "",
                "loot": [],
                "created_at": now_iso(),
                "updated_at": now_iso(),
            }
            if system == "COC 7th":
                base.update({
                    "derived": {"MOV": 7, "SAN_loss": "0/1d6", "DB": "+1d4", "BUILD": 1, "ARMOR": 0},
                    "attributes": {"STR": 60, "CON": 60, "SIZ": 50, "DEX": 60, "INT": 50, "POW": 60, "HP": 11},
                })
        base["schema"] = kind
        return base

    def schema(self, kind: Kind) -> dict:
        if kind not in SCHEMAS:
            raise ValidationFailed(f"未知实体类型：{kind}")
        data = copy.deepcopy(SCHEMAS[kind])
        data["rule_systems"] = RULE_SYSTEMS
        return data

    # ------------------------------------------------------------ CRUD
    def list(self, campaign_id: str | None, kind: Kind, *, query: str = "") -> list[dict]:
        folder = self._folder(campaign_id, kind)
        out = []
        q = (query or "").strip().lower()
        for f in sorted(folder.glob("*.json"), key=lambda p: p.name.lower()):
            if f.name.startswith((".", "_")):   # 跳过原子写残留的 .tmp-* 与内部文件
                continue
            data = read_json(f, {}) or {}
            if not isinstance(data, dict) or not data.get("name"):
                continue
            name = str(data.get("name", ""))
            if q and q not in name.lower() and q not in f.stem.lower():
                continue
            out.append({
                "slug": f.stem,
                "id": data.get("id", f.stem),
                "name": name,
                "system": data.get("system", ""),
                "summary": _summary(kind, data),
                "updated_at": data.get("updated_at", ""),
            })
        return out

    def get(self, campaign_id: str | None, kind: Kind, slug: str) -> dict:
        f = self._file(campaign_id, kind, slug)
        data = read_json(f)
        if not data:
            raise NotFound(f"{SCHEMAS[kind]['label']}不存在：{slug}")
        data["_slug"] = f.stem
        return data

    def create(self, campaign_id: str | None, kind: Kind, data: dict) -> dict:
        data = dict(data or {})
        if not data.get("id"):
            data["id"] = uid("pc" if kind == "character" else "mn")
        if not data.get("system"):
            data["system"] = "DND 5e"
        data["schema"] = kind
        now = now_iso()
        data.setdefault("created_at", now)
        data["updated_at"] = now
        validate_document(kind, data)
        slug = slugify(data.get("name", ""), fallback=data["id"])
        f = self._file(campaign_id, kind, slug)
        if f.exists():
            slug = f"{slug}-{data['id'][-4:]}"
            f = self._file(campaign_id, kind, slug)
        write_json(f, data)
        result = {"slug": slug, **data}
        self.emit(f"{kind}/created", result)
        return result

    def save(self, campaign_id: str | None, kind: Kind, slug: str, data: dict, *,
             rename: bool = False) -> dict:
        old = self._file(campaign_id, kind, slug)
        if not old.exists():
            raise NotFound(f"{SCHEMAS[kind]['label']}不存在：{slug}")
        data = dict(data or {})
        data["schema"] = kind
        data["updated_at"] = now_iso()
        existing = read_json(old, {})
        data.setdefault("created_at", existing.get("created_at", data["updated_at"]))
        validate_document(kind, data)

        new_slug = slug
        if rename and data.get("name"):
            candidate = slugify(data["name"], fallback=slug)
            if candidate != slug:
                new_slug = candidate
        target = self._file(campaign_id, kind, new_slug)
        if target != old and target.exists():
            raise Conflict(f"同名文件已存在：{new_slug}.json")
        if target != old:
            old.unlink()
        write_json(target, data)
        result = {"slug": new_slug, **data}
        self.emit(f"{kind}/saved", {"slug": new_slug, "renamed_from": slug if new_slug != slug else None})
        return result

    def delete(self, campaign_id: str | None, kind: Kind, slug: str) -> dict:
        f = self._file(campaign_id, kind, slug)
        if not f.exists():
            raise NotFound(f"{SCHEMAS[kind]['label']}不存在：{slug}")
        cid = campaign_id or self.campaigns.active_id()
        data = read_json(f, {}) or {}
        return self.trash.move_to_trash(
            f, campaign_id=cid, kind=kind, origin=data.get("name", slug),
            extra={"slug": slug, "relative_path": f"{FOLDERS[kind]}/{slug}.json"})

    def duplicate(self, campaign_id: str | None, kind: Kind, slug: str) -> dict:
        data = self.get(campaign_id, kind, slug)
        data.pop("_slug", None)
        data["id"] = uid("pc" if kind == "character" else "mn")
        data["name"] = f"{data.get('name', '副本')} (副本)"
        return self.create(campaign_id, kind, data)

    def adjust_hp(self, campaign_id: str | None, kind: Kind, slug: str, delta: int) -> dict:
        """快捷掉血/治疗，跑团高频操作。"""
        data = self.get(campaign_id, kind, slug)
        hp = data.get("hp") or {}
        current = int(hp.get("current", 0)) + int(delta)
        hp["current"] = max(0, min(int(hp.get("max", 0) or 999), current))
        data["hp"] = hp
        return self.save(campaign_id, kind, slug, data)


def _summary(kind: str, data: dict) -> dict:
    if kind == "character":
        return {
            "level": data.get("level"),
            "klass": data.get("klass", ""),
            "hp": f"{(data.get('hp') or {}).get('current', '?')}/{(data.get('hp') or {}).get('max', '?')}",
            "ac": data.get("ac", ""),
        }
    return {
        "cr": data.get("cr", ""),
        "type": data.get("type", ""),
        "hp": f"{(data.get('hp') or {}).get('current', '?')}/{(data.get('hp') or {}).get('max', '?')}",
        "ac": data.get("ac", ""),
    }
