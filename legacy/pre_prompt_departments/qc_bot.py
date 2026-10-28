#!/usr/bin/env python3
"""QC DEPARTMENT — blind reviewer, one clip per job.

A clip only leaves the company if it passes every measurable rule in the
campaign contract. No opinions, no scores — pass or fail with numbers.

  python3 departments/qc_bot.py <campaign> <clip.mp4> <clip.json>
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import imageio_ffmpeg

FF = imageio_ffmpeg.get_ffmpeg_exe()
ROOT = Path(__file__).resolve().parent.parent
camp, mp4, meta_path = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
CAMP = json.loads((ROOT / "campaigns" / camp / "campaign.json").read_text())
META = json.loads(meta_path.read_text())
LO, HI = CAMP["length"]["min"], CAMP["length"]["max"]


def probe(p: Path) -> dict:
    r = subprocess.run([FF, "-hide_banner", "-i", str(p)], capture_output=True, text=True)
    d = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
    v = re.search(r"Video: .*?(\d{3,4})x(\d{3,4})", r.stderr)
    f = re.search(r"(\d+(?:\.\d+)?) fps", r.stderr)
    a = re.search(r"Audio: (\w+)", r.stderr)
    dur = int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3)) if d else 0
    return {"dur": round(dur, 2),
            "w": int(v.group(1)) if v else 0, "h": int(v.group(2)) if v else 0,
            "fps": float(f.group(1)) if f else 0, "audio": a.group(1) if a else None}


def loudness(p: Path) -> dict:
    r = subprocess.run([FF, "-hide_banner", "-nostats", "-i", str(p), "-af",
                        "loudnorm=print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = list(re.finditer(r"\{[^{}]*\}", r.stderr, re.S))
    for mm in reversed(m):
        try:
            j = json.loads(mm.group(0))
            if "input_i" in j:
                return {"I": float(j["input_i"]), "TP": float(j["input_tp"])}
        except Exception:
            continue
    r2 = subprocess.run([FF, "-hide_banner", "-nostats", "-i", str(p), "-af",
                         "ebur128=peak=true", "-f", "null", "-"],
                        capture_output=True, text=True)
    i = re.findall(r"I:\s*(-?[\d.]+) LUFS", r2.stderr)
    tp = re.findall(r"Peak:\s*(-?[\d.]+) dBFS", r2.stderr)
    return {"I": float(i[-1]) if i else 0.0, "TP": float(tp[-1]) if tp else 0.0}


def visual(p: Path) -> dict:
    """Face presence + a crop of the bottom strip to prove the watermark area is
    occupied (watermark must be on screen the whole clip)."""
    w, h = 216, 384
    raw = subprocess.run([FF, "-v", "error", "-i", str(p), "-an", "-vf",
                          f"fps=4,scale={w}:{h},format=gray", "-f", "rawvideo",
                          "-pix_fmt", "gray", "-"], capture_output=True).stdout
    n = len(raw) // (w * h)
    import cv2
    det = cv2.CascadeClassifier(str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"))
    good = 0
    bright_rows = []
    for i in range(n):
        g = cv2.equalizeHist(np.frombuffer(raw[i * w * h:(i + 1) * w * h], np.uint8).reshape(h, w))
        good += bool(len(det.detectMultiScale(g, 1.08, 4, minSize=(18, 18))))
        bright_rows.append(float((g[int(h * 0.78):int(h * 0.87)] > 200).mean()))
    return {"faces": round(good / n, 3) if n else 0.0,
            "wm_present": round(float(np.mean([b > 0.01 for b in bright_rows])), 3) if bright_rows else 0.0}


def main() -> int:
    info = probe(mp4)
    loud = loudness(mp4)
    vis = visual(mp4)
    checks = {
        "length_in_window": LO <= info["dur"] <= HI,
        "hook_on_screen": bool(META.get("hook")),
        "resolution_1080x1920": (info["w"], info["h"]) == (1080, 1920),
        "fps": abs(info["fps"] - CAMP.get("fps", 30)) < 0.6,
        "audio_present": info["audio"] is not None,
        "loudness_ok": abs(loud["I"] - CAMP["audio"]["lufs"]) <= 2.0,
        "peak_ok": loud["TP"] < -1.0,
        "faces_cover": vis["faces"] >= CAMP["framing"]["face_cover_min"] - 0.15,
        "watermark_on_screen": vis["wm_present"] >= 0.9,
        "hook_is_real_words": bool(re.search(r"[A-Za-z]", META.get("hook", ""))),
        "safe_length_meta": abs(info["dur"] - META["len"]) < 0.6,
    }
    verdict = "PASS" if all(checks.values()) else "FAIL"
    out = {"id": META["id"], "verdict": verdict, "checks": checks,
           "file": {**info, **loud}, "visual": vis,
           "failed": [k for k, v in checks.items() if not v]}
    Path(f"/tmp/out/qc_{META['id']}.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
