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


def sample_faces(src: Path, t0: float, t1: float, fps: float = 4.0, offset: float = 0.0):
    """[(t, [(cx, cy, w, h) …])] in source pixels, for one piece."""
    w, h = PROXY
    dur = max(0.2, t1 - t0)
    raw = subprocess.run([FF, "-v", "error", "-ss", f"{max(0.0, t0 - offset):.3f}", "-t", f"{dur:.3f}",
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


def face_in_crop(src, t: float, box: dict, offset: float = 0.0, fps: float = 4.0) -> bool:
    """Is there a face inside the *cropped* picture at this instant?

    Detecting faces in the full frame is not the same question: the frame can hold
    two people while the planned 9:16 box points at the curtain between them. The
    only honest test decodes the crop itself.
    """
    w, h = 540, 960
    raw = subprocess.run([FF, "-v", "error", "-ss", f"{max(0.0, t - offset):.3f}",
                          "-i", str(src), "-frames:v", "1", "-an",
                          "-vf", f"crop={box['w']}:{box['h']}:{box['x']}:{box['y']},"
                                 f"scale={w}:{h}",
                          "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                         capture_output=True).stdout
    if len(raw) < w * h * 3:
        return False
    fr = np.frombuffer(raw[:w * h * 3], np.uint8).reshape(h, w, 3).copy()
    det = cv2.FaceDetectorYN.create(str(_MODEL), "", (w, h), 0.55, 0.3, 5000)
    det.setInputSize((w, h))
    ok, faces = det.detect(fr)
    return bool(ok and faces is not None and len([f for f in faces if f[2] >= 10]))


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


def audit(src: Path, pieces, fps: float = 4.0, offset: float = 0.0):
    """Fix every piece in place. Returns (pieces, report)."""
    fixed, report = [], {"checked": 0, "moved": 0, "split": 0, "no_face": 0, "dead": 0,
                         "notes": []}
    for p in pieces:
        samples = sample_faces(src, p["src_in"], p["src_out"], fps, offset=offset)
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
            report["notes"].append(f"{p['src_in']:.2f}: no face at all")
            p = dict(p); p["audit"] = "no_face"     # resolved in the pass below
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
                # only split something long enough to hold two halves; clamping a
                # 0.2 s piece produced a negative-length second half
                if p["src_out"] - p["src_in"] < 0.6:
                    cut_at = None
                    break
                cut_at = min(max(cut_at, p["src_in"] + 0.12), p["src_out"] - 0.12)
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

            # Candidate framings: the planned box first, then the box centred on
            # each person actually seen in the piece. The chosen one has to pass a
            # test on the decoded crop — a box that contains no face is on the
            # curtain between two people, however plausible it looks on paper.
            cands = [dict(box)]
            clusters = []
            for _, f in sub:
                if all(abs(f[0] - c[0]) > box["w"] * 0.3 for c in clusters):
                    clusters.append(f)
            for f in sorted(clusters, key=lambda f: abs(f[0] - (box["x"] + box["w"] / 2))):
                cands.append(_shift(box, f))
            probes = [h0 + (h1 - h0) * k for k in (0.3, 0.7)] if h1 > h0 else [h0]
            chosen = None
            for cand in cands:
                hits = sum(1 for t in probes if face_in_crop(src, t, cand, offset=offset))
                if hits == len(probes):
                    chosen = cand
                    break
            if chosen is None:
                part["dead"] = True
                report["dead"] = report.get("dead", 0) + 1
                report["notes"].append(f"{h0:.2f}-{h1:.2f}: no face inside any framing — "
                                       f"cut this span out of the plan")
                fixed.append(part)
                continue
            if chosen != box:
                report["moved"] += 1
                report["notes"].append(f"{h0:.2f}: framing moved x {box['x']}→{chosen['x']}")
            part["crop"] = chosen
            part["audit"] = "moved" if part["crop"] != box else "kept"
            if hi:
                part.pop("glide", None)
            fixed.append(part)

    # A stretch where the detector sees nothing must not be framed by the guess
    # that produced it: hold the nearest framed box so the camera stays on the
    # person who was just talking instead of drifting to the empty chair.
    known = [(i, q) for i, q in enumerate(fixed)
             if q.get("audit") in ("moved", "kept") and q.get("crop")]
    for i, q in enumerate(fixed):
        if q.get("audit") != "no_face" or not known:
            continue
        near = min(known, key=lambda kq: min(abs(kq[1]["src_in"] - q["src_out"]),
                                             abs(q["src_in"] - kq[1]["src_out"])))
        q["crop"] = dict(near[1]["crop"])
        q["audit"] = "inherited"
        report["notes"].append(f"{q['src_in']:.2f}: held the last framed box "
                               f"(from {near[1]['src_in']:.2f})")

    return fixed, report
