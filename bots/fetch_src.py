#!/usr/bin/env python3
"""SOURCE BOT — makes sure src/snackwars.mp4 exists (1080p video + audio merged).

The sandbox does not keep symlinks or /tmp between sessions, so this bot is the
self-healing first step: if the file is gone it re-downloads and merges it.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "snackwars.mp4"
URL = "https://www.youtube.com/watch?v=-jNqG2Dx1t8"
FF = imageio_ffmpeg.get_ffmpeg_exe()


def ok() -> bool:
    if not SRC.exists() or SRC.stat().st_size < 50_000_000:
        return False
    i = subprocess.run([FF, "-hide_banner", "-i", str(SRC)],
                       capture_output=True, text=True).stderr
    return "1920x1080" in i


def main() -> int:
    if ok():
        print("source: present")
        return 0
    SRC.parent.mkdir(parents=True, exist_ok=True)
    for f in SRC.parent.glob("src.*"):
        f.unlink(missing_ok=True)
    print("source: downloading")
    subprocess.run([sys.executable, "-m", "yt_dlp",
                    "-f", "bv*[height<=1080][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=1080]+ba",
                    "-o", str(SRC.parent / "src.%(ext)s"), "--no-playlist", URL],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    v = next(SRC.parent.glob("src.f*.mp4"))
    a = next(SRC.parent.glob("src.f*.m4a"))
    subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y", "-i", str(v),
                    "-i", str(a), "-c", "copy", "-movflags", "+faststart", str(SRC)],
                   check=True)
    v.unlink(missing_ok=True)
    a.unlink(missing_ok=True)
    print(f"source: ready {SRC.stat().st_size/1e6:.0f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
