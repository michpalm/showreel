import os

from showreel import lock
from showreel.lock import read_lock, remove_lock, stream_consumers, write_lock


def test_write_read_remove(tmp_path):
    path = str(tmp_path / "capture.lock")
    write_lock(42, path)
    assert read_lock(path) == {"pid": 42, "owner": "Showreel"}
    remove_lock(path)
    remove_lock(path)
    assert read_lock(path) is None


def test_write_is_atomic(tmp_path, monkeypatch):
    path = str(tmp_path / "capture.lock")
    calls = []
    real = os.replace
    monkeypatch.setattr(lock.os, "replace", lambda src, dst: (calls.append((src, dst)), real(src, dst)))
    write_lock(7, path)
    (src, dst), = calls
    assert dst == path and os.path.dirname(src) == str(tmp_path) and src != path


def test_read_garbage_is_none(tmp_path):
    path = tmp_path / "capture.lock"
    path.write_text("not json")
    assert read_lock(str(path)) is None


def node(id_, name, cls="Stream/Input/Video"):
    return {"id": id_, "type": "PipeWire:Interface:Node", "info": {"props": {"node.name": name, "media.class": cls}}}


def link(out, inp):
    return {"id": 1000 + out * 10 + inp, "type": "PipeWire:Interface:Link",
            "info": {"output-node-id": out, "input-node-id": inp}}


def test_stream_consumers():
    dump = [node(78, "gamescope", "Video/Source"), node(84, "ambideck"), node(90, "gpu-screen-recorder"),
            node(5, "other", "Audio/Source"), link(78, 90), link(78, 84), link(5, 84)]
    assert stream_consumers(dump) == ["ambideck", "gpu-screen-recorder"]
    assert stream_consumers([node(84, "ambideck"), link(5, 84)]) == []
