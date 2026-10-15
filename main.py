import asyncio
import json
import os
import pwd
import subprocess
import threading
import time

import decky

from showreel import gsr, lock
from showreel.library import Library
from showreel.recorder import Deps, Recorder
from showreel.server import DownloadServer, lan_ip

LOG = "[showreel]"
PORT = 8790
# Root-owned and outside /tmp: root may not reopen a file another user owns in /tmp (protected_regular).
GSR_LOG = os.path.join(decky.DECKY_PLUGIN_LOG_DIR, "gpu-screen-recorder.log")
SETTINGS = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "settings.json")
# The backend runs as root; the recorder, ffmpeg and pw-dump run as the session user.
_home = os.stat(decky.DECKY_USER_HOME)
UID, GID = _home.st_uid, _home.st_gid
USER = pwd.getpwuid(UID).pw_name
ENV = gsr.session_env(os.environ)
AS_USER = {"user": UID, "group": GID, "extra_groups": os.getgrouplist(USER, GID), "env": ENV}


def chown(path: str) -> None:
    try:
        os.chown(path, UID, GID, follow_symlinks=False)
    except OSError:
        pass


def run(cmd: list[str], timeout: float = 30) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, timeout=timeout, **AS_USER)


def spawn(cmd: list[str], log_path: str):
    out = open(log_path, "w", encoding="utf-8")
    try:
        return subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                start_new_session=True, **AS_USER)
    finally:
        out.close()


def send(pid: int, sig: int) -> None:
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        pass


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as f:
            return f.read().rsplit(")", 1)[1].split()[0] not in ("Z", "X")
    except (OSError, IndexError):
        return True


def consumers() -> list[str]:
    try:
        return lock.stream_consumers(json.loads(run(["pw-dump"], timeout=5).stdout or b"[]"))
    except (OSError, ValueError, subprocess.SubprocessError):
        return ["pw-dump failed"]  # unknown counts as busy: never start on a stream we can't see


def remux(mkv: str, mp4: str) -> bool:
    """Into a .part file first, so a remux cut short (unload, power loss) never leaves a truncated .mp4."""
    part = mp4 + ".part"
    try:
        done = run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", mkv, "-c", "copy",
                    "-movflags", "+faststart", "-f", "mp4", part], timeout=300)
        ok = done.returncode == 0
        if not ok:
            decky.logger.warning(f"{LOG} remux failed for {mkv}: {done.stderr.decode(errors='replace')[-500:]}")
    except (OSError, subprocess.SubprocessError) as error:
        decky.logger.warning(f"{LOG} remux failed for {mkv}: {error}")
        ok = False
    if ok:
        os.replace(part, mp4)
        chown(mp4)
    elif os.path.exists(part):
        os.remove(part)
    return ok


def probe_duration(path: str) -> float | None:
    """As the session user: the files belong to it, and this runs on every listing."""
    try:
        out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path], timeout=10)
        return round(float(out.stdout.decode().strip()), 1)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def log_tail(path: str) -> str:
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(f.tell() - 4096, 0))
            return f.read().decode(errors="replace")
    except OSError:
        return ""


def installed() -> bool:
    try:
        return gsr.installed(lambda cmd: run(cmd, timeout=15).returncode)
    except (OSError, subprocess.SubprocessError):
        return False


def load_settings() -> dict:
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(data: dict) -> None:
    os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
    with open(SETTINGS, "w", encoding="utf-8") as f:
        json.dump(data, f)


class Plugin:
    async def _main(self):
        loop = asyncio.get_running_loop()

        def emit(event, *args):
            try:
                asyncio.run_coroutine_threadsafe(decky.emit(event, *args), loop)
            except RuntimeError:  # the loop is closing (unload): the event no longer matters
                pass

        self.library = Library(os.path.join(decky.DECKY_USER_HOME, "Videos", "Showreel"),
                               probe_duration=probe_duration, chown=chown)
        self.library.ensure()
        self.recorder = Recorder(self.library, Deps(
            spawn=spawn, signal=send, pid_alive=pid_alive, find_inner_pid=gsr.find_inner_pid, consumers=consumers,
            write_lock=lock.write_lock, remove_lock=lock.remove_lock, read_lock=lock.read_lock, remux=remux,
            installed=installed, log_tail=log_tail, output_of=gsr.output_of, emit=emit, clock=time.monotonic,
            sleep=time.sleep, own_pid=os.getpid(), free_bytes=self.library.free_bytes, localtime=time.localtime,
            find_recorders=lambda: gsr.recorders_writing_into(self.library.root)),
            log_path=GSR_LOG)
        await asyncio.to_thread(self.recorder.recover)
        self.server = DownloadServer(self.library, port=PORT)
        if load_settings().get("server"):
            await asyncio.to_thread(self._server_on, True)
        self._quit = threading.Event()
        self._worker = threading.Thread(target=self._run, name="showreel-worker", daemon=True)
        self._worker.start()
        decky.logger.info(f"{LOG} backend started")

    def _run(self):
        while not self._quit.wait(0.5):
            try:
                self.recorder.tick()
            except Exception:
                decky.logger.exception(f"{LOG} worker tick failed")

    def _server_on(self, on: bool) -> dict:
        try:
            if on:
                self.server.start()
            else:
                self.server.stop()
        except OSError as error:
            decky.logger.warning(f"{LOG} download page: {error}")
        ip = lan_ip()
        return {"on": self.server.running, "url": f"http://{ip}:{PORT}/" if self.server.running and ip else None}

    async def _unload(self):
        self._quit.set()
        await asyncio.to_thread(self.recorder.stop, "user")
        for _ in range(48):  # a start in progress cancels itself; give it time to clean up
            if self.recorder.status()["state"] == "idle":
                break
            await asyncio.sleep(0.25)
        await asyncio.to_thread(self.server.stop)
        decky.logger.info(f"{LOG} backend stopped")

    async def start(self):
        return await asyncio.to_thread(self.recorder.start)

    async def stop(self):
        return await asyncio.to_thread(self.recorder.stop, "user")

    async def get_status(self):
        return self.recorder.status()

    async def list_recordings(self):
        return await asyncio.to_thread(self.library.recordings)

    async def delete(self, name: str) -> bool:
        return await asyncio.to_thread(self.library.delete, str(name))

    async def set_game_running(self, running: bool) -> None:
        await asyncio.to_thread(self.recorder.set_game_running, bool(running))

    async def set_server(self, on: bool):
        state = await asyncio.to_thread(self._server_on, bool(on))
        save_settings({"server": state["on"]})
        return state

    async def get_settings(self):
        ip = lan_ip()
        on = self.server.running
        return {"server": on, "url": f"http://{ip}:{PORT}/" if on and ip else None}

    async def get_version(self) -> str:
        return decky.DECKY_PLUGIN_VERSION

