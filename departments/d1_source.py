#!/usr/bin/env python3
"""D1 — Source intake and technical preparation.

Acquires the authorized source, keeps the original untouched, probes it, and
publishes one canonical source clock plus audio shards. Nothing downstream ever
touches a gigabyte file again; they consume shards and proxies by reference.

  python3 departments/d1_source.py <campaign_id> [--shards N]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

import imageio_ffmpeg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from orchestrator import store  # noqa: E402

FF = imageio_ffmpeg.get_ffmpeg_exe()
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0"}


def wetransfer_direct_link(tid: str, security_hash: str) -> str:
    body = json.dumps({"security_hash": security_hash, "intent": "entire_transfer"}).encode()
    req = urllib.request.Request(f"https://wetransfer.com/api/v4/transfers/{tid}/download",
                                 data=body, headers={**UA, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)["direct_link"]


def download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=900) as r, dest.open("wb") as f:
        while chunk := r.read(1 << 22):
            f.write(chunk)


def probe(p: Path) -> dict:
    r = subprocess.run([FF, "-hide_banner", "-i", str(p)], capture_output=True, text=True)
    dur = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
    vid = re.search(r"Video: (\w+).*?(\d{3,4})x(\d{3,4})", r.stderr)
    fps = re.search(r"(\d+(?:\.\d+)?) fps", r.stderr)
    aud = re.search(r"Audio: (\w+), (\d+) Hz", r.stderr)
    d = int(dur.group(1)) * 3600 + int(dur.group(2)) * 60 + float(dur.group(3)) if dur else 0
    return {"duration": round(d, 3),
            "video_codec": vid.group(1) if vid else None,
            "width": int(vid.group(2)) if vid else 0,
            "height": int(vid.group(3)) if vid else 0,
            "fps": float(fps.group(1)) if fps else 0,
            "audio_codec": aud.group(1) if aud else None,
            "audio_rate": int(aud.group(2)) if aud else 0}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("campaign_id")
    ap.add_argument("--shards", type=int, default=None)
    a = ap.parse_args()
    cid = a.campaign_id
    brief = store.validate_brief(cid)
    work = Path("/tmp/src.mp4")

    if not work.exists():
        src = brief["source"]
        if src["type"] == "LOCAL_FILE":
            work = Path(src["path_or_url"])
            if not work.exists():
                raise SystemExit(f"source file missing: {work}")
        elif src["type"] == "WETRANSFER":
            wt = src["wetransfer"]
            download(wetransfer_direct_link(wt["transfer_id"], wt["security_hash"]), work)
        elif src["type"] in ("DIRECT_URL", "YOUTUBE_URL"):
            download(src["path_or_url"], work)
        else:
            raise SystemExit(f"unsupported source type {src['type']}")

    info = probe(work)
    info["bytes"] = work.stat().st_size
    store.artifact(cid, "source_meta", info)
    store.gate(cid, "_campaign", "SOURCE_VALID", info["duration"] > 0, f"{info['duration']}s")

    wav = Path("/tmp/src.wav")
    subprocess.run([FF, "-nostdin", "-v", "error", "-y", "-i", str(work), "-vn",
                    "-ac", "1", "-ar", "16000", str(wav)], check=True)

    n = a.shards or max(4, min(40, round(info["duration"] / 75)))
    step = info["duration"] / n
    overlap = 10.0
    for i in range(n):
        t0 = max(0.0, round(i * step - overlap / 2, 2))
        t1 = round(min(info["duration"], (i + 1) * step + overlap / 2), 2)
        d = store.path(cid, f"shards/shard_{i:02d}.json")
        subprocess.run([FF, "-nostdin", "-v", "error", "-y", "-ss", f"{t0}", "-t", f"{t1 - t0}",
                        "-i", str(wav), str(d.with_suffix(".wav"))], check=True)
        d.write_text(json.dumps({"index": i, "core_t0": round(i * step, 2),
                                 "core_t1": round((i + 1) * step, 2), "t0": t0, "t1": t1}))
    store.artifact(cid, "shard_plan", {"shards": n, "step": round(step, 2), "overlap": overlap})
    print(json.dumps({"source": info, "shards": n}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
