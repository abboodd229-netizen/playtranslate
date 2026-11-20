"""Sends subtitles to the TV app (and any browser) over the home network.

* WebSocket at ws://<laptop>:<port>/ws: JSON messages, see PROTOCOL below.
* http://<laptop>:<port>/overlay: a web page that shows the subtitles, for
  testing on a phone or second screen before the TV app is installed.
* UDP beacon on <discovery_port> once a second so the TV app finds the laptop
  without typing an IP address.

The server runs its own asyncio loop in a background thread. The public
methods are thread-safe and never block the caller.

PROTOCOL (version 1), server -> client:
    {"type": "hello", "protocol": 1, "server": "<name>", "style": {...}}
    {"type": "show", "seq": 12, "lines": [{"speaker": "آرثر", "text": "..."}]}
        optional "mode": "page" = a whole-screen translation (smaller text, centred)
    {"type": "hide", "seq": 12}
    {"type": "style", "style": {...}}
    {"type": "ping", "t": 1700000000.0}
client -> server:
    {"type": "hello", "client": "tv", "name": "...", "protocol": 1}
    {"type": "pong", "t": ...}
    {"type": "translate_page"}   (phone remote: translate the whole screen once)
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import sys
import threading
import time
from importlib import resources
from pathlib import Path
from typing import Callable

from aiohttp import WSMsgType, web

from .. import PROTOCOL_VERSION, __version__

log = logging.getLogger(__name__)

BEACON_MAGIC = "playtranslate"


def local_ips() -> list[str]:
    """IPv4 addresses of this machine on the local network (best guess first)."""
    ips: list[str] = []
    try:
        # No packet is sent; this just asks the OS which interface routes outward.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.168.0.1", 9))
            ips.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    good = [ip for ip in ips if not ip.startswith(("127.", "169.254."))]
    return good or ["127.0.0.1"]


def apk_path() -> Path | None:
    """The TV app bundled with this build, if any."""
    candidates = [Path(__file__).resolve().parent / "static" / "PlayTranslateTV.apk"]
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "PlayTranslateTV.apk")
    for c in candidates:
        if c.is_file():
            return c
    return None


class DisplayServer:
    def __init__(self, port: int = 8765, discovery_port: int = 8766, name: str | None = None):
        self.port = port
        self.discovery_port = discovery_port
        self.name = name or socket.gethostname()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._runner: web.AppRunner | None = None
        self._clients: dict[web.WebSocketResponse, dict] = {}
        self._state: dict | None = None  # last show message, replayed to new clients
        self._style: dict = {}
        self._seq = 0
        self._started = threading.Event()
        self._stop_event: asyncio.Event | None = None
        self.start_error: str = ""
        self.on_clients_changed: Callable[[list[dict]], None] | None = None
        # Called (from the server thread) when a phone asks for a whole-screen translation.
        self.on_translate_page: Callable[[], None] | None = None

    # ---- lifecycle ---------------------------------------------------

    def start(self, timeout: float = 5.0) -> bool:
        if self._thread and self._thread.is_alive():
            return True
        self._started.clear()
        self.start_error = ""
        self._thread = threading.Thread(target=self._run, name="display-server", daemon=True)
        self._thread.start()
        self._started.wait(timeout)
        return not self.start_error and self._started.is_set()

    def stop(self) -> None:
        loop = self._loop
        if loop and self._stop_event is not None:
            loop.call_soon_threadsafe(self._stop_event.set)
        if self._thread:
            self._thread.join(timeout=5)
        self._thread = None

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._main())
        except Exception as exc:
            log.exception("Display server crashed")
            self.start_error = str(exc)
        finally:
            self._started.set()
            loop.close()
            self._loop = None

    async def _main(self) -> None:
        self._stop_event = asyncio.Event()
        app = web.Application()
        app.router.add_get("/", self._index)
        app.router.add_get("/overlay", self._overlay)
        app.router.add_get("/remote", self._remote)
        app.router.add_get("/ws", self._ws)
        app.router.add_get("/api/state", self._api_state)
        app.router.add_get("/tv.apk", self._apk)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        # reuse_address is left at the platform default (on Windows it would let two apps share the port).
        site = web.TCPSite(self._runner, host="0.0.0.0", port=self.port)
        try:
            await site.start()
        except OSError as exc:
            self.start_error = f"المنفذ {self.port} مستخدم من برنامج آخر ({exc})"
            await self._runner.cleanup()
            self._started.set()
            return
        log.info("Display server on port %s (%s)", self.port, ", ".join(local_ips()))
        self._started.set()
        beacon = asyncio.create_task(self._beacon())
        pinger = asyncio.create_task(self._pinger())
        await self._stop_event.wait()
        beacon.cancel()
        pinger.cancel()
        for ws in list(self._clients):
            await ws.close()
        await self._runner.cleanup()

    # ---- HTTP --------------------------------------------------------

    async def _index(self, request: web.Request) -> web.Response:
        raise web.HTTPFound("/overlay")

    async def _overlay(self, request: web.Request) -> web.Response:
        html = resources.files(__package__).joinpath("static/overlay.html").read_text(encoding="utf-8")
        return web.Response(text=html, content_type="text/html", charset="utf-8")

    async def _remote(self, request: web.Request) -> web.Response:
        """A phone page with one big button: translate the whole screen."""
        html = resources.files(__package__).joinpath("static/remote.html").read_text(encoding="utf-8")
        return web.Response(text=html, content_type="text/html", charset="utf-8")

    async def _apk(self, request: web.Request) -> web.StreamResponse:
        """Lets the TV download its app from the laptop (Downloader app -> http://<laptop>:8765/tv.apk)."""
        path = apk_path()
        if path is None:
            return web.Response(status=404, text="ملف تطبيق التلفزيون غير موجود في هذه النسخة.", charset="utf-8")
        return web.FileResponse(path, headers={
            "Content-Type": "application/vnd.android.package-archive",
            "Content-Disposition": 'attachment; filename="PlayTranslateTV.apk"',
        })

    async def _api_state(self, request: web.Request) -> web.Response:
        return web.json_response({
            "server": self.name, "version": __version__, "protocol": PROTOCOL_VERSION,
            "clients": list(self._clients.values()), "showing": self._state,
        })

    async def _ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=10, max_msg_size=64 * 1024)
        await ws.prepare(request)
        info = {"address": request.remote or "?", "name": "", "client": "browser", "since": time.time()}
        self._clients[ws] = info
        self._notify_clients()
        try:
            await ws.send_json({"type": "hello", "protocol": PROTOCOL_VERSION, "server": self.name,
                                "version": __version__, "style": self._style})
            if self._state:
                await ws.send_json(self._state)
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(msg.data)
                except ValueError:
                    continue
                if not isinstance(data, dict):
                    continue
                if data.get("type") == "hello":
                    info["name"] = str(data.get("name", ""))[:64]
                    info["client"] = str(data.get("client", "browser"))[:16]
                    self._notify_clients()
                elif data.get("type") == "translate_page":
                    cb = self.on_translate_page
                    if cb:
                        try:
                            cb()
                        except Exception:
                            log.exception("on_translate_page failed")
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            self._clients.pop(ws, None)
            self._notify_clients()
        return ws

    def _notify_clients(self) -> None:
        cb = self.on_clients_changed
        if cb:
            try:
                cb(list(self._clients.values()))
            except Exception:
                log.exception("on_clients_changed failed")

    # ---- background tasks --------------------------------------------

    async def _beacon(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setblocking(False)
        try:
            while True:
                ips = local_ips()
                payload = json.dumps({"app": BEACON_MAGIC, "protocol": PROTOCOL_VERSION, "port": self.port,
                                      "name": self.name, "ips": ips}).encode("utf-8")
                targets = {"255.255.255.255"}
                for ip in ips:
                    parts = ip.split(".")
                    if len(parts) == 4:
                        # Most home networks are /24; a directed broadcast reaches the TV
                        # even when the laptop has several adapters (VPN, Hyper-V).
                        targets.add(".".join(parts[:3] + ["255"]))
                for target in targets:
                    try:
                        sock.sendto(payload, (target, self.discovery_port))
                    except OSError:
                        pass
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            pass
        finally:
            sock.close()

    async def _pinger(self) -> None:
        try:
            while True:
                await asyncio.sleep(5)
                await self._broadcast({"type": "ping", "t": time.time()})
        except asyncio.CancelledError:
            pass

    async def _broadcast(self, message: dict) -> None:
        if not self._clients:
            return
        data = json.dumps(message, ensure_ascii=False)
        dead = []
        for ws in list(self._clients):
            try:
                await ws.send_str(data)
            except (ConnectionResetError, RuntimeError):
                dead.append(ws)
        for ws in dead:
            self._clients.pop(ws, None)
        if dead:
            self._notify_clients()

    # ---- public, thread-safe -----------------------------------------

    def _submit(self, message: dict) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            asyncio.run_coroutine_threadsafe(self._broadcast(message), loop)
        except RuntimeError:
            pass

    def show(self, lines: list[dict], mode: str = "subtitle") -> int:
        """lines: [{"speaker": str, "text": str}]. Returns the sequence number."""
        self._seq += 1
        msg = {"type": "show", "seq": self._seq, "lines": lines}
        if mode != "subtitle":
            msg["mode"] = mode
        self._state = msg
        self._submit(msg)
        return self._seq

    def hide(self) -> None:
        self._state = None
        self._submit({"type": "hide", "seq": self._seq})

    def set_style(self, style: dict) -> None:
        self._style = dict(style)
        self._submit({"type": "style", "style": self._style})

    @property
    def clients(self) -> list[dict]:
        for _ in range(3):
            try:
                return [dict(c) for c in self._clients.values()]
            except RuntimeError:  # changed size while the server thread updated it
                continue
        return []

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and not self.start_error)
