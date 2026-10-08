"""JSON / 文本原子读写。

原子写策略：写临时文件 -> fsync -> os.replace。
任何崩溃都不会留下半截 JSON，这是本地工具可靠性的底线。
"""
from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

READ_SUFFIX = {".json", ".txt", ".md", ".yaml", ".yml", ".csv", ".dot", ".log", ".jsonl"}
MAX_FILE_BYTES = 8 * 1024 * 1024  # 单文件 8MB 上限，防止误拖电影进来


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def uid(prefix: str = "") -> str:
    return (prefix + secrets.token_hex(6)) if prefix else secrets.token_hex(8)


def slugify(text: str, fallback: str = "item") -> str:
    text = unicodedata.normalize("NFKC", str(text)).strip().lower()
    text = re.sub(r"[^\w\u4e00-\u9fff]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or fallback


def read_json(path: Path, default: Any = None) -> Any:
    if not Path(path).exists():
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any, *, indent: int = 2) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)  # POSIX/Windows 均为原子替换
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def read_text(path: Path, default: str = "") -> str:
    if not Path(path).exists():
        return default
    return Path(path).read_text(encoding="utf-8", errors="replace")


def write_text(path: Path, content: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".txt", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def read_jsonl(path: Path) -> list[dict]:
    if not Path(path).exists():
        return []
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # 容错：坏行跳过，不阻塞整体加载
    return out


def cleanup_temp_files(root: Path, *, pattern: str = ".tmp-*") -> int:
    """启动时清理原子写残留。

    写入流程是「临时文件 → os.replace」，进程被强杀时临时文件会留在目录里。
    它们同样是 .json，会被列表接口当成正常数据读出来
    （表现为剧情下拉框里多出一个打不开的条目）。
    启动阶段不存在并发写入，所以这里遇到的 .tmp-* 一律视作残留。
    """
    root = Path(root)
    if not root.exists():
        return 0
    removed = 0
    for f in root.rglob(pattern):
        try:
            if f.is_file():
                f.unlink()
                removed += 1
        except OSError:
            pass  # 删不掉就算了，列表层也已经过滤了
    return removed


def append_jsonl(path: Path, record: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush()
