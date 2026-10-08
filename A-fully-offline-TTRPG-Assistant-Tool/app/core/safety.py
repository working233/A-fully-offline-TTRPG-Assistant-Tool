"""安全守卫：任何落盘或读取操作，都必须证明目标位于数据根之内。"""
from __future__ import annotations

import os
from pathlib import Path

from .errors import SafetyViolation


def _norm(p: Path) -> str:
    # Windows 下路径大小写不敏感，统一归一化避免绕过根目录检查
    return os.path.normcase(os.path.normpath(str(p)))


def ensure_inside(root: Path, target: Path | str, *, must_exist: bool = False) -> Path:
    """校验 target 位于 root 内（含 root 自身），返回解析后的绝对路径。

    防止 `../..` 穿越构造的路径注入；这是所有 File IO 的唯一入口。
    """
    root_r = Path(root).resolve()
    target_r = Path(target)
    target_r = (target_r if target_r.is_absolute() else (root_r / target_r)).resolve()

    if _norm(target_r) != _norm(root_r) and not _norm(target_r).startswith(_norm(root_r) + os.sep):
        raise SafetyViolation(f"路径越界：{target}", {"resolved": str(target_r), "root": str(root_r)})

    if must_exist and not target_r.exists():
        raise SafetyViolation(f"路径不存在：{target_r}")
    return target_r


def safe_name(name: str) -> str:
    """清洗单级文件名，禁止路径分隔符与控制字符。"""
    cleaned = name.replace("\\", "_").replace("/", "_").replace("\x00", "")
    cleaned = cleaned.strip().strip(".")
    if cleaned in ("", ".", ".."):
        raise SafetyViolation(f"非法文件名：{name!r}")
    return cleaned
