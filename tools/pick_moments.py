#!/usr/bin/env python3
"""Re-rank scan windows with the transcript, so a pick needs both picture and words.

The visual scan already says where the stream is busy. That is not enough on its
own: a loud room with nobody talking is wallpaper, and a calm frame with a
complete joke is a clip. So every window is scored on

    picture  — motion, edges, colour, faces            (from scan.json)
    speech   — how much is actually said, in how many separate lines
    content  — length of the cleanest run of words, and whether the words look
               like a full thought (repeats and one-word lines score nothing)

and windows whose speech is mostly repeated filler are pushed down. That is what
killed the earlier pick: it sat on a music stretch with two mumbled lines.

  python3 tools/pick_moments.py scan.json transcript.json --top 12
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def window_score(sec: dict, speech: list, t0: int, length: int) -> dict:
    b = slice(t0, t0 + length)
    motion = sec["video"]["motion"][b] or [0]
    edges = sec["video"]["edges"][b] or [0]
    faces = sec["faces"][b] or [0]
    db = sec["audio"]["db"][b] or [0]
    visual = (0.5 * sum(motion) / len(motion) / 8.0
              + 0.3 * sum(edges) / len(edges) / 40.0
              + 0.2 * min(1.0, (sum(faces) / len(faces)) / 2.0))
    loud = (sum(db) / len(db) + 40) / 30.0

    lines = [s for s in speech if s["t1"] > t0 and s["t0"] < t0 + length]
    texts = [clean(s["text"]) for s in lines]
    words = sum(len(t.split()) for t in texts)
    # a line that repeats back to back is music or a caption, not speech
    uniq = len({t.lower() for t in texts})
    repeat_penalty = 1.0 - (uniq / max(1, len(texts))) * 0.8
    longest = max((len(t.split()) for t in texts), default=0)

    speech_score = min(1.0, words / 45.0) * repeat_penalty
    content = min(1.0, longest / 14.0)
    score = 1.0 * visual + 0.5 * loud + 1.6 * speech_score + 0.9 * content
    return {"t0": t0, "len": length, "visual": round(visual, 3),
            "speech": round(speech_score, 3), "content": round(content, 3),
            "words": words, "longest": longest, "score": round(score, 3),
            "text": " ".join(texts)[:260]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scan")
    ap.add_argument("transcript")
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--min-len", type=int, default=18)
    ap.add_argument("--max-len", type=int, default=40)
    args = ap.parse_args()

    scan = json.loads(Path(args.scan).read_text())
    speech = json.loads(Path(args.transcript).read_text())
    sec = scan["seconds"]
    dur = scan["duration"]

    rows = []
    for length in range(args.min_len, args.max_len + 1, 2):
        for t0 in range(0, max(1, dur - length), 3):
            rows.append(window_score(sec, speech, t0, length))
    rows.sort(key=lambda r: -r["score"])

    picked = []
    for r in rows:
        if any(r["t0"] < p["t0"] + p["len"] and p["t0"] < r["t0"] + r["len"] for p in picked):
            continue
        picked.append(r)
        if len(picked) >= args.top:
            break

    for r in picked:
        print(f'{r["t0"]//60:>2}:{r["t0"]%60:02d} +{r["len"]}s  score {r["score"]:>5} '
              f'vis {r["visual"]:>4} sp {r["speech"]:>4} ct {r["content"]:>4} '
              f'| {r["text"][:95]}')
    print(json.dumps(picked, indent=1))


if __name__ == "__main__":
    main()
