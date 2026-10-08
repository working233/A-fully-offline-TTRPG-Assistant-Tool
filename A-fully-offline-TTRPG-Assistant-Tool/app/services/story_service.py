"""剧情编辑器服务：结构化剧情 JSON 的 CRUD、图谱校验、自动布局与 DOT 导出。

剧情模型（cards-node graph）：
    story.nodes[]       节点：main（主线）/ branch（分支）/ ending（结局）
    node.next           直连下一节点（单出口）
    node.choices[]      分支选择：{id,label,target,condition,effects}
    condition           条件跳转：flag 判定 / 技能检定 / 表达式
    effects             通过后写入的剧情标记：{type:'flag'|'san'|'item', ...}

可视化链路：JSON -> layout()(自动分层坐标) -> to_dot() -> graphviz/svg
"""
from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any

from ..core.errors import Conflict, NotFound, ValidationFailed
from ..core.jsonio import now_iso, read_json, slugify, uid, write_json
from ..core.safety import ensure_inside, safe_name
from ..core.validate import ENDINGS, NODE_TYPES, validate_document
from .base import BaseService
from .campaign_service import CampaignService
from .trash_service import TrashService


class StoryService(BaseService):
    FOLDER = "stories"

    def __init__(self, paths=None, bus=None, campaigns: CampaignService | None = None,
                 trash: TrashService | None = None) -> None:
        super().__init__(paths, bus)
        self.campaigns = campaigns or CampaignService(paths, bus)
        self.trash = trash or TrashService(paths, bus)

    # ------------------------------------------------------------ 路径
    def _folder(self, campaign_id: str | None) -> Path:
        root = self.campaigns.resolve(campaign_id)
        return ensure_inside(root, root / self.FOLDER)

    def _file(self, campaign_id: str | None, slug: str) -> Path:
        folder = self._folder(campaign_id)
        return ensure_inside(folder, folder / f"{safe_name(slug)}.json")

    # ------------------------------------------------------------ 模板
    def template(self, system: str = "DND 5e") -> dict:
        start = uid("n")
        return {
            "id": uid("st"),
            "title": "新剧情",
            "system": system,
            "synopsis": "",
            "version": 1,
            "start_node": start,
            "flags": {},
            "nodes": [
                {
                    "id": start,
                    "type": "main",
                    "title": "序章",
                    "text": "在这里描述开场場景……",
                    "tags": [],
                    "effects": [],
                    "choices": [],
                    "next": None,
                    "position": {"x": 320, "y": 80},
                }
            ],
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }

    # ------------------------------------------------------------ CRUD
    def list(self, campaign_id: str | None = None) -> list[dict]:
        folder = self._folder(campaign_id)
        out = []
        for f in sorted(folder.glob("*.json"), key=lambda p: p.name.lower()):
            if f.name.startswith((".", "_")):   # 跳过原子写残留的 .tmp-* 与内部文件
                continue
            data = read_json(f, {}) or {}
            if not isinstance(data, dict) or not data.get("title"):
                continue
            out.append({
                "slug": f.stem,
                "id": data.get("id", f.stem),
                "title": data.get("title", f.stem),
                "system": data.get("system", ""),
                "nodes": len(data.get("nodes", []) or []),
                "endings": sum(1 for n in (data.get("nodes") or []) if n.get("type") == "ending"),
                "updated_at": data.get("updated_at", ""),
            })
        return out

    def get(self, campaign_id: str | None, slug: str) -> dict:
        f = self._file(campaign_id, slug)
        data = read_json(f)
        if not data:
            raise NotFound(f"剧情不存在：{slug}")
        data["_slug"] = f.stem
        return data

    def create(self, campaign_id: str | None, data: dict | None = None) -> dict:
        data = data or self.template()
        data.setdefault("id", uid("st"))
        data.setdefault("nodes", [])
        data.setdefault("start_node", (data["nodes"][0]["id"] if data.get("nodes") else ""))
        data["updated_at"] = now_iso()
        validate_document("story", data)
        slug = slugify(data.get("title", ""), fallback=data["id"])
        f = self._file(campaign_id, slug)
        if f.exists():
            slug = f"{slug}-{data['id'][-4:]}"
            f = self._file(campaign_id, slug)
        write_json(f, data)
        self.emit("story/created", {"slug": slug, "title": data.get("title")})
        return {"slug": slug, **data}

    def save(self, campaign_id: str | None, slug: str, data: dict, *, validate: bool = True) -> dict:
        old = self._file(campaign_id, slug)
        if not old.exists():
            raise NotFound(f"剧情不存在：{slug}")
        data = dict(data or {})
        data["updated_at"] = now_iso()
        data["version"] = int(read_json(old, {}).get("version", 1)) + 1
        if validate:
            validate_document("story", data)
        write_json(old, data)
        self.emit("story/saved", {"slug": slug})
        return {"slug": slug, **data}

    def delete(self, campaign_id: str | None, slug: str) -> dict:
        f = self._file(campaign_id, slug)
        if not f.exists():
            raise NotFound(f"剧情不存在：{slug}")
        data = read_json(f, {}) or {}
        cid = campaign_id or self.campaigns.active_id()
        return self.trash.move_to_trash(f, campaign_id=cid, kind="story",
                                        origin=data.get("title", slug),
                                        extra={"slug": slug, "relative_path": f"{self.FOLDER}/{slug}.json"})

    # ------------------------------------------------------------ 节点级操作
    def add_node(self, campaign_id: str | None, slug: str, node: dict | None = None,
                 *, attach_to: str | None = None, as_choice: bool = False, label: str = "") -> dict:
        story = self.get(campaign_id, slug)
        nodes = story.setdefault("nodes", [])
        nid = (node or {}).get("id") or uid("n")
        if any(n.get("id") == nid for n in nodes):
            raise Conflict(f"节点 id 已存在：{nid}")

        count = len(nodes)
        new_node = {
            "id": nid,
            "type": (node or {}).get("type", "main" if not as_choice else "branch"),
            "title": (node or {}).get("title", f"节点 {count + 1}"),
            "text": (node or {}).get("text", ""),
            "tags": (node or {}).get("tags", []),
            "effects": (node or {}).get("effects", []),
            "choices": (node or {}).get("choices", []),
            "next": (node or {}).get("next"),
            "position": (node or {}).get("position") or {"x": 320, "y": 80 + count * 130},
        }
        nodes.append(new_node)

        if attach_to:
            parent = self._node(story, attach_to)
            if as_choice:
                parent.setdefault("choices", []).append({
                    "id": uid("c"), "label": label or "新选项", "target": nid,
                    "condition": None, "effects": [],
                })
            else:
                parent["next"] = nid

        if (new_node.get("type") or "") == "ending":
            new_node.setdefault("ending_type", "neutral")
        validate_document("story", story)
        self.save(campaign_id, slug, story)
        self.emit("story/node_added", {"slug": slug, "node": new_node})
        return new_node

    def update_node(self, campaign_id: str | None, slug: str, node_id: str, patch: dict) -> dict:
        story = self.get(campaign_id, slug)
        node = self._node(story, node_id)
        for k, v in (patch or {}).items():
            if k == "id":
                continue
            node[k] = v
        validate_document("story", story)
        self.save(campaign_id, slug, story)
        self.emit("story/node_updated", {"slug": slug, "node": node})
        return node

    def delete_node(self, campaign_id: str | None, slug: str, node_id: str, *,
                    relink: bool = True) -> dict:
        """删除节点，并清理所有指向它的连线。

        relink=True 时会把「父节点 -> 被删节点」的连线接到它的后继上，
        避免图谱断开，这是编辑器里最常见的误操作场景。
        """
        story = self.get(campaign_id, slug)
        node = self._node(story, node_id)
        successor = node.get("next") or (node.get("choices") or [{}])[0].get("target")

        if story.get("start_node") == node_id:
            raise ValidationFailed("起始节点不可删除，请先修改 start_node")

        for n in story.get("nodes", []):
            if relink and n.get("next") == node_id:
                n["next"] = successor
            elif n.get("next") == node_id:
                n["next"] = None
            kept = []
            for c in n.get("choices") or []:
                if c.get("target") != node_id:
                    kept.append(c)
                elif relink and successor:
                    kept.append({**c, "target": successor})
            n["choices"] = kept

        story["nodes"] = [n for n in story["nodes"] if n.get("id") != node_id]
        self.save(campaign_id, slug, story)
        self.emit("story/node_deleted", {"slug": slug, "node_id": node_id})
        return {"deleted": node_id, "relinked_to": successor if relink else None}

    def link(self, campaign_id: str | None, slug: str, source: str, target: str,
             *, kind: str = "next", label: str = "") -> dict:
        story = self.get(campaign_id, slug)
        parent = self._node(story, source)
        self._node(story, target)  # 确认目标存在
        if kind == "next":
            parent["next"] = target
        else:
            parent.setdefault("choices", []).append(
                {"id": uid("c"), "label": label or "新分支", "target": target,
                 "condition": None, "effects": []})
        validate_document("story", story)
        self.save(campaign_id, slug, story)
        return {"source": source, "target": target, "kind": kind}

    @staticmethod
    def _node(story: dict, node_id: str) -> dict:
        for n in story.get("nodes") or []:
            if n.get("id") == node_id:
                return n
        raise NotFound(f"节点不存在：{node_id}")

    # ------------------------------------------------------------ 分析
    def validate_graph(self, campaign_id: str | None, slug: str) -> dict:
        story = self.get(campaign_id, slug)
        try:
            validate_document("story", story)
        except ValidationFailed as e:
            return {"valid": False, "errors": [e.message] + list((e.details or {}).get("errors", []))}

        nodes = {n["id"]: n for n in story["nodes"]}
        seen, queue = set(), deque([story["start_node"]])
        while queue:
            cur = queue.popleft()
            if cur in seen or cur not in nodes:
                continue
            seen.add(cur)
            n = nodes[cur]
            if n.get("next"):
                queue.append(n["next"])
            for c in n.get("choices") or []:
                if c.get("target"):
                    queue.append(c["target"])

        unreachable = sorted(set(nodes) - seen)
        dead_ends = sorted(i for i, n in nodes.items()
                           if n.get("type") != "ending" and not n.get("next") and not n.get("choices"))
        return {
            "valid": True,
            "warnings": [
                *(f"节点 {i} 从起点不可达" for i in unreachable),
                *(f"节点 {i} 是死路（无后继且非结局）" for i in dead_ends),
            ],
            "unreachable": unreachable,
            "dead_ends": dead_ends,
            "reachable": len(seen),
        }

    def layout(self, campaign_id: str | None, slug: str, *,
               col_width: int = 260, row_height: int = 150) -> dict:
        """BFS 分层布局：给没有手排坐标的节点自动安排层/列，前端直接渲染。"""
        story = self.get(campaign_id, slug)
        nodes = {n["id"]: n for n in story["nodes"]}
        level: dict[str, int] = {story["start_node"]: 0}
        order_q = deque([story["start_node"]])
        while order_q:
            cur = order_q.popleft()
            for nxt in _successors(nodes.get(cur, {})):
                if nxt in nodes and nxt not in level:
                    level[nxt] = level[cur] + 1
                    order_q.append(nxt)
        # 孤立节点补到最后一层的下一层
        base = max(level.values(), default=-1) + 1
        for i in nodes:
            level.setdefault(i, base)

        buckets: dict[int, list[str]] = {}
        for nid, lv in level.items():
            buckets.setdefault(lv, []).append(nid)

        positions = {}
        for lv, ids in buckets.items():
            for idx, nid in enumerate(sorted(ids)):
                pos = (nodes[nid].get("position") or {})
                if pos.get("locked"):
                    positions[nid] = {"x": pos.get("x", 0), "y": pos.get("y", 0)}
                else:
                    positions[nid] = {"x": 80 + lv * col_width, "y": 80 + idx * row_height}
        return {"positions": positions, "levels": len(buckets)}

    def to_dot(self, campaign_id: str | None, slug: str) -> str:
        """导出 Graphviz DOT：`dot -Tsvg story.dot -o story.svg` 即可得矢量流程图。"""
        story = self.get(campaign_id, slug)
        shape = {"main": "box", "branch": "box3d", "ending": "doubleoctagon"}
        color = {"main": "#2563eb", "branch": "#7c3aed", "ending": "#dc2626"}
        lines = ["digraph story {", '  rankdir=LR;',
                 '  node [fontname="Microsoft YaHei", style="rounded,filled", fillcolor="#f8fafc"];',
                 f'  label="{_esc(story.get("title", ""))}"; labelloc=t;']
        for n in story.get("nodes") or []:
            nid = _q(n.get("id"))
            label = f'{_esc(n.get("title", nid))}\\n[{_esc(n.get("type", ""))}]'
            lines.append(f'  {nid} [label="{label}", shape="{shape.get(n.get("type"), "box")}", '
                         f'color="{color.get(n.get("type"), "#334155")}"];')
        for n in story.get("nodes") or []:
            nid = _q(n.get("id"))
            if n.get("next"):
                lines.append(f'  {nid} -> {_q(n["next"])} [label="继续"];')
            for c in n.get("choices") or []:
                if not c.get("target"):
                    continue
                cond = c.get("condition") or {}
                tip = _esc(cond.get("skill") or cond.get("flag") or cond.get("expr") or "")
                lines.append(f'  {nid} -> {_q(c["target"])} [label="{_esc(c.get("label", ""))}'
                             f'{"/" + tip if tip else ""}", style=dashed];')
        lines.append("}")
        return "\n".join(lines)

    def walk(self, campaign_id: str | None, slug: str, flags: dict | None = None) -> dict:
        """按当前标记模拟推进剧情，返回到达的节点路径（用于排练 / 自动朗读）。"""
        story = self.get(campaign_id, slug)
        nodes = {n["id"]: n for n in story["nodes"]}
        state = dict(story.get("flags") or {})
        state.update(flags or {})
        path, cur, guard = [], story["start_node"], 0
        while cur and guard < 200:
            node = nodes.get(cur)
            if not node:
                break
            path.append({"id": cur, "title": node.get("title"), "type": node.get("type")})
            for eff in node.get("effects") or []:
                if eff.get("type") == "flag":
                    state[eff.get("flag")] = eff.get("value", True)
            if node.get("type") == "ending":
                break
            nxt = node.get("next")
            for c in node.get("choices") or []:
                if _cond_ok(c.get("condition"), state):
                    for eff in c.get("effects") or []:
                        if eff.get("type") == "flag":
                            state[eff.get("flag")] = eff.get("value", True)
                    nxt = c.get("target")
                    break
            cur = nxt
            guard += 1
        return {"path": path, "flags": state}


def _successors(node: dict) -> list[str]:
    out = []
    if node.get("next"):
        out.append(node["next"])
    out += [c.get("target") for c in (node.get("choices") or []) if c.get("target")]
    return out


def _cond_ok(cond: dict | None, state: dict) -> bool:
    if not cond:
        return True
    kind = cond.get("type")
    if kind == "flag":
        return bool(state.get(cond.get("flag"))) == bool(cond.get("equals", True))
    if kind == "skill":
        return bool(state.get(f"skill:{cond.get('skill')}"))
    if kind == "expr":
        try:
            return bool(eval(cond.get("expr", "False"), {"__builtins__": {}}, dict(state)))
        except Exception:
            return False
    return True


def _esc(text: Any) -> str:
    return str(text).replace('"', '\\"').replace("\n", "\\n")


def _q(text: Any) -> str:
    return '"' + str(text) + '"'
