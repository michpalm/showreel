# Showreel device checklist

| # | Check | Expected |
|---|-------|----------|
| 1 | Record 60 s: home screen → open QAM → Ambideck panel → library → Stop | MP4 plays on the Mac with QAM and panel visible; 1080p, smooth 60 fps, ≤25 MB/min |
| 1b | With a game running | Record is disabled with "Recording works on the Steam UI only. Close the game first." |
| 1c | Launch a game while recording (5×, a game where a crash doesn't matter) | Recording stops at launch with a toast; no gamescope crash |
| 2 | CPU and battery while recording vs idle | Small difference |
| 3 | Ambideck during and after recording | "Paused while Showreel records"; lights hand back; follows again within ~1 s at 128×72; no "out of buffers" |
| 3b | Kill Showreel's backend while recording, then reload it | The lock holds (recorder's PID) until the reload finishes the orphan; then Ambideck resumes |
| 4 | Suspend while recording | Playable file; toast "Recording ended unexpectedly" |
| 5 | Docked (DP-2) recording | Records the external display |
| 6 | From the Mac: `curl http://<ally>:8790/recordings.json`, `curl -O …/latest.mp4`, seek in a browser; Claude drives start/stop over CEF | All work |
| 7 | Download page off | Port 8790 closed |
| 8 | GPU Screen Recorder flatpak missing | Record shows the install hint |
