"""极简事件总线：UI 层订阅、Service 层发布，实现双向解耦。"""
from __future__ import annotations

from collections import defaultdict
from typing import Callable


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[Callable[[dict], None]]] = defaultdict(list)

    def on(self, topic: str, fn: Callable[[dict], None]) -> Callable[[], None]:
        self._subs[topic].append(fn)

        def _off():
            try:
                self._subs[topic].remove(fn)
            except ValueError:
                pass

        return _off

    def emit(self, topic: str, payload: dict | None = None) -> None:
        payload = payload or {}
        for fn in list(self._subs.get(topic, [])):
            try:
                fn(payload)
            except Exception:  # 订阅者异常不应打断发布者
                pass
        for fn in list(self._subs.get("*", [])):
            try:
                fn({"topic": topic, **payload})
            except Exception:
                pass

    def subscribers(self, topic: str) -> int:
        return len(self._subs.get(topic, []))
