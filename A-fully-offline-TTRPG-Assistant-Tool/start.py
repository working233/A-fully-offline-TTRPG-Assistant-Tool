#!/usr/bin/env python3
"""一键启动脚本（跨平台）—— 所有中文提示都从这里输出。

Windows 用户请双击 `启动跑团工具.bat`，它只负责找到解释器，然后调用本脚本。
macOS / Linux 直接：python3 start.py
参数原样透传，例如：start.py --no-open --port 9000
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _console_encoding() -> str:
    """跟随当前控制台的实际编码，避免在 GBK 控制台里输出 UTF-8 变乱码。"""
    enc = getattr(sys.stdout, "encoding", None)
    return (enc or "utf-8").replace("cp65001", "utf-8")


def _say(msg: str = "") -> None:
    try:
        print(msg)
    except UnicodeEncodeError:  # 控制台编码表达不了的字符，退化处理而不是崩溃
        enc = _console_encoding()
        try:
            sys.stdout.flush()
            sys.stdout.buffer.write((msg + "\n").encode(enc, "replace"))
            sys.stdout.flush()
        except Exception:
            print(msg.encode("ascii", "replace").decode())


def check_python() -> bool:
    if sys.version_info < (3, 11):
        _say(f"[错误] 当前 Python 是 {sys.version.split()[0]}，本工具需要 3.11 或更高版本。")
        _say("       升级地址：https://www.python.org/downloads/")
        return False
    _say(f"[1/3] Python 版本检查通过：{sys.version.split()[0]}")
    return True


def run_doctor(py: str, env: dict) -> None:
    """自检子进程要用和终端一致的编码，否则它的 UTF-8 输出会在 GBK 控制台变乱码。"""
    _say("")
    _say("[2/3] 数据目录自检：")
    try:
        subprocess.run([py, "-m", "app.main", "--doctor"], cwd=ROOT, check=False, env=env)
    except Exception as e:
        _say(f"       自检跳过（{e}）")


def wait_key() -> None:
    if sys.platform != "win32":
        return
    try:
        _say("")
        input("服务已结束，按回车键关闭窗口…")
    except EOFError:
        pass


def main() -> int:
    os.chdir(ROOT)
    _say("=" * 58)
    _say("   本地跑团辅助工具  ·  一键启动")
    _say("=" * 58)
    _say("")

    if not (ROOT / "app" / "main.py").exists():
        _say(f"[错误] 在 {ROOT} 下找不到 app/main.py")
        _say("       请确认本脚本与 README.md 在同一目录下。")
        wait_key()
        return 1

    if not check_python():
        wait_key()
        return 2

    env = os.environ.copy()
    # 让子进程的输出编码跟随控制台，避免终端里出现乱码
    env["PYTHONIOENCODING"] = _console_encoding()
    env.pop("PYTHONUTF8", None)

    run_doctor(sys.executable, env)

    _say("")
    _say("[3/3] 启动本地服务器（浏览器会自动打开）")
    _say("      直接关掉浏览器，服务约 25 秒后自动退出；想立刻停止按 Ctrl+C。")
    _say("-" * 58)

    env = os.environ.copy()
    # 让子进程的输出编码跟随控制台，避免终端里出现乱码
    env["PYTHONIOENCODING"] = _console_encoding()
    env.pop("PYTHONUTF8", None)

    try:
        code = subprocess.run(
            [sys.executable, "-m", "app.main", *sys.argv[1:]], cwd=ROOT, env=env
        ).returncode
    except KeyboardInterrupt:
        _say("\n已停止。")
        code = 0

    wait_key()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
