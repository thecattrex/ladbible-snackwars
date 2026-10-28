#!/usr/bin/env python3
"""TRANSCRIBE DEPARTMENT — worker.

One shard in, one word-timing file out. No decisions, no filtering: the worker
that "interprets" is a worker that lies. Honest ASR only, in absolute seconds.

  python3 departments/transcribe_bot.py <campaign> <shard_index> <shard_dir>
"""
from __future__ import annotations

import json
import sys
import wave
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel

ROOT = Path(__file__).resolve().parent.parent
camp = sys.argv[1]
idx = int(sys.argv[2])
shard_dir = Path(sys.argv[3])
CAMP = json.loads((ROOT / "campaigns" / camp / "campaign.json").read_text())
OUT = Path("/tmp/out")
OUT.mkdir(exist_ok=True)

meta = json.loads(next(shard_dir.glob("shard_*.json")).read_text())
wav_path = next(shard_dir.glob("shard_*.wav"))

with wave.open(str(wav_path)) as w:
    audio = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768.0

model = WhisperModel(CAMP["transcribe"]["model"], device="cpu",
                     compute_type="int8", cpu_threads=4)
segs, info = model.transcribe(audio, language="en", word_timestamps=True,
                              vad_filter=True, beam_size=5,
                              condition_on_previous_text=True,
                              initial_prompt=CAMP["transcribe"]["initial_prompt"])

off = float(meta["t0"])
words = []
for s in segs:
    for w in (s.words or []):
        txt = w.word.strip()
        if txt:
            words.append({"t": round(float(w.start) + off, 3),
                          "e": round(float(w.end) + off, 3),
                          "w": txt})
words.sort(key=lambda z: z["t"])

(OUT / f"words_{idx:02d}.json").write_text(json.dumps({"index": idx, "t0": off, "words": words}))
print(f"shard {idx:02d}: {len(words)} words, {words[0]['t'] if words else 0}-{words[-1]['e'] if words else 0}s")
print(" ".join(w["w"] for w in words)[:300])
