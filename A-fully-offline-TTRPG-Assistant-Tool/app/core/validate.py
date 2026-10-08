"""轻量 schema 校验。

不引入 jsonschema 依赖，用声明式 DSL 描述必填项、类型与取值域，
既能做数据校验，也能直接喂给前端渲染表单（GET /api/schema/<kind>）。
"""
from __future__ import annotations

from typing import Any

from .errors import ValidationFailed

# 支持的规则系统，新增规则只需在此登记
RULE_SYSTEMS = ["DND 5e", "COC 7th", "泛用/无规则", "自定义"]

CHARACTER_SCHEMA: dict[str, Any] = {
    "kind": "character",
    "label": "人物卡",
    "required": ["id", "system", "name"],
    "fields": [
        {"key": "name", "label": "姓名", "type": "string", "placeholder": "例如：瓦伦·索恩"},
        {"key": "player", "label": "玩家", "type": "string"},
        {"key": "system", "label": "规则", "type": "enum", "options": RULE_SYSTEMS},
        {"key": "race", "label": "种族", "type": "string"},
        {"key": "klass", "label": "职业", "type": "string"},
        {"key": "level", "label": "等级", "type": "number", "min": 0, "max": 30, "default": 1},
        {"key": "hp", "label": "生命值", "type": "group", "children": [
            {"key": "current", "label": "当前", "type": "number"},
            {"key": "max", "label": "上限", "type": "number"},
            {"key": "temp", "label": "临时", "type": "number", "default": 0},
        ]},
        {"key": "ac", "label": "护甲等级", "type": "number", "default": 10},
        {"key": "speed", "label": "速度", "type": "string", "default": "30尺"},
        {"key": "attributes", "label": "属性", "type": "map", "value_type": "number"},
        {"key": "skills", "label": "技能", "type": "map", "value_type": "number"},
        {"key": "saves", "label": "豁免", "type": "map", "value_type": "number"},
        {"key": "equipment", "label": "装备", "type": "list", "item_type": "string"},
        {"key": "features", "label": "特性/法术", "type": "list", "item_type": "string"},
        {"key": "background", "label": "背景", "type": "textarea"},
        {"key": "notes", "label": "备注", "type": "textarea"},
        {"key": "portrait", "label": "立绘路径", "type": "string", "placeholder": "assets/valen.png（跑团目录内的相对路径）"},
    ],
}

MONSTER_SCHEMA: dict[str, Any] = {
    "kind": "monster",
    "label": "怪物卡",
    "required": ["id", "system", "name"],
    "fields": [
        {"key": "name", "label": "名称", "type": "string"},
        {"key": "system", "label": "规则", "type": "enum", "options": RULE_SYSTEMS},
        {"key": "type", "label": "类型/体型", "type": "string", "placeholder": "中型 异怪"},
        {"key": "alignment", "label": "阵营", "type": "string"},
        {"key": "cr", "label": "挑战等级", "type": "string", "placeholder": "1/2"},
        {"key": "hp", "label": "生命值", "type": "group", "children": [
            {"key": "current", "label": "当前", "type": "number"},
            {"key": "max", "label": "上限", "type": "number"},
        ]},
        {"key": "ac", "label": "护甲等级", "type": "number", "default": 10},
        {"key": "speed", "label": "速度", "type": "string", "default": "30尺"},
        {"key": "attributes", "label": "属性", "type": "map", "value_type": "number"},
        {"key": "skills", "label": "技能/豁免", "type": "map", "value_type": "number"},
        {"key": "resistances", "label": "抗性", "type": "list", "item_type": "string"},
        {"key": "immunities", "label": "免疫", "type": "list", "item_type": "string"},
        {"key": "vulnerabilities", "label": "易伤", "type": "list", "item_type": "string"},
        {"key": "attacks", "label": "攻击动作", "type": "list", "item_type": "object"},
        {"key": "abilities", "label": "特殊能力", "type": "list", "item_type": "string"},
        {"key": "description", "label": "描述", "type": "textarea"},
        {"key": "loot", "label": "掉落", "type": "list", "item_type": "string"},
    ],
}

STORY_SCHEMA: dict[str, Any] = {
    "kind": "story",
    "label": "剧情",
    "required": ["id", "title", "start_node", "nodes"],
    "fields": [
        {"key": "title", "label": "标题", "type": "string"},
        {"key": "system", "label": "规则", "type": "enum", "options": RULE_SYSTEMS},
        {"key": "synopsis", "label": "简介", "type": "textarea"},
        {"key": "start_node", "label": "起始节点", "type": "string"},
    ],
}

SCHEMAS = {"character": CHARACTER_SCHEMA, "monster": MONSTER_SCHEMA, "story": STORY_SCHEMA}

NODE_TYPES = ["main", "branch", "ending"]
ENDINGS = ["good", "bad", "neutral", "open"]


def validate_document(kind: str, data: dict) -> dict:
    schema = SCHEMAS.get(kind)
    if not schema:
        raise ValidationFailed(f"未知数据类型：{kind}")
    if not isinstance(data, dict):
        raise ValidationFailed(f"{kind} 必须是 JSON 对象")
    missing = [k for k in schema["required"] if k not in data or data[k] in (None, "")]
    if missing:
        raise ValidationFailed(f"缺少必填字段：{', '.join(missing)}", {"missing": missing})

    if kind == "story":
        _validate_story(data)
    return data


def _validate_story(story: dict) -> None:
    nodes = story.get("nodes") or []
    if not isinstance(nodes, list) or not nodes:
        raise ValidationFailed("剧情至少需要一个节点")
    ids = [n.get("id") for n in nodes]
    if len(ids) != len(set(ids)):
        dup = [i for i in ids if ids.count(i) > 1]
        raise ValidationFailed(f"节点 id 重复：{sorted(set(dup))}")

    idset = set(ids)
    if story.get("start_node") not in idset:
        raise ValidationFailed(f"起始节点 {story.get('start_node')} 不存在")

    errors = []
    for n in nodes:
        nid = n.get("id")
        if n.get("type") not in NODE_TYPES:
            errors.append(f"节点 {nid}: type 必须是 {NODE_TYPES} 之一")
        if n.get("type") == "ending" and n.get("ending_type") not in ENDINGS:
            errors.append(f"节点 {nid}: ending_type 必须是 {ENDINGS} 之一")
        targets = []
        if n.get("next"):
            targets.append(n["next"])
        for c in n.get("choices", []) or []:
            if not c.get("id"):
                errors.append(f"节点 {nid}: 分支缺少 id")
            if c.get("target"):
                targets.append(c["target"])
        for t in targets:
            if t not in idset:
                errors.append(f"节点 {nid}: 目标节点 {t} 不存在")
    if errors:
        raise ValidationFailed("剧情图谱校验失败", {"errors": errors})
