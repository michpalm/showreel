"""The capture lock shared with Ambideck, and who is reading gamescope's screen stream.

gamescope has one PipeWire stream whose format the first reader sets, so a recorder must have it to itself.
Ambideck (1.2.0+) lets go while a live process holds the lock.
"""
from __future__ import annotations

import json
import os
import tempfile

LOCK_PATH = "/run/decky-screen-capture.lock"


def write_lock(pid: int, path: str = LOCK_PATH, owner: str = "Showreel") -> None:
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".capture-lock-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"pid": pid, "owner": owner}, f)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def read_lock(path: str = LOCK_PATH) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            lock = json.load(f)
    except (OSError, ValueError):
        return None
    return lock if isinstance(lock, dict) else None


def remove_lock(path: str = LOCK_PATH) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def stream_consumers(dump: list) -> list[str]:
    """Names of the nodes reading gamescope's video stream, from `pw-dump` output."""
    nodes = {o.get("id"): ((o.get("info") or {}).get("props") or {}) for o in dump
             if str(o.get("type", "")).endswith("Node")}
    source = next((i for i, p in nodes.items()
                   if p.get("node.name") == "gamescope" and p.get("media.class") == "Video/Source"), None)
    if source is None:
        return []
    readers = [(o.get("info") or {}).get("input-node-id") for o in dump
               if str(o.get("type", "")).endswith("Link") and (o.get("info") or {}).get("output-node-id") == source]
    return sorted(str(nodes.get(r, {}).get("node.name", r)) for r in readers)
