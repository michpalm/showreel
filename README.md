# Showreel

A small Decky plugin that records the Steam UI on the ROG Xbox Ally, Quick Access menu and Decky panels included, so you can show off plugins. It has one button: **Record**, then **Stop**.

- **Video:** H.264 MP4, 1080p at 60 fps, encoded on the GPU by [GPU Screen Recorder](https://git.dec05eba.com/gpu-screen-recorder/about/). No audio.
- **Files:** saved to `~/Videos/Showreel/` as `YYYY-MM-DD_HH-MM-SS.mp4`. `latest.mp4` always points to the newest one.
- **Download page** (off by default): switch it on in the panel and open the address it shows (`http://<ally-ip>:8790/`) on another device. Tools can fetch `/recordings.json` and `/latest.mp4`. The page is read-only.

## Steam UI only

Record is unavailable while a game is running, and a game that starts mid-recording stops it.

The reason: on SteamOS 3.8 (gamescope 3.16), disconnecting a full-size screen capture **while a game is drawing** can crash gamescope, which closes the game. In testing this happened with every capture method tried. Recording on the Steam UI has been safe.

## Requirements

- SteamOS in Game Mode, with Decky Loader.
- The GPU Screen Recorder flatpak. Install it from Discover in Desktop Mode, or run:

  ```
  flatpak install flathub com.dec05eba.gpu_screen_recorder
  ```

## Plays well with Ambideck (and other screen readers)

gamescope has one screen stream, and the first app reading it sets its size for everyone. While recording, Showreel holds a capture lock at `/run/decky-screen-capture.lock`, containing `{"pid": <recorder pid>, "owner": "Showreel"}`.

- [Ambideck](https://github.com/michpalm/ambideck) 1.2.0+ lets go of the stream while the lock is held, and hands the lights back.
- Another plugin can do the same. The rule: the lock counts only while that PID is alive (and not a zombie).
- If anything else is reading the stream, Showreel won't start and names it.

## Install

Download `showreel.zip` from the releases, then in Decky go to Settings → Developer → Install plugin from ZIP.

## Development

```
pnpm install && pnpm test && pnpm build
python3 -m venv .venv && .venv/bin/pip install pytest && .venv/bin/python -m pytest tests/py
scripts/package.sh   # out/showreel.zip
scripts/serve.sh     # serve it to the device on port 8767
```

## About this project

A personal project, maintained on a best-effort basis. The code was written with [Claude](https://claude.ai)
(Anthropic's AI), directed, reviewed and tested on device by the author.

## Credits

- Recording by [GPU Screen Recorder](https://git.dec05eba.com/gpu-screen-recorder/about/) by dec05eba (flatpak
  `com.dec05eba.gpu_screen_recorder`), run as a separate program.
- Not affiliated with ASUS, Microsoft or Valve.

## License

MIT
