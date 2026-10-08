"""内置智能本地服务器。

关键约束（本地优先 / 隐私优先）：
    1. 只绑定回环地址 127.0.0.1，局域网内其他设备无法访问；
    2. 端口自动分配：先尝试偏好区间，全部被占用则交给内核分配空闲端口；
    3. 心跳看门狗：前端每 5 秒 ping 一次；浏览器关闭后超过阈值自动退出进程，
       不留后台常驻进程，也不占用端口；
    4. 静态资源与 API 走同一个端口，避免 CORS 与跨端口凭证问题。
"""
from __future__ import annotations

import socket
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

from .api import ApiRouter, HttpAdapter
from .core.jsonio import now_iso
from .services import ServiceRegistry

PREFERRED_PORTS = range(8765, 8805)


class ApiHandler(BaseHTTPRequestHandler):
    server_version = "TRPG-Local/0.1"
    router: ApiRouter
    web_dir: Path
    keepalive = False

    # ---------------------------------------------------------------- 通用收发
    def _respond(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass

    def _handle(self, method: str) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        self.server.touch(ping=self.path.startswith("/api/ping"))  # type: ignore[attr-defined]
        try:
            status, body, ctype = HttpAdapter.handle_request(
                self.router, self.web_dir, method, self.path, raw)
        except Exception as exc:  # noqa: BLE001 - 统一错误出口
            status, body = HttpAdapter.error_payload(exc)
            ctype = "application/json; charset=utf-8"
        self._respond(status, body, ctype)

    def do_GET(self) -> None:  # noqa: N802
        self._handle("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._handle("POST")

    def do_PUT(self) -> None:  # noqa: N802
        self._handle("PUT")

    def do_PATCH(self) -> None:  # noqa: N802
        self._handle("PATCH")

    def do_DELETE(self) -> None:  # noqa: N802
        self._handle("DELETE")

    def do_HEAD(self) -> None:  # noqa: N802
        self._respond(200, b"", "text/plain; charset=utf-8")

    def log_message(self, fmt: str, *args) -> None:  # 静默，避免刷屏
        pass


class TrpgServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, handler_cls, *, heartbeat_timeout: float, on_stop=None) -> None:
        super().__init__(addr, handler_cls)
        self._last_seen = time.time()
        self._seen_pings = False
        self._heartbeat_timeout = heartbeat_timeout
        self._on_stop = on_stop
        self._lock = threading.Lock()

    def touch(self, ping: bool = False) -> None:
        with self._lock:
            self._last_seen = time.time()
            if ping:
                self._seen_pings = True

    @property
    def idle_seconds(self) -> float:
        return time.time() - self._last_seen

    @property
    def had_pings(self) -> bool:
        return self._seen_pings

    def _watchdog(self) -> None:
        while True:
            time.sleep(2)
            if self.had_pings and self.idle_seconds > self._heartbeat_timeout:
                print(f"\n[server] 浏览器已关闭（{self.idle_seconds:.0f}s 无心跳），正在停止本地服务……")
                if self._on_stop:
                    try:
                        self._on_stop()
                    except Exception:
                        pass
                threading.Thread(target=self.shutdown, daemon=True).start()
                return


class LocalServer:
    def __init__(self, registry: ServiceRegistry, web_dir: Path | str, *,
                 host: str = "127.0.0.1", port: int | None = None,
                 heartbeat_timeout: float = 25.0, open_browser: bool = True,
                 verbose: bool = True) -> None:
        self.registry = registry
        self.web_dir = Path(web_dir)
        self.host = host
        self.requested_port = port
        self.heartbeat_timeout = heartbeat_timeout
        self.open_browser = open_browser
        self.verbose = verbose
        self.httpd: TrpgServer | None = None

    # ---------------------------------------------------------------- 端口
    def pick_port(self) -> int:
        if self.requested_port:
            if _port_free(self.host, self.requested_port):
                return self.requested_port
            raise OSError(f"端口 {self.requested_port} 已被占用，请换一个（或省略 --port 自动分配）")
        for p in PREFERRED_PORTS:
            if _port_free(self.host, p):
                return p
        with socket.socket() as s:  # 交给内核分配
            s.bind((self.host, 0))
            return s.getsockname()[1]

    # ---------------------------------------------------------------- 启动
    def serve(self) -> str:
        port = self.pick_port()
        handler = type("BoundHandler", (ApiHandler,), {"router": ApiRouter(self.registry),
                                                       "web_dir": self.web_dir})
        httpd = TrpgServer((self.host, port), handler,
                           heartbeat_timeout=self.heartbeat_timeout, on_stop=None)
        self.httpd = httpd
        base = f"http://{self.host}:{port}"
        threading.Thread(target=httpd._watchdog, daemon=True).start()

        try:
            self.registry.campaigns.paths.ensure()
            if self.registry.campaigns.list():
                self.registry.set_persistent_dice_history(self.registry.campaigns.active_id())
        except Exception:
            pass

        print("=" * 62)
        print(f"  本地跑团辅助工具 · Web 编辑器已就绪")
        print(f"  访问地址：{base}")
        print(f"  数据目录：{self.registry.paths.root}")
        print(f"  仅监听回环地址 {self.host}，外部设备无法访问")
        print(f"  浏览器关闭后约 {int(self.heartbeat_timeout)}s 自动停止服务")
        print("=" * 62)
        if self.open_browser:
            threading.Timer(0.6, lambda: webbrowser.open(base)).start()

        try:
            httpd.serve_forever(poll_interval=0.5)
        except KeyboardInterrupt:
            print("\n[server] 收到中断信号，正在关闭……")
        finally:
            httpd.server_close()
            print(f"[server] {now_iso()} 已停止")
        return base


def _port_free(host: str, port: int) -> bool:
    if port <= 0 or port > 65535:
        return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False
