import http.client
import json
import os
import socket

import pytest

from showreel.library import Library
from showreel.server import DownloadServer

A, B = "2026-10-15_10-00-00.mp4", "2026-10-15_11-00-00.mp4"


@pytest.fixture
def served(tmp_path):
    library = Library(str(tmp_path / "Showreel"), probe_duration=lambda p: 3.0)
    library.ensure()
    for name, mtime, data in ((A, 100, b"0123456789"), (B, 200, b"abcdefghijklmnop")):
        path = os.path.join(library.root, name)
        with open(path, "wb") as f:
            f.write(data)
        os.utime(path, (mtime, mtime))
    library.update_latest()
    server = DownloadServer(library, port=0, host="127.0.0.1")
    server.start()
    yield library, server
    server.stop()


def get(server, path, method="GET", headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    conn.request(method, path, headers=headers or {})
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp, body


def test_index_lists_recordings(served):
    _lib, server = served
    resp, body = get(server, "/")
    assert resp.status == 200 and resp.getheader("Content-Type").startswith("text/html")
    assert f'href="/files/{A}"'.encode() in body and f'href="/files/{B}"'.encode() in body


def test_json(served):
    library, server = served
    resp, body = get(server, "/recordings.json")
    assert resp.status == 200 and json.loads(body) == library.recordings()


def test_latest_and_files_serve_bytes(served):
    _lib, server = served
    resp, body = get(server, "/latest.mp4")
    assert resp.status == 200 and body == b"abcdefghijklmnop" and resp.getheader("Content-Type") == "video/mp4"
    resp, body = get(server, f"/files/{A}")
    assert body == b"0123456789"
    resp, body = get(server, f"/files/{A}", method="HEAD")
    assert resp.status == 200 and body == b"" and resp.getheader("Content-Length") == "10"


def test_range(served):
    _lib, server = served
    resp, body = get(server, f"/files/{A}", headers={"Range": "bytes=2-5"})
    assert resp.status == 206 and body == b"2345" and resp.getheader("Content-Range") == "bytes 2-5/10"
    resp, body = get(server, f"/files/{A}", headers={"Range": "bytes=7-"})
    assert resp.status == 206 and body == b"789"
    resp, _ = get(server, f"/files/{A}", headers={"Range": "bytes=999999-"})
    assert resp.status == 416


def test_rejects(served):
    _lib, server = served
    for path in ("/files/..%2Fsecret", "/files/x.mp4", "/files/", "/nope", "/files/latest.mp4x"):
        assert get(server, path)[0].status == 404, path
    assert get(server, f"/files/{A}?x=1")[0].status == 200
    for method in ("POST", "PUT", "DELETE"):
        assert get(server, "/recordings.json", method=method)[0].status == 405


def test_stop_closes_port(served):
    _lib, server = served
    port = server.port
    server.stop()
    assert not server.running
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=1)


def test_symlink_is_not_served(served, tmp_path):
    library, server = served
    secret = tmp_path / "secret"
    secret.write_text("root only")
    os.symlink(str(secret), os.path.join(library.root, "2026-10-15_12-00-00.mp4"))
    assert get(server, "/files/2026-10-15_12-00-00.mp4")[0].status == 404
