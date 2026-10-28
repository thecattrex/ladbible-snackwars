#!/usr/bin/env python3
"""Framing — per-shot face map and a speaker-aware 9:16 crop.

Why this exists: a podcast episode cuts between close-ups and wide two-shots.
One crop decision for the whole clip is wrong by construction — it lands on an
empty desk the moment the camera goes wide. So the framing department measures
the picture first:

  1. one decode pass over the clip window -> low-res proxy frames (4 fps);
  2. YuNet face detection on every frame (small faces included);
  3. consecutive frames with the same face layout are grouped into shots, so
     every camera cut becomes a boundary;
  4. inside a shot, the speaker is the face with the most mouth-region motion;
     a lone face is simply that face;
  5. each shot gets a crop box that keeps the speaker's face centred, and a
     "cannot frame" flag if no face exists at all (that shot is then reported,
     never silently delivered).

Everything is measured from the actual frames; nothing here is guessed from the
transcript.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import cv2
import numpy as np
import imageio_ffmpeg

FF = imageio_ffmpeg.get_ffmpeg_exe()
MODEL = Path(__file__).resolve().parent.parent / "assets" / "face_detection_yunet.onnx"


def proxy(src: Path, t0: float, t1: float, fps: float = 4.0, w: int = 960):
    h = w * 9 // 16
    raw = subprocess.run([FF, "-v", "error", "-ss", f"{t0:.3f}", "-t", f"{t1 - t0:.3f}",
                          "-i", str(src), "-vf", f"fps={fps},scale={w}:{h}",
                          "-pix_fmt", "bgr24", "-f", "rawvideo", "-"],
                         capture_output=True).stdout
    n = len(raw) // (w * h * 3)
    frames = np.frombuffer(raw[:n * w * h * 3], np.uint8).reshape(n, h, w, 3)
    return frames, fps, w, h


def detector(w: int, h: int):
    d = cv2.FaceDetectorYN.create(str(MODEL), "", (w, h), 0.55, 0.3, 5000)
    return d


def detect(d, frame, w, h):
    d.setInputSize((w, h))
    ok, faces = d.detect(frame)
    out = []
    if ok and faces is not None:
        for f in faces:
            x, y, fw, fh = f[:4]
            score = float(f[14])
            if fw < 14 or fh < 14:
                continue
            out.append({"x": float(x), "y": float(y), "w": float(fw), "h": float(fh),
                        "score": score})
    return out


def mouth_motion(prev, cur, face) -> float:
    """Mean absolute difference in the lower-middle of a face box."""
    if prev is None:
        return 0.0
    x, y, w, h = face["x"], face["y"], face["w"], face["h"]
    x0 = int(max(0, x + 0.22 * w)); x1 = int(x + 0.78 * w)
    y0 = int(max(0, y + 0.55 * h)); y1 = int(y + 0.95 * h)
    if x1 - x0 < 6 or y1 - y0 < 6:
        return 0.0
    a = cv2.cvtColor(prev[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY).astype(np.float32)
    b = cv2.cvtColor(cur[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY).astype(np.float32)
    return float(np.abs(b - a).mean())


def analyse(src: Path, t0: float, t1: float, fps: float = 4.0) -> dict:
    frames, fps, w, h = proxy(src, t0, t1, fps)
    d = detector(w, h)
    per_frame = []
    prev = None
    for i, fr in enumerate(frames):
        faces = detect(d, fr, w, h)
        for f in faces:
            f["motion"] = mouth_motion(prev, fr, f)
        faces.sort(key=lambda f: -f["w"])
        per_frame.append({"t": round(t0 + i / fps, 3), "faces": faces})
        prev = fr

    # group frames into shots by face-layout signature
    def sig(fs):
        return tuple(sorted((round(f["x"] / 60), round(f["y"] / 60), round(f["w"] / 60))
                            for f in fs))
    shots, cur = [], None
    for pf in per_frame:
        s = sig(pf["faces"])
        if cur is None or s != cur["sig"] or pf["t"] - cur["t1"] > 0.6:
            if cur:
                shots.append(cur)
            cur = {"t0": pf["t"], "t1": round(pf["t"] + 1 / fps, 3), "sig": s, "frames": [pf]}
        else:
            cur["t1"] = round(pf["t"] + 1 / fps, 3)
            cur["frames"].append(pf)
    if cur:
        shots.append(cur)

    # speaker per shot = the recurring face with the most mouth motion
    out = []
    for sh in shots:
        n_frames = len(sh["frames"])
        tally = {}
        for pf in sh["frames"]:
            for f in pf["faces"]:
                key = (round(f["x"] / 60), round(f["y"] / 60))
                e = tally.setdefault(key, {"n": 0, "w": [], "motion": 0.0, "x": [], "y": []})
                e["n"] += 1
                e["w"].append(f["w"])
                e["motion"] += f["motion"]
                e["x"].append(f["x"] + f["w"] / 2)
                e["y"].append(f["y"] + f["h"] / 2)
        cands = []
        for key, e in tally.items():
            if e["n"] < max(1, n_frames * 0.4):
                continue
            cands.append({"cx": float(np.median(e["x"])), "cy": float(np.median(e["y"])),
                          "w": float(np.median(e["w"])), "seen": e["n"] / n_frames,
                          "motion": e["motion"] / max(1, e["n"])})
        if not cands:
            out.append({"t0": sh["t0"], "t1": sh["t1"], "faces": 0, "speaker": None,
                        "kind": "NO_FACE", "frames": n_frames})
            continue
        close = [c for c in cands if c["w"] > 0.11 * w]
        if len(close) == 1:
            spk = close[0]
            kind = "CLOSE_ONE"
        else:
            spk = max(cands, key=lambda c: c["motion"])
            kind = "CLOSE_ONE" if len(close) == 1 else ("WIDE_TWO" if len(cands) > 1 else "WIDE_ONE")
        out.append({"t0": sh["t0"], "t1": sh["t1"], "faces": len(cands),
                    "speaker": {"cx": round(spk["cx"] / w, 4), "cy": round(spk["cy"] / h, 4),
                                "w": round(spk["w"] / w, 4), "seen": round(spk["seen"], 2),
                                "motion": round(spk["motion"], 2)},
                    "kind": kind, "frames": n_frames,
                    "candidates": [{"cx": round(c["cx"] / w, 3), "w": round(c["w"] / w, 3),
                                    "motion": round(c["motion"], 2)} for c in cands]})
    # a face drifting by a few pixels is not a camera cut: merge neighbouring
    # shots whose speaker sits in the same place at the same size
    merged = []
    for sh in out:
        if merged:
            a, b = merged[-1], sh
            sa, sb = a.get("speaker"), b.get("speaker")
            if sa and sb and abs(sa["cx"] - sb["cx"]) < 0.12 and (sa["w"] / max(1e-6, sb["w"])) < 1.45 \
                    and (sb["w"] / max(1e-6, sa["w"])) < 1.45:
                a["t1"] = b["t1"]
                a["frames"] += b["frames"]
                continue
        merged.append(sh)
    out = merged

    covered = sum(s["t1"] - s["t0"] for s in out if s["speaker"])
    return {"window": [t0, t1], "fps": fps, "frames": len(per_frame), "shots": out,
            "face_coverage": round(covered / max(0.001, t1 - t0), 3),
            "proxy_size": [w, h],
            "method": "YuNet faces @4fps, shot grouping by layout, speaker by mouth motion"}


def crop_for(shot: dict, full_w: int, full_h: int, punch: float = 1.0,
             target_face_frac: float = 0.30, anchor: float = 0.40) -> dict:
    """Map a shot's speaker position onto a 9:16 crop of the full frame.

    The crop width is chosen so the speaker's face lands at roughly
    `target_face_frac` of the output width: a close-up therefore barely zooms,
    while a wide two-shot is pushed in until the speaker reads at phone size.
    `punch` < 1 tightens the crop (a punch-in on a beat).
    """
    spk = shot.get("speaker")
    if not spk:
        crop_h = full_h
        crop_w = int(round(crop_h * 9 / 16))
        return {"x": (full_w - crop_w) // 2, "y": 0, "w": crop_w, "h": crop_h}
    face_px = spk["w"] * full_w
    crop_w = face_px / max(0.10, target_face_frac)
    crop_w = crop_w * punch
    crop_w = max(760.0, min(full_w, crop_w))
    crop_h = crop_w * 16 / 9
    if crop_h > full_h:
        crop_h = full_h
        crop_w = crop_h * 9 / 16
    crop_w, crop_h = int(round(crop_w)), int(round(crop_h))
    cx = spk["cx"] * full_w
    cy = spk["cy"] * full_h
    x = int(round(cx - crop_w / 2))
    y = int(round(cy - anchor * crop_h))
    x = max(0, min(full_w - crop_w, x))
    y = max(0, min(full_h - crop_h, y))
    return {"x": x, "y": y, "w": crop_w, "h": crop_h}
