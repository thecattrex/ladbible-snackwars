#!/usr/bin/env python3
"""TRANSCRIBER BOT — one pass over the whole episode, chunked so a 2 GB box
survives, and writes assets/words_all.json (word-level, absolute time).

After this the render bots never load Whisper: they filter this file. That is
what makes 20 clips in parallel possible at all.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import imageio_ffmpeg

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "snackwars.mp4"
OUT = ROOT / "assets" / "words_all.json"
FF = imageio_ffmpeg.get_ffmpeg_exe()
CHUNK = 45.0          # seconds per ASR chunk
SR = 16000


def video_len() -> float:
    i = subprocess.run([FF, "-hide_banner", "-i", str(SRC)],
                       capture_output=True, text=True).stderr
    for line in i.splitlines():
        if "Duration:" in line:
            h, m, sec = line.split("Duration:")[1].split(",")[0].strip().split(":")
            return int(h) * 3600 + int(m) * 60 + float(sec)
    return 0.0


def main():
    if OUT.exists():
        print(f"transcriber: cache already there ({len(json.loads(OUT.read_text()))} words)")
        return
    total = video_len()
    print(f"transcriber: {total:.1f}s of video, {int(total // CHUNK) + 1} chunks")
    from faster_whisper import WhisperModel
    model = WhisperModel("small.en", device="cpu", compute_type="int8", cpu_threads=1)
    words = []
    t = 0.0
    while t < total:
        raw = subprocess.run([FF, "-v", "error", "-ss", f"{t:.2f}", "-t", f"{CHUNK:.2f}",
                              "-i", str(SRC), "-vn", "-ac", "1", "-ar", str(SR),
                              "-f", "s16le", "-"], capture_output=True).stdout
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if audio.size:
            segs, _ = model.transcribe(audio, language="en", beam_size=1,
                                       vad_filter=True, word_timestamps=True,
                                       condition_on_previous_text=False)
            for s in segs:
                for w in s.words:
                    txt = w.word.strip()
                    if txt:
                        words.append(dict(t=round(w.start + t, 2),
                                          e=round(w.end + t, 2), w=txt))
        print(f"  {t:6.1f}s -> {len(words)} words", flush=True)
        t += CHUNK
    words.sort(key=lambda w: w["t"])
    OUT.write_text(json.dumps(words, ensure_ascii=False), encoding="utf8")
    print(f"transcriber: wrote {len(words)} words -> {OUT}")


if __name__ == "__main__":
    sys.exit(main())
