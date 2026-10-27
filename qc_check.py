#!/usr/bin/env python3
"""Sample a finished clip and report %% of frames that contain a face.

Usage: python3 qc_check.py clips_v3/ep02.mp4 [more.mp4 ...]
Writes a contact sheet to assets/qc_<name>.jpg
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import imageio_ffmpeg

FF = imageio_ffmpeg.get_ffmpeg_exe()
ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
W, H = 270, 480          # analysis size
_casc = None


def casc():
    global _casc
    if _casc is None:
        _casc = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    return _casc


def any_face(gray):
    for sc in (0.35, 0.55, 1.0):
        g = gray if sc == 1.0 else cv2.resize(gray, None, fx=sc, fy=sc,
                                             interpolation=cv2.INTER_AREA)
        if len(casc().detectMultiScale(g, 1.12, 5, minSize=(24, 24))) > 0:
            return True
    return False


def sheet(frames, out, cols=8):
    if not frames:
        return
    rows = (len(frames) + cols - 1) // cols
    h, w = frames[0].shape[:2]
    canvas = np.full((rows * h, cols * w, 3), 30, np.uint8)
    for i, f in enumerate(frames):
        canvas[(i // cols) * h:(i // cols) * h + h,
               (i % cols) * w:(i % cols) * w + w] = f
    cv2.imwrite(str(out), canvas, [cv2.IMWRITE_JPEG_QUALITY, 88])


def check(path: Path, fps_sample=3.0):
    raw = subprocess.run([FF, "-v", "error", "-i", str(path), "-an", "-vf",
                          f"fps={fps_sample},scale={W}:{H},format=gray",
                          "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                         capture_output=True).stdout
    n = len(raw) // (W * H)
    good, frames = 0, []
    for i in range(n):
        g = np.frombuffer(raw[i * W * H:(i + 1) * W * H], np.uint8).reshape(H, W)
        ok = any_face(g)
        good += ok
        frames.append(cv2.cvtColor(g, cv2.COLOR_GRAY2BGR))
    cov = good / max(1, n)
    sheet(frames, ASSETS / f"qc_{path.stem}.jpg")
    return n, cov


def main():
    ASSETS.mkdir(exist_ok=True)
    for p in sys.argv[1:]:
        path = Path(p)
        n, cov = check(path)
        flag = "OK" if cov >= 0.9 else ("CHECK" if cov >= 0.75 else "BAD")
        print(f"{path.name:16s} {n:3d} samples  face {cov*100:5.1f}%  [{flag}]")


if __name__ == "__main__":
    main()
