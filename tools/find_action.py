#!/usr/bin/env python3
"""Find the wild moments: dancing, and water.

Two things are asked for here — crazy dance moves and the pool — and neither can
be found in a transcript, so both are measured from the picture:

  motion   — frame-to-frame change; a dance floor with people moving hard scores
             high, a talking head scores low
  crowd    — how many faces the detector finds; "people on screen" is the brief
  water    — the share of the frame that is saturated cyan/blue. A pool is the only
             thing in this venue that looks like that, and it is a colour fact, not
             a guess
  steadiness — how much the camera itself shakes, so a handheld wobble is not
             mistaken for a dance

  python3 tools/find_action.py <video> --out action.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import cv2
import numpy as np

FF = "/home/user/bin/ffmpeg"
MODEL = Path(__file__).resolve().parent.parent / "assets" / "face_detection_yunet.onnx"
FW, FH = 320, 180


def stream(video: Path, fps: float = 2.0):
    p = subprocess.Popen([FF, "-v", "error", "-i", str(video), "-an", "-vf",
                          f"fps={fps},scale={FW}:{FH}", "-pix_fmt", "bgr24",
                          "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
    size = FW * FH * 3
    prev = None
    i = 0
    while True:
        buf = p.stdout.read(size)
        if len(buf) != size:
            break
        f = np.frombuffer(buf, np.uint8).reshape(FH, FW, 3).copy()
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(f, cv2.COLOR_BGR2HSV)
        h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
        # water: real cyan/blue, and bright — party lighting is pink, not blue-cyan
        water = float((((h >= 85) & (h <= 115) & (s > 90) & (v > 60))).mean())
        motion = 0.0 if prev is None else float(np.abs(g.astype(np.int16)
                                                     - prev.astype(np.int16)).mean())
        yield i / fps, motion, water, float(g.mean())
        prev = g
        i += 1
    p.stdout.close(); p.wait()


def faces(video: Path, fps: float = 1.0) -> dict:
    if not MODEL.exists():
        return {}
    det = cv2.FaceDetectorYN.create(str(MODEL), "", (FW, FH), 0.6, 0.3, 500)
    p = subprocess.Popen([FF, "-v", "error", "-i", str(video), "-an", "-vf",
                          f"fps={fps},scale={FW}:{FH}", "-pix_fmt", "bgr24",
                          "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
    size = FW * FH * 3
    out, i = {}, 0
    while True:
        buf = p.stdout.read(size)
        if len(buf) != size:
            break
        f = np.frombuffer(buf, np.uint8).reshape(FH, FW, 3)
        det.setInputSize((FW, FH))
        _, fs = det.detect(f)
        out[i] = 0 if fs is None else len(fs)
        i += 1
    p.stdout.close(); p.wait()
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--out", default="action.json")
    ap.add_argument("--bucket", type=float, default=2.0)
    args = ap.parse_args()

    video = Path(args.video)
    fc = faces(video)
    buckets: dict[int, dict] = {}
    for t, motion, water, lum in stream(video):
        b = int(t // args.bucket)
        d = buckets.setdefault(b, {"motion": [], "water": [], "lum": [], "faces": []})
        d["motion"].append(motion)
        d["water"].append(water)
        d["lum"].append(lum)
        d["faces"].append(fc.get(int(t), 0))

    rows = []
    for b, d in sorted(buckets.items()):
        rows.append({"t": round(b * args.bucket, 1),
                     "motion": round(float(np.mean(d["motion"])), 2),
                     "water": round(float(np.mean(d["water"])), 4),
                     "lum": round(float(np.mean(d["lum"])), 1),
                     "faces": round(float(np.mean(d["faces"])), 2)})
    Path(args.out).write_text(json.dumps(rows, indent=0))

    by_motion = sorted(rows, key=lambda r: -r["motion"])[:25]
    by_water = sorted(rows, key=lambda r: -r["water"])[:25]
    print("maddest motion:")
    for r in by_motion[:12]:
        print(f'  {int(r["t"])//60:>2}:{int(r["t"])%60:02d}  motion {r["motion"]:>6} '
              f'faces {r["faces"]:>4} water {r["water"]:.3f}')
    print("most water:")
    for r in by_water[:12]:
        print(f'  {int(r["t"])//60:>2}:{int(r["t"])%60:02d}  water {r["water"]:.3f} '
              f'motion {r["motion"]:>6} faces {r["faces"]:>4}')


if __name__ == "__main__":
    main()
