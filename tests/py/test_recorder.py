import os
import signal
import threading
import time

from showreel import gsr
from showreel.library import Library
from showreel.recorder import (GAME_MSG, INSTALL_MSG, MIN_FREE_RECORDING, SPACE_MSG, Deps, Recorder)

NOW = time.struct_time((2026, 10, 15, 14, 3, 22, 3, 288, 1))
OWN = 500


class Handle:
    def __init__(self, pid, world=None, exit_at=None):
        self.pid, self.code, self._world, self._exit_at = pid, None, world, exit_at

    def poll(self):
        if self.code is None and self._exit_at is not None and self._world.t >= self._exit_at:
            self.code = 1
        return self.code


class World:
    """Fake processes, PipeWire and clock. Every side effect lands in self.log, in order."""

    def __init__(self, root):
        self.log, self.events = [], []
        self.t = 0.0
        self.alive = set()
        self.readers = []  # gamescope stream consumers
        self.next_pid = 1000
        self.lock = None
        self.free = 10 << 30
        self.stubborn = False  # the recorder ignores SIGINT
        self.early_exit_logs = []  # per spawn: a log text that makes the wrapper exit at once
        self.installed_ok = True
        self.handles = []
        self.on_consumers = None  # hook called on each consumers() poll
        self.late_exit_logs = []
        self.empty_mkv = False  # gsr buffers: on a still screen the .mkv stays empty for a long time
        self.hide_inner = 0  # find_inner_pid answers None this many times
        self.wrappers_alive = set()
        self.library = Library(root, probe_duration=lambda p: 1.0)
        self.library.ensure()
        self.last_log = ""

    # Deps
    def spawn(self, cmd, log_path):
        wrapper, inner = self.next_pid, self.next_pid + 2
        self.next_pid += 10
        self.log.append(("spawn", cmd))
        handle = Handle(wrapper)
        self.handles.append(handle)
        self.wrappers_alive.add(wrapper)
        if self.late_exit_logs:  # gsr starts but never gets a frame, then gives up
            self.last_log = self.late_exit_logs.pop(0)
            handle._world, handle._exit_at = self, self.t + 5.5
            return handle
        if self.early_exit_logs:
            self.last_log = self.early_exit_logs.pop(0)
            handle.code = 1
            return handle
        self.alive.add(inner)
        self.inner = {wrapper: inner}
        self.readers.append("gpu-screen-recorder")
        self.last_log = "gsr info: gsr_capture_portal_start: pipewire negotiation finished\n"
        with open(cmd[-1], "wb") as f:
            f.write(b"" if self.empty_mkv else b"x" * 100)
        if self.empty_mkv:
            self.pending_mkv = cmd[-1]
        return handle

    def signal(self, pid, sig):
        self.log.append(("signal", pid, sig))
        if pid in self.wrappers_alive and sig == signal.SIGKILL:
            self.wrappers_alive.discard(pid)
            for h in self.handles:
                if h.pid == pid:
                    h.code = -9
            self._exit(getattr(self, "inner", {}).get(pid))  # bwrap --die-with-parent takes gsr with it
            return
        if sig == signal.SIGKILL or (sig == signal.SIGINT and not self.stubborn):
            self._exit(pid)

    def _exit(self, pid):
        if pid in self.alive:
            self.alive.discard(pid)
            if "gpu-screen-recorder" in self.readers:
                self.readers.remove("gpu-screen-recorder")
            for h in self.handles:
                if self.inner.get(h.pid) == pid:
                    h.code = 0

    def pid_alive(self, pid):
        return pid in self.alive

    def find_inner_pid(self, wrapper):
        if self.hide_inner > 0:
            self.hide_inner -= 1
            return None
        return getattr(self, "inner", {}).get(wrapper)

    def ambideck_leaves(self):
        if "ambideck" in self.readers:
            self.readers.remove("ambideck")

    def consumers(self):
        if self.on_consumers:
            self.on_consumers()
        self.log.append(("consumers", list(self.readers)))
        return list(self.readers)

    def write_lock(self, pid):
        self.log.append(("write_lock", pid))
        self.lock = {"pid": pid, "owner": "Showreel"}

    def remove_lock(self):
        self.log.append(("remove_lock",))
        self.lock = None

    def read_lock(self):
        return self.lock

    def remux(self, mkv, mp4):
        self.log.append(("remux", os.path.basename(mkv), os.path.basename(mp4)))
        with open(mkv, "rb") as src, open(mp4, "wb") as dst:
            dst.write(src.read())
        return True

    def emit(self, event, *args):
        self.events.append((event, *args))

    def sleep(self, s):
        self.t += s
        if getattr(self, "on_sleep", None):
            self.on_sleep()

    def deps(self):
        return Deps(spawn=self.spawn, signal=self.signal, pid_alive=self.pid_alive,
                    find_inner_pid=self.find_inner_pid, consumers=self.consumers, write_lock=self.write_lock,
                    remove_lock=self.remove_lock, read_lock=self.read_lock, remux=self.remux,
                    installed=lambda: self.installed_ok, log_tail=lambda path: self.last_log,
                    output_of=lambda pid: getattr(self, "orphan_output", None) if pid in self.alive else None,
                    emit=self.emit, clock=lambda: self.t, sleep=self.sleep, own_pid=OWN,
                    localtime=lambda: NOW, free_bytes=lambda: self.free)


def make(tmp_path):
    world = World(str(tmp_path / "Showreel"))
    return world, Recorder(world.library, world.deps(), log_path=str(tmp_path / "gsr.log"))


def kinds(world):
    return [entry[0] for entry in world.log if entry[0] != "consumers"]


def test_start_order(tmp_path):
    world, rec = make(tmp_path)
    world.readers = ["ambideck"]
    world.on_consumers = lambda: world.ambideck_leaves() if world.t >= 0.5 else None
    assert rec.start() == {"ok": True, "error": None}
    assert world.log[0] == ("write_lock", OWN)
    spawn_at = kinds(world).index("spawn")
    assert ("consumers", []) in world.log[:world.log.index(("spawn", gsr.command(
        os.path.join(world.library.root, "2026-10-15_14-03-22.mkv"))))]
    assert kinds(world)[spawn_at + 1:] == ["write_lock"] and world.lock["pid"] == 1002
    assert rec.status()["state"] == "recording"
    assert ("recording_starting",) in world.events


def test_refusals(tmp_path):
    world, rec = make(tmp_path)
    rec.set_game_running(True)
    assert rec.start() == {"ok": False, "error": GAME_MSG}
    rec.set_game_running(False)
    world.installed_ok = False
    assert rec.start() == {"ok": False, "error": INSTALL_MSG}
    world.installed_ok = True
    world.free = 500 << 20
    assert rec.start() == {"ok": False, "error": SPACE_MSG}
    assert world.lock is None and "spawn" not in kinds(world)


def test_stream_busy_removes_lock(tmp_path):
    world, rec = make(tmp_path)
    world.readers = ["DeckCast"]
    assert rec.start() == {"ok": False, "error": "Screen stream in use by DeckCast"}
    assert world.lock is None and "spawn" not in kinds(world)
    assert ("recording_error", "Screen stream in use by DeckCast") in world.events
    assert rec.status()["state"] == "idle"


def test_negotiation_timeout_after_five_seconds_retries(tmp_path):
    world, rec = make(tmp_path)
    world.late_exit_logs = [f"gsr info: gsr_capture_portal_start: {gsr.NEGOTIATION_TIMEOUT} (5 seconds)\n"]
    assert rec.start() == {"ok": True, "error": None}
    assert kinds(world).count("spawn") == 2 and rec.status()["state"] == "recording"


def test_negotiation_timeout_retries_once(tmp_path):
    world, rec = make(tmp_path)
    world.early_exit_logs = [f"gsr info: gsr_capture_portal_start: {gsr.NEGOTIATION_TIMEOUT} (5 seconds)\n"]
    assert rec.start()["ok"] is True
    assert kinds(world).count("spawn") == 2
    assert [e for e in world.events if e[0] == "recording_starting"] == [("recording_starting",)] * 2


def test_early_exit_other_error_fails_with_log_tail(tmp_path):
    world, rec = make(tmp_path)
    world.early_exit_logs = ["gsr error: something broke\n"]
    result = rec.start()
    assert result["ok"] is False and "something broke" in result["error"]
    assert kinds(world).count("spawn") == 1 and world.lock is None
    assert rec.status()["state"] == "idle"


def test_stop_order(tmp_path):
    world, rec = make(tmp_path)
    rec.start()
    world.log.clear()
    assert rec.stop() == {"ok": True, "error": None}
    assert world.log[0] == ("signal", 1002, signal.SIGINT)
    order = kinds(world)
    assert order.index("remove_lock") < order.index("remux")
    last_consumers = max(i for i, e in enumerate(world.log) if e[0] == "consumers")
    assert world.log[last_consumers] == ("consumers", []) and last_consumers < world.log.index(("remove_lock",))
    root = world.library.root
    assert not os.path.exists(os.path.join(root, "2026-10-15_14-03-22.mkv"))
    assert os.readlink(os.path.join(root, "latest.mp4")) == "2026-10-15_14-03-22.mp4"
    assert ("recording_finished", "2026-10-15_14-03-22.mp4", 100) in world.events
    assert rec.status()["state"] == "idle"


def test_stop_timeout_kills(tmp_path):
    world, rec = make(tmp_path)
    rec.start()
    world.stubborn = True
    t0 = world.t
    rec.stop()
    sigs = [e for e in world.log if e[0] == "signal"]
    assert sigs == [("signal", 1002, signal.SIGINT), ("signal", 1002, signal.SIGKILL)]
    assert world.t - t0 >= 10


def test_gsr_dies_is_finalised(tmp_path):
    world, rec = make(tmp_path)
    rec.start()
    world._exit(1002)
    rec.tick()
    assert ("recording_stopped", "ended") in world.events
    assert world.lock is None and rec.status()["state"] == "idle"
    assert any(e[0] == "recording_finished" for e in world.events)


def test_game_guard_stops_recording(tmp_path):
    world, rec = make(tmp_path)
    rec.start()
    rec.set_game_running(True)
    assert ("recording_stopped", "game") in world.events
    assert world.lock is None and rec.status()["state"] == "idle"


def test_game_during_start_aborts(tmp_path):
    world, rec = make(tmp_path)
    world.readers = ["ambideck"]

    def game_starts():
        if world.t >= 0.5:
            world.ambideck_leaves()
            rec.set_game_running(True)

    world.on_consumers = game_starts
    result = rec.start()
    assert result["ok"] is False
    assert world.lock is None and not world.alive
    assert rec.status()["state"] == "idle"


def test_second_start_is_refused(tmp_path):
    world, rec = make(tmp_path)
    world.readers = ["ambideck"]
    gate = threading.Event()
    world.on_consumers = lambda: (gate.wait(1), world.ambideck_leaves())
    results = []
    first = threading.Thread(target=lambda: results.append(rec.start()))
    first.start()
    time.sleep(0.05)
    assert rec.start() == {"ok": False, "error": "not idle"}
    gate.set()
    first.join()
    assert results == [{"ok": True, "error": None}] and kinds(world).count("spawn") == 1


def test_stop_while_starting_cancels(tmp_path):
    world, rec = make(tmp_path)
    world.readers = ["ambideck"]

    def stop_now():
        if world.t >= 0.5:
            world.ambideck_leaves()
            rec.stop()

    world.on_consumers = stop_now
    assert rec.start()["ok"] is False
    assert world.lock is None and not world.alive and rec.status()["state"] == "idle"


def test_low_disk_while_recording_stops(tmp_path):
    world, rec = make(tmp_path)
    rec.start()
    world.free = MIN_FREE_RECORDING - 1
    rec.tick()
    assert ("recording_stopped", "disk") in world.events and rec.status()["state"] == "idle"


def test_status_while_recording(tmp_path):
    world, rec = make(tmp_path)
    rec.start()
    world.t += 7
    status = rec.status()
    assert status["state"] == "recording" and status["file"] == "2026-10-15_14-03-22.mp4"
    assert status["size"] == 100 and 6.5 <= status["elapsed"] <= 7.5 and status["gameRunning"] is False


def test_recover_orphan(tmp_path):
    world, rec = make(tmp_path)
    mkv = os.path.join(world.library.root, "2026-10-15_13-00-00.mkv")
    with open(mkv, "wb") as f:
        f.write(b"y" * 40)
    world.alive.add(77)
    world.readers = ["gpu-screen-recorder"]
    world.inner = {}
    world.orphan_output = mkv
    world.lock = {"pid": 77, "owner": "Showreel"}
    rec.recover()
    assert ("signal", 77, signal.SIGINT) in world.log and world.lock is None
    assert os.path.exists(mkv[:-4] + ".mp4") and not os.path.exists(mkv)

    world.lock = {"pid": 88, "owner": "other"}
    rec.recover()
    assert world.lock == {"pid": 88, "owner": "other"}

    world.lock = {"pid": 99, "owner": "Showreel"}
    rec.recover()
    assert world.lock is None


def test_game_during_first_frame_wait_stops_gsr(tmp_path):
    world, rec = make(tmp_path)
    world.hide_inner = 1  # startup takes one poll, so the game can arrive during it

    def game_after_spawn():
        if "spawn" in kinds(world) and not rec.status()["gameRunning"]:
            rec.set_game_running(True)

    world.on_sleep = game_after_spawn
    assert rec.start()["ok"] is False
    assert ("signal", 1002, signal.SIGINT) in world.log
    assert world.lock is None and not world.alive and rec.status()["state"] == "idle"
    assert ("recording_stopped", "game") in world.events


def test_unexpected_error_during_start_releases_everything(tmp_path):
    world, rec = make(tmp_path)

    def broken_spawn(cmd, log_path):
        raise PermissionError(13, "Permission denied", log_path)

    rec._d.spawn = broken_spawn
    result = rec.start()
    assert result["ok"] is False and "Permission denied" in result["error"]
    assert world.lock is None and rec.status()["state"] == "idle"
    assert rec.start()["ok"] is False  # still broken, but not stuck: a clean refusal, not "not idle"
    assert rec.status()["state"] == "idle"


def test_cancel_before_inner_pid_is_visible_still_stops_gsr(tmp_path):
    world, rec = make(tmp_path)
    world.hide_inner = 2

    def game_after_spawn():
        if "spawn" in kinds(world) and not rec.status()["gameRunning"]:
            rec.set_game_running(True)

    world.on_sleep = game_after_spawn
    assert rec.start()["ok"] is False
    assert ("signal", 1002, signal.SIGINT) in world.log
    assert not world.alive and world.readers == [] and world.lock is None
    assert rec.status()["state"] == "idle"


def test_inner_never_found_kills_wrapper_before_unlocking(tmp_path):
    world, rec = make(tmp_path)
    world.hide_inner = 10 ** 6
    result = rec.start()
    assert result["ok"] is False
    kill_at = world.log.index(("signal", 1000, signal.SIGKILL))
    assert kill_at < world.log.index(("remove_lock",))
    assert world.handles[0].poll() is not None and world.lock is None


def test_finish_failure_still_returns_to_idle(tmp_path):
    world, rec = make(tmp_path)
    rec.start()

    def broken_remux(mkv, mp4):
        raise OSError("disk gone")

    rec._d.remux = broken_remux
    rec.stop()
    status = rec.status()
    assert status["state"] == "idle" and "disk gone" in status["error"] and world.lock is None


def test_recover_finalises_stray_mkv(tmp_path):
    world, rec = make(tmp_path)
    mkv = os.path.join(world.library.root, "2026-10-15_09-00-00.mkv")
    with open(mkv, "wb") as f:
        f.write(b"z" * 30)
    rec.recover()
    assert os.path.exists(mkv[:-4] + ".mp4") and not os.path.exists(mkv)
    assert os.readlink(os.path.join(world.library.root, "latest.mp4")) == "2026-10-15_09-00-00.mp4"


def test_start_succeeds_while_the_mkv_is_still_empty(tmp_path):
    world, rec = make(tmp_path)
    world.empty_mkv = True
    assert rec.start() == {"ok": True, "error": None}
    assert rec.status()["state"] == "recording"


def test_not_streaming_until_negotiation_finished(tmp_path):
    world, rec = make(tmp_path)
    real_spawn = world.spawn

    def spawn_without_negotiation(cmd, log_path):
        handle = real_spawn(cmd, log_path)
        world.last_log = "gsr info: gsr_capture_portal_start: waiting for pipewire negotiation\n"
        return handle

    rec._d.spawn = spawn_without_negotiation
    assert rec.start() == {"ok": False, "error": "GPU Screen Recorder did not start"}
    assert world.lock is None and not world.alive
