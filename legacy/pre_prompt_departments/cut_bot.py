#!/usr/bin/env python3
"""CUT DEPARTMENT.

Takes every lens's candidates, removes duplicates, enforces the campaign
contract (length window, sentence-aligned start/end, no two clips telling the
same story) and hands the company a final clip list plus one merged transcript
so no downstream worker has to re-download audio.

  python3 departments/cut_bot.py <campaign> <cand_dir> <words_dir>
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
camp, cand_dir, words_dir = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
CAMP = json.loads((ROOT / "campaigns" / camp / "campaign.json").read_text())
OUT = Path("/tmp/out")
OUT.mkdir(exist_ok=True)
LO, HI = CAMP["length"]["min"], CAMP["length"]["max"]
N = int(CAMP["clips"])


def merged_words():
    pool = []
    for p in sorted(words_dir.glob("words_*.json")):
        pool += json.loads(p.read_text())["words"]
    pool.sort(key=lambda z: (z["t"], z["e"]))
    words = []
    for w in pool:
        if words and abs(w["t"] - words[-1]["t"]) < 0.08 and w["w"] == words[-1]["w"]:
            continue
        if words and w["t"] < words[-1]["e"] - 0.25 and w["w"] == words[-1]["w"]:
            continue
        # ASR stutter across shard seams: "I I", "But But", "level level"
        if words and _norm(w["w"]) == _norm(words[-1]["w"]) and w["t"] - words[-1]["t"] < 1.2:
            continue
        words.append(w)
    return words


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9$%]", "", s.lower())


def boundaries(words):
    """Real sentence starts/ends: punctuation, or a spoken pause long enough to
    read as a new sentence."""
    starts, ends = [0], []
    for i, w in enumerate(words):
        gap = (words[i + 1]["t"] - w["e"]) if i + 1 < len(words) else 1.0
        if w["w"][-1] in ".?!" or gap > 0.55:
            ends.append(i)
            if i + 1 < len(words):
                starts.append(i + 1)
    return starts, ends


def snap(words, c):
    """Pull a candidate onto the nearest real sentence start/end so a clip never
    opens mid-clause and never stops half a thought."""
    starts, ends = boundaries(words)
    st = [i for i in starts if c["t0"] - 1.6 <= words[i]["t"] <= c["t1"] - LO + 1.6]
    en = [i for i in ends if c["t1"] - 1.6 <= words[i]["e"] <= c["t0"] + HI + 1.6]
    if not st or not en:
        return None
    i = min(st, key=lambda k: abs(words[k]["t"] - c["t0"]))
    j = min(en, key=lambda k: abs(words[k]["e"] - c["t1"]))
    if j <= i:
        return None
    t0 = round(words[i]["t"] - 0.22, 3)
    t1 = round(words[j]["e"] + 0.30, 3)
    if not (LO <= t1 - t0 <= HI):
        return None
    return t0, t1, i, j


def overlap(a, b):
    return max(0.0, min(a["t1"], b["t1"]) - max(a["t0"], b["t0"]))


def main():
    words = merged_words()
    if not words:
        raise SystemExit("no words")
    (OUT / "words-all.json").write_text(json.dumps(words))

    cands = []
    for p in sorted(cand_dir.glob("cand_*.json")):
        cands += json.loads(p.read_text())
    # same line found by several lenses -> keep it once, sum the evidence
    cands.sort(key=lambda c: (-c["score"], abs(c["dur"] - 33)))
    picked = []
    for c in cands:
        if not (LO <= c["dur"] <= HI):
            continue
        sn = snap(words, c)
        if sn is None:
            continue
        c["t0"], c["t1"], c["i0"], c["i1"] = sn
        c["dur"] = round(c["t1"] - c["t0"], 2)
        if not (LO <= c["dur"] <= HI):
            continue
        if any(overlap(c, p) > 0.5 * min(c["dur"], p["dur"]) for p in picked):
            continue
        if any(abs(c["t0"] - p["t0"]) < 20 for p in picked):   # story diversity
            continue
        picked.append(c)
        if len(picked) >= N:
            break

    if len(picked) < N:      # not enough room between windows -> fill densely
        for c in cands:
            if len(picked) >= N:
                break
            if not (LO <= c["dur"] <= HI):
                continue
            sn = snap(words, c)
            if sn is None:
                continue
            c["t0"], c["t1"], c["i0"], c["i1"] = sn
            c["dur"] = round(c["t1"] - c["t0"], 2)
            if not (LO <= c["dur"] <= HI):
                continue
            if any(overlap(c, p) > 0.4 * min(c["dur"], p["dur"]) for p in picked):
                continue
            picked.append(c)

    picked.sort(key=lambda c: c["t0"])
    clips = []
    for i, c in enumerate(picked):
        seg = words[c["i0"]:c["i1"] + 1]
        first = seg[0]["w"] if seg else ""
        last = seg[-1]["w"] if seg else ""
        clips.append({
            "id": f"h{i+1:02d}",
            "t0": c["t0"],
            "t1": c["t1"],
            "len": c["dur"],
            "score": c["score"],
            "lens": c["lens"],
            "reasons": c["reasons"],
            "first_words": first,
            "last_words": last,
            "text": c["text"],
            "hook": "",                              # filled by the boss review
        })
    clips = [c for c in clips if LO <= c["len"] <= HI]
    (OUT / "clips.json").write_text(json.dumps(clips, indent=1))
    print(f"{len(clips)} clips in contract window")
    for c in clips:
        print(f"  {c['id']} {c['len']:5.1f}s @{c['t0']:8.1f} [{c['lens']}] {c['text'][:90]}")


if __name__ == "__main__":
    main()
