import os
import time

from showreel.library import Library

NOW = time.struct_time((2026, 10, 15, 14, 3, 22, 3, 288, 1))


def lib(tmp_path):
    library = Library(str(tmp_path / "Showreel"), probe_duration=lambda path: 12.5)
    library.ensure()
    return library


def touch(library, name, mtime, size=10):
    path = os.path.join(library.root, name)
    with open(path, "wb") as f:
        f.write(b"x" * size)
    os.utime(path, (mtime, mtime))
    return path


def test_new_stem_and_collisions(tmp_path):
    library = lib(tmp_path)
    assert library.new_stem(NOW) == "2026-10-15_14-03-22"
    touch(library, "2026-10-15_14-03-22.mp4", 1)
    assert library.new_stem(NOW) == "2026-10-15_14-03-22-2"
    touch(library, "2026-10-15_14-03-22-2.mkv", 1)
    assert library.new_stem(NOW) == "2026-10-15_14-03-22-3"
    assert library.paths("a") == (os.path.join(library.root, "a.mkv"), os.path.join(library.root, "a.mp4"))


def test_recordings_sorted_and_filtered(tmp_path):
    library = lib(tmp_path)
    touch(library, "2026-10-15_10-00-00.mp4", 100, size=5)
    touch(library, "2026-10-15_11-00-00.mp4", 200, size=7)
    touch(library, "notes.txt", 300)
    touch(library, "x.mp4", 300)
    library.update_latest()
    recs = library.recordings()
    assert [r["name"] for r in recs] == ["2026-10-15_11-00-00.mp4", "2026-10-15_10-00-00.mp4"]
    assert recs[0] == {"name": "2026-10-15_11-00-00.mp4", "size": 7, "duration": 12.5, "mtime": 200}


def test_latest_link_follows_newest_and_disappears(tmp_path):
    library = lib(tmp_path)
    touch(library, "2026-10-15_10-00-00.mp4", 100)
    touch(library, "2026-10-15_11-00-00.mp4", 200)
    library.update_latest()
    latest = os.path.join(library.root, "latest.mp4")
    assert os.readlink(latest) == "2026-10-15_11-00-00.mp4"
    assert library.delete("2026-10-15_11-00-00.mp4") is True
    assert os.readlink(latest) == "2026-10-15_10-00-00.mp4"
    library.delete("2026-10-15_10-00-00.mp4")
    assert not os.path.lexists(latest)


def test_resolve_rejects_everything_else(tmp_path):
    library = lib(tmp_path)
    good = touch(library, "2026-10-15_10-00-00.mp4", 100)
    touch(library, "x.mp4", 100)
    touch(library, "notes.txt", 100)
    library.update_latest()
    for name in ("../x.mp4", "x.mp4", "notes.txt", "", "2026-10-15_09-00-00.mp4"):
        assert library.resolve(name) is None, name
    assert library.resolve("2026-10-15_10-00-00.mp4") == good
    assert library.resolve("latest.mp4") == good


def test_delete_only_valid_names(tmp_path):
    library = lib(tmp_path)
    victim = tmp_path / "passwd"
    victim.write_text("keep")
    assert library.delete("../passwd") is False
    assert library.delete("2026-10-15_10-00-00.mp4") is False
    assert victim.exists()


def test_free_bytes_and_ensure_chowns(tmp_path):
    owned = []
    library = Library(str(tmp_path / "S"), probe_duration=lambda p: None, chown=owned.append)
    library.ensure()
    assert owned == [library.root] and library.free_bytes() > 0


def test_symlinked_recordings_are_never_resolved(tmp_path):
    library = lib(tmp_path)
    secret = tmp_path / "secret"
    secret.write_text("root only")
    os.symlink(str(secret), os.path.join(library.root, "2026-10-15_12-00-00.mp4"))
    assert library.resolve("2026-10-15_12-00-00.mp4") is None
    assert [r["name"] for r in library.recordings()] == []
    library.update_latest()
    assert library.resolve("latest.mp4") is None
