"""命令行入口。

用法：
    python -m app.main                 # 启动本地服务器并自动打开浏览器
    python -m app.main --port 9000     # 指定端口
    python -m app.main --no-open       # 不自动打开浏览器（便于自己用手机/远程调试）
    python -m app.main --seed-demo     # 导入示例跑团数据
    python -m app.main --backup        # 生成一次全量备份
    python -m app.main --doctor        # 自检（目录、端口、数据完整性）
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

# Windows 控制台默认 GBK，通常统一输出编码避免中文乱码；
# 但如果调用方（如 start.py）已经指定了 PYTHONIOENCODING，就尊重它，
# 否则在 GBK 终端里打印 UTF-8 反而会变成乱码。
if sys.version_info >= (3, 9) and not os.environ.get("PYTHONIOENCODING"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from .core.paths import APP_VERSION, Paths, WEB_DIR  # noqa: E402
from .services import ServiceRegistry  # noqa: E402
from .server import LocalServer  # noqa: E402

SAMPLE_DIR = Path(__file__).resolve().parents[1] / "samples" / "demo-campaign"


def build_registry(data_root: str | None = None) -> ServiceRegistry:
    paths = Paths(data_root).ensure() if data_root else Paths().ensure()
    return ServiceRegistry(paths)


def seed_demo(registry: ServiceRegistry) -> str:
    """把仓库内的示例跑团复制进数据目录（已存在则跳过）。"""
    if not SAMPLE_DIR.exists():
        print(f"[seed] 示例目录不存在：{SAMPLE_DIR}")
        return ""
    for folder in sorted(SAMPLE_DIR.iterdir()):
        if not folder.is_dir():
            continue
        target = registry.paths.campaigns / folder.name
        if target.exists():
            print(f"[seed] 已存在，跳过：{folder.name}")
            continue
        shutil.copytree(folder, target)
        print(f"[seed] 已导入示例跑团：{folder.name}")
    first = next(iter(sorted(registry.paths.campaigns.iterdir())), None)
    if first and not registry.campaigns.active_id():
        registry.campaigns.set_active(first.name)
        registry.set_persistent_dice_history(first.name)
    return str(first) if first else ""


def doctor(registry: ServiceRegistry) -> int:
    print("=== 环境自检 ===")
    print(f"Python      : {sys.version.split()[0]}")
    print(f"版本        : {APP_VERSION}")
    print(f"数据根目录  : {registry.paths.root}")
    print(f"跑团数量    : {len(registry.campaigns.list())}")
    print(f"当前跑团    : {registry.campaigns.active_id() or '(未选择)'}")
    print(f"前端目录    : {WEB_DIR}  存在={WEB_DIR.exists()}")
    bad = 0
    for c in registry.campaigns.list():
        try:
            report = registry.stories.list(c["id"])
            invalid = [s["slug"] for s in report
                       if not registry.stories.validate_graph(c["id"], s["slug"])["valid"]]
            print(f"  - {c['name']}: 剧情 {len(report)} 篇，异常 {len(invalid)}")
            bad += len(invalid)
        except Exception as e:
            print(f"  - {c['name']}: 检查失败 {e}")
            bad += 1
    print(f"回收站条目  : {len(registry.trash.list())}")
    print(f"备份文件    : {len(registry.backups.list())}")
    print("结论        :", "一切正常" if bad == 0 else f"发现 {bad} 处异常")
    return 0 if bad == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.main",
                                     description="本地跑团辅助工具（全量本地存储，无云端依赖）")
    parser.add_argument("--port", type=int, default=None, help="指定端口，默认自动分配")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址，默认 127.0.0.1（仅本机）")
    parser.add_argument("--data-dir", default=None, help="数据根目录，默认 ~/TRPG-Local-Assistant")
    parser.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    parser.add_argument("--heartbeat", type=float, default=25.0, help="心跳超时秒数，超时即自动停止")
    parser.add_argument("--seed-demo", action="store_true", help="导入示例跑团数据")
    parser.add_argument("--backup", action="store_true", help="生成一次全量备份")
    parser.add_argument("--doctor", action="store_true", help="运行环境自检")
    args = parser.parse_args(argv)

    registry = build_registry(args.data_dir)

    if args.seed_demo:
        seed_demo(registry)
        return 0
    if args.backup:
        path = registry.backups.create()
        print(f"[backup] 已生成：{path}")
        return 0
    if args.doctor:
        return doctor(registry)

    if not registry.campaigns.list():
        print("[init] 数据目录为空，自动导入示例跑团……")
        seed_demo(registry)

    server = LocalServer(registry, WEB_DIR, host=args.host, port=args.port,
                         heartbeat_timeout=args.heartbeat, open_browser=not args.no_open)
    try:
        server.serve()
    except OSError as e:
        print(f"[error] {e}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
