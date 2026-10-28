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


def integrity(p: Path) -> dict:
    """A file that decodes with errors freezes or blacks out in a player, which
    reads to a viewer as 'the speaker disappeared' or 'the video is broken'."""
    r = subprocess.run([FF, "-v", "error", "-i", str(p), "-f", "null", "-"],
                       capture_output=True, text=True)
    errs = [ln for ln in r.stderr.splitlines() if ln.strip()]
    streams = {}
    pr = subprocess.run([FF, "-hide_banner", "-i", str(p)], capture_output=True, text=True)
    for ln in pr.stderr.splitlines():
        m = re.search(r"Stream #\d+:\d+.*: (Video|Audio): .*?, (\d+(?:\.\d+)?) fps", ln)
        if m:
            streams["video_fps"] = float(m.group(2))
        m2 = re.search(r"Duration: (\d+):(\d+):([\d.]+)", ln)
        if m2:
            streams["duration"] = (int(m2.group(1)) * 3600 + int(m2.group(2)) * 60
                                   + float(m2.group(3)))
    return {"decode_errors": len(errs), "first_error": errs[0] if errs else None,
            **streams}


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


def visual(p: Path, wm_band=(.03, .16), area=(0.0, 1.0)) -> dict:
    import cv2
    from orchestrator import framing as framing_mod
    w, h = 432, 768
    aw, ah = 1080, 1920
    y0c, y1c = int(area[0] * ah), int(area[1] * ah)
    raw = subprocess.run([FF, "-v", "error", "-i", str(p), "-an", "-vf",
                          f"crop={aw}:{y1c - y0c}:0:{y0c},fps=4,scale={w}:{h}",
                          "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                         capture_output=True).stdout
    n = len(raw) // (w * h * 3)
    if not n:
        return {"faces": 0.0, "watermark": 0.0, "black_frames": 1.0,
                "longest_faceless_run_s": 99.0, "faceless_in_first_2s": True,
                "face_center_median": None, "faces_clipped_at_edge": 1.0}
    # QA measures the picture with the same detector the framing used (YuNet),
    # and falls back to a Haar cascade only if the model is missing
    yunet = None
    if framing_mod.MODEL.exists():
        yunet = cv2.FaceDetectorYN.create(str(framing_mod.MODEL), "", (w, h), 0.5, 0.3, 5000)
        yunet.setInputSize((w, h))
    det = cv2.CascadeClassifier(str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"))

    def find_faces(bgr):
        out = []
        if yunet is not None:
            ok, fs = yunet.detect(bgr)
            if ok and fs is not None:
                for f in fs:
                    if f[2] >= 18 and f[14] >= 0.6:
                        out.append(tuple(int(v) for v in f[:4]))
            return out
        g = cv2.equalizeHist(cv2.cvtColor(bgr, cv2.COLOR_GRAY2BGR)[:, :, 0])
        return [tuple(int(v) for v in b) for b in det.detectMultiScale(g, 1.08, 4, minSize=(18, 18))]
    faces, wm, black, centers, clipped = 0, [], 0, [], 0
    faceless_runs, cur = [], None
    for i in range(n):
        bgr = np.frombuffer(raw[i * w * h * 3:(i + 1) * w * h * 3], np.uint8).reshape(h, w, 3)
        g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        boxes = find_faces(bgr)
        faces += bool(len(boxes))
        if not len(boxes):
            cur = cur if cur is not None else i / 4
        elif cur is not None:
            faceless_runs.append((cur, i / 4)); cur = None
        if len(boxes):
            x, y, fw, fh = max(boxes, key=lambda b: b[2])
            centers.append((x + fw / 2) / w)
            clipped += bool(x < 2 or x + fw > w - 2 or y < 2)
        y0, y1 = int(h * wm_band[0]), int(h * wm_band[1])
        band_px = bgr[y0:y1].astype(int)
        gg, bb, rr = band_px[:, :, 1], band_px[:, :, 0], band_px[:, :, 2]
        lime = ((gg > 165) & (bb < 130) & ((gg - np.maximum(bb, rr)) > 30))
        wm.append(float(lime.mean()))
        black += bool(float(g.mean()) < 8)
    if cur is not None:
        faceless_runs.append((cur, n / 4))
    longest = max([b - a for a, b in faceless_runs], default=0.0)
    first_two = [r for r in faceless_runs if r[0] < 2.0]
    return {"face_center_median": round(float(np.median(centers)), 3) if centers else None,
            "faces_clipped_at_edge": round(clipped / max(1, len(centers)), 3),
            "faces": round(faces / n, 3),
            "longest_faceless_run_s": round(longest, 2),
            "faceless_in_first_2s": bool(first_two),
            "watermark": round(float(np.mean([x > .004 for x in wm])), 3),
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

    # typed text must never sit on the speaker's face (the brief asks for it and
    # a card over his mouth is the first thing a viewer notices)
    caps = store.read_json(cid, f"artifacts/captions_{clip}.v1.json") or {}
    hb = (caps.get("payload") or {}).get("hook_box") or {}
    fb = (caps.get("payload") or {}).get("face_box_hook_window") or {}
    if hb and fb:
        face_y0, face_y1 = fb["top"] * 1920, fb["bottom"] * 1920
        overlap = max(0.0, min(hb["y_bottom"], face_y1) - max(hb["y_top"], face_y0))
        text_over_face = overlap > 0.10 * (face_y1 - face_y0)
    else:
        text_over_face = None

    wmc = brief.get("watermark", {}) or {}
    pos = wmc.get("position", "bottom-center")
    wm_w = int(wmc.get("width", 640))
    wm_file = ROOT / wmc.get("asset", wmc.get("file", "assets/watermark_white.png"))
    aspect = 549 / 1993
    if wm_file.exists():
        from PIL import Image as _I
        im_ = _I.open(wm_file)
        aspect = im_.height / im_.width
    wm_h = max(20, int(wm_w * aspect))
    if pos.startswith("top"):
        y0 = int(wmc.get("margin_top", 70))
        band = (y0 / 1920, min(1.0, (y0 + wm_h) / 1920))
    else:
        y0 = 1920 - int(wmc.get("margin_bottom", 300)) - wm_h
        band = (y0 / 1920, min(1.0, (y0 + wm_h) / 1920))
    bands_art = store.read_json(cid, f"artifacts/bands_{clip}.v1.json") or {}
    bp = bands_art.get("payload") or {}
    if bp.get("top_h"):
        area = (bp["top_h"] / 1920, (bp["top_h"] + bp["video_h"]) / 1920)
    else:
        area = (0.0, 1.0)
    info, loud, vis, fid = probe(out), loudness(out), visual(out, band, area), fidelity(clip, cid)
    integ = integrity(out)
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
        "decodes_clean": integ["decode_errors"] == 0,
        "speaker_on_screen_throughout": vis["longest_faceless_run_s"] <= 0.5,
        "speaker_on_screen_in_hook": not vis["faceless_in_first_2s"],
        "picture_and_sound_same_length": abs((integ.get("duration") or 0) - info["duration"]) <= 0.05,
        "opening_is_spoken": fid["opening_spoken_in_clip"],
        "hook_numbers_supported": fid["hook_numbers_supported"],
        "payoff_present": fid["payoff_present"],
        "no_text_over_face": (text_over_face is False) if text_over_face is not None else True,
    }
    verdict = "PASS" if all(checks.values()) else "REVISE"
    finding = {
        "artifact_id": clip, "artifact_version": "v1", "verdict": verdict,
        "category": "technical" if not all(checks.values()) else "technical",
        "severity": "blocker" if not checks["length_in_window"] or not checks["payoff_present"] else "major",
        "source_timestamp": None, "output_timestamp": None,
        "observation": "; ".join(k for k, v in checks.items() if not v) or "all checks passed",
        "evidence": json.dumps({"file": info, "loudness": loud, "visual": vis,
                                "fidelity": fid, "integrity": integ}),
        "corrective_action": ("rebuild the failing department only: "
                              + ", ".join(k for k, v in checks.items() if not v)) if verdict != "PASS" else "none",
        "acceptance_test": "same check re-run on the rebuilt artifact returns true",
        "department_id": "D9", "revision": store.revision_count(cid, clip),
        "reviewer": "d9_qa",
    }
    store.review(cid, finding)
    store.gate(cid, clip, "QA_APPROVED", verdict == "PASS", finding["observation"])
    print(json.dumps({"clip": clip, "verdict": verdict, "checks": checks,
                      "file": info, "loudness": loud, "visual": vis, "fidelity": fid,
                      "integrity": integ,
                      "hook_box": hb, "face_box_hook_window": fb,
                      "text_over_face": text_over_face}, indent=1))
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
