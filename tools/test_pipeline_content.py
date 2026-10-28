#!/usr/bin/env python3
"""Integration check: the content judge drives the cut, not just the QA report.

Uses the two synthetic clips from tools/test_meaningful_frame.py as a "source", so
this exercises the same code D6 runs on real footage:

  1. content.source_scan finds no dead span in the busy clip;
  2. it finds the one dead second in the wall clip, at the right time;
  3. timeline.build with that span in `avoid` removes it and keeps the clip inside
     its length band, so the plan D6 would render has no dead frame in it.

  python3 tools/test_meaningful_frame.py && python3 tools/test_pipeline_content.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from orchestrator import content, timeline  # noqa: E402

BUSY = Path("/tmp/content_test/content_busy.mp4")
DEAD = Path("/tmp/content_test/content_dead.mp4")


def words_between(t0: float, t1: float):
    """A steady stream of words, one every 0.2 s, for the cut plan to work on."""
    out, t = [], t0
    n = 0
    while t < t1:
        out.append({"w": f"word{n}.", "t": round(t, 3), "e": round(t + 0.30, 3)})
        t += 0.35
        n += 1
    return out


def main() -> int:
    if not BUSY.exists() or not DEAD.exists():
        print("run tools/test_meaningful_frame.py first")
        return 1
    fails = []

    samples = content.source_scan(BUSY, 0.0, 6.0)
    dead = content.runs(samples, "alive", False, min_len=0.40)
    ok = not dead
    print(f"  {'ok  ' if ok else 'FAIL'} busy clip: dead spans {dead} (wanted none)")
    if not ok:
        fails.append("false positive on a busy clip")

    samples = content.source_scan(DEAD, 0.0, 6.0)
    dead = content.runs(samples, "alive", False, min_len=0.40)
    ok = len(dead) == 1 and abs(dead[0][0] - 2.5) < 0.4 and abs(dead[0][1] - 3.5) < 0.4
    print(f"  {'ok  ' if ok else 'FAIL'} wall clip: dead spans {dead} (wanted [[2.5, 3.5]])")
    if not ok:
        fails.append("missed the black wall")

    # the cut the editor would make: keep the speech, drop the dead second
    words = words_between(0.0, 6.0)
    cfg = {"min_dur": 4.0, "max_dur": 8.0, "avoid": dead}
    plan = timeline.build(words, 0.0, 6.0, cfg)
    inside = all(not (a - 0.001 <= s["src_in"] < b + 0.001 and s["src_in"] < b)
                 for s in plan["segments"] for a, b in dead)
    ok = inside and plan["within_band"]
    print(f"  {'ok  ' if ok else 'FAIL'} plan after avoid: {plan['duration']}s, "
          f"segments {[(round(s['src_in'], 2), round(s['src_out'], 2)) for s in plan['segments']]}")
    if not ok:
        fails.append("plan still contains the dead second")

    print()
    if fails:
        print("FAILED:", ", ".join(fails))
        return 1
    print("pipeline content checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
