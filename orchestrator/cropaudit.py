#!/usr/bin/env python3
"""Crop audit — the camera must always be pointing at a person.

The framing pass decides a crop per *shot* from a 4 fps face track. That track
is a summary: when the source cuts to a new setup between two samples the track
still says "wide two-shot" while the picture is already a single close-up, and
the crop that follows the old layout ends up on an empty desk. That is exactly
the bug that put 0.3 s of mic-arm-and-curtain on screen at 15.4 s of c557.

So every crop gets checked against the real picture before it is rendered:
decode the piece, look at the frames, and if the crop does not contain a face,
move it onto the nearest face; if the face jumps mid-piece the piece is split at
that frame so each part gets its own box.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import cv2
import numpy as np
import imageio_ffmpeg

FF = imageio_ffmpeg.get_ffmpeg_exe()
PROXY = (960, 540)
_MODEL = Path(__file__).resolve().parent.parent / "assets" / "face_detection_yunet.onnx"


def _detector():
    return cv2.FaceDetectorYN.create(str(_MODEL), "", PROXY, 0.6, 0.3, 5000)


def sample_faces(src: Path, t0: float, t1: float, fps: float = 4.0):
    """[(t, [(cx, cy, w, h) …])] in source pixels, for one piece."""
    w, h = PROXY
    dur = max(0.2, t1 - t0)
    raw = subprocess.run([FF, "-v", "error", "-ss", f"{max(0.0, t0):.3f}", "-t", f"{dur:.3f}",
                          "-i", str(src), "-an", "-vf", f"fps={fps},scale={w}:{h}",
                          "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                         capture_output=True).stdout
    n = len(raw) // (w * h * 3)
    det = _detector()
    out = []
    for i in range(n):
        fr = np.frombuffer(raw[i * w * h * 3:(i + 1) * w * h * 3], np.uint8).reshape(h, w, 3).copy()
        det.setInputSize((w, h))
        _, faces = det.detect(fr)
        got = []
        if faces is not None:
            for f in faces:
                x, y, fw, fh = f[:4]
                if fw < 12:                      # noise, not a face
                    continue
                got.append((float(x + fw / 2) * 3840 / w, float(y + fh / 2) * 2160 / h,
                            float(fw) * 3840 / w, float(fh) * 2160 / h))
        out.append((round(t0 + i / fps, 3), got))
    return out


def _shift(box: dict, face) -> dict:
    cx, cy = face[0], face[1]
    x = int(max(0, min(3840 - box["w"], cx - box["w"] / 2)))
    y = int(max(0, min(2160 - box["h"], cy - 0.40 * box["h"])))
    return {"x": x, "y": y, "w": box["w"], "h": box["h"]}


def _inside(box: dict, face, margin: float = 0.06) -> bool:
    mx = box["w"] * margin
    my = box["h"] * margin
    return (box["x"] + mx <= face[0] <= box["x"] + box["w"] - mx and
            box["y"] + my <= face[1] <= box["y"] + box["h"] - my)


def audit(src: Path, pieces, fps: float = 4.0):
    """Fix every piece in place. Returns (pieces, report)."""
    fixed, report = [], {"checked": 0, "moved": 0, "split": 0, "no_face": 0, "notes": []}
    for p in pieces:
        samples = sample_faces(src, p["src_in"], p["src_out"], fps)
        report["checked"] += 1
        box = dict(p["crop"])

        # per-sample target: the largest face (the person being shot)
        targets = []
        for t, faces in samples:
            if not faces:
                targets.append((t, None))
                continue
            targets.append((t, max(faces, key=lambda f: f[2])))

        have = [t for t, f in targets if f]
        if not have:
            report["no_face"] += 1
            report["notes"].append(f"{p['src_in']:.2f}: no face at all — left as planned")
            fixed.append(p)
            continue

        # a jump in face size or position means the source cut inside the piece:
        # split there so each side of the cut gets the crop it deserves
        cut_at = None
        for i in range(1, len(targets)):
            (ta, fa), (tb, fb) = targets[i - 1], targets[i]
            if fa is None or fb is None:
                continue
            if (abs(fb[0] - fa[0]) > box["w"] * 0.35 or
                    (fa[2] > 0 and not 0.6 <= fb[2] / fa[2] <= 1.7)):
                cut_at = tb if ta < (p["src_in"] + p["src_out"]) / 2 else ta
                cut_at = max(p["src_in"] + 0.12, min(p["src_out"] - 0.12, cut_at))
                break

        halves = [(p["src_in"], p["src_out"])] if cut_at is None else \
                 [(p["src_in"], cut_at), (cut_at, p["src_out"])]
        if cut_at is not None:
            report["split"] += 1
            report["notes"].append(f"split at {cut_at:.2f}: face jumps inside the piece")

        for hi, (h0, h1) in enumerate(halves):
            sub = [(t, f) for t, f in targets if h0 - 0.26 <= t <= h1 + 0.26 and f]
            part = dict(p)
            part["src_in"], part["src_out"] = round(h0, 3), round(h1, 3)
            part["crop"] = dict(box)
            if sub:
                # does the planned box already hold the subject?
                cover = sum(1 for _, f in sub if _inside(box, f)) / len(sub)
                if cover < 0.6:
                    best = max(sub, key=lambda s: s[1][2])[1]
                    part["crop"] = _shift(box, best)
                    report["moved"] += 1
                    report["notes"].append(
                        f"{h0:.2f}: crop was on nobody ({cover:.0%} of frames), "
                        f"moved x {box['x']}→{part['crop']['x']}")
                else:
                    part["crop"] = _shift(box, max(sub, key=lambda s: s[1][2])[1])
            part["audit"] = "moved" if part["crop"] != box else "kept"
            if hi:
                part.pop("glide", None)
                part.pop("box_to", None)
                part.pop("move", None)
            fixed.append(part)
    return fixed, report
