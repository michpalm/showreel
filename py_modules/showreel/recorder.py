"""Start and stop gpu-screen-recorder around the capture lock, in the only order that is safe for gamescope.

Start: lock (our pid) -> wait until nobody reads gamescope's stream -> gsr -> lock (gsr's pid).
Stop:  SIGINT gsr -> wait until its stream node is gone -> unlock -> remux .mkv to .mp4.
Ambideck reconnects as soon as the lock goes, so it must never go while gsr is still connected.
Never record while a game runs: stopping a full-size capture mid-game can crash gamescope (spec, 2026-10-15).
"""
from __future__ import annotations

import logging
import os
import signal
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from . import gsr
from .library import Library

log = logging.getLogger("showreel")

MIN_FREE_START = 1 << 30
MIN_FREE_RECORDING = 300 << 20
CONSUMER_WAIT_S = 5.0
STREAM_WAIT_S = 8.0  # gsr gives up after 5 s without a first frame; that exit must land inside this wait
INNER_WAIT_S = 3.0
STOP_TIMEOUT_S = 10.0
NODE_GONE_S = 5.0
POLL_S = 0.25

GAME_MSG = "Recording works on the Steam UI only. Close the game first."
INSTALL_MSG = "Install GPU Screen Recorder (Discover, or flatpak install flathub com.dec05eba.gpu_screen_recorder)"
SPACE_MSG = "Not enough free space"
GSR_NODE = "gpu-screen-recorder"


@dataclass
class Deps:
    spawn: Callable[[list[str], str], object]
    signal: Callable[[int, int], None]
    pid_alive: Callable[[int], bool]
    find_inner_pid: Callable[[int], int | None]
    consumers: Callable[[], list[str]]
    write_lock: Callable[[int], None]
    remove_lock: Callable[[], None]
    read_lock: Callable[[], dict | None]
    remux: Callable[[str, str], bool]
    installed: Callable[[], bool]
    log_tail: Callable[[str], str]
    output_of: Callable[[int], str | None]
    emit: Callable
    clock: Callable[[], float]
    sleep: Callable[[float], None]
    own_pid: int
    free_bytes: Callable[[], int]
    localtime: Callable[[], time.struct_time] = field(default=time.localtime)
    find_recorders: Callable[[], list[tuple[int, str]]] = field(default=lambda: [])


class _Cancelled(Exception):
    pass


class Recorder:
    def __init__(self, library: Library, deps: Deps, log_path: str) -> None:
        self._lib, self._d, self._log_path = library, deps, log_path
        self._mx = threading.Lock()
        self._state = "idle"
        self._error: str | None = None
        self._game = False
        self._cancel: str | None = None  # stop reason requested while starting
        self._inner: int | None = None
        self._mkv = self._mp4 = None
        self._started = 0.0

    # --- queries -------------------------------------------------------------------------------------------
    def status(self) -> dict:
        with self._mx:
            state, mkv, mp4 = self._state, self._mkv, self._mp4
            elapsed = self._d.clock() - self._started if state == "recording" else 0.0
            error, game = self._error, self._game
        size = 0
        if state in ("recording", "finishing") and mkv:
            try:
                size = os.path.getsize(mkv)
            except OSError:
                pass
        return {"state": state, "elapsed": round(elapsed, 1), "size": size,
                "file": os.path.basename(mp4) if mp4 and state != "idle" else None,
                "error": error, "gameRunning": game}

    # --- start ---------------------------------------------------------------------------------------------
    def _refusal(self) -> str | None:
        if self._game:
            return GAME_MSG
        if not self._d.installed():
            return INSTALL_MSG
        if self._d.free_bytes() < MIN_FREE_START:
            return SPACE_MSG
        return None

    def _check_cancel(self) -> None:
        with self._mx:
            if self._cancel is not None:
                raise _Cancelled(self._cancel)

    def _wait(self, done: Callable[[], bool], seconds: float) -> bool:
        deadline = self._d.clock() + seconds
        while True:
            if done():
                return True
            if self._d.clock() >= deadline:
                return False
            self._check_cancel()
            self._d.sleep(POLL_S)

    def start(self) -> dict:
        with self._mx:
            if self._state != "idle":
                return {"ok": False, "error": "not idle"}
            refusal = self._refusal()
            if refusal:
                return {"ok": False, "error": refusal}
            self._state, self._error, self._cancel, self._inner = "starting", None, None, None
            self._mkv = self._mp4 = None
        handle = None
        try:
            self._d.write_lock(self._d.own_pid)
            seen: list[str] = []

            def stream_free() -> bool:
                seen[:] = self._d.consumers()
                return not seen

            if not self._wait(stream_free, CONSUMER_WAIT_S):
                return self._abort(handle, error="Screen stream in use by " + (", ".join(seen) or "another app"))
            stem = self._lib.new_stem(self._d.localtime())
            self._mkv, self._mp4 = self._lib.paths(stem)
            for attempt in (1, 2):
                self._check_cancel()
                handle = self._d.spawn(gsr.command(self._mkv), self._log_path)
                self._d.write_lock(handle.pid)  # the wrapper lives exactly as long as gsr: never an unnamed recorder
                self._d.emit("recording_starting")
                outcome = self._wait_streaming(handle)
                if outcome == "streaming":
                    break
                if outcome == "timeout":
                    return self._abort(handle, error="GPU Screen Recorder did not start")
                tail = self._d.log_tail(self._log_path)
                if attempt == 1 and gsr.NEGOTIATION_TIMEOUT in tail:
                    log.info("[showreel] no first frame, retrying once")
                    self._d.write_lock(self._d.own_pid)
                    handle, self._inner = None, None
                    continue
                return self._abort(handle, error="GPU Screen Recorder stopped: " + _last_line(tail))
            self._d.write_lock(self._inner)
            with self._mx:
                if self._cancel is None:
                    self._state, self._started = "recording", self._d.clock()
                    return {"ok": True, "error": None}
                reason = self._cancel
            raise _Cancelled(reason)
        except _Cancelled as cancelled:
            return self._abort(handle, reason=str(cancelled))
        except Exception as error:  # never leave the lock held or the state stuck on "starting"
            log.exception("[showreel] start failed")
            return self._abort(handle, error=f"Could not start: {error}")

    def _wait_streaming(self, handle) -> str:
        """'streaming' once gsr has negotiated gamescope's stream; 'exited' or 'timeout' otherwise.

        Not the file size: gsr buffers, and on a still screen the .mkv stays empty for many seconds (device, 10:22).
        """
        deadline = self._d.clock() + STREAM_WAIT_S
        while self._d.clock() < deadline:
            if handle.poll() is not None:
                return "exited"
            if self._inner is None:
                self._inner = self._d.find_inner_pid(handle.pid)
            if (self._inner is not None and gsr.NEGOTIATED in self._d.log_tail(self._log_path)
                    and GSR_NODE in self._d.consumers()):
                return "streaming"
            self._check_cancel()
            self._d.sleep(POLL_S)
        return "exited" if handle.poll() is not None else "timeout"

    def _abort(self, handle, reason: str | None = None, error: str | None = None) -> dict:
        """Undo a start: stop whatever gsr runs, and only then let go of the lock (Ambideck reconnects at once)."""
        if handle is not None and handle.poll() is None:
            inner = self._inner
            deadline = self._d.clock() + INNER_WAIT_S
            while inner is None and handle.poll() is None and self._d.clock() < deadline:
                inner = self._d.find_inner_pid(handle.pid)
                if inner is None:
                    self._d.sleep(POLL_S)
            if inner is not None:
                self._stop_pid(inner)
            if handle.poll() is None:  # no recorder inside (yet): the sandbox dies with its wrapper
                self._d.signal(handle.pid, signal.SIGKILL)
                self._wait_plain(lambda: handle.poll() is not None, 2.0)
            self._wait_plain(lambda: GSR_NODE not in self._d.consumers(), NODE_GONE_S)
        if handle is not None and handle.poll() is None:
            log.error("[showreel] the recorder wrapper %s would not exit; keeping the capture lock", handle.pid)
            self._d.write_lock(handle.pid)
        else:
            self._d.remove_lock()
        file_error = self._finalise_file_safely()
        message = error or file_error
        self._reset(error=message)
        if error:
            log.warning("[showreel] %s", error)
            self._d.emit("recording_error", error)
        elif reason not in (None, "user"):
            self._d.emit("recording_stopped", reason)
        return {"ok": False, "error": error or "cancelled"}

    def _stop_pid(self, pid: int) -> None:
        if not self._d.pid_alive(pid):
            return
        self._d.signal(pid, signal.SIGINT)
        if not self._wait_plain(lambda: not self._d.pid_alive(pid), STOP_TIMEOUT_S):
            self._d.signal(pid, signal.SIGKILL)
            self._wait_plain(lambda: not self._d.pid_alive(pid), 2.0)

    def _reset(self, error: str | None = None) -> None:
        with self._mx:
            self._state, self._error, self._cancel = "idle", error, None
            self._inner = None

    # --- stop ----------------------------------------------------------------------------------------------
    def stop(self, reason: str = "user") -> dict:
        with self._mx:
            if self._state == "starting":
                self._cancel = reason
                return {"ok": True, "error": None}
            if self._state != "recording":
                return {"ok": False, "error": "not recording"}
            self._state = "finishing"
        self._finish(reason)
        return {"ok": True, "error": None}

    def _finish(self, reason: str) -> None:
        error = None
        try:
            if self._inner is not None:
                self._stop_pid(self._inner)
            self._wait_plain(lambda: GSR_NODE not in self._d.consumers(), NODE_GONE_S)
            self._d.remove_lock()
            error = self._finalise_file_safely()
        finally:
            self._reset(error=error)
        if reason != "user":
            self._d.emit("recording_stopped", reason)

    def _wait_plain(self, done: Callable[[], bool], seconds: float) -> bool:
        deadline = self._d.clock() + seconds
        while not done():
            if self._d.clock() >= deadline:
                return False
            self._d.sleep(POLL_S)
        return True

    def _finalise_file_safely(self) -> str | None:
        try:
            return self._finalise_file()
        except Exception as error:
            log.exception("[showreel] could not finish the recording")
            return f"Could not finish the recording: {error}"

    def _finalise_file(self) -> str | None:
        mkv, mp4 = self._mkv, self._mp4
        if not mkv or _size(mkv) == 0:
            return None
        if not self._d.remux(mkv, mp4):
            return f"Could not finish {os.path.basename(mkv)}"
        os.remove(mkv)
        self._lib.update_latest()
        self._d.emit("recording_finished", os.path.basename(mp4), os.path.getsize(mp4))
        return None

    # --- background ----------------------------------------------------------------------------------------
    def tick(self) -> None:
        with self._mx:
            if self._state != "recording":
                return
            pid = self._inner
        if pid is None or not self._d.pid_alive(pid):
            with self._mx:
                if self._state != "recording":
                    return
                self._state = "finishing"
            self._finish("ended")
        elif self._d.free_bytes() < MIN_FREE_RECORDING:
            self.stop("disk")

    def set_game_running(self, running: bool) -> None:
        with self._mx:
            self._game = bool(running)
            state = self._state
        if running and state in ("starting", "recording"):
            self.stop("game")

    def recover(self) -> None:
        """On load: finish a recording a previous backend left behind, then any .mkv it never remuxed."""
        lock = self._d.read_lock()
        if lock and lock.get("owner") == "Showreel":
            pid = lock.get("pid")
            output = self._d.output_of(pid) if isinstance(pid, int) and self._d.pid_alive(pid) else None
            if output is None:
                self._d.remove_lock()
            else:
                with self._mx:
                    self._state, self._inner = "finishing", pid
                    self._mkv = output
                    self._mp4 = output[:-4] + ".mp4" if output.endswith(".mkv") else output + ".mp4"
                self._finish("user")
        for pid, output in self._d.find_recorders():  # e.g. the backend died while gsr was starting
            if not output.startswith(os.path.join(self._lib.root, "")):
                continue
            log.warning("[showreel] finishing an orphaned recorder %s", pid)
            self._d.write_lock(pid)
            with self._mx:
                self._state, self._inner = "finishing", pid
                self._mkv = output
                self._mp4 = output[:-4] + ".mp4" if output.endswith(".mkv") else output + ".mp4"
            self._finish("user")
        for stem in self._lib.stray_recordings():
            with self._mx:
                self._mkv, self._mp4 = self._lib.paths(stem)
            error = self._finalise_file_safely()
            if error:
                log.warning("[showreel] %s", error)
        with self._mx:
            self._mkv = self._mp4 = None


def _size(path: str | None) -> int:
    try:
        return os.path.getsize(path) if path else 0
    except OSError:
        return 0


def _last_line(text: str) -> str:
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    return lines[-1] if lines else "no output"
