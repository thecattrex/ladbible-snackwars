#!/usr/bin/env python3
"""D6 — Picture editing, reframing.

Picture only. Produces the locked picture for one clip plus its EDL picture
events, so D7 (audio) and D8 (captions/colour) can work against a stable
timeline. Any later duration change invalidates them by design.

  python3 departments/d6_edit.py <campaign_id> --clip <candidate_id>
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
from orchestrator import store, timeline, framing  # noqa: E402

FF = imageio_ffmpeg.get_ffmpeg_exe()
import os
from pathlib import Path
MEDIA = Path(os.environ.get("MEDIA_ROOT", "/var/tmp"))
SRC = MEDIA / "src.mp4"
W, H = 1080, 1920
cv2.setNumThreads(2)


def crop_box(fr: dict, punch: bool = False):
    cw, ch = fr.get("crop_w", 1068), fr.get("crop_h", 1898)
    if punch:
        cw = int(cw * fr.get("punch_in", 1.06) ** -1)
        ch = int(cw * 16 / 9)
    return int(cw), int(ch)


def frames_at(t: float, w: int = 800):
    h = w * 9 // 16 // 2 * 2
    raw = subprocess.run([FF, "-v", "error", "-ss", f"{max(0, t):.2f}", "-i", str(SRC),
                          "-frames:v", "1", "-vf", f"scale={w}:{h}", "-pix_fmt", "gray",
                          "-f", "rawvideo", "-"], capture_output=True).stdout
    if len(raw) < w * h:
        return None
    return np.frombuffer(raw[:w * h], np.uint8).reshape(h, w), 3840 / w


def faces(t: float):
    st = frames_at(t)
    if st is None:
        return []
    g, k = st
    g = cv2.equalizeHist(g)
    det = cv2.CascadeClassifier(str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"))
    det2 = cv2.CascadeClassifier(str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_alt2.xml"))
    out = []
    for d in (det, det2):
        for (x, y, fw, fh) in d.detectMultiScale(g, 1.08, 5, minSize=(30, 30)):
            out.append((x * k, y * k, fw * k))
    keep = []
    for f in sorted(out, key=lambda z: -z[2]):
        if all(abs(f[0] - c[0]) > f[2] * .6 or abs(f[1] - c[1]) > f[2] * .6 for c in keep):
            keep.append(f)
    return keep[:2]


def stable_face(t0: float, t1: float, step: float = 1.0):
    """One framing decision for the whole clip.

    A podcast two-shot does not need a new crop every three seconds: the camera
    never moves. Sampling the window and taking the face that recurs most often
    (and sits nearest the frame centre) is more stable than re-deciding per cut,
    which is what put the first draft on a curtain.
    """
    from collections import Counter
    hits = []
    t = t0
    while t < t1:
        for (x, y, fw) in faces(t):
            if 380 <= fw <= 900 and y < 1150:
                hits.append((round(x / 120), round(y / 120), fw))
        t += step
    if not hits:
        return None
    counts = Counter((h[0], h[1]) for h in hits)
    (bx, by), _ = counts.most_common(1)[0]
    cluster = [h for h in hits if (h[0], h[1]) == (bx, by)]
    cluster.sort(key=lambda h: h[2])
    fw = cluster[len(cluster) // 2][2]
    cx = sum(h[0] for h in cluster) / len(cluster) * 120
    cy = sum(h[1] for h in cluster) / len(cluster) * 120
    return {"cx": cx + fw / 2, "cy": cy, "fw": fw, "hits": len(cluster), "samples": len(hits)}


def box_from_face(face, fr: dict, punch: bool = False):
    cw, ch = crop_box(fr, punch)
    x = int(max(0, min(3840 - cw, face["cx"] - cw / 2)))
    y = int(max(0, min(2160 - ch, face["cy"] - .40 * ch)))
    return {"x": x, "y": y, "w": cw, "h": ch}


def face_cover(path: Path) -> float:
    w, h = 216, 384
    raw = subprocess.run([FF, "-v", "error", "-i", str(path), "-an", "-vf",
                          f"fps=6,scale={w}:{h},format=gray", "-f", "rawvideo",
                          "-pix_fmt", "gray", "-"], capture_output=True).stdout
    n = len(raw) // (w * h)
    if not n:
        return 0.0
    det = cv2.CascadeClassifier(str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"))
    good = 0
    for i in range(n):
        g = cv2.equalizeHist(np.frombuffer(raw[i * w * h:(i + 1) * w * h], np.uint8).reshape(h, w))
        good += bool(len(det.detectMultiScale(g, 1.08, 4, minSize=(18, 18))))
    return good / n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("campaign_id")
    ap.add_argument("--clip", required=True)
    a = ap.parse_args()
    cid, cid_clip = a.campaign_id, a.clip
    brief = store.validate_brief(cid)
    fps = int(brief["delivery"].get("fps", 30))
    portfolio = store.read_json(cid, "artifacts/portfolio.v1.json")["payload"]["selected"]
    card = next(c for c in portfolio if c["candidate_id"] == cid_clip)
    words = store.read_json(cid, "artifacts/transcript.v1.json")["payload"]["words"]

    if not SRC.exists():
        raise SystemExit(f"{SRC} missing — run D1 on this machine first")

    edit = dict(brief.get("edit", {}))
    edit.update((store.read_json(cid, "edit_overrides.json", {}) or {}).get(cid_clip, {}))
    edit.setdefault("min_dur", brief["clip_length"]["min"])
    edit.setdefault("max_dur", brief["clip_length"]["max"])

    t0 = float(edit.get("t0", card["t0"]))
    t1 = float(edit.get("t1", card["t1"]))
    plan = timeline.build(words, t0, t1, edit)
    plan["window_source"] = "editor override" if ("t0" in edit or "t1" in edit) else "candidate card"
    plan["candidate_id"] = cid_clip
    if not plan["within_band"]:
        raise SystemExit(f"cut plan {plan['duration']}s outside band {plan['band']} "
                         f"— widen the moment, not the rule")

    # --- picture: one crop per camera shot, never one crop for the whole clip
    shots = framing.analyse(SRC, t0, t1, float(edit.get("face_fps", 4.0)))
    store.artifact(cid, f"framing_{cid_clip}", shots)
    if shots["face_coverage"] < float(edit.get("min_face_coverage", 0.97)):
        raise SystemExit(f"only {shots['face_coverage']:.0%} of the window has a face on "
                         f"screen — reframe or move the moment")
    shot_ok = [s for s in shots["shots"] if s["speaker"]]
    store.gate(cid, cid_clip, "FRAMING_VALID", True,
               f"{len(shot_ok)} shots, coverage {shots['face_coverage']:.0%}")

    pieces = []
    for seg in plan["segments"]:
        inside = [sh for sh in shot_ok
                  if sh["t1"] > seg["src_in"] + 0.02 and sh["t0"] < seg["src_out"] - 0.02]
        if not inside:
            raise SystemExit(f"segment {seg['index']} has no framed shot")
        for sh in inside:
            a0 = max(seg["src_in"], sh["t0"])
            a1 = min(seg["src_out"], sh["t1"])
            if pieces and a1 - a0 < 0.20:
                # too short to read as its own shot: absorb it rather than drop it
                # (dropping shortened the picture against the audio)
                pieces[-1]["src_out"] = round(max(pieces[-1]["src_out"], a1), 3)
                continue
            pieces.append({"src_in": round(a0, 3), "src_out": round(a1, 3),
                           "shot": sh, "segment": seg["index"]})

    # beat structure: a long take gets a punch-in halfway so the frame changes
    # size every few seconds instead of sitting still for the whole sentence
    beat = float(edit.get("beat_seconds", 4.5))
    split = []
    for p in pieces:
        d = p["src_out"] - p["src_in"]
        if d > beat * 2:
            mid = round(p["src_in"] + d / 2, 3)
            first = dict(p); first["src_out"] = mid
            second = dict(p); second["src_in"] = mid; second["punch"] = True
            split += [first, second]
        else:
            split.append(p)
    pieces = split

    # the picture must tile the audio exactly: same first frame, same last frame
    total_pic = round(sum(p["src_out"] - p["src_in"] for p in pieces), 3)
    if abs(total_pic - plan["duration"]) > 0.05:
        raise SystemExit(f"picture {total_pic}s != audio {plan['duration']}s — refusing to "
                         f"render a clip whose layers disagree")

    # punch-in doubles: a beat reads as an edit because the frame changes size
    punch = float(edit.get("punch_zoom", 0.90))
    out_t = 0.0
    prev_key = None
    for i, p in enumerate(pieces):
        key = (round(p["shot"]["speaker"]["cx"], 2) if p["shot"]["speaker"] else None)
        p["punch"] = bool(p.get("punch") or p["segment"] in
                          [s["index"] for s in plan["segments"] if s["punch"]])
        box = framing.crop_for(p["shot"], 3840, 2160,
                               punch=punch if p["punch"] else 1.0,
                               target_face_frac=float(edit.get("target_face_frac", 0.30)))
        p["crop"] = box
        p["out_in"] = round(out_t, 3)
        p["out_out"] = round(out_t + (p["src_out"] - p["src_in"]), 3)
        out_t = p["out_out"]
        prev_key = key

    parts = []
    for i, p in enumerate(pieces):
        b = p["crop"]
        f = store.path(cid, f"work/{cid_clip}_v{i:02d}.mp4")
        vf = (f"crop={b['w']}:{b['h']}:{b['x']}:{b['y']},"
              f"scale={W}:{H}:flags=lanczos,setsar=1,fps={fps}")
        subprocess.run([FF, "-nostdin", "-v", "error", "-y",
                        "-ss", f"{p['src_in']:.3f}", "-t", f"{p['src_out'] - p['src_in']:.3f}",
                        "-i", str(SRC), "-vf", vf, "-an",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                        "-pix_fmt", "yuv420p", str(f)], check=True)
        parts.append(f)

    lst = store.path(cid, f"work/{cid_clip}_plist.txt")
    lst.write_text("".join(f"file '{x.as_posix()}'\n" for x in parts))
    picture = store.path(cid, f"render/{cid_clip}_picture.mp4")
    subprocess.run([FF, "-nostdin", "-v", "error", "-y", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-c", "copy", str(picture)], check=True)

    events = [{"event_id": f"v{i:02d}", "layer": "picture",
               "source_in": p["src_in"], "source_out": p["src_out"],
               "output_in": p["out_in"], "output_out": p["out_out"],
               "speed": 1.0, "crop": p["crop"], "asset": "source",
               "provenance": "campaign source", "transition": "cut",
               "shot_kind": p["shot"]["kind"], "speaker_cx": p["shot"]["speaker"]["cx"],
               "purpose": ("punch-in on the point" if p["punch"] else
                           ("speaker close-up" if p["shot"]["kind"] == "CLOSE_ONE"
                            else "speaker in wide shot")),
               "segment": p["segment"]} for i, p in enumerate(pieces)]
    edl = {"campaign_id": cid, "clip_id": cid_clip, "edit_version": "picture-v2",
           "timeline_convention": "zero-based output seconds, end-exclusive; "
                                  "source seconds in the original 24 fps clock",
           "output_duration": plan["duration"], "events": events,
           "framing": {"method": shots["method"], "face_coverage": shots["face_coverage"],
                       "shots": len(shots["shots"])}}
    plan["picture_pieces"] = events
    store.artifact(cid, f"cutplan_{cid_clip}", plan)
    store.artifact(cid, f"edl_picture_{cid_clip}", edl)
    store.gate(cid, cid_clip, "STORY_LOCKED", True,
               f"{len(plan['segments'])} audio segments, {len(events)} picture pieces, "
               f"{plan['duration']}s")
    store.gate(cid, cid_clip, "TIMELINE_LOCKED", True, "picture locked; audio/captions must follow")
    for x in parts + [lst]:
        x.unlink(missing_ok=True)
    print(json.dumps({"clip": cid_clip, "duration": plan["duration"],
                      "audio_segments": len(plan["segments"]),
                      "picture_pieces": len(events),
                      "shot_kinds": sorted({e["shot_kind"] for e in events}),
                      "punch_ins": sum(1 for e in events if e["purpose"].startswith("punch")),
                      "face_coverage": shots["face_coverage"],
                      "picture": str(picture)}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
