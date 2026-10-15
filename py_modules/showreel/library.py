"""The recordings folder: names, listing, the latest.mp4 link, deleting. Only names it made are ever served or deleted."""
from __future__ import annotations

import os
import re
import shutil
import time
from typing import Callable

NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}(-\d+)?\.mp4$")
LATEST = "latest.mp4"


class Library:
    def __init__(self, root: str, probe_duration: Callable[[str], float | None],
                 chown: Callable[[str], None] = lambda path: None) -> None:
        self.root, self._probe, self._chown = root, probe_duration, chown

    def ensure(self) -> None:
        os.makedirs(self.root, exist_ok=True)
        self._chown(self.root)

    def new_stem(self, now: time.struct_time) -> str:
        base = time.strftime("%Y-%m-%d_%H-%M-%S", now)
        stem, n = base, 1
        while any(os.path.lexists(p) for p in self.paths(stem)):
            n += 1
            stem = f"{base}-{n}"
        return stem

    def paths(self, stem: str) -> tuple[str, str]:
        return os.path.join(self.root, stem + ".mkv"), os.path.join(self.root, stem + ".mp4")

    def _names(self) -> list[str]:
        try:
            # Never symlinks: the download page runs as root, and the folder belongs to the session user.
            names = [n for n in os.listdir(self.root)
                     if NAME_RE.fullmatch(n) and not os.path.islink(os.path.join(self.root, n))]
        except OSError:
            return []
        return sorted(names, key=lambda n: os.path.getmtime(os.path.join(self.root, n)), reverse=True)

    def stray_recordings(self) -> list[str]:
        """Stems of .mkv files left by a recording that was never finished (crash, suspend, reboot)."""
        try:
            names = os.listdir(self.root)
        except OSError:
            return []
        return sorted(n[:-4] for n in names if n.endswith(".mkv") and NAME_RE.fullmatch(n[:-4] + ".mp4")
                      and not os.path.islink(os.path.join(self.root, n)))

    def recordings(self) -> list[dict]:
        out = []
        for name in self._names():
            path = os.path.join(self.root, name)
            st = os.stat(path)
            out.append({"name": name, "size": st.st_size, "duration": self._probe(path), "mtime": int(st.st_mtime)})
        return out

    def update_latest(self) -> None:
        link = os.path.join(self.root, LATEST)
        names = self._names()
        if not names:
            if os.path.lexists(link):
                os.remove(link)
            return
        tmp = os.path.join(self.root, ".latest.tmp")
        if os.path.lexists(tmp):
            os.remove(tmp)
        os.symlink(names[0], tmp)
        os.replace(tmp, link)

    def resolve(self, name: str) -> str | None:
        if name == LATEST:
            link = os.path.join(self.root, LATEST)
            target = os.readlink(link) if os.path.islink(link) else None
            return self.resolve(target) if target else None
        if not NAME_RE.fullmatch(name or ""):
            return None
        path = os.path.join(self.root, name)
        return path if os.path.isfile(path) and not os.path.islink(path) else None

    def delete(self, name: str) -> bool:
        path = self.resolve(name) if name != LATEST else None
        if path is None:
            return False
        os.remove(path)
        self.update_latest()
        return True

    def free_bytes(self) -> int:
        return shutil.disk_usage(self.root).free

