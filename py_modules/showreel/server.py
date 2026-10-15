"""Read-only download page for the recordings: a list for people, JSON and latest.mp4 for tools.

It serves files the library made and nothing else, and accepts no actions (GET and HEAD only).
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
import socket
import stat
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

from .library import Library

log = logging.getLogger("showreel")
CHUNK = 64 << 10
RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


def lan_ip() -> str | None:
    """The address other devices reach us on (connecting a UDP socket sends nothing)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.168.0.1", 9))
            return s.getsockname()[0]
    except OSError:
        return None


def _size(n: int) -> str:
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{round(n / 1e6)} MB" if n >= 1e6 else f"{round(n / 1e3)} KB"


class DownloadServer:
    def __init__(self, library: Library, port: int = 8790, host: str = "0.0.0.0") -> None:
        self._library, self._host, self.port = library, host, port
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._httpd is not None

    def start(self) -> None:
        if self._httpd is not None:
            return
        library = self._library

        class Handler(_Handler):
            lib = library

        self._httpd = ThreadingHTTPServer((self._host, self.port), Handler)
        self._httpd.daemon_threads = True
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="showreel-http", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        httpd, self._httpd = self._httpd, None
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
            if self._thread is not None:
                self._thread.join(2.0)


class _Handler(BaseHTTPRequestHandler):
    lib: Library
    server_version = "Showreel"
    sys_version = ""

    def log_message(self, fmt, *args):  # noqa: N802 (stdlib name)
        log.debug("[showreel] http " + fmt, *args)

    def _not_allowed(self):
        self.send_response(405)
        self.send_header("Allow", "GET, HEAD")
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _not_allowed

    def do_HEAD(self):  # noqa: N802
        self._route(head=True)

    def do_GET(self):  # noqa: N802
        self._route(head=False)

    def _route(self, head: bool) -> None:
        path = urlsplit(self.path).path
        if path == "/":
            return self._send_bytes(self._index().encode(), "text/html; charset=utf-8", head)
        if path == "/recordings.json":
            return self._send_bytes(json.dumps(self.lib.recordings()).encode(), "application/json", head)
        if path == "/latest.mp4":
            return self._send_file(self.lib.resolve("latest.mp4"), head)
        if path.startswith("/files/"):
            name = unquote(path[len("/files/"):])
            if "/" not in name and name != "latest.mp4":
                return self._send_file(self.lib.resolve(name), head)
        self._send_bytes(b"Not found\n", "text/plain", head, status=404)

    def _index(self) -> str:
        rows = "".join(
            f'<li><a href="/files/{html.escape(r["name"])}">{html.escape(r["name"])}</a> · {_size(r["size"])}'
            + (f' · {r["duration"]:.0f} s' if r["duration"] else "") + "</li>"
            for r in self.lib.recordings())
        return ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
                "<title>Showreel</title><style>body{font:16px system-ui;margin:2em auto;max-width:40em;padding:0 1em}"
                "li{margin:.4em 0}</style><h1>Showreel</h1>"
                + (f"<ul>{rows}</ul>" if rows else "<p>No recordings yet.</p>")
                + "<p><a href='/latest.mp4'>latest.mp4</a> · <a href='/recordings.json'>recordings.json</a></p>")

    def _send_bytes(self, body: bytes, ctype: str, head: bool, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def _send_file(self, path: str | None, head: bool) -> None:
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW) if path else -1
        except OSError:
            fd = -1
        if fd < 0 or not stat.S_ISREG(os.fstat(fd).st_mode):
            if fd >= 0:
                os.close(fd)
            return self._send_bytes(b"Not found\n", "text/plain", head, status=404)
        with os.fdopen(fd, "rb") as f:
            self._send_open_file(f, os.fstat(fd).st_size, head)

    def _send_open_file(self, f, size: int, head: bool) -> None:
        start, end, status = 0, size - 1, 200
        wanted = self.headers.get("Range")
        if wanted:
            m = RANGE_RE.match(wanted.strip())
            if m and (m.group(1) or m.group(2)):
                if m.group(1):
                    start = int(m.group(1))
                    end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
                else:
                    start = max(size - int(m.group(2)), 0)
                if start >= size or start > end:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                status = 206
        self.send_response(status)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if head:
            return
        f.seek(start)
        left = end - start + 1
        while left > 0:
            chunk = f.read(min(CHUNK, left))
            if not chunk:
                break
            self.wfile.write(chunk)
            left -= len(chunk)
