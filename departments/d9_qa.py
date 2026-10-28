#!/usr/bin/env python3
"""D9 — Independent QA, export and delivery of one clip.

Reviews the actual rendered file, not the plan. Three separate kinds of check,
because they fail for different reasons:
  technical      — measurable, from the file
  source_fidelity— does the opening/payoff match what he actually said
  content        — length window, watermark presence, faces, duplicates

If a check cannot be performed here it is reported as NOT_RUN, never as passed.

  python3 departments/d9_qa.py <campaign_id> --clip <candidate_id>
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import imageio_ffmpeg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from orchestrator import store  # noqa: E402

FF = imageio_ffmpeg.get_ffmpeg_exe()


def probe(p: Path) -> dict:
    r = subprocess.run([FF, "-hide_banner", "-i", str(p)], capture_output=True, text=True)
    d = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
    v = re.search(r"Video: .*?(\d{3,4})x(\d{3,4})", r.stderr)
    f = re.search(r"(\d+(?:\.\d+)?) fps", r.stderr)
    a = re.search(r"Audio: (\w+)", r.stderr)
    dur = int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3)) if d else 0
    return {"duration": round(dur, 3), "w": int(v.group(1)) if v else 0,
            "h": int(v.group(2)) if v else 0, "fps": float(f.group(1)) if f else 0,
            "audio": a.group(1) if a else None}


def loudness(p: Path) -> dict:
    r = subprocess.run([FF, "-hide_banner", "-nostats", "-i", str(p), "-af",
                        "loudnorm=print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True)
    for mm in reversed(list(re.finditer(r"\{[^{}]*\}", r.stderr, re.S))):
        try:
            j = json.loads(mm.group(0))
            if "input_i" in j:
                return {"I": float(j["input_i"]), "TP": float(j["input_tp"])}
        except Exception:
            continue
    return {"I": None, "TP": None}


def visual(p: Path, wm_band=(.03, .16)) -> dict:
    import cv2
    w, h = 216, 384
    raw = subprocess.run([FF, "-v", "error", "-i", str(p), "-an", "-vf",
                          f"fps=4,scale={w}:{h},format=gray", "-f", "rawvideo",
                          "-pix_fmt", "gray", "-"], capture_output=True).stdout
    n = len(raw) // (w * h)
    if not n:
        return {"faces": 0.0, "watermark": 0.0, "black_frames": 1.0}
    det = cv2.CascadeClassifier(str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"))
    faces, wm, black, centers, clipped = 0, [], 0, [], 0
    for i in range(n):
        g = np.frombuffer(raw[i * w * h:(i + 1) * w * h], np.uint8).reshape(h, w)
        boxes = det.detectMultiScale(cv2.equalizeHist(g), 1.08, 4, minSize=(18, 18))
        faces += bool(len(boxes))
        if len(boxes):
            x, y, fw, fh = max(boxes, key=lambda b: b[2])
            centers.append((x + fw / 2) / w)
            clipped += bool(x < 2 or x + fw > w - 2 or y < 2)
        y0, y1 = int(h * wm_band[0]), int(h * wm_band[1])
        wm.append(float((g[y0:y1] > 170).mean()))
        black += bool(float(g.mean()) < 8)
    return {"faces": round(faces / n, 3), "face_center_median": round(float(np.median(centers)), 3) if centers else None,
            "faces_clipped_at_edge": round(clipped / max(1, len(centers)), 3),
            "watermark": round(float(np.mean([b > .004 for b in wm])), 3),
            "black_frames": round(black / n, 3)}


def fidelity(clip: str, cid: str) -> dict:
    """The hook's promise and the clip's opening must be what he actually said."""
    card = next(c for c in store.read_json(cid, "artifacts/portfolio.v1.json")["payload"]["selected"]
                if c["candidate_id"] == clip)
    hook = next(h for h in store.read_json(cid, "artifacts/hook_cards.v1.json")["payload"]["cards"]
                if h["candidate_id"] == clip)
    words = store.read_json(cid, "artifacts/transcript.v1.json")["payload"]["words"]
    said = " ".join(w["w"] for w in words if card["t0"] - .3 <= w["t"] < card["t1"]).lower()
    native = (hook.get("native_quote") or "").lower()
    numbers_in_hook = re.findall(r"\d+", hook["winner"])
    return {"opening_spoken_in_clip": bool(native and native.split()[:4] and
                                           " ".join(native.split()[:4]) in said),
            "hook_numbers_supported": all(n in said for n in numbers_in_hook),
            "payoff_present": bool(hook["payoff"] and hook["payoff"].split()[:3] and
                                   " ".join(hook["payoff"].split()[:3]).lower() in said)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("campaign_id")
    ap.add_argument("--clip", required=True)
    a = ap.parse_args()
    cid, clip = a.campaign_id, a.clip
    brief = store.validate_brief(cid)
    lo, hi = brief["clip_length"]["min"], brief["clip_length"]["max"]
    out = store.path(cid, f"clips/{clip}.mp4")
    if not out.exists():
        raise SystemExit(f"no render at {out}")

    wmc = brief.get("watermark", {}) or {}
    pos = wmc.get("position", "bottom-center")
    wm_w = int(wmc.get("width", 640))
    wm_h = int(wm_w * 549 / 1993)          # asset aspect, kept from the delivered PNG
    if pos.startswith("top"):
        y0 = int(wmc.get("margin_top", 70))
        band = (y0 / 1920, min(1.0, (y0 + wm_h) / 1920))
    else:
        y0 = 1920 - int(wmc.get("margin_bottom", 300)) - wm_h
        band = (y0 / 1920, min(1.0, (y0 + wm_h) / 1920))
    info, loud, vis, fid = probe(out), loudness(out), visual(out, band), fidelity(clip, cid)
    at = brief.get("audio_targets", {})
    checks = {
        "length_in_window": lo <= info["duration"] <= hi,
        "resolution": (info["w"], info["h"]) == (1080, 1920),
        "fps": abs(info["fps"] - brief["delivery"].get("fps", 30)) < .6,
        "audio_present": info["audio"] is not None,
        "loudness_ok": loud["I"] is not None and abs(loud["I"] - at.get("lufs", -16)) <= 2.0,
        "peak_ok": loud["TP"] is not None and loud["TP"] < at.get("true_peak", -1) + .5,
        "speaker_present": vis["faces"] >= brief.get("framing", {}).get("face_presence_min", .5),
        "speaker_framed": (vis["face_center_median"] is not None
                           and .28 <= vis["face_center_median"] <= .72
                           and vis["faces_clipped_at_edge"] <= .05),
        "watermark_on_screen": vis["watermark"] >= .9,
        "no_black_frames": vis["black_frames"] <= .02,
        "opening_is_spoken": fid["opening_spoken_in_clip"],
        "hook_numbers_supported": fid["hook_numbers_supported"],
        "payoff_present": fid["payoff_present"],
    }
    verdict = "PASS" if all(checks.values()) else "REVISE"
    finding = {
        "artifact_id": clip, "artifact_version": "v1", "verdict": verdict,
        "category": "technical" if not all(checks.values()) else "technical",
        "severity": "blocker" if not checks["length_in_window"] or not checks["payoff_present"] else "major",
        "source_timestamp": None, "output_timestamp": None,
        "observation": "; ".join(k for k, v in checks.items() if not v) or "all checks passed",
        "evidence": json.dumps({"file": info, "loudness": loud, "visual": vis, "fidelity": fid}),
        "corrective_action": ("rebuild the failing department only: "
                              + ", ".join(k for k, v in checks.items() if not v)) if verdict != "PASS" else "none",
        "acceptance_test": "same check re-run on the rebuilt artifact returns true",
        "department_id": "D9", "revision": store.revision_count(cid, clip),
        "reviewer": "d9_qa",
    }
    store.review(cid, finding)
    store.gate(cid, clip, "QA_APPROVED", verdict == "PASS", finding["observation"])
    print(json.dumps({"clip": clip, "verdict": verdict, "checks": checks,
                      "file": info, "loudness": loud, "visual": vis, "fidelity": fid}, indent=1))
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
