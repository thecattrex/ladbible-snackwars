#!/usr/bin/env python3
"""D3 — Whole-video understanding and audiovisual indexing.

Builds the shared map D4 is not allowed to skip: where the picture changes, who
is on screen, what the transcript is doing there, and which intervals were
actually inspected versus left uncertain.

This box samples frames; it does not watch every frame. The coverage map says so
explicitly so no later department can claim a full visual review.

  python3 departments/d3_index.py <campaign_id> [--sample 20]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import imageio_ffmpeg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from orchestrator import store  # noqa: E402

FF = imageio_ffmpeg.get_ffmpeg_exe()
SRC = Path("/tmp/src.mp4")


def scene_changes(t0: float, t1: float) -> list:
    """Cheap histogram-based cut detection on a low-resolution proxy."""
    w, h = 320, 180
    raw = subprocess.run([FF, "-v", "error", "-ss", f"{max(0, t0):.2f}", "-t", f"{t1 - t0:.2f}",
                          "-i", str(SRC), "-vf", f"fps=2,scale={w}:{h}", "-pix_fmt", "bgr24",
                          "-f", "rawvideo", "-"], capture_output=True).stdout
    n = len(raw) // (w * h * 3)
    cuts, prev = [], None
    for i in range(n):
        f = np.frombuffer(raw[i * w * h * 3:(i + 1) * w * h * 3], np.uint8).reshape(h, w, 3)
        hist = cv2.calcHist([f], [0, 1], None, [16, 16], [0, 256, 0, 256])
        cv2.normalize(hist, hist)
        if prev is not None:
            d = cv2.compareHist(prev, hist, cv2.HISTCMP_BHATTACHARYYA)
            if d > 0.45:
                cuts.append(round(t0 + i / 2, 2))
        prev = hist
    return cuts[:400]


def faces_and_layout(t: float) -> dict:
    w = 640
    h = w * 9 // 16 // 2 * 2
    raw = subprocess.run([FF, "-v", "error", "-ss", f"{max(0, t):.2f}", "-i", str(SRC),
                          "-frames:v", "1", "-vf", f"scale={w}:{h}", "-pix_fmt", "gray",
                          "-f", "rawvideo", "-"], capture_output=True).stdout
    if len(raw) < w * h:
        return {"faces": 0, "boxes": []}
    g = cv2.equalizeHist(np.frombuffer(raw[:w * h], np.uint8).reshape(h, w))
    det = cv2.CascadeClassifier(str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"))
    boxes = [[round(x * 3840 / w), round(y * 2160 / h), round(fw * 3840 / w)]
             for (x, y, fw, fh) in det.detectMultiScale(g, 1.08, 5, minSize=(28, 28))]
    return {"faces": len(boxes), "boxes": boxes[:3]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("campaign_id")
    ap.add_argument("--sample", type=float, default=20.0, help="seconds between sampled frames")
    a = ap.parse_args()
    cid = a.campaign_id
    meta = store.read_json(cid, "artifacts/source_meta.v1.json")["payload"]
    dur = meta["duration"]

    samples, t = [], 0.0
    while t < dur:
        samples.append({"t": round(t, 2), **faces_and_layout(t)})
        t += a.sample
    cuts = scene_changes(0, dur)

    words = store.read_json(cid, "artifacts/transcript.v1.json")["payload"]["words"]
    topics = []
    win = 60.0
    for start in np.arange(0, max(1.0, dur), win):
        seg = [w["w"] for w in words if start <= w["t"] < start + win]
        if seg:
            topics.append({"window": [round(start, 1), round(min(dur, start + win), 1)],
                           "words": len(seg), "first": " ".join(seg[:12]),
                           "faces_sampled": sum(s["faces"] for s in samples
                                                if start <= s["t"] < start + win)})

    map_ = {
        "campaign_id": cid,
        "source_duration": dur,
        "sampled_frames": len(samples),
        "sampling_interval_s": a.sample,
        "scene_cuts_detected": len(cuts),
        "scene_cuts": cuts[:200],
        "transcript_windows": topics,
        "coverage": {
            "audio": {"status": "INSPECTED", "note": "full transcript, word timings"},
            "visual": {"status": "SAMPLED", "note": f"1 frame / {a.sample}s — not frame-by-frame"},
            "motion": {"status": "NOT_INSPECTED",
                       "note": "no motion review performed at this stage"},
            "uncertain_intervals": [g["at"] for g in
                                    (store.read_json(cid, "artifacts/boundary_report.v1.json")["payload"]["gaps"] or [])],
        },
        "visual_summary": {
            "intervals_with_faces": sum(1 for s in samples if s["faces"]),
            "intervals_without_faces": sum(1 for s in samples if not s["faces"]),
            "max_faces_seen": max([s["faces"] for s in samples], default=0),
        },
    }
    store.artifact(cid, "av_index", map_)
    store.artifact(cid, "coverage_map", map_["coverage"])
    print(json.dumps({"sampled": len(samples), "cuts": len(cuts),
                      "faces": map_["visual_summary"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
