#!/usr/bin/env python3
"""Find the moments worth clipping in a long Twitch VOD.

No keyword search, no guessing from titles: the stream is measured.

  energy  — decode the audio once, measure loudness and spectral flux per half
            second, and mark the stretches that stand out from the stream's own
            baseline. An IRL party peaks when someone screams or the room reacts.
  speech  — faster-whisper transcribes the whole VOD locally (no API, no quota),
            and flags laughs, shouts and swearing, which is where clip gold lives.
  windows — energy and speech are combined into candidate 15-60 s windows with a
            score, so the editor's first stop is 20 real candidates, not 65 minutes
            of tape.

  python3 tools/peaks.py <media> --out peaks.json [--model base.en]
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import numpy as np

SR = 16000

LAUGH = ("haha", "hahaha", "lol", "laugh", "laughing")
SHOUT = ("oh my god", "oh my gosh", "what the", "no way", "bro", "dude", "stop",
         "let's go", "lets go", "holy", "scream", "shut up", "wait wait", "look look")


def decode(media: Path, wav: Path) -> np.ndarray:
    if not wav.exists():
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(media), "-ac", "1",
                        "-ar", str(SR), "-vn", str(wav)], check=True)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(wav), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32)


def energy_curve(x: np.ndarray, hop: float = 0.5) -> dict:
    n = int(SR * hop)
    frames = len(x) // n
    x = x[:frames * n].reshape(frames, n)
    rms = np.sqrt((x ** 2).mean(axis=1))
    db = 20 * np.log10(rms + 1e-8)
    # brightness of the spectrum: laughter and screams are broadband
    spec = np.abs(np.fft.rfft(x * np.hanning(n), axis=1))
    freqs = np.fft.rfftfreq(n, 1 / SR)
    hi = spec[:, freqs > 2000].sum(axis=1)
    lo = spec[:, freqs <= 2000].sum(axis=1) + 1e-9
    bright = hi / lo
    return {"hop": hop, "db": db.tolist(), "bright": bright.tolist(),
            "median_db": float(np.median(db)), "p90_db": float(np.percentile(db, 90))}


def speech_pass(media: Path, model_name: str) -> list:
    from faster_whisper import WhisperModel
    model = WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=8)
    segs, _ = model.transcribe(str(media), vad_filter=True, beam_size=1,
                               condition_on_previous_text=False)
    out = []
    for s in segs:
        out.append({"t0": round(s.start, 2), "t1": round(s.end, 2), "text": s.text.strip()})
    return out


def score_windows(energy: dict, speech: list, win: float = 30.0, step: float = 5.0,
                  min_len: float = 15.0, max_len: float = 60.0) -> list:
    db = np.array(energy["db"])
    bright = np.array(energy["bright"])
    hop = energy["hop"]
    base = energy["median_db"]
    dur = len(db) * hop

    cands = []
    t = 0.0
    while t + min_len <= dur:
        for length in (min_len, 25.0, 30.0, 40.0, 50.0, max_len):
            if t + length > dur:
                continue
            a, b = int(t / hop), int((t + length) / hop)
            seg_db = db[a:b]
            seg_br = bright[a:b]
            voice = [s for s in speech if s["t1"] > t and s["t0"] < t + length]
            if len(voice) < 2:
                continue
            words = " ".join(s["text"].lower() for s in voice)
            laugh = sum(w in words for w in LAUGH) 
            shout = sum(w in words for w in SHOUT)
            spam = len(voice) / length          # lines per second: fast talk / overlap
            cands.append({
                "t0": round(t, 2), "t1": round(t + length, 2), "len": length,
                "loud_db": round(float(np.percentile(seg_db, 90) - base), 2),
                "peak_db": round(float(seg_db.max() - base), 2),
                "bright": round(float(np.percentile(seg_br, 80)), 3),
                "laugh": laugh, "shout": shout, "lines": len(voice),
                "rate": round(spam, 3),
                "text": words[:220],
            })
        t += step

    for c in cands:
        c["score"] = round(
            1.0 * c["loud_db"] + 0.8 * c["peak_db"] + 6.0 * c["laugh"] + 2.0 * c["shout"]
            + 4.0 * c["rate"] + 3.0 * min(c["bright"], 3.0), 2)
    cands.sort(key=lambda c: -c["score"])

    picked, used = [], []
    for c in cands:                              # keep the list non-overlapping
        if any(c["t0"] < u["t1"] and u["t0"] < c["t1"] for u in picked):
            continue
        picked.append(c)
        if len(picked) >= 24:
            break
    return picked


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("media")
    ap.add_argument("--out", default="peaks.json")
    ap.add_argument("--wav", default="/tmp/peaks_audio.wav")
    ap.add_argument("--model", default="base.en")
    ap.add_argument("--reuse-energy", default=None, help="json from a previous run")
    args = ap.parse_args()

    media = Path(args.media)
    if args.reuse_energy:
        energy = json.loads(Path(args.reuse_energy).read_text())["energy"]
    else:
        x = decode(media, Path(args.wav))
        energy = energy_curve(x)
    speech = speech_pass(media, args.model)
    windows = score_windows(energy, speech)

    Path(args.out).write_text(json.dumps({
        "media": str(media), "energy": energy, "speech": speech, "windows": windows,
    }, indent=1))
    print(f"{len(speech)} speech segments, {len(windows)} candidate windows -> {args.out}")
    for w in windows[:12]:
        print(f"  {int(w['t0'])//60:>2}:{int(w['t0'])%60:02d} +{int(w['len'])}s  "
              f"score {w['score']:>6}  laugh {w['laugh']} shout {w['shout']} "
              f"| {w['text'][:70]}")


if __name__ == "__main__":
    main()
