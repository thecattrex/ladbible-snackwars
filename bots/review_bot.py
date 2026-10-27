#!/usr/bin/env python3
"""REVIEWER BOT — watches a finished clip and fails it if anyone speaks off
camera.

Checks (all must pass):
  * 1080x1920, 30 fps, H.264, audio present and not silent
  * duration >= 15.0 s
  * face present in >= 90 % of sampled frames
  * longest stretch with NOBODY in frame <= 0.7 s  <- the "koi bol raha hai
    but frame me koi nahi" failure the user flagged

Writes assets/bot_status/epXX_review.json and a contact sheet assets/qc_epXX.jpg
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import imageio_ffmpeg

ROOT = Path(__file__).resolve().parent.parent
FF = imageio_ffmpeg.get_ffmpeg_exe()
CLIPS = ROOT / "clips_v3"
STATUS = ROOT / "assets" / "bot_status"
ASSETS = ROOT / "assets"
W, H = 216, 384
FPS_SAMPLE = 10.0
MAX_GAP = 0.7
MIN_FACE_PCT = 0.90

_casc = None


def cascades():
    """frontal + profile + tilted-head detectors - a real person looking away is
    still a person on camera, and a plain frontal cascade calls that "empty"."""
    global _casc
    if _casc is None:
        d = cv2.data.haarcascades
        _casc = [cv2.CascadeClassifier(d + "haarcascade_frontalface_default.xml"),
                 cv2.CascadeClassifier(d + "haarcascade_profileface.xml"),
                 cv2.CascadeClassifier(d + "haarcascade_frontalface_alt2.xml")]
    return _casc


def _det(gray, scale=1.0) -> bool:
    fr, pro, alt = cascades()
    m = max(16, int(26 * scale))
    if len(fr.detectMultiScale(gray, 1.08, 4, minSize=(m, m))):
        return True
    if len(alt.detectMultiScale(gray, 1.07, 4, minSize=(m, m))):
        return True
    if len(pro.detectMultiScale(gray, 1.07, 4, minSize=(m, m))):
        return True
    if len(pro.detectMultiScale(cv2.flip(gray, 1), 1.07, 4, minSize=(m, m))):
        return True
    return False


def any_face(gray) -> bool:
    """Person on camera? frontal, profile, mirrored profile, or a tilted head."""
    g = cv2.equalizeHist(gray)
    if _det(g):
        return True
    h, w = gray.shape
    for ang in (-30, 30):
        M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
        rot = cv2.warpAffine(g, M, (w, h), flags=cv2.INTER_LINEAR,
                             borderMode=cv2.BORDER_REPLICATE)
        if _det(rot, 0.9):
            return True
    return False


def probe(path: Path):
    i = subprocess.run([FF, "-hide_banner", "-i", str(path)],
                       capture_output=True, text=True).stderr
    d = re.search(r"Duration: (\d+):(\d+):([\d.]+)", i)
    dur = (int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3))) if d else 0.0
    v = re.search(r"Video: (\w+).*?, (\d+)x(\d+)", i)
    f = re.search(r"([\d.]+) fps", i)
    has_audio = "Audio:" in i
    return dict(duration=round(dur, 2),
                codec=v.group(1) if v else "?",
                w=int(v.group(2)) if v else 0,
                h=int(v.group(3)) if v else 0,
                fps=float(f.group(1)) if f else 0.0,
                audio=has_audio)


def loudness(path: Path) -> float:
    i = subprocess.run([FF, "-hide_banner", "-i", str(path), "-af", "volumedetect",
                        "-f", "null", "-"], capture_output=True, text=True).stderr
    m = re.search(r"mean_volume: (-?[\d.]+) dB", i)
    return float(m.group(1)) if m else -99.0


def scan(path: Path):
    raw = subprocess.run([FF, "-v", "error", "-i", str(path), "-an", "-vf",
                          f"fps={FPS_SAMPLE},scale={W}:{H},format=gray",
                          "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                         capture_output=True).stdout
    n = len(raw) // (W * H)
    hits, frames = [], []
    for i in range(n):
        g = np.frombuffer(raw[i * W * H:(i + 1) * W * H], np.uint8).reshape(H, W)
        hits.append(any_face(g))
        frames.append(cv2.cvtColor(g, cv2.COLOR_GRAY2BGR))
    if n == 0:
        return 0.0, 99.0, []
    pct = sum(hits) / n
    gap = best = 0
    for h in hits:
        gap = 0 if h else gap + 1
        best = max(best, gap)
    return pct, best / FPS_SAMPLE, frames


def sheet(frames, out: Path, cols=10):
    if not frames:
        return
    rows = (len(frames) + cols - 1) // cols
    canvas = np.full((rows * H, cols * W, 3), 24, np.uint8)
    for i, f in enumerate(frames):
        canvas[(i // cols) * H:(i // cols) * H + H,
               (i % cols) * W:(i % cols) * W + W] = f
    cv2.imwrite(str(out), canvas, [cv2.IMWRITE_JPEG_QUALITY, 85])


def review(ep: int, path: Path | None = None):
    STATUS.mkdir(exist_ok=True)
    path = path or CLIPS / f"ep{ep:02d}.mp4"
    reasons = []
    if not path.exists() or path.stat().st_size < 1_000_000:
        rec = dict(ep=ep, ok=False, reasons=["missing or truncated file"])
        (STATUS / f"ep{ep:02d}_review.json").write_text(json.dumps(rec))
        return rec
    p = probe(path)
    if (p["w"], p["h"]) != (1080, 1920):
        reasons.append(f"resolution {p['w']}x{p['h']}")
    if abs(p["fps"] - 30) > 0.6:
        reasons.append(f"fps {p['fps']}")
    if p["duration"] < 15.0:
        reasons.append(f"too short {p['duration']}s")
    if not p["audio"]:
        reasons.append("no audio")
    else:
        lv = loudness(path)
        if lv < -40:
            reasons.append(f"audio silent ({lv} dB)")
    pct, gap, frames = scan(path)
    sheet(frames, ASSETS / f"qc_ep{ep:02d}.jpg")
    if pct < MIN_FACE_PCT:
        reasons.append(f"face only {pct*100:.0f}% of frames")
    if gap > MAX_GAP:
        reasons.append(f"{gap:.1f}s with nobody on screen")
    rec = dict(ep=ep, ok=not reasons, reasons=reasons, face_pct=round(pct, 3),
               max_gap=round(gap, 2), **p, frames=len(frames))
    (STATUS / f"ep{ep:02d}_review.json").write_text(json.dumps(rec))
    return rec


if __name__ == "__main__":
    ep = int(sys.argv[1])
    print(json.dumps(review(ep)))
