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
from orchestrator import store, timeline, framing, cropaudit  # noqa: E402

FF = imageio_ffmpeg.get_ffmpeg_exe()
import os
from pathlib import Path
MEDIA = Path(os.environ.get("MEDIA_ROOT", "/var/tmp"))
SRC = MEDIA / "src.mp4"
# the media may be a cut of the episode: SRC_OFFSET says which source second its
# first frame is, so every seek can still be written in absolute episode time
OFF = float(os.environ.get("SRC_OFFSET", "0") or 0)
W, H = 1080, 1920   # full-bleed vertical: the client rejected the letterbox bands
cv2.setNumThreads(2)


def crop_box(fr: dict, punch: bool = False):
    cw, ch = fr.get("crop_w", 1068), fr.get("crop_h", 1898)
    if punch:
        cw = int(cw * fr.get("punch_in", 1.06) ** -1)
        ch = int(cw * 16 / 9)
    return int(cw), int(ch)


def frames_at(t: float, w: int = 800):
    h = w * 9 // 16 // 2 * 2
    raw = subprocess.run([FF, "-v", "error", "-ss", f"{max(0.0, t - OFF):.2f}", "-i", str(SRC),
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

    # The source cuts to an empty room now and then (wide shot, mic arm, curtain).
    # An editor cuts away from that; so does the plan: the dead stretch is found on
    # the picture, removed from the timeline and the window is extended until the
    # clip is back inside its band. Searching happens before anything is rendered,
    # because a faceless second is a REVISE in QA and a reshoot in the edit.
    avoid = [list(x) for x in (edit.get("avoid") or [])]
    limit = min(float(edit["max_dur"]) + 12.0, 1e9)
    for _ in range(4):
        plan = timeline.build(words, t0, t1, dict(edit, avoid=avoid))
        if plan["duration"] >= float(edit["min_dur"]):
            break
        t1 += min(float(edit["min_dur"]) - plan["duration"] + 2.0, 6.0)
        if t1 - t0 > limit:
            raise SystemExit(f"no face-safe window near {t0:.1f}s — move the moment")
    if not plan["within_band"]:
        raise SystemExit(f"cut plan {plan['duration']}s outside band {plan['band']} "
                         f"— widen the moment, not the rule")
    plan["window_source"] = "editor override" if ("t0" in edit or "t1" in edit) else "candidate card"
    plan["candidate_id"] = cid_clip
    if not plan["within_band"]:
        raise SystemExit(f"cut plan {plan['duration']}s outside band {plan['band']} "
                         f"— widen the moment, not the rule")

    # --- picture: one crop per camera shot, never one crop for the whole clip
    shots = framing.analyse(SRC, t0, t1, float(edit.get("face_fps", 4.0)), offset=OFF)
    store.artifact(cid, f"framing_{cid_clip}", shots)

    def dead_spans(_shots) -> list[list[float]]:
        """Stretches of the window where nothing is happening on screen.

        Not "no face": the client's rule is that the frame must contain something
        meaningful — a person, an animation on a monitor, a busy room. What is not
        allowed is a black wall, an empty backdrop, or a camera swinging past a
        curtain. That is measured on decoded pixels (contrast, edge detail,
        colour, motion) at 4 fps over the whole window; faces are only one of the
        ways a frame can qualify.
        """
        samples = content.source_scan(SRC, t0, t1, offset=OFF,
                                      cfg=brief.get("framing", {}).get("content"))
        store.artifact(cid, f"content_{cid_clip}", {"samples": samples})
        return content.runs(samples, "alive", False, min_len=0.40)

    dead = dead_spans(shots)
    if dead:
        # rebuild the cut with the dead picture removed, then look again at the new
        # window: the extension can land on another empty shot
        for _ in range(3):
            avoid += dead
            plan = timeline.build(words, t0, t1, dict(edit, avoid=avoid))
            while plan["duration"] < float(edit["min_dur"]) and t1 - t0 < limit:
                t1 += min(float(edit["min_dur"]) - plan["duration"] + 2.0, 6.0)
                plan = timeline.build(words, t0, t1, dict(edit, avoid=avoid))
            shots = framing.analyse(SRC, t0, t1, float(edit.get("face_fps", 4.0)), offset=OFF)
            dead = dead_spans(shots)
            if not dead:
                break
        store.artifact(cid, f"framing_{cid_clip}", shots)
        store.artifact(cid, f"avoid_{cid_clip}", {"spans": avoid,
                                                  "why": "camera on an empty room"})
        print(f"avoiding {len(avoid)} faceless spans: {avoid}", file=sys.stderr)
    if not plan["within_band"]:
        raise SystemExit(f"cut plan {plan['duration']}s outside band {plan['band']} "
                         f"after avoiding empty shots")
    # A window may legitimately have no face for a while (a screen insert, a busy
    # room, a prop). What it may not have is dead frames: black wall, empty
    # backdrop, nothing happening. That is the gate now.
    live = content.source_scan(SRC, t0, t1, offset=OFF,
                               cfg=brief.get("framing", {}).get("content"))
    alive_ratio = sum(1 for v in live if v["alive"]) / max(1, len(live))
    if alive_ratio < float(edit.get("min_alive_ratio", 0.90)):
        raise SystemExit(f"only {alive_ratio:.0%} of the window has anything happening in "
                         f"frame — move the moment")
    store.artifact(cid, f"content_{cid_clip}", {"samples": live,
                                                "alive_ratio": round(alive_ratio, 3)})
    shot_ok = [s for s in shots["shots"] if s["speaker"]]
    store.gate(cid, cid_clip, "FRAMING_VALID", True,
               f"{len(shot_ok)} shots, coverage {shots['face_coverage']:.0%}")

    pieces = []
    for seg in plan["segments"]:
        inside = [sh for sh in shot_ok
                  if sh["t1"] > seg["src_in"] + 0.02 and sh["t0"] < seg["src_out"] - 0.02]
        if not inside:
            # no framed speaker here: the shot still shows something worth keeping,
            # so it gets a piece with a neutral, centred frame
            inside = [{"t0": seg["src_in"], "t1": seg["src_out"], "speaker": None,
                       "kind": "CONTENT", "faces": 0}]
        seg_pieces = []
        for sh in inside:
            a0 = max(seg["src_in"], sh["t0"])
            a1 = min(seg["src_out"], sh["t1"])
            if a1 - a0 < 0.20:
                # too short to read as its own shot: absorb it rather than drop it
                # (dropping shortened the picture against the audio)
                if seg_pieces:
                    seg_pieces[-1]["src_out"] = a1
                continue
            seg_pieces.append({"src_in": a0, "src_out": a1,
                               "shot": sh, "segment": seg["index"]})
        if not seg_pieces:                      # one shot covers the whole segment
            seg_pieces = [{"src_in": seg["src_in"], "src_out": seg["src_out"],
                           "shot": inside[0], "segment": seg["index"]}]
        # the pieces of a segment must tile it exactly: the shot track is a
        # summary with rounded bounds, so overlaps and hairline gaps are closed
        # here rather than left to show up as a layer mismatch at render time
        seg_pieces[0]["src_in"] = seg["src_in"]
        seg_pieces[-1]["src_out"] = seg["src_out"]
        for k in range(1, len(seg_pieces)):
            seg_pieces[k]["src_in"] = seg_pieces[k - 1]["src_out"]
        pieces += [{"src_in": round(q["src_in"], 3), "src_out": round(q["src_out"], 3),
                    "shot": q["shot"], "segment": q["segment"]} for q in seg_pieces]

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
    if os.environ.get("PIECE_DEBUG"):
        print("AFTER_BEAT " + json.dumps([{"in": p["src_in"], "out": p["src_out"],
                                           "seg": p["segment"]} for p in pieces]),
              file=sys.stderr)

    # the picture must tile the audio exactly: same first frame, same last frame
    total_pic = round(sum(p["src_out"] - p["src_in"] for p in pieces), 3)
    if abs(total_pic - plan["duration"]) > 0.05:
        raise SystemExit(f"picture {total_pic}s != audio {plan['duration']}s — refusing to "
                         f"render a clip whose layers disagree")

    # --- split frame: the moment both people are talking at once, the reference
    # edit puts them side by side with a divider instead of choosing one.
    # The replacement is done by walking the pieces in source order and splitting
    # the overlap, so the output clock stays exact and nothing is duplicated.
    split_win = edit.get("split_src")           # [src_in, src_out] or None
    if split_win:
        a0, a1 = float(split_win[0]), float(split_win[1])
        wide = next((sh for sh in shots["shots"]
                     if (sh.get("candidates") or []) and len(sh["candidates"]) >= 2
                     and sh["t1"] > a0 and sh["t0"] < a1), None)
        if wide:
            cands = sorted(wide["candidates"], key=lambda c: c["cx"])
            ss, ee = round(max(a0, wide["t0"]), 3), round(min(a1, wide["t1"]), 3)
            if ee - ss > 0.6:
                rebuilt = []
                for pc in pieces:
                    if pc["src_out"] <= ss + 0.001 or pc["src_in"] >= ee - 0.001:
                        rebuilt.append(pc)
                        continue
                    if pc["src_in"] < ss:
                        rebuilt.append({**pc, "src_out": ss})
                    rebuilt.append({"src_in": ss, "src_out": ee, "shot": wide,
                                    "segment": pc["segment"], "split": True,
                                    "side": {"left": cands[0], "right": cands[-1]}})
                    if pc["src_out"] > ee:
                        rebuilt.append({**pc, "src_in": ee})
                pieces = rebuilt
                plan["split_frame"] = {"src": [ss, ee],
                                       "left_cx": cands[0]["cx"], "right_cx": cands[-1]["cx"]}
                plan["note_split"] = ("both speakers talking: side-by-side with a divider, "
                                      "replacing the single-crop piece for that window")

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

    # ---- crop audit: the framing track is a summary, the picture is the truth.
    # If the source cut to a new setup between two track samples the planned crop
    # can sit on an empty desk, so every box is checked against real frames.
    pieces, audit = cropaudit.audit(SRC, pieces, float(edit.get("audit_fps", 4.0)), offset=OFF)
    store.artifact(cid, f"cropaudit_{cid_clip}", audit)

    if audit.get("dead"):
        # A sliver of empty frame at a shot boundary is just a bad sample: hold the
        # neighbouring framing over it, the way a dissolve hides a camera move. A
        # real stretch with no person in any framing is not something an editor can
        # fix with a crop, so the plan has to leave it out and say so.
        keep = []
        long_dead = []
        for p in pieces:
            if not p.get("dead"):
                keep.append(p)
                continue
            d = p["src_out"] - p["src_in"]
            if d >= 0.8:
                long_dead.append([round(p["src_in"], 2), round(p["src_out"], 2)])
                keep.append(p)
                continue
            if keep:                                  # extend the piece before it
                keep[-1] = dict(keep[-1], src_out=p["src_out"])
            else:
                p = dict(p)
                p.pop("dead", None)
                keep.append(p)
        if long_dead:
            raise SystemExit(f"no face in any framing for {long_dead} — move the moment, "
                             f"not the crop")
        pieces = keep
        store.artifact(cid, f"cropaudit_{cid_clip}", dict(audit, absorbed_slivers=True))
    if audit["moved"] or audit["split"] or audit["no_face"]:
        print(json.dumps({"crop_audit": audit}, indent=1), file=sys.stderr)
    if os.environ.get("PIECE_DEBUG"):
        print(json.dumps([{"i": i, "in": round(x["src_in"], 3), "out": round(x["src_out"], 3),
                           "kind": x["shot"]["kind"], "seg": x["segment"],
                           "split": bool(x.get("split"))} for i, x in enumerate(pieces)],
                         indent=1), file=sys.stderr)

    # ---- frame grid: a cut can only land on a source frame.
    # Un-snapped cuts made every piece render one frame long, and the error adds
    # up across nine pieces: the picture ended 0.4 s behind the audio, which is
    # exactly the "video speed does not match audio" lag in the review.
    grid = float(edit.get("source_fps", 24.0))

    def snap(t: float) -> float:
        return round(round(t * grid) / grid, 4)

    for p in pieces:
        p["src_in"], p["src_out"] = snap(p["src_in"]), snap(p["src_out"])
    pieces = [p for p in pieces if p["src_out"] > p["src_in"]]   # never a negative piece
    # close sub-frame gaps only *inside* a segment. Between segments there is an
    # intentional jump in the source (the filler that was cut out), and forcing the
    # joint closed there pulls the removed words straight back into the picture.
    for a, b in zip(pieces, pieces[1:]):
        if a["segment"] == b["segment"] and 0 < b["src_in"] - a["src_out"] < 0.5:
            b["src_in"] = a["src_out"]
    pieces = [p for p in pieces if p["src_out"] - p["src_in"] > 0]
    bad = [p for p in pieces if p["src_out"] <= p["src_in"]]
    assert not bad, f"inverted pieces: {bad}"
    total = round(sum(p["src_out"] - p["src_in"] for p in pieces), 4)
    # the timeline length has to sit on the same grid, or the last cut cannot
    # land on a frame and every piece re-rounds
    want = round(round(float(plan["duration"]) * grid) / grid, 4)
    if abs(total - want) > 0.0001:
        # absorb rounding on the last piece: a frame either way on the final cut is
        # invisible, a drifted timeline is not. A big difference is a plan bug, not
        # rounding, and must stop the render instead of squashing the last shot.
        if abs(total - want) > 0.5:
            raise SystemExit(f"picture {total}s vs audio {want}s — plan disagrees, "
                             f"not a rounding error")
        pieces[-1]["src_out"] = round(pieces[-1]["src_out"] + (want - total), 4)
    total = round(sum(p["src_out"] - p["src_in"] for p in pieces), 4)
    # the sum is exact by construction; what is left is float noise from adding
    # grid-snapped durations, so the tolerance is a millisecond, not a frame
    assert abs(total - want) < 1e-3, f"picture {total} != audio {want}"

    out_t = 0.0
    for p in pieces:                       # rebuilding can change the piece count
        p["out_in"] = round(out_t, 3)
        p["out_out"] = round(out_t + (p["src_out"] - p["src_in"]), 3)
        out_t = p["out_out"]
    if os.environ.get("PIECE_DEBUG"):
        print("FINAL " + json.dumps([{"i": i, "in": p["src_in"], "out": p["src_out"],
                                      "dur": round(p["src_out"] - p["src_in"], 3)}
                                     for i, p in enumerate(pieces)]), file=sys.stderr)

    # ---- camera: a moving window, not a stack of stills.
    # In the reference edit the frame glides from one speaker to the next across
    # the wide shot instead of cutting, and it never sits perfectly still. So each
    # piece carries a camera path: hold, then glide into the next speaker's box.
    move_s = float(edit.get("move_seconds", 0.55))
    for i in range(len(pieces) - 1):
        a, b = pieces[i], pieces[i + 1]
        ba, bb = a["crop"], b["crop"]
        same_size = abs(ba["w"] - bb["w"]) <= 40 and abs(ba["h"] - bb["h"]) <= 70
        wide = a["shot"].get("candidates") and len(a["shot"].get("candidates") or []) >= 2
        if same_size and wide and abs(ba["x"] - bb["x"]) > 60:
            # both speakers share this wide shot: glide across, do not cut
            a["box_to"] = bb
            a["move"] = min(move_s, max(0.35, (a["src_out"] - a["src_in"]) * 0.45))
            a["glide"] = True

    # a slow, continuous drift on every static piece so the frame feels like it is
    # held by an operator rather than locked on a tripod
    drift = float(edit.get("drift_px", 14))
    for i, p in enumerate(pieces):
        if p.get("glide"):
            continue
        b = p["crop"]
        direction = 1 if (i % 2 == 0) else -1
        p["box_to"] = {"x": max(0, min(3840 - b["w"], b["x"] + direction * drift)),
                       "y": b["y"], "w": b["w"], "h": b["h"]}
        p["move"] = p["src_out"] - p["src_in"]      # drift over the whole piece
        p["glide"] = False

    def crop_expr(p):
        a, b = p["crop"], p["box_to"]
        d = p["src_out"] - p["src_in"]
        m = max(0.05, min(p["move"], d))
        if abs(a["x"] - b["x"]) < 1 and abs(a["y"] - b["y"]) < 1:
            return f"crop={a['w']}:{a['h']}:{a['x']}:{a['y']}"
        # ease-out on the glide, linear gentle drift otherwise
        ramp = (f"min(1\\,max(0\\,(t-{max(0.0, d - m):.3f})/{m:.3f}))"
                if p.get("glide") else f"min(1\\,(t/{d:.3f}))")
        ease = f"(1-pow(1-{ramp}\\,2))" if p.get("glide") else ramp
        x = f"({a['x']}+({b['x']}-{a['x']})*{ease})"
        y = f"({a['y']}+({b['y']}-{a['y']})*{ease})"
        return f"crop={a['w']}:{a['h']}:x='{x}':y='{y}'"

    parts = []
    for i, p in enumerate(pieces):
        f = store.path(cid, f"work/{cid_clip}_v{i:02d}.mp4")
        dur_i = p["src_out"] - p["src_in"]
        nf = int(round(dur_i * grid))       # exact frame count, never "about one more"
        if p.get("split"):
            half_w = (W - 5) // 2
            boxes = []
            for side_key in ("left", "right"):
                cx = p["side"][side_key]["cx"] * 3840
                cw = int(half_w * 3840 / W)
                ch = int(cw * H / half_w)
                # zoom the panel in: a full-height slice leaves a dead band of
                # curtain above both heads, which reads as an empty frame
                ch = min(2160, int(ch * 0.78))
                cw = int(ch * half_w / H)
                cx0 = int(max(0, min(3840 - cw, cx - cw / 2)))
                cy0 = int(max(0, min(2160 - ch, 0.44 * 2160 - 0.40 * ch)))
                boxes.append((cx0, cy0, cw, ch))
            (lx, ly, lw, lh), (rx, ry, rw_, rh) = boxes
            fc = (f"[0:v]crop={lw}:{lh}:{lx}:{ly},scale={half_w}:{H}:flags=lanczos[l];"
                  f"[0:v]crop={rw_}:{rh}:{rx}:{ry},scale={half_w}:{H}:flags=lanczos[r];"
                  f"color=c=0xB4E600:s=5x{H}:d=1[lime];"
                  f"[l][lime][r]hstack=inputs=3,setsar=1[v]")
            subprocess.run([FF, "-nostdin", "-v", "error", "-y",
                            "-ss", f"{max(0.0, p['src_in'] - OFF):.6f}", "-t", f"{dur_i + .5:.6f}",
                            "-i", str(SRC), "-filter_complex", fc, "-map", "[v]", "-an",
                            "-frames:v", str(nf), "-r", str(grid),
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "14",
                            "-pix_fmt", "yuv420p", str(f)], check=True)
        else:
            vf = f"{crop_expr(p)},scale={W}:{H}:flags=lanczos,setsar=1"
            subprocess.run([FF, "-nostdin", "-v", "error", "-y",
                            "-ss", f"{max(0.0, p['src_in'] - OFF):.6f}", "-t", f"{dur_i + .5:.6f}",
                            "-i", str(SRC), "-vf", vf, "-an",
                            "-frames:v", str(nf), "-r", str(grid),
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "14",
                            "-pix_fmt", "yuv420p", str(f)], check=True)
        got = round(nf / grid, 4)
        if abs(got - dur_i) > 1e-3:
            raise SystemExit(f"{p['src_in']}-{p['src_out']}: rendered {got}s, wanted {dur_i}s")
        parts.append(f)

    lst = store.path(cid, f"work/{cid_clip}_plist.txt")
    lst.write_text("".join(f"file '{x.as_posix()}'\n" for x in parts))
    pic_src = store.path(cid, f"work/{cid_clip}_picture_{int(grid)}.mp4")
    subprocess.run([FF, "-nostdin", "-v", "error", "-y", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-c", "copy", str(pic_src)], check=True)
    # one frame-rate conversion for the whole timeline, not one per piece: every
    # 24->30 conversion rounds, and nine roundings is a visible drift
    picture = store.path(cid, f"render/{cid_clip}_picture.mp4")
    subprocess.run([FF, "-nostdin", "-v", "error", "-y", "-i", str(pic_src),
                    "-vf", f"fps={fps}", "-t", f"{total:.6f}", "-an",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                    "-pix_fmt", "yuv420p", "-r", str(fps), str(picture)], check=True)
    pic_dur = store.probe_duration(picture) if hasattr(store, "probe_duration") else total

    events = [{"event_id": f"v{i:02d}", "layer": "picture",
               "source_in": p["src_in"], "source_out": p["src_out"],
               "output_in": p["out_in"], "output_out": p["out_out"],
               "speed": 1.0, "crop": p["crop"], "asset": "source",
               "provenance": "campaign source", "transition": "cut",
               "shot_kind": p["shot"]["kind"], "speaker_cx": p["shot"]["speaker"]["cx"],
               "camera": "glide" if p.get("glide") else "drift",
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
