#!/usr/bin/env python3
"""Fetch only the seconds each clip needs, from the 4K source.

The episode is 75 minutes; this campaign uses about 35 s of it, twenty times.
Pulling the whole 1 GiB file through a free proxy that drops every few hundred
MB is waste, so each clip gets its own cut of the master: D6/D7 are told the
cut's first source timestamp through SRC_OFFSET and keep working in episode
time. Nothing downstream knows the media was cut.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from orchestrator import store  # noqa: E402
import imageio_ffmpeg  # noqa: E402

FF = imageio_ffmpeg.get_ffmpeg_exe()
OUT = Path("/var/tmp/clips")
PAD_HEAD, PAD_TAIL = 3.0, 3.0
VID, AUD = "401", "251-3"
URL = "https://www.youtube.com/watch?v=jszn8rFtxm4"
PROXIES = [l.strip() for l in open("/var/tmp/hf/ok.txt") if l.strip()]


def dur(path: Path) -> float:
    if not path.exists():
        return 0.0
    out = subprocess.run([FF, "-i", str(path)], capture_output=True, text=True).stderr
    for line in out.splitlines():
        if "Duration:" in line:
            h, m, s = line.split("Duration:")[1].split(",")[0].strip().split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
    return 0.0


def grab(clip: str, t0: float, t1: float) -> bool:
    d = OUT / clip
    d.mkdir(parents=True, exist_ok=True)
    first = max(0.0, t0 - PAD_HEAD)
    last = t1 + PAD_TAIL
    want = last - first
    src = d / "src.mp4"
    (d / "offset.txt").write_text(f"{first:.3f}\n")
    if dur(src) >= want - 0.5:
        print(f"{clip}: have {dur(src):.1f}s / {want:.1f}s", flush=True)
        return True
    sec = f"*{first:.1f}-{last:.1f}"
    for attempt, proxy in enumerate(PROXIES * 3, 1):
        v = d / f"v.{VID}.mp4"
        a = d / f"a.{AUD}.webm"
        for f in (v, a):
            f.unlink(missing_ok=True)
        t = time.time()
        r = subprocess.run(["yt-dlp", "--proxy", f"http://{proxy}", "--ffmpeg-location", FF,
                            "--download-sections", sec, "-f", VID, "--no-audio",
                            "-o", str(v.with_suffix("")) + ".%(ext)s", URL],
                           capture_output=True, text=True, timeout=600)
        if r.returncode != 0 or not v.exists():
            print(f"{clip}: video attempt {attempt} via {proxy} failed", flush=True)
            continue
        r = subprocess.run(["yt-dlp", "--proxy", f"http://{proxy}", "--ffmpeg-location", FF,
                            "--download-sections", sec, "-f", AUD,
                            "-o", str(a.with_suffix("")) + ".%(ext)s", URL],
                           capture_output=True, text=True, timeout=600)
        if r.returncode != 0 or not a.exists():
            print(f"{clip}: audio attempt {attempt} via {proxy} failed", flush=True)
            continue
        tmp = d / "tmp.mp4"
        subprocess.run([FF, "-v", "error", "-y", "-i", str(v), "-i", str(a),
                        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
                        str(tmp)], check=True)
        os.replace(tmp, src)
        v.unlink(missing_ok=True)
        a.unlink(missing_ok=True)
        print(f"{clip}: {dur(src):.1f}s in {time.time() - t:.0f}s via {proxy}", flush=True)
        return True
    return False


def main():
    cid = "higgsfield-20vc"
    ov = store.read_json(cid, "edit_overrides.json", {}) or {}
    port = {c["candidate_id"]: c for c in
            store.read_json(cid, "artifacts/portfolio.v1.json")["payload"]["selected"]}
    only = sys.argv[1:]
    ok, bad = [], []
    for clip in sorted(port, key=lambda k: port[k]["t0"]):
        if only and clip not in only:
            continue
        e = ov.get(clip, {})
        t0 = float(e.get("t0", port[clip]["t0"]))
        t1 = float(e.get("t1", port[clip]["t1"]))
        (ok if grab(clip, t0, t1) else bad).append(clip)
    print("FETCHED", len(ok), "FAILED", bad, flush=True)


if __name__ == "__main__":
    main()
