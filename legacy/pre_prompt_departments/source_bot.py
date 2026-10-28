#!/usr/bin/env python3
"""SOURCE DEPARTMENT.

One job, one responsibility: get the footage and hand the rest of the company a
clean, sharded audio package. Nothing downstream ever touches the 1.2 GB file.

Outputs (artifacts):
  meta.json           duration, fps, size, source kind
  audio-XX.zip        shard_XX.wav (16 kHz mono) + shard_XX.json (offset)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

import imageio_ffmpeg

FF = imageio_ffmpeg.get_ffmpeg_exe()
ROOT = Path(__file__).resolve().parent.parent
CAMP = json.loads((ROOT / "campaigns" / sys.argv[1] / "campaign.json").read_text())
OUT = Path("/tmp/out")
OUT.mkdir(exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0"}


def wetransfer_link() -> str:
    src = CAMP["source"]
    body = json.dumps({"security_hash": src["security_hash"],
                       "intent": "entire_transfer"}).encode()
    req = urllib.request.Request(
        f"https://wetransfer.com/api/v4/transfers/{src['transfer_id']}/download",
        data=body, headers={**UA, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)["direct_link"]


def download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=300) as r, dest.open("wb") as f:
        total = 0
        while chunk := r.read(1 << 22):
            f.write(chunk)
            total += len(chunk)
            if total % (1 << 28) < (1 << 22):
                print(f"  {total/1e9:.2f} GB", flush=True)
    print("downloaded bytes:", dest.stat().st_size, flush=True)


def probe(p: Path) -> dict:
    r = subprocess.run([FF, "-hide_banner", "-i", str(p)], capture_output=True, text=True)
    import re
    d = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
    v = re.search(r"Video: .*?(\d{3,4})x(\d{3,4})", r.stderr)
    f = re.search(r"(\d+(?:\.\d+)?) fps", r.stderr)
    dur = int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3)) if d else 0
    return {"duration": round(dur, 2),
            "width": int(v.group(1)) if v else 0,
            "height": int(v.group(2)) if v else 0,
            "fps": float(f.group(1)) if f else 0}


def main() -> int:
    src = Path("/tmp/src.mp4")
    if not src.exists():
        url = CAMP["source"].get("src_url") or wetransfer_link()
        print("source link ok", flush=True)
        download(url, src)
    meta = probe(src)
    meta["bytes"] = src.stat().st_size
    (OUT / "meta.json").write_text(json.dumps(meta))
    print("meta:", meta, flush=True)

    wav = Path("/tmp/src.wav")
    subprocess.run([FF, "-nostdin", "-v", "error", "-y", "-i", str(src), "-vn",
                    "-ac", "1", "-ar", "16000", str(wav)], check=True)

    n = int(CAMP.get("shards", 12))
    step = meta["duration"] / n
    for i in range(n):
        t0 = round(i * step, 2)
        dur = round(min(step + 1.0, meta["duration"] - t0), 2)   # 1 s overlap
        d = OUT / f"audio-{i:02d}"
        d.mkdir(exist_ok=True)
        subprocess.run([FF, "-nostdin", "-v", "error", "-y", "-ss", f"{t0}", "-t", f"{dur}",
                        "-i", str(wav), str(d / f"shard_{i:02d}.wav")], check=True)
        (d / f"shard_{i:02d}.json").write_text(json.dumps({"index": i, "t0": t0, "dur": dur}))
        print(f"shard {i:02d} @ {t0}s +{dur}s", flush=True)
    src.unlink(missing_ok=True)
    wav.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
