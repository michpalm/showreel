"""GPU Screen Recorder (flatpak): how to run it as the session user, and how to find the real recorder process.

flatpak runs it inside bwrap, so the process we start is only a wrapper: signals must go to the inner
`gpu-screen-recorder`, or it keeps recording (and keeps gamescope's stream) after the wrapper is gone.
"""
from __future__ import annotations

import os
from typing import Callable

APP_ID = "com.dec05eba.gpu_screen_recorder"
NEGOTIATION_TIMEOUT = "timed out waiting for pipewire negotiation"  # no frame within 5 s: retry once
NEGOTIATED = "pipewire negotiation finished"  # streaming; the .mkv itself stays empty for a while (buffered)
DECK_UID = 1000


def command(output: str) -> list[str]:
    return ["flatpak", "run", "--command=gpu-screen-recorder", APP_ID,
            "-w", "portal", "-f", "60", "-k", "h264", "-fm", "cfr", "-cursor", "no", "-c", "mkv", "-o", output]


def session_env(base: dict) -> dict:
    """Environment for system binaries run as the session user from Decky's root backend."""
    env = dict(base)
    if "LD_LIBRARY_PATH_ORIG" in env:
        env["LD_LIBRARY_PATH"] = env["LD_LIBRARY_PATH_ORIG"]
    else:
        env.pop("LD_LIBRARY_PATH", None)
    runtime = f"/run/user/{DECK_UID}"
    env.update({"XDG_RUNTIME_DIR": runtime, "WAYLAND_DISPLAY": "gamescope-0",
                "DBUS_SESSION_BUS_ADDRESS": f"unix:path={runtime}/bus", "HOME": "/home/deck"})
    return env


def installed(run: Callable[[list[str]], int]) -> bool:
    return run(["flatpak", "info", APP_ID]) == 0


def _argv(pid: int, proc_root: str) -> list[str]:
    try:
        with open(os.path.join(proc_root, str(pid), "cmdline"), "rb") as f:
            return [a.decode(errors="replace") for a in f.read().split(b"\0") if a]
    except OSError:
        return []


def _children(proc_root: str) -> dict[int, list[int]]:
    children: dict[int, list[int]] = {}
    for entry in os.listdir(proc_root):
        if not entry.isdigit():
            continue
        try:
            with open(os.path.join(proc_root, entry, "stat"), encoding="utf-8", errors="replace") as f:
                ppid = int(f.read().rsplit(")", 1)[1].split()[1])  # the name may contain spaces and ')'
        except (OSError, IndexError, ValueError):
            continue
        children.setdefault(ppid, []).append(int(entry))
    return children


def find_inner_pid(wrapper_pid: int, proc_root: str = "/proc") -> int | None:
    children = _children(proc_root)
    todo = list(children.get(wrapper_pid, []))
    while todo:
        pid = todo.pop(0)
        argv = _argv(pid, proc_root)
        if argv and os.path.basename(argv[0]) == "gpu-screen-recorder":
            return pid
        todo.extend(children.get(pid, []))
    return None


def recorders_writing_into(root: str, proc_root: str = "/proc") -> list[tuple[int, str]]:
    """Every running gpu-screen-recorder whose output file is inside `root`, as (pid, output)."""
    found = []
    prefix = os.path.join(root, "")
    for entry in os.listdir(proc_root):
        if not entry.isdigit():
            continue
        argv = _argv(int(entry), proc_root)
        if argv and os.path.basename(argv[0]) == "gpu-screen-recorder":
            output = output_of(int(entry), proc_root)
            if output and output.startswith(prefix):
                found.append((int(entry), output))
    return sorted(found)


def output_of(pid: int, proc_root: str = "/proc") -> str | None:
    argv = _argv(pid, proc_root)
    if "-o" in argv and argv.index("-o") + 1 < len(argv):
        return argv[argv.index("-o") + 1]
    return None
