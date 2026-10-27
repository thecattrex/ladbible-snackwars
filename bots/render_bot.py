#!/usr/bin/env python3
"""RENDER BOT — builds ONE clip (ep number on the command line).

Each render bot is a separate OS process with its own memory, its own 1-thread
x264 encode and its own render/verify/retry loop, so 20 of them can chew
through the episode list at the same time without sharing state.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

os.environ.setdefault("MALLOC_ARENA_MAX", "2")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

STATUS = ROOT / "assets" / "bot_status"


def main(ep: int, strict: bool = False) -> int:
    t0 = time.time()
    STATUS.mkdir(exist_ok=True)
    (STATUS / f"ep{ep:02d}.json").write_text(
        json.dumps(dict(ep=ep, state="rendering", strict=strict, started=t0)))
    if strict:                       # fixer-bot mode: demand more of every shot
        os.environ["LAD_MIN_COV"] = "0.82"
        os.environ["LAD_STOP_COV"] = "0.96"
        os.environ["LAD_ANCHORS"] = "4"
    try:
        import edit_lad_v3 as ed
        out, total, shots, runs, cover = ed.build(ep)
        rec = dict(ep=ep, state="rendered", file=str(out), duration=round(total, 2),
                   shots=shots, runs=runs, coverage=round(cover, 3),
                   seconds=round(time.time() - t0, 1), strict=strict)
    except Exception:
        import os
        tb = traceback.format_exc()
        print(tb, file=sys.stderr, flush=True)
        rec = dict(ep=ep, state="error", error=tb[-1500:],
                   seconds=round(time.time() - t0, 1), strict=strict)
    (STATUS / f"ep{ep:02d}.json").write_text(json.dumps(rec))
    print(json.dumps({k: v for k, v in rec.items() if k != "error"}))
    return 0 if rec["state"] == "rendered" else 1


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if x != "--strict"]
    sys.exit(main(int(a[0]), "--strict" in sys.argv))
