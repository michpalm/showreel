# Showreel device checklist

| # | Check | Expected |
|---|-------|----------|
| 1 | Record 60 s: home screen → open QAM → Ambideck panel → library → Stop | MP4 plays on the Mac with QAM and panel visible; native resolution, smooth 60 fps, ≤25 MB/min |
| 1b | With a game running | Record is disabled with "Recording works on the Steam UI only. Close the game first." |
| 1c | Launch a game while recording (5×, a game where a crash doesn't matter) | Recording stops at launch with a toast; no gamescope crash |
| 2 | CPU and battery while recording vs idle | Small difference |
| 3 | Ambideck during and after recording | "Paused while Showreel records"; lights hand back; follows again within ~1 s at 128×72; no "out of buffers" |
| 3b | Kill Showreel's backend while recording, then reload it | The lock keeps naming the recorder; Ambideck stays off; the next load stops the recorder, finishes the file and removes the lock. (Killing a plugin from outside wedges Decky's calls until Decky restarts; its service only kills the main process, so stop leftover plugin processes too.) |
| 4 | Suspend while recording | Keeps recording after wake; the suspended time is left out of the video |
| 5 | Docked (DP-2) recording | Records the external display |
| 6 | From the Mac: `curl http://<device>:8790/recordings.json`, `curl -O …/latest.mp4`, seek in a browser; Claude drives start/stop over CEF | All work |
| 7 | Download page off | Port 8790 closed |
| 8 | GPU Screen Recorder flatpak missing | Record shows the install hint |

## Results, ROG Xbox Ally (RC73YA), SteamOS 3.8.28, 2026-10-15

1 ✅ · 1b ✅ · 1c ✅ 5/5, no crash · 2 ✅ +0.8 W, gpu-screen-recorder ~2.4 % of a core · 3 ✅ · 3b ✅ (after the orphan fix) · 4 ✅ · 5 not run (not docked) · 6 ✅ · 7 ✅ · 8 ✅
