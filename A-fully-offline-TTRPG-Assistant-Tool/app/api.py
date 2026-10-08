"""HTTP API 层：把 Service 能力暴露成一组扁平 JSON 接口。

约定：
    统一返回 {"ok": true, "data": ...} 或 {"ok": false, "error": {code, message, details}}
    业务异常（ServiceError）自动映射 HTTP 状态码，UI 只需处理同一套错误结构。
"""
from __future__ import annotations

import json
import mimetypes
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .core.errors import NotFound, ServiceError, ValidationFailed
from .core.validate import ENDINGS, NODE_TYPES, RULE_SYSTEMS
from .services import ServiceRegistry

MIME_FALLBACK = {
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
}


def _first(query: dict, key: str, default: str = "") -> str:
    val = query.get(key)
    if isinstance(val, list) and val:
        return str(val[0])
    return default


def _int(query: dict, key: str, default: int) -> int:
    raw = _first(query, key, "")
    try:
        return int(raw)
    except ValueError:
        return default


class ApiRouter:
    """与传输方式无关的一层：理论上可以接到 CLI、WebSocket 或本地 socket 上。"""

    def __init__(self, registry: ServiceRegistry) -> None:
        self.r = registry

    # ------------------------------------------------------------------ 工具
    def _cid(self, query: dict, body: dict | None = None) -> str:
        cid = _first(query, "campaign") or (body or {}).get("campaign") or ""
        return cid or self.r.campaigns.active_id()

    # ------------------------------------------------------------------ 分发
    ROUTES: list[tuple[str, str, str]] = []

    def dispatch(self, method: str, path: str, query: dict, body: Any) -> tuple[int, Any, str]:
        for meth, pattern, attr in ApiRouter.ROUTES:
            if meth != method:
                continue
            m = re.fullmatch(pattern, path)
            if m:
                result = getattr(self, attr)(m, query, body)
                return self._shape(result)
        raise NotFound(f"接口不存在：{method} {path}")

    @staticmethod
    def _shape(result: Any) -> tuple[int, Any, str]:
        if isinstance(result, tuple) and len(result) == 3:
            status, payload, kind = result
            return status, payload, kind
        return 200, {"ok": True, "data": result}, "json"

    # ------------------------------------------------------------------ 系统
    def _health(self, m, query, body):
        return {"status": "ok", "service": "trpg-local-assistant",
                "active_campaign": self.r.campaigns.active_id(),
                "data_root": str(self.r.paths.root),
                "campaigns": len(self.r.campaigns.list())}

    def _ping(self, m, query, body):
        return {"pong": True}

    # ------------------------------------------------------------------ 跑团
    def _campaigns_list(self, m, query, body):
        return {"items": self.r.campaigns.list(), "active": self.r.campaigns.active_id(),
                "data_root": str(self.r.paths.root)}

    def _campaigns_create(self, m, query, body):
        body = body or {}
        meta = self.r.campaigns.create(body.get("name", ""), body.get("system", "DND 5e"),
                                       body.get("description", ""), body.get("dm", ""))
        self.r.set_persistent_dice_history(meta["id"])
        return meta

    def _campaigns_get(self, m, query, body):
        return self.r.campaigns.get(m.group(1))

    def _campaigns_update(self, m, query, body):
        return self.r.campaigns.update(m.group(1), body or {})

    def _campaigns_activate(self, m, query, body):
        result = self.r.campaigns.set_active(m.group(1))
        self.r.set_persistent_dice_history(m.group(1))
        return result

    def _campaigns_delete(self, m, query, body):
        return self.r.campaigns.delete(m.group(1))

    def _campaigns_tree(self, m, query, body):
        return self.r.files.tree(m.group(1), _first(query, "path"), _int(query, "depth", 3))

    # ------------------------------------------------------------------ 文件
    def _files_tree(self, m, query, body):
        return self.r.files.tree(self._cid(query), _first(query, "path"), _int(query, "depth", 3))

    def _files_read(self, m, query, body):
        return self.r.files.read(self._cid(query), _first(query, "path"))

    def _files_write(self, m, query, body):
        body = body or {}
        return self.r.files.write(self._cid(query, body), body.get("path", ""), body.get("content", ""))

    def _files_mkdir(self, m, query, body):
        body = body or {}
        return self.r.files.mkdir(self._cid(query, body), body.get("path", ""))

    def _files_rename(self, m, query, body):
        body = body or {}
        return self.r.files.rename(self._cid(query, body), body.get("path", ""), body.get("new_name", ""))

    def _files_move(self, m, query, body):
        body = body or {}
        return self.r.files.move(self._cid(query, body), body.get("path", ""), body.get("dest", ""))

    def _files_delete(self, m, query, body):
        return self.r.files.delete(self._cid(query), _first(query, "path"))

    def _files_search(self, m, query, body):
        return {"items": self.r.files.search(self._cid(query), _first(query, "q"))}

    def _files_import(self, m, query, body):
        body = body or {}
        return self.r.files.import_bytes(self._cid(query, body), body.get("folder", "maps"),
                                         body.get("filename", "asset.bin"),
                                         data_base64=body.get("base64"),
                                         source_path=body.get("source_path"))

    # ------------------------------------------------------------------ 回收站
    def _trash_list(self, m, query, body):
        return {"items": self.r.trash.list()}

    def _trash_restore(self, m, query, body):
        body = body or {}
        if not body.get("token"):
            raise ValidationFailed("缺少 token")
        return self.r.trash.restore(body["token"], target_name=body.get("target_name"))

    def _trash_delete(self, m, query, body):
        token = _first(query, "token")
        if token:
            return self.r.trash.purge(token)
        return self.r.trash.empty()

    # ------------------------------------------------------------------ 实体卡
    @staticmethod
    def _kind(raw: str) -> str:
        """URL 里资源名是复数（characters/monsters），Service 里用单数。
        同时兼容单数写法（character/monster），避免调用方写错就直接 404。"""
        return "character" if raw.startswith("character") else "monster"

    def _entities_list(self, m, query, body):
        kind = m.group(1)
        return {"items": self.r.entities.list(self._cid(query), self._kind(m.group(1)), query=_first(query, "q"))}

    def _entities_get(self, m, query, body):
        return self.r.entities.get(self._cid(query), self._kind(m.group(1)), m.group(2))

    def _entities_create(self, m, query, body):
        return self.r.entities.create(self._cid(query, body), self._kind(m.group(1)), body or {})

    def _entities_save(self, m, query, body):
        return self.r.entities.save(self._cid(query, body), self._kind(m.group(1)), m.group(2), body or {},
                                    rename=bool((body or {}).get("rename", True)))

    def _entities_delete(self, m, query, body):
        return self.r.entities.delete(self._cid(query), self._kind(m.group(1)), m.group(2))

    def _entities_duplicate(self, m, query, body):
        return self.r.entities.duplicate(self._cid(query, body), self._kind(m.group(1)), m.group(2))

    def _entities_hp(self, m, query, body):
        body = body or {}
        try:
            delta = int(body.get("delta", 0))
        except (TypeError, ValueError):
            raise ValidationFailed("delta 必须是整数")
        return self.r.entities.adjust_hp(self._cid(query, body), self._kind(m.group(1)), m.group(2), delta)

    def _template(self, m, query, body):
        return self.r.entities.template(m.group(1), _first(query, "system", "DND 5e"))

    def _schema(self, m, query, body):
        kind = m.group(1)
        if kind == "story":
            return {"kind": "story", "node_types": NODE_TYPES, "endings": ENDINGS,
                    "rule_systems": RULE_SYSTEMS}
        return self.r.entities.schema(kind)  # type: ignore[arg-type]

    # ------------------------------------------------------------------ 剧情
    def _stories_list(self, m, query, body):
        return {"items": self.r.stories.list(self._cid(query))}

    def _stories_create(self, m, query, body):
        return self.r.stories.create(self._cid(query, body), body)

    def _stories_get(self, m, query, body):
        return self.r.stories.get(self._cid(query), m.group(1))

    def _stories_save(self, m, query, body):
        return self.r.stories.save(self._cid(query, body), m.group(1), body)

    def _stories_delete(self, m, query, body):
        return self.r.stories.delete(self._cid(query), m.group(1))

    def _story_nodes_add(self, m, query, body):
        body = body or {}
        return self.r.stories.add_node(self._cid(query, body), m.group(1), body.get("node"),
                                       attach_to=body.get("attach_to"),
                                       as_choice=bool(body.get("as_choice")),
                                       label=body.get("label", ""))

    def _story_nodes_update(self, m, query, body):
        return self.r.stories.update_node(self._cid(query, body), m.group(1), m.group(2), body or {})

    def _story_nodes_delete(self, m, query, body):
        return self.r.stories.delete_node(self._cid(query, body), m.group(1), m.group(2),
                                          relink=bool((body or {}).get("relink", True)))

    def _story_link(self, m, query, body):
        body = body or {}
        return self.r.stories.link(self._cid(query, body), m.group(1), body.get("source", ""),
                                   body.get("target", ""), kind=body.get("kind", "next"),
                                   label=body.get("label", ""))

    def _story_layout(self, m, query, body):
        return self.r.stories.layout(self._cid(query), m.group(1))

    def _story_dot(self, m, query, body):
        dot = self.r.stories.to_dot(self._cid(query), m.group(1))
        return 200, dot, "text"

    def _story_validate(self, m, query, body):
        return self.r.stories.validate_graph(self._cid(query), m.group(1))

    def _story_walk(self, m, query, body):
        return self.r.stories.walk(self._cid(query), m.group(1), (body or {}).get("flags"))

    # ------------------------------------------------------------------ 骰子
    def _dice_roll(self, m, query, body):
        body = body or {}
        expr = str(body.get("expression") or body.get("expr") or "").strip()
        if not expr:
            raise ValidationFailed("缺少骰子表达式")
        try:
            result = self.r.dice.roll(expr, advantage=body.get("advantage"),
                                      seed=body.get("seed"), label=body.get("label", ""),
                                      reason=body.get("reason", ""))
        except ValueError as e:
            raise ValidationFailed(str(e))
        return result.to_dict()

    def _dice_history(self, m, query, body):
        return {"items": self.r.dice.history(_int(query, "limit", 100) or None)}

    def _dice_clear(self, m, query, body):
        self.r.dice.clear_history()
        return {"cleared": True}

    def _dice_expected(self, m, query, body):
        expr = _first(query, "expr")
        if not expr:
            raise ValidationFailed("缺少 expr 参数")
        try:
            value = self.r.dice.expected_of(expr, _first(query, "advantage", None) or None)
        except ValueError as e:
            raise ValidationFailed(str(e))
        return {"expression": expr, "expected": round(value, 3)}

    def _dice_stats(self, m, query, body):
        return self.r.dice.stats()

    def _dice_probability(self, m, query, body):
        expr = _first(query, "expr")
        dc = _first(query, "dc")
        if not expr:
            raise ValidationFailed("缺少 expr 参数")
        try:
            dc_int = int(dc)
        except ValueError:
            raise ValidationFailed("dc 必须是整数")
        try:
            p = self.r.dice.probability_at_least(expr, dc_int)
        except ValueError as e:
            raise ValidationFailed(str(e))
        return {"expression": expr, "dc": dc_int, "probability_percent": p}

    # ------------------------------------------------------------------ 记录
    def _log_list(self, m, query, body):
        return {"items": self.r.records.read_logs(self._cid(query), _first(query, "session") or None,
                                                  limit=_int(query, "limit", 300))}

    def _log_create(self, m, query, body):
        body = body or {}
        return self.r.records.log(self._cid(query, body), body.get("text", ""),
                                  entry_type=body.get("type", "event"),
                                  session=body.get("session"),
                                  tags=body.get("tags"), actor=body.get("actor", ""),
                                  dice=body.get("dice"))

    def _sessions(self, m, query, body):
        return {"items": self.r.records.sessions(self._cid(query))}

    def _party_get(self, m, query, body):
        return self.r.records.party(self._cid(query))

    def _party_add(self, m, query, body):
        body = body or {}
        return self.r.records.add_player(self._cid(query, body), body.get("name", ""),
                                         body.get("character", ""), body.get("contact", ""),
                                         body.get("note", ""))

    def _party_remove(self, m, query, body):
        return self.r.records.remove_player(self._cid(query), _first(query, "player_id"))

    def _loot_list(self, m, query, body):
        return {"items": self.r.records.loot(self._cid(query))}

    def _loot_add(self, m, query, body):
        return self.r.records.add_loot(self._cid(query, body), body or {})

    def _loot_update(self, m, query, body):
        return self.r.records.update_loot(self._cid(query, body), m.group(1), body or {})

    def _loot_remove(self, m, query, body):
        return self.r.records.remove_loot(self._cid(query), m.group(1))

    def _records_export(self, m, query, body):
        fmt = _first(query, "format", "md")
        if fmt != "md":
            raise ValidationFailed("暂仅支持 markdown 导出")
        text = self.r.records.export_markdown(self._cid(query), _first(query, "session") or None)
        return 200, text, "text"

    # ------------------------------------------------------------------ 备份
    def _backups_list(self, m, query, body):
        return {"items": self.r.backups.list()}

    def _backups_create(self, m, query, body):
        body = body or {}
        path = self.r.backups.create(self._cid(query, body) or None, note=body.get("note", ""))
        return {"path": str(path), "file": path.name}

    def _backups_restore(self, m, query, body):
        body = body or {}
        return self.r.backups.restore(body.get("file", ""))


ApiRouter.ROUTES = [
    ("GET", r"/api/health", "_health"),
    ("POST", r"/api/ping", "_ping"),

    ("GET", r"/api/campaigns", "_campaigns_list"),
    ("POST", r"/api/campaigns", "_campaigns_create"),
    ("GET", r"/api/campaigns/([^/]+)", "_campaigns_get"),
    ("PATCH", r"/api/campaigns/([^/]+)", "_campaigns_update"),
    ("POST", r"/api/campaigns/([^/]+)/activate", "_campaigns_activate"),
    ("DELETE", r"/api/campaigns/([^/]+)", "_campaigns_delete"),
    ("GET", r"/api/campaigns/([^/]+)/tree", "_campaigns_tree"),

    ("GET", r"/api/files", "_files_tree"),
    ("GET", r"/api/files/content", "_files_read"),
    ("PUT", r"/api/files", "_files_write"),
    ("POST", r"/api/files/mkdir", "_files_mkdir"),
    ("POST", r"/api/files/rename", "_files_rename"),
    ("POST", r"/api/files/move", "_files_move"),
    ("DELETE", r"/api/files", "_files_delete"),
    ("GET", r"/api/files/search", "_files_search"),
    ("POST", r"/api/files/import", "_files_import"),

    ("GET", r"/api/trash", "_trash_list"),
    ("POST", r"/api/trash/restore", "_trash_restore"),
    ("DELETE", r"/api/trash", "_trash_delete"),

    ("GET", r"/api/(characters|monsters)", "_entities_list"),
    ("GET", r"/api/(characters|monsters)/([^/]+)", "_entities_get"),
    ("POST", r"/api/(characters|monsters)", "_entities_create"),
    ("PUT", r"/api/(characters|monsters)/([^/]+)", "_entities_save"),
    ("DELETE", r"/api/(characters|monsters)/([^/]+)", "_entities_delete"),
    ("POST", r"/api/(characters|monsters)/([^/]+)/duplicate", "_entities_duplicate"),
    ("POST", r"/api/(characters|monsters)/([^/]+)/hp", "_entities_hp"),
    # 单数别名：前端或第三方脚本写 /api/character 也能用，不至于 404
    ("GET", r"/api/(character|monster)", "_entities_list"),
    ("GET", r"/api/(character|monster)/([^/]+)", "_entities_get"),
    ("POST", r"/api/(character|monster)", "_entities_create"),
    ("PUT", r"/api/(character|monster)/([^/]+)", "_entities_save"),
    ("DELETE", r"/api/(character|monster)/([^/]+)", "_entities_delete"),
    ("POST", r"/api/(character|monster)/([^/]+)/duplicate", "_entities_duplicate"),
    ("POST", r"/api/(character|monster)/([^/]+)/hp", "_entities_hp"),
    ("GET", r"/api/templates/(character|monster)", "_template"),
    ("GET", r"/api/schemas/(character|monster|story)", "_schema"),

    ("GET", r"/api/stories", "_stories_list"),
    ("POST", r"/api/stories", "_stories_create"),
    ("GET", r"/api/stories/([^/]+)", "_stories_get"),
    ("PUT", r"/api/stories/([^/]+)", "_stories_save"),
    ("DELETE", r"/api/stories/([^/]+)", "_stories_delete"),
    ("POST", r"/api/stories/([^/]+)/nodes", "_story_nodes_add"),
    ("PUT", r"/api/stories/([^/]+)/nodes/([^/]+)", "_story_nodes_update"),
    ("DELETE", r"/api/stories/([^/]+)/nodes/([^/]+)", "_story_nodes_delete"),
    ("POST", r"/api/stories/([^/]+)/link", "_story_link"),
    ("GET", r"/api/stories/([^/]+)/layout", "_story_layout"),
    ("GET", r"/api/stories/([^/]+)/dot", "_story_dot"),
    ("GET", r"/api/stories/([^/]+)/validate", "_story_validate"),
    ("POST", r"/api/stories/([^/]+)/walk", "_story_walk"),

    ("POST", r"/api/dice/roll", "_dice_roll"),
    ("GET", r"/api/dice/history", "_dice_history"),
    ("DELETE", r"/api/dice/history", "_dice_clear"),
    ("GET", r"/api/dice/expected", "_dice_expected"),
    ("GET", r"/api/dice/probability", "_dice_probability"),
    ("GET", r"/api/dice/stats", "_dice_stats"),

    ("GET", r"/api/records/logs", "_log_list"),
    ("POST", r"/api/records/logs", "_log_create"),
    ("GET", r"/api/records/sessions", "_sessions"),
    ("GET", r"/api/records/party", "_party_get"),
    ("POST", r"/api/records/party", "_party_add"),
    ("DELETE", r"/api/records/party", "_party_remove"),
    ("GET", r"/api/records/loot", "_loot_list"),
    ("POST", r"/api/records/loot", "_loot_add"),
    ("PUT", r"/api/records/loot/([^/]+)", "_loot_update"),
    ("DELETE", r"/api/records/loot/([^/]+)", "_loot_remove"),
    ("GET", r"/api/records/export", "_records_export"),

    ("GET", r"/api/backups", "_backups_list"),
    ("POST", r"/api/backups", "_backups_create"),
    ("POST", r"/api/backups/restore", "_backups_restore"),
]


# ---------------------------------------------------------------------- HTTP 适配
class HttpAdapter:
    """把 BaseHTTPRequestHandler 的请求转成 ApiRouter.dispatch。"""

    @staticmethod
    def serve_static(web_dir: Path, rel: str) -> tuple[int, bytes, str] | None:
        web_dir = Path(web_dir)
        rel = rel.strip("/") or "index.html"
        target = (web_dir / rel).resolve()
        try:
            target.relative_to(web_dir.resolve())
        except ValueError:
            return 403, b"Forbidden", "text/plain; charset=utf-8"
        if not target.is_file():
            return None
        ctype = MIME_FALLBACK.get(target.suffix.lower()) or mimetypes.guess_type(str(target))[0] \
            or "application/octet-stream"
        return 200, target.read_bytes(), ctype

    @staticmethod
    def handle_request(router: ApiRouter, web_dir: Path, method: str, raw_path: str, raw_body: bytes):
        parsed = urlparse(raw_path)
        # BaseHTTPRequestHandler 不会自动解码 %XX；跑团名很可能是中文，必须先解码，
        # 否则 <slug>/<id> 形式的路径参数会拿到编码后的字符串。
        path = unquote(parsed.path)
        query = parse_qs(parsed.query)

        if not path.startswith("/api/"):
            static = HttpAdapter.serve_static(web_dir, path)
            if static:
                return static
            if path.startswith("/api"):
                raise NotFound(f"未知接口：{path}")
            index = HttpAdapter.serve_static(web_dir, "index.html")
            if index:
                return index
            raise NotFound("未找到页面")

        body: Any = None
        if raw_body:
            text = raw_body.decode("utf-8", errors="replace")
            try:
                if text.strip().startswith(("{", "[")):
                    body = json.loads(text)
                else:
                    body = {k: v[0] for k, v in parse_qs(text).items()}
            except json.JSONDecodeError as e:
                raise ValidationFailed(f"请求体 JSON 解析失败：{e.msg}")
        status, payload, kind = router.dispatch(method, path, query, body)
        if kind == "text":
            return status, str(payload).encode("utf-8"), "text/plain; charset=utf-8"
        return status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8"

    @staticmethod
    def error_payload(exc: Exception) -> tuple[int, bytes]:
        if isinstance(exc, ServiceError):
            status, detail = exc.status, exc.to_dict()
        elif isinstance(exc, FileNotFoundError):
            status, detail = 404, {"code": "not_found", "message": str(exc), "details": {}}
        elif isinstance(exc, (FileExistsError, IsADirectoryError, PermissionError)):
            status, detail = 409, {"code": "io_error", "message": str(exc), "details": {}}
        else:
            status, detail = 500, {"code": "internal_error", "message": f"{type(exc).__name__}: {exc}",
                                   "details": {}}
        payload = json.dumps({"ok": False, "error": detail}, ensure_ascii=False).encode("utf-8")
        return status, payload
