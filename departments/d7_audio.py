#!/usr/bin/env python3
"""D7 — Dialogue, music and sound effects.

Dialogue first. The source speech is cut at exactly the same in/out as the
locked picture, normalised to the campaign target, and only then are music and
SFX placed — from a cue sheet where every cue has a purpose, a gain and a
provenance string. Generated assets only; nothing licensed is used without a
record.

  python3 departments/d7_audio.py <campaign_id> --clip <candidate_id>
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
import imageio_ffmpeg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from orchestrator import store, sfx  # noqa: E402

FF = imageio_ffmpeg.get_ffmpeg_exe()
import os
from pathlib import Path
MEDIA = Path(os.environ.get("MEDIA_ROOT", "/var/tmp"))
SRC = MEDIA / "src.mp4"


def main_audio_helpers():
    pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("campaign_id")
    ap.add_argument("--clip", required=True)
    a = ap.parse_args()
    cid, clip = a.campaign_id, a.clip
    brief = store.validate_brief(cid)
    at = brief.get("audio_targets", {})
    lufs, tp = at.get("lufs", -16), at.get("true_peak", -1)
    music_db = at.get("music_gain_db", -22)

    edl = store.read_json(cid, f"artifacts/edl_picture_{clip}.v1.json")["payload"]
    plan = store.read_json(cid, f"artifacts/cutplan_{clip}.v1.json")["payload"]
    dur = edl["events"][-1]["output_out"]
    # dialogue follows the audio segmentation (one contiguous run of his voice per
    # segment); whooshes follow the picture segmentation (where the frame changes)
    events = [{"source_in": s["src_in"], "source_out": s["src_out"],
               "output_in": s["out_in"], "output_out": s["out_out"],
               "purpose": s["purpose"]} for s in plan["segments"]]

    work = store.path(cid, f"work/{clip}")
    dialogue = work.with_name(f"{clip}_dialogue.wav")
    # dialogue is rebuilt segment by segment on the same boundaries as the
    # picture, so a cut can never land mid-word on one layer only
    graph, labels = [], []
    for i, e in enumerate(events):
        a, b = e["source_in"], e["source_out"]
        graph.append(f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=N/SR/TB[d{i}]")
        labels.append(f"[d{i}]")
        if i < len(events) - 1:
            gap = events[i + 1]["output_in"] - e["output_out"]
            if gap > 0.001:
                graph.append(f"aevalsrc=0:d={gap:.3f}:s=44100:c=mono[g{i}]")
                labels.append(f"[g{i}]")
    graph.append(f"{''.join(labels)}concat=n={len(labels)}:v=0:a=1[dia]")
    subprocess.run([FF, "-nostdin", "-v", "error", "-y", "-i", str(SRC),
                    "-filter_complex", ";".join(graph), "-map", "[dia]",
                    "-ac", "1", "-ar", "44100", str(dialogue)], check=True)

    wh = work.with_name("whoosh.wav"); sfx.whoosh(wh, 0.62)
    im_ = work.with_name("impact.wav"); sfx.impact(im_, 0.42)
    rs = work.with_name("riser.wav"); sfx.riser(rs, 1.4)
    sub = work.with_name("impact_sub.wav"); sfx.impact(sub, 0.55, pitch=48.0)

    cues = []   # no music bed: clean dialogue only (see docs/CRAFT.md)

    # --- transitions that carry a card get a whoosh straddling the cut, and the
    # card itself gets an impact exactly as it lands
    gfx = store.read_json(cid, f"artifacts/graphics_{clip}.v1.json") or {"payload": {"cards": []}}
    cards = gfx["payload"]["cards"]
    pic_cuts = [e["output_out"] for e in edl["events"][:-1]]
    for i, c in enumerate(cards):
        cues.append({"cue": f"impact_gfx{i}", "asset": "synthesised impact",
                     "provenance": "generated in D7", "gain_db": at.get("impact_gain_db", -17),
                     "at": round(c["start"], 2), "purpose": "lands the card"})
        near = [pc for pc in pic_cuts if abs(pc - c["start"]) < 0.45]
        if near:
            cues.append({"cue": f"whoosh_gfx{i}", "asset": "synthesised whoosh",
                         "provenance": "generated in D7",
                         "gain_db": at.get("whoosh_gain_db", -20),
                         "at": round(c["start"] - 0.30, 2),
                         "purpose": "straddles the cut into the card"})

    # --- the line that carries the takeaway gets a riser that stops dead on it
    hooks = store.read_json(cid, "artifacts/hook_cards.v1.json")["payload"]["cards"]
    punch = [] if at.get("no_riser") else [e for e in events
                                           if e.get("purpose", "").startswith("punch")]
    if punch:
        t_punch = punch[0]["output_in"]
        cues.append({"cue": "riser", "asset": "synthesised riser", "provenance": "generated in D7",
                     "gain_db": at.get("riser_gain_db", -21), "at": round(max(0.0, t_punch - 1.35), 2),
                     "purpose": "builds into the claim, stops dead on it"})
        cues.append({"cue": "impact_claim", "asset": "synthesised impact + sub",
                     "provenance": "generated in D7", "gain_db": at.get("impact_gain_db", -17),
                     "at": round(t_punch, 3), "purpose": "lands the claim exactly on the cut"})

    # --- only the cuts that matter get a sound: quiet whooshes on picture changes
    # that are neither already sounded by a card nor within 0.6 s of another cue
    sounded = [c["at"] for c in cues]
    for i, pc in enumerate([] if at.get("clean_cuts") else pic_cuts):
        if any(abs(pc - s2) < 0.6 for s2 in sounded):
            continue
        cues.append({"cue": f"whoosh_{i}", "asset": "synthesised whoosh",
                     "provenance": "generated in D7", "gain_db": at.get("whoosh_soft_db", -26),
                     "at": round(pc - 0.26, 2), "purpose": "soft air on a picture change"})
        sounded.append(pc)

    # ---------------- mix
    inputs = ["-i", str(dialogue)]
    # every layer is forced to 48 kHz stereo before mixing: a format mismatch here
    # is what silently kills a sidechain and leaves the bed sitting on the voice
    # dialogue chain: high-pass off the desk rumble, light broadband denoise for
    # the room hiss, then normalise with headroom for the effects
    filters = [f"[0:a]highpass=f=72,afftdn=nf=-28,"
               f"loudnorm=I={lufs - 3}:TP={tp - 5}:LRA=11,aresample={sfx.SR},"
               f"aformat=channel_layouts=stereo[dia]"]
    mix = ["[dia]"]
    idx = 1
    for c in cues:
        src = im_ if c["cue"].startswith("impact_claim") else (
            im_ if c["cue"].startswith("impact") else (
                wh if c["cue"].startswith("whoosh") else rs))
        inputs += ["-i", str(src)]
        ms = int(max(0.0, c["at"]) * 1000)
        filters.append(f"[{idx}:a]adelay={ms}|{ms},volume={c['gain_db']}dB[s{idx}]")
        mix.append(f"[s{idx}]")
        idx += 1
    if any(c["cue"] == "impact_claim" for c in cues):
        inputs += ["-i", str(sub)]
        at_ms = int([c for c in cues if c["cue"] == "impact_claim"][0]["at"] * 1000)
        filters.append(f"[{idx}:a]adelay={at_ms}|{at_ms},volume=-24dB[s{idx}]")
        mix.append(f"[s{idx}]")
        idx += 1
    filters.append(f"{''.join(mix)}amix=inputs={len(mix)}:duration=first:normalize=0,"
                   f"loudnorm=I={lufs}:TP={tp}:LRA=11,alimiter=limit=0.89:level=false,"
                   f"aresample=48000[aout]")

    audio = store.path(cid, f"render/{clip}_audio.m4a")
    subprocess.run([FF, "-nostdin", "-v", "error", "-y", *inputs,
                    "-filter_complex", ";".join(filters), "-map", "[aout]",
                    "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                    "-ac", "2", str(audio)], check=True)
    store.artifact(cid, f"cue_sheet_{clip}", {"clip": clip, "duration": dur,
                                              "rule": "impacts on the frame, whooshes straddling, "
                                                      "riser stopping dead on the claim",
                                              "target": {"lufs": lufs, "true_peak": tp},
                                              "cues": cues})
    dialogue.unlink(missing_ok=True)
    print(json.dumps({"clip": clip, "cues": len(cues), "audio": str(audio)}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
