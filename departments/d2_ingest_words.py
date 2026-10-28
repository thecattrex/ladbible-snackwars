#!/usr/bin/env python3
"""D2 adjunct — ingest externally produced word timings as shard artifacts.

D2's worker contract is: one audio window -> words with absolute source
timestamps. On this box (2 cores, 1.9 GB) a whole-file or 40-shard whisper run
OOMs, so the same faster-whisper small.en int8 engine is run in two parallel
processes over 300 s windows, each window loaded from disk alone. The result is
shaped exactly like D2's own shard output and then merged by D2 --merge, so all
downstream departments (D3/D4/D5) see one canonical transcript.

  python3 departments/d2_ingest_words.py <campaign_id> [--parts f1.json f2.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from orchestrator import store  # noqa: E402

WINDOW = 300.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("campaign_id")
    ap.add_argument("--parts", nargs="+", required=True)
    a = ap.parse_args()
    cid = a.campaign_id
    store.validate_brief(cid)

    words = []
    for f in a.parts:
        p = Path(f)
        if not p.exists():
            raise SystemExit(f"missing part file {p}")
        for seg in json.loads(p.read_text()):
            for w in seg.get("words") or []:
                t = (w["w"] or "").strip()
                if t:
                    words.append({"t": round(w["s"], 3), "e": round(w["e"], 3),
                                  "w": t, "conf": round(w.get("p", 0) or 0, 3)})
    words.sort(key=lambda z: (z["t"], z["e"]))
    if not words:
        raise SystemExit("no words ingested")

    dur = max(w["e"] for w in words)
    n = 0
    for i in range(int(dur // WINDOW) + 1):
        t0, t1 = i * WINDOW, min(dur, (i + 1) * WINDOW)
        chunk = [w for w in words if t0 <= w["t"] < t1]
        if not chunk:
            continue
        store.artifact(cid, f"words_shard_{n:02d}", {
            "index": n, "core": [round(t0, 2), round(t1, 2)],
            "overlap": [round(t0, 2), round(t1, 2)], "words": chunk,
            "tool": {"name": "faster-whisper", "model": "small.en",
                     "precision": "word-timestamps", "diarization": "UNAVAILABLE",
                     "note": "300 s windows, two parallel processes, local CPU"}})
        n += 1
    print(json.dumps({"shards": n, "words": len(words), "duration": round(dur, 2)}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
