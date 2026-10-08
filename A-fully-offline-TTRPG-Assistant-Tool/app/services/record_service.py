"""跑团记录服务：游戏日志、战利品（LOOT）、玩家名单与 Markdown 导出。

日志用 .jsonl 追加写（每行一条，天然抗损坏、便于 diff），
战利品与花名册用结构化 JSON，方便结算时汇总。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.errors import NotFound, ValidationFailed
from ..core.jsonio import append_jsonl, now_iso, read_json, read_jsonl, uid, write_json
from ..core.safety import ensure_inside, safe_name
from .base import BaseService
from .campaign_service import CampaignService


class RecordService(BaseService):
    LOGS = "logs"

    def __init__(self, paths=None, bus=None, campaigns: CampaignService | None = None) -> None:
        super().__init__(paths, bus)
        self.campaigns = campaigns or CampaignService(paths, bus)

    # ------------------------------------------------------------ 路径
    def _root(self, campaign_id: str | None) -> Path:
        root = self.campaigns.resolve(campaign_id)
        return ensure_inside(root, root / self.LOGS)

    def _log_file(self, campaign_id: str | None, session: str) -> Path:
        base = self._root(campaign_id)
        return ensure_inside(base, base / f"{safe_name(session)}.jsonl")

    def _party_file(self, campaign_id: str | None) -> Path:
        return ensure_inside(self._root(campaign_id), self._root(campaign_id) / "party.json")

    # ------------------------------------------------------------ 日志
    def sessions(self, campaign_id: str | None = None) -> list[dict]:
        base = self._root(campaign_id)
        out = []
        for f in sorted(base.glob("*.jsonl"), key=lambda p: p.name, reverse=True):
            lines = read_jsonl(f)
            out.append({
                "session": f.stem,
                "entries": len(lines),
                "last_at": lines[-1].get("timestamp", "") if lines else "",
            })
        return out

    def log(self, campaign_id: str | None, text: str, *,
            entry_type: str = "event", session: str | None = None,
            tags: list[str] | None = None, actor: str = "", dice: dict | None = None) -> dict:
        text = (text or "").strip()
        if not text:
            raise ValidationFailed("日志内容不能为空")
        session = session or _default_session()
        record = {
            "id": uid("lg"),
            "timestamp": now_iso(),
            "session": session,
            "type": entry_type,          # event | combat | roleplay | loot | dice | milestone
            "actor": actor,
            "tags": tags or [],
            "text": text,
            "dice": dice,
        }
        append_jsonl(self._log_file(campaign_id, session), record)
        self.emit("record/logged", record)
        return record

    def read_logs(self, campaign_id: str | None = None, session: str | None = None,
                  *, limit: int = 500, types: list[str] | None = None) -> list[dict]:
        base = self._root(campaign_id)
        files = [self._log_file(campaign_id, session)] if session else sorted(base.glob("*.jsonl"))
        lines: list[dict] = []
        for f in files:
            if f.exists():
                lines.extend(read_jsonl(f))
        lines.sort(key=lambda r: r.get("timestamp", ""))
        if types:
            lines = [r for r in lines if r.get("type") in types]
        return lines[-limit:]

    # ------------------------------------------------------------ 花名册 / 战利品
    def party(self, campaign_id: str | None = None) -> dict:
        return read_json(self._party_file(campaign_id), {"players": [], "loot": []}) or {"players": [], "loot": []}

    def add_player(self, campaign_id: str | None, name: str, character: str = "",
                   contact: str = "", note: str = "") -> dict:
        data = self.party(campaign_id)
        if any(p.get("name") == name for p in data.setdefault("players", [])):
            raise ValidationFailed(f"玩家已存在：{name}")
        player = {"id": uid("pl"), "name": name, "character": character,
                  "contact": contact, "note": note, "joined_at": now_iso()}
        data["players"].append(player)
        write_json(self._party_file(campaign_id), data)
        self.emit("record/player_added", player)
        return player

    def remove_player(self, campaign_id: str | None, player_id: str) -> dict:
        data = self.party(campaign_id)
        players = [p for p in data.get("players", []) if p.get("id") != player_id]
        if len(players) == len(data.get("players", [])):
            raise NotFound(f"玩家不存在：{player_id}")
        data["players"] = players
        write_json(self._party_file(campaign_id), data)
        return {"removed": player_id}

    def loot(self, campaign_id: str | None = None) -> list[dict]:
        return self.party(campaign_id).get("loot", [])

    def add_loot(self, campaign_id: str | None, item: dict) -> dict:
        data = self.party(campaign_id)
        entry = {
            "id": uid("lt"),
            "name": (item or {}).get("name", "").strip(),
            "qty": (item or {}).get("qty", 1),
            "value": (item or {}).get("value", ""),
            "rarity": (item or {}).get("rarity", "普通"),
            "owner": (item or {}).get("owner", ""),
            "source": (item or {}).get("source", ""),
            "session": (item or {}).get("session", _default_session()),
            "status": (item or {}).get("status", "队伍持有"),  # 队伍持有 | 已分配 | 已出售
            "created_at": now_iso(),
        }
        if not entry["name"]:
            raise ValidationFailed("战利品名称不能为空")
        data.setdefault("loot", []).append(entry)
        write_json(self._party_file(campaign_id), data)
        self.log(campaign_id, f"获得战利品：{entry['name']} x{entry['qty']}", entry_type="loot")
        self.emit("record/loot_added", entry)
        return entry

    def update_loot(self, campaign_id: str | None, loot_id: str, patch: dict) -> dict:
        data = self.party(campaign_id)
        for entry in data.get("loot", []):
            if entry.get("id") == loot_id:
                entry.update(patch or {})
                write_json(self._party_file(campaign_id), data)
                self.emit("record/loot_updated", entry)
                return entry
        raise NotFound(f"战利品不存在：{loot_id}")

    def remove_loot(self, campaign_id: str | None, loot_id: str) -> dict:
        data = self.party(campaign_id)
        before = len(data.get("loot", []))
        data["loot"] = [x for x in data.get("loot", []) if x.get("id") != loot_id]
        if len(data["loot"]) == before:
            raise NotFound(f"战利品不存在：{loot_id}")
        write_json(self._party_file(campaign_id), data)
        return {"removed": loot_id}

    # ------------------------------------------------------------ 导出
    def export_markdown(self, campaign_id: str | None = None, session: str | None = None) -> str:
        meta = self.campaigns.get(campaign_id) if campaign_id else {}
        lines = [f"# {meta.get('name', '跑团记录')}", "",
                 f"- 规则：{meta.get('system', '-')}",
                 f"- 导出时间：{now_iso()}",
                 ""]
        party = self.party(campaign_id)
        if party.get("players"):
            lines += ["## 玩家名单", ""]
            lines += [f"- **{p.get('name')}** —— {p.get('character', '')}" for p in party["players"]]
            lines.append("")
        loot = party.get("loot", [])
        if loot:
            lines += ["## 战利品", "", "| 物品 | 数量 | 价值 | 持有 |", "| --- | --- | --- | --- |"]
            lines += [f"| {x.get('name')} | {x.get('qty')} | {x.get('value')} | {x.get('owner') or '队伍'} |"
                      for x in loot]
            lines.append("")
        logs = self.read_logs(campaign_id, session)
        lines += ["## 冒险日志", ""]
        cur_session = None
        for r in logs:
            if r.get("session") != cur_session:
                cur_session = r.get("session")
                lines += ["", f"### Session {cur_session}"]
            tag = ("".join(f" #{t}" for t in (r.get("tags") or [])))
            actor = f"**{r.get('actor')}**：" if r.get("actor") else ""
            lines.append(f"- `{r.get('timestamp', '')[:16]}` [{r.get('type')}] {actor}{r.get('text')}{tag}")
        return "\n".join(lines) + "\n"


def _default_session() -> str:
    from datetime import datetime
    d = datetime.now()
    return f"s{d.year}{d.month:02d}{d.day:02d}"
