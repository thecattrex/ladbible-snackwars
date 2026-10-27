#!/usr/bin/env python3
"""ORCHESTRATOR — the shift manager.

  stage 0  transcriber bot        : word timings once (render bots then skip Whisper)
  stage 1  20 render bots         : one bot per clip, 2 running at a time (2 CPUs / 2 GB)
  stage 2  4 reviewer bots        : every clip judged, contact sheet written
  stage 3  fixer bots             : failed clips re-rendered in strict mode, re-reviewed
  stage 4  final gate             : only clips that pass land in clips_final/

Usage: python3 bots/orchestrator.py [--eps 1 2 3 ...] [--render-slots 2]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATUS = ROOT / "assets" / "bot_status"
FINAL = ROOT / "clips_final"
ALL_EPS = list(range(1, 21))


def run(cmd, env=None, timeout=1800):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          timeout=timeout)


def stage_source():
    r = run([sys.executable, "bots/fetch_src.py"], timeout=900)
    print("[source]", (r.stdout or r.stderr).strip()[-200:])
    return (ROOT / "src" / "snackwars.mp4").exists()


def stage_transcribe():
    w = ROOT / "assets" / "words_all.json"
    if w.exists():
        print("[transcriber] cache present")
        return True
    r = run([sys.executable, "-u", "bots/transcribe_bot.py"], timeout=2400)
    print("[transcriber]", r.stdout.strip()[-400:] or r.stderr.strip()[-400:])
    return w.exists()


def render_one(ep: int, strict=False) -> dict:
    cmd = [sys.executable, "-u", "bots/render_bot.py", str(ep)]
    if strict:
        cmd.append("--strict")
    t0 = time.time()
    r = run(cmd)
    tag = "fixer" if strict else "render"
    out = [l for l in r.stdout.strip().splitlines() if l.startswith("{")]
    print(f"[{tag} {ep:02d}] {time.time()-t0:5.0f}s  {out[-1] if out else r.stderr[-200:]}")
    try:
        return json.loads((STATUS / f"ep{ep:02d}.json").read_text())
    except Exception:
        return dict(ep=ep, state="error", error=r.stderr[-300:])


def review_one(ep: int) -> dict:
    r = run([sys.executable, "bots/review_bot.py", str(ep)], timeout=600)
    try:
        rec = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        rec = dict(ep=ep, ok=False, reasons=["review crashed"])
    mark = "PASS" if rec.get("ok") else "FAIL"
    extra = "" if rec.get("ok") else "  " + "; ".join(rec.get("reasons", []))
    print(f"[review {ep:02d}] {mark} face {rec.get('face_pct', 0)*100:5.1f}% "
          f"gap {rec.get('max_gap', 0):4.1f}s{extra}")
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eps", type=int, nargs="*", default=ALL_EPS)
    ap.add_argument("--render-slots", type=int, default=2)
    a = ap.parse_args()
    eps = a.eps
    STATUS.mkdir(parents=True, exist_ok=True)
    FINAL.mkdir(exist_ok=True)

    if not stage_source():
        print("FATAL: source video missing"); return 1
    if not stage_transcribe():
        print("FATAL: transcription cache missing"); return 1

    t_start = time.time()
    print(f"\n=== stage 1: render bots ({len(eps)} clips, {a.render_slots} at a time) ===")
    with ThreadPoolExecutor(max_workers=a.render_slots) as pool:
        rendered = list(pool.map(render_one, eps))
    bad = [r["ep"] for r in rendered if r.get("state") != "rendered"]
    print(f"rendered {len(eps)-len(bad)}/{len(eps)}  failed: {bad}")

    print("\n=== stage 2: reviewer bots ===")
    with ThreadPoolExecutor(max_workers=4) as pool:
        reviews = list(pool.map(review_one, eps))
    failed = [r["ep"] for r in reviews if not r.get("ok")]
    print(f"passed {len(eps)-len(failed)}/{len(eps)}  failed: {failed}")

    # stage 3: fixer bots, two rounds
    for rnd in (1, 2):
        if not failed:
            break
        print(f"\n=== stage 3.{rnd}: fixer bots strict re-cut for {failed} ===")
        with ThreadPoolExecutor(max_workers=a.render_slots) as pool:
            list(pool.map(lambda e: render_one(e, strict=True), failed))
        with ThreadPoolExecutor(max_workers=4) as pool:
            fixed = list(pool.map(review_one, failed))
        failed = [r["ep"] for r in fixed if not r.get("ok")]

    print("\n=== stage 4: final gate ===")
    passed = []
    for ep in eps:
        p = ROOT / "clips_v3" / f"ep{ep:02d}.mp4"
        j = STATUS / f"ep{ep:02d}_review.json"
        ok = j.exists() and json.loads(j.read_text()).get("ok")
        if ok and p.exists():
            (FINAL / f"ep{ep:02d}.mp4").unlink(missing_ok=True)
            p.replace(FINAL / f"ep{ep:02d}.mp4")
            passed.append(ep)
    # clips that never passed stay in clips_v3 as rejects
    print(f"final folder: {len(passed)}/{len(eps)} clips -> {FINAL}")
    missing = [e for e in eps if e not in passed]
    if missing:
        print(f"NOT shipped (rejects left in clips_v3): {missing}")
    print(f"total {time.time()-t_start:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
