"""Service 基类：统一持有 Paths / EventBus，并提供轻量撤销支持。"""
from __future__ import annotations

from typing import Any

from ..core.events import EventBus
from ..core.paths import Paths


class BaseService:
    """所有业务服务的共同父亲。

    分层约定：
        Service 只做业务与 IO，**绝不引用 UI/Tk/HTTP**；
        UI 通过返回值 + 事件总线感知变化，二者可独立演进与测试。
    """

    def __init__(self, paths: Paths | None = None, bus: EventBus | None = None) -> None:
        self.paths = paths or Paths()
        self.bus = bus or EventBus()

    def emit(self, topic: str, payload: dict | None = None) -> None:
        self.bus.emit(topic, payload)

    def log(self, message: str, level: str = "info", **extra: Any) -> None:
        self.bus.emit("log", {"level": level, "message": message, **extra})
