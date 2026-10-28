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
from orchestrator import store  # noqa: E402

FF = imageio_ffmpeg.get_ffmpeg_exe()
SRC = Path("/tmp/src.mp4")
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


def box_for(t0: float, t1: float, fr: dict, punch: bool = False):
    tm = (t0 + t1) / 2
    cw, ch = crop_box(fr, punch)
    found = []
    for tt in (tm - .8, tm, min(t1, tm + .8)):
        for (x, y, fw) in faces(max(t0, tt)):
            if y < 1150 and fw >= 140:
                found.append((x, y, fw))
    if not found:
        return {"x": (3840 - cw) // 2, "y": 0, "w": cw, "h": ch}
    big = [f for f in found if f[2] > 420]
    left = [f for f in big if f[0] + f[2] / 2 < 1700]
    pick = left or big
    if pick:
        cx, cy, fw = max(pick, key=lambda f: f[2])
    else:
        cx, cy, fw = min(found, key=lambda f: f[0] + f[2] / 2)
    x = int(max(0, min(3840 - cw, cx + fw / 2 - cw / 2)))
    y = int(max(0, min(2160 - ch, cy - .42 * ch)))
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
    fr = brief.get("framing", {})
    fps = int(brief["delivery"].get("fps", 30))
    portfolio = store.read_json(cid, "artifacts/portfolio.v1.json")["payload"]["selected"]
    card = next(c for c in portfolio if c["candidate_id"] == cid_clip)
    t0, t1 = card["t0"], card["t1"]
    dur = round(t1 - t0, 3)

    if not SRC.exists():
        raise SystemExit("/tmp/src.mp4 missing — run D1 on this machine first")

    # beats: 2.5-3.5 s, merged while the framing holds, max 4 shots
    beats, cur = [], t0
    while cur < t1 - .3:
        nxt = min(cur + 3.2, t1)
        beats.append((cur, nxt))
        cur = nxt
    plan, prev = [], None
    for i, (x0, x1) in enumerate(beats):
        box = box_for(x0, x1, fr, punch=(i % 2 == 1 and i > 0))
        if prev and abs(box["x"] - prev["x"]) < 200:
            plan[-1]["out"] = x1
        else:
            plan.append({"in": x0, "out": x1, "box": box, "punch": i % 2 == 1 and i > 0})
        prev = box
    while len(plan) > 4:
        i = min(range(len(plan) - 1), key=lambda j: plan[j]["out"] - plan[j]["in"])
        plan[i]["out"] = plan[i + 1]["out"]
        del plan[i + 1]

    work = store.path(cid, f"work/{cid_clip}")
    parts = []
    for k, shot in enumerate(plan):
        b = shot["box"]
        f = work.with_name(f"{cid_clip}_p{k}.mp4")
        subprocess.run([FF, "-nostdin", "-v", "error", "-y", "-ss", f"{shot['in']:.3f}",
                        "-t", f"{shot['out'] - shot['in']:.3f}", "-i", str(SRC),
                        "-vf", f"crop={b['w']}:{b['h']}:{b['x']}:{b['y']},"
                               f"scale={W}:{H}:flags=lanczos,setsar=1,fps={fps}", "-an",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                        "-pix_fmt", "yuv420p", str(f)], check=True)
        cov = face_cover(f)
        if cov < fr.get("face_cover_min", .85) and k > 0:      # hold the previous framing
            pb = plan[k - 1]["box"]
            subprocess.run([FF, "-nostdin", "-v", "error", "-y", "-ss", f"{shot['in']:.3f}",
                            "-t", f"{shot['out'] - shot['in']:.3f}", "-i", str(SRC),
                            "-vf", f"crop={pb['w']}:{pb['h']}:{pb['x']}:{pb['y']},"
                                   f"scale={W}:{H}:flags=lanczos,setsar=1,fps={fps}", "-an",
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                            "-pix_fmt", "yuv420p", str(f)], check=True)
        parts.append(f)

    lst = work.with_name(f"{cid_clip}_plist.txt")
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts))
    picture = store.path(cid, f"render/{cid_clip}_picture.mp4")
    subprocess.run([FF, "-nostdin", "-v", "error", "-y", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-c", "copy", str(picture)], check=True)

    events, out_t = [], 0.0
    for k, shot in enumerate(plan):
        d = shot["out"] - shot["in"]
        events.append({"event_id": f"p{k:02d}", "layer": "picture",
                       "source_in": round(shot["in"], 3), "source_out": round(shot["out"], 3),
                       "output_in": round(out_t, 3), "output_out": round(out_t + d, 3),
                       "speed": 1.0, "crop": shot["box"], "asset": "source",
                       "provenance": "campaign source", "transition": "cut",
                       "purpose": "punch-in on the point" if shot["punch"] else "speaker framing"})
        out_t += d

    edl = {"campaign_id": cid, "clip_id": cid_clip, "edit_version": "picture-v1",
           "source_version": (store.read_json(cid, "artifacts/source_meta.v1.json") or {}).get("version", "v1"),
           "timeline_convention": "zero-based output seconds, end-exclusive; source seconds in original time base",
           "events": events}
    store.artifact(cid, f"edl_picture_{cid_clip}", edl)
    store.gate(cid, cid_clip, "STORY_LOCKED", True, f"{len(plan)} shots, {dur}s")
    store.gate(cid, cid_clip, "TIMELINE_LOCKED", True, "picture locked; audio/captions must follow")
    for p in parts + [lst]:
        p.unlink(missing_ok=True)
    print(json.dumps({"clip": cid_clip, "duration": dur, "shots": len(plan),
                      "face_cover": round(face_cover(picture), 3),
                      "picture": str(picture)}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
