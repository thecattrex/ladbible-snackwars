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
from orchestrator import store  # noqa: E402

FF = imageio_ffmpeg.get_ffmpeg_exe()
SRC = Path("/tmp/src.mp4")


def make_sfx(dest: Path, kind: str, sr: int = 44100):
    rng = np.random.default_rng(7)
    if kind == "whoosh":
        n = int(.28 * sr); t = np.linspace(0, 1, n)
        a = rng.normal(0, 1, n) * np.sin(np.pi * t) ** 2
        a = np.convolve(a, np.ones(24) / 24, mode="same") * .5
    elif kind == "thump":
        n = int(.35 * sr); t = np.linspace(0, .35, n)
        a = (np.sin(2 * np.pi * 68 * t) * np.exp(-9 * t)
             + .4 * np.sin(2 * np.pi * 132 * t) * np.exp(-14 * t)) * .8
    else:                                   # riser
        n = int(.9 * sr); t = np.linspace(0, .9, n)
        a = np.sin(2 * np.pi * (180 + 420 * t / .9) * t) * (t / .9) ** 2 * .28
    a = np.clip(a, -1, 1)
    with wave.open(str(dest), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((a * 32767).astype(np.int16).tobytes())


def music_bed(dest: Path, seconds: float, sr: int = 22050):
    n = int((seconds + 2) * sr)
    t = np.linspace(0, n / sr, n)
    a = (np.sin(2 * np.pi * 110 * t) * .5 + np.sin(2 * np.pi * 164.81 * t) * .3
         + np.sin(2 * np.pi * 220.6 * t) * .12)
    a *= .55 + .45 * np.sin(2 * np.pi * .08 * t)
    a = a + np.random.default_rng(3).normal(0, 1, n) * .05
    a = np.convolve(a, np.ones(400) / 400, mode="same")
    a = a / (np.abs(a).max() + 1e-9) * .6
    with wave.open(str(dest), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((a * 32767).astype(np.int16).tobytes())


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
    dur = edl["events"][-1]["output_out"]
    card = next(c for c in store.read_json(cid, "artifacts/portfolio.v1.json")["payload"]["selected"]
                if c["candidate_id"] == clip)
    t0 = card["t0"]

    work = store.path(cid, f"work/{clip}")
    dialogue = work.with_name(f"{clip}_dialogue.wav")
    subprocess.run([FF, "-nostdin", "-v", "error", "-y", "-ss", f"{t0:.3f}", "-t", f"{dur:.3f}",
                    "-i", str(SRC), "-vn", "-ac", "1", "-ar", "44100", str(dialogue)], check=True)

    bed = work.with_name(f"{clip}_bed.wav"); music_bed(bed, dur)
    whoosh = work.with_name("whoosh.wav"); make_sfx(whoosh, "whoosh")
    thump = work.with_name("thump.wav"); make_sfx(thump, "thump")
    riser = work.with_name("riser.wav"); make_sfx(riser, "riser")

    cues = [{"cue": "music_bed", "asset": "generated pad", "provenance": "synthesised in D7",
             "gain_db": music_db, "at": 0.0, "purpose": "fill room tone under speech; ducked"}]
    cut_points = [e["output_out"] for e in edl["events"][:-1]]
    for i, ct in enumerate(cut_points):
        cues.append({"cue": f"whoosh_{i}", "asset": "generated whoosh", "provenance": "synthesised in D7",
                     "gain_db": at.get("whoosh_gain_db", -14), "at": round(ct, 2),
                     "purpose": "mark a camera cut"})
    words = store.read_json(cid, "artifacts/transcript.v1.json")["payload"]["words"]
    import re
    num = next((w["t"] - t0 for w in words if t0 <= w["t"] < t0 + dur and re.search(r"\d", w["w"])), None)
    if num and num > 0.5:
        cues.append({"cue": "thump", "asset": "generated low impact", "provenance": "synthesised in D7",
                     "gain_db": at.get("thump_gain_db", -12), "at": round(num, 2),
                     "purpose": "land the number being said"})
    cues.append({"cue": "riser", "asset": "generated riser", "provenance": "synthesised in D7",
                 "gain_db": -18, "at": 0.0, "purpose": "carry the hook card only"})

    inputs = ["-i", str(dialogue), "-i", str(bed)]
    filters = [f"[0:a]loudnorm=I={lufs}:TP={tp}:LRA=11[main]",
               f"[1:a]atrim=0:{dur},asetpts=N/SR/TB[bed]"]
    mix = ["[main]", "[bed]"]
    idx = 2
    for c in cues:
        if c["cue"].startswith("whoosh"):
            inputs += ["-i", str(whoosh)]
            ms = int(c["at"] * 1000)
            filters.append(f"[{idx}:a]adelay={ms}|{ms},volume={c['gain_db']}dB[w{idx}]")
            mix.append(f"[w{idx}]"); idx += 1
        elif c["cue"] == "thump":
            inputs += ["-i", str(thump)]
            ms = int(c["at"] * 1000)
            filters.append(f"[{idx}:a]adelay={ms}|{ms},volume={c['gain_db']}dB[t]")
            mix.append("[t]"); idx += 1
        elif c["cue"] == "riser":
            inputs += ["-i", str(riser)]
            filters.append(f"[{idx}:a]volume={c['gain_db']}dB,atrim=0:0.9[r]")
            mix.append("[r]"); idx += 1
    filters.append(f"{''.join(mix)}amix=inputs={len(mix)}:duration=first:normalize=0[aout]")

    audio = store.path(cid, f"render/{clip}_audio.m4a")
    subprocess.run([FF, "-nostdin", "-v", "error", "-y", *inputs,
                    "-filter_complex", ";".join(filters), "-map", "[aout]",
                    "-c:a", "aac", "-b:a", "192k", str(audio)], check=True)
    store.artifact(cid, f"cue_sheet_{clip}", {"clip": clip, "duration": dur,
                                              "target": {"lufs": lufs, "true_peak": tp},
                                              "cues": cues})
    dialogue.unlink(missing_ok=True)
    print(json.dumps({"clip": clip, "cues": len(cues), "audio": str(audio)}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
