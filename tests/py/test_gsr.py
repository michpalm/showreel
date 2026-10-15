from showreel import gsr


def test_command_matches_spec():
    assert gsr.command("/home/deck/Videos/Showreel/a.mkv") == [
        "flatpak", "run", "--command=gpu-screen-recorder", "com.dec05eba.gpu_screen_recorder",
        "-w", "portal", "-f", "60", "-k", "h264", "-fm", "cfr", "-cursor", "no", "-c", "mkv",
        "-o", "/home/deck/Videos/Showreel/a.mkv"]


def test_session_env_restores_library_path():
    env = gsr.session_env({"LD_LIBRARY_PATH": "/decky", "LD_LIBRARY_PATH_ORIG": "/usr/lib", "PATH": "/bin"})
    assert env["LD_LIBRARY_PATH"] == "/usr/lib" and env["PATH"] == "/bin"
    assert env["XDG_RUNTIME_DIR"] == "/run/user/1000"
    assert env["WAYLAND_DISPLAY"] == "gamescope-0"
    assert env["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/run/user/1000/bus"
    assert env["HOME"] == "/home/deck"
    assert "LD_LIBRARY_PATH" not in gsr.session_env({"LD_LIBRARY_PATH": "/decky"})


def test_installed():
    seen = []
    assert gsr.installed(lambda cmd: (seen.append(cmd), 0)[1]) is True
    assert seen == [["flatpak", "info", "com.dec05eba.gpu_screen_recorder"]]
    assert gsr.installed(lambda cmd: 1) is False


def proc(root, pid, ppid, argv, comm=None):
    d = root / str(pid)
    d.mkdir()
    name = comm or argv[0].rsplit("/", 1)[-1][:15]
    (d / "stat").write_text(f"{pid} ({name}) S {ppid} {pid} {pid} 0 -1 4194560\n")
    (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")


def fake_proc(tmp_path):
    proc(tmp_path, 100, 1, ["/usr/bin/flatpak", "run", "--command=gpu-screen-recorder"])
    proc(tmp_path, 101, 100, ["bwrap", "--args", "72"], comm="bwrap (x) y")
    proc(tmp_path, 102, 101, ["gpu-screen-recorder", "-w", "portal", "-o", "/home/deck/Videos/Showreel/x.mkv"])
    proc(tmp_path, 200, 1, ["gpu-screen-recorder", "-w", "portal"])
    (tmp_path / "self").mkdir()
    return str(tmp_path)


def test_find_inner_pid(tmp_path):
    root = fake_proc(tmp_path)
    assert gsr.find_inner_pid(100, root) == 102
    assert gsr.find_inner_pid(999, root) is None


def test_output_of(tmp_path):
    root = fake_proc(tmp_path)
    assert gsr.output_of(102, root) == "/home/deck/Videos/Showreel/x.mkv"
    assert gsr.output_of(200, root) is None
    assert gsr.output_of(999, root) is None


def test_recorders_writing_into(tmp_path):
    root = fake_proc(tmp_path)
    assert gsr.recorders_writing_into("/home/deck/Videos/Showreel", root) == [
        (102, "/home/deck/Videos/Showreel/x.mkv")]
    assert gsr.recorders_writing_into("/elsewhere", root) == []
