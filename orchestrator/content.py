#!/usr/bin/env python3
"""Content — is there anything worth watching in this frame?

The client's rule is not "keep a person on screen". It is: **something meaningful
must be happening in the frame** — a person talking, an animation playing on a
monitor, people working, a reaction, a busy room. What is not allowed is a dead
frame: a black wall, an empty backdrop, the middle of a camera move where the
frame is still swinging past a curtain.

So a frame earns its place in one of three ways:

  * **a face** is in it (the normal case for a podcast), or
  * it is **visually rich** — real detail and colour, the way a scene with action
    or a screen full of content measures, or
  * it **moves** — something is happening in it, even if the shot itself is plain.

Everything else is "dead" and is reported as such; D6 cuts dead spans out of the
plan and D9 fails a clip that still ships one. All three tests are measured on
decoded pixels, never guessed from the edit.
"""
from __future__ import annotations

import cv2
import numpy as np

# A frame is dead when all of these are true. The numbers were set against
# measured frames: studio black (std 3-6, edges 0.000), a plain curtain
# (std 12-18, edges 0.002-0.004, no colour), a real wide shot (std 35-60,
# edges 0.02-0.06, colour spread 15-40).
DEFAULTS = {
    "lum_std_min": 20.0,      # contrast: a flat wall sits well under this
    "edge_min": 0.008,        # fraction of pixels on a real edge
    "colour_min": 14.0,       # Hasler-Süsstrunk colourfulness
    "motion_min": 1.6,        # mean |frame - previous frame|
    "face_min_px": 10,        # a face smaller than this is noise
}


def _cfg(over=None) -> dict:
    c = dict(DEFAULTS)
    c.update(over or {})
    return c


def richness(bgr: np.ndarray, cfg: dict | None = None) -> dict:
    """How much is actually in this frame. Cheap enough to run at 4 fps."""
    c = _cfg(cfg)
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
    g = cv2.resize(g, (270, 480), interpolation=cv2.INTER_AREA)
    small = cv2.resize(bgr, (270, 480), interpolation=cv2.INTER_AREA) if bgr.ndim == 3 else None

    lum_std = float(g.std())
    edges = cv2.Canny(g, 60, 160)
    edge_density = float((edges > 0).mean())

    colour = 0.0
    if small is not None:
        b, gr, r = [small[:, :, i].astype(np.float32) for i in range(3)]
        rg = r - gr
        yb = 0.5 * (r + gr) - b
        colour = float(np.sqrt(rg.std() ** 2 + yb.std() ** 2)
                       + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2))

    return {"lum_std": round(lum_std, 1), "edge": round(edge_density, 4),
            "colour": round(colour, 1), "black": lum_std < c["lum_std_min"] * 0.4}


def motion(prev: np.ndarray | None, bgr: np.ndarray) -> float:
    """Mean absolute difference against the previous sample (0 when unknown)."""
    if prev is None:
        return 0.0
    a = cv2.cvtColor(prev, cv2.COLOR_BGR2GRAY) if prev.ndim == 3 else prev
    b = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
    a = cv2.resize(a, (270, 480), interpolation=cv2.INTER_AREA).astype(np.int16)
    b = cv2.resize(b, (270, 480), interpolation=cv2.INTER_AREA).astype(np.int16)
    return float(np.abs(a - b).mean())


def has_face(det, bgr: np.ndarray, cfg: dict | None = None) -> bool:
    """A YuNet detector, already sized for the frame."""
    c = _cfg(cfg)
    h, w = bgr.shape[:2]
    det.setInputSize((w, h))
    ok, faces = det.detect(bgr)
    if not ok or faces is None:
        return False
    return any(f[2] >= c["face_min_px"] and f[14] >= 0.55 for f in faces)


def judge(bgr: np.ndarray, prev: np.ndarray | None = None, face: bool = False,
          cfg: dict | None = None) -> dict:
    """Decide one frame. Returns the verdict and the numbers behind it."""
    c = _cfg(cfg)
    r = richness(bgr, c)
    m = motion(prev, bgr)
    rich = r["edge"] >= c["edge_min"] and r["colour"] >= c["colour_min"]
    moving = m >= c["motion_min"] and r["lum_std"] >= c["lum_std_min"] * 0.6
    alive = bool(face or rich or moving)
    return {"alive": alive, "face": face, **r, "motion": round(m, 2),
            "why": ("face" if face else "rich" if rich else "motion" if moving else "dead")}


def source_scan(src, t0: float, t1: float, offset: float = 0.0, fps: float = 4.0,
                w: int = 540, h: int = 960, cfg: dict | None = None) -> list[dict]:
    """Judge every sample of a source window. Times are in *source* time."""
    import subprocess

    import imageio_ffmpeg

    from . import framing

    ff = imageio_ffmpeg.get_ffmpeg_exe()
    dur = max(0.2, t1 - t0)
    raw = subprocess.run([ff, "-v", "error", "-ss", f"{max(0.0, t0 - offset):.3f}",
                          "-t", f"{dur:.3f}", "-i", str(src), "-an",
                          "-vf", f"fps={fps},scale={w}:{h}", "-f", "rawvideo",
                          "-pix_fmt", "bgr24", "-"], capture_output=True).stdout
    n = len(raw) // (w * h * 3)
    det = cv2.FaceDetectorYN.create(str(framing.MODEL), "", (w, h), 0.55, 0.3, 5000)
    out, prev = [], None
    for i in range(n):
        fr = np.frombuffer(raw[i * w * h * 3:(i + 1) * w * h * 3], np.uint8).reshape(h, w, 3)
        v = judge(fr, prev, face=has_face(det, fr, cfg), cfg=cfg)
        v["t"] = round(t0 + i / fps, 3)
        out.append(v)
        prev = fr
    return out


def runs(samples: list[dict], key: str = "alive", value=False, min_len: float = 0.40) -> list[list[float]]:
    """Contiguous stretches where `key` is `value`, longer than `min_len`."""
    out, start = [], None
    step = (samples[1]["t"] - samples[0]["t"]) if len(samples) > 1 else 0.25
    for s in samples:
        if s.get(key) == value:
            start = s["t"] if start is None else start
        elif start is not None:
            if s["t"] - start >= min_len:
                out.append([round(start, 2), round(s["t"], 2)])
            start = None
    if start is not None and samples and samples[-1]["t"] + step - start >= min_len:
        out.append([round(start, 2), round(samples[-1]["t"] + step, 2)])
    return out
