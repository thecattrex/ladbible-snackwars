#!/usr/bin/env python3
"""D2 — Transcription, alignment, speakers.

Two roles in one file, like the department:
  worker: one shard -> words with absolute source timestamps
  merge : all shards -> one transcript + boundary report (duplicates, gaps,
          seam stutters) so D4 never reads a spliced sentence by accident.

Diarization is declared UNAVAILABLE here rather than guessed: this box has no
speaker-embedding model, and inventing speaker labels would corrupt D5.

  python3 departments/d2_transcribe.py <campaign_id> --shard N
  python3 departments/d2_transcribe.py <campaign_id> --merge
"""
from __future__ import annotations

import argparse
import json
import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from orchestrator import store  # noqa: E402


def norm(s: str) -> str:
    import re
    return re.sub(r"[^a-z0-9$%]", "", s.lower())


def transcribe_shard(cid: str, idx: int) -> int:
    from faster_whisper import WhisperModel
    brief = store.validate_brief(cid)
    meta = json.loads(store.path(cid, f"shards/shard_{idx:02d}.json").read_text())
    wav_path = store.path(cid, f"shards/shard_{idx:02d}.wav")
    with wave.open(str(wav_path)) as w:
        audio = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768.0
    model = WhisperModel(brief.get("asr_model", "small.en"), device="cpu",
                         compute_type="int8", cpu_threads=4)
    segments, info = model.transcribe(
        audio, language=brief.get("spoken_language") or "en",
        word_timestamps=True, vad_filter=True, beam_size=5,
        condition_on_previous_text=True,
        initial_prompt=brief.get("asr_prompt") or None)
    off = float(meta["t0"])
    words = []
    for s in segments:
        for w in (s.words or []):
            t = w.word.strip()
            if t:
                words.append({"t": round(float(w.start) + off, 3),
                              "e": round(float(w.end) + off, 3), "w": t,
                              "conf": round(float(getattr(w, "probability", 0) or 0), 3)})
    words.sort(key=lambda z: z["t"])
    out = {"index": idx, "core": [meta["core_t0"], meta["core_t1"]],
           "overlap": [meta["t0"], meta["t1"]], "words": words,
           "tool": {"name": "faster-whisper", "model": brief.get("asr_model", "small.en"),
                    "precision": "word-timestamps", "diarization": "UNAVAILABLE"}}
    store.artifact(cid, f"words_shard_{idx:02d}", out)
    print(f"shard {idx:02d}: {len(words)} words")
    return 0


def merge(cid: str) -> int:
    """Reconcile overlaps, restore absolute time, drop seam duplicates, and
    report what a human must re-listen to."""
    bdir = store.campaign_dir(cid) / "artifacts"
    shards = sorted(bdir.glob("words_shard_*.v1.json"))
    if not shards:
        raise SystemExit("no shard transcripts")
    loaded = [json.loads(p.read_text())["payload"] for p in shards]
    pool = []
    for s in loaded:
        pool += s["words"]
    pool.sort(key=lambda z: (z["t"], z["e"]))

    words, dropped_seam, dropped_stutter = [], 0, 0
    for w in pool:
        if words:
            prev = words[-1]
            if abs(w["t"] - prev["t"]) < 0.08 and w["w"] == prev["w"]:
                dropped_seam += 1
                continue
            if w["t"] < prev["e"] - 0.25 and w["w"] == prev["w"]:
                dropped_seam += 1
                continue
            if norm(w["w"]) == norm(prev["w"]) and w["t"] - prev["t"] < 1.2:
                dropped_stutter += 1
                continue
        words.append(w)

    coverage, gaps, cursor = [], [], 0.0
    for s in loaded:
        coverage.append({"shard": s["index"], "core": s["core"], "overlap": s["overlap"],
                         "words": len(s["words"]), "diarization": "UNAVAILABLE"})
    for i, w in enumerate(words[:-1]):
        gap = words[i + 1]["t"] - w["e"]
        if gap > 6.0:
            gaps.append({"at": round(w["e"], 2), "gap": round(gap, 2),
                         "note": "long pause or missed speech — re-listen before using"})
    low_conf = [w for w in words if w.get("conf") and w["conf"] < 0.5]
    report = {"shards": len(loaded), "words": len(words),
              "dropped_seam_duplicates": dropped_seam, "dropped_stutter": dropped_stutter,
              "gaps": gaps, "low_confidence_words": len(low_conf),
              "low_confidence_examples": [w["w"] for w in low_conf[:25]],
              "coverage": coverage}
    store.artifact(cid, "transcript", {"words": words})
    store.artifact(cid, "boundary_report", report)
    print(json.dumps({k: v for k, v in report.items() if k != "coverage"}, indent=1))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("campaign_id")
    ap.add_argument("--shard", type=int)
    ap.add_argument("--merge", action="store_true")
    a = ap.parse_args()
    if a.merge:
        return merge(a.campaign_id)
    if a.shard is None:
        raise SystemExit("give --shard N or --merge")
    return transcribe_shard(a.campaign_id, a.shard)


if __name__ == "__main__":
    raise SystemExit(main())
