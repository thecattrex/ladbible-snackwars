#!/usr/bin/env python3
"""HOOK DEPARTMENT — one clone per lens.

Five identical workers produce identical thoughts, so each clone is given a
different lens instead. Every clone reads the whole transcript (cheap), scores
sentence-aligned spans inside the campaign length window, and reports its
candidates with reasons. Nothing is cut here.

  python3 departments/hook_bot.py <campaign> <lens> <words_dir>
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
camp, lens, words_dir = sys.argv[1], sys.argv[2], Path(sys.argv[3])
CAMP = json.loads((ROOT / "campaigns" / camp / "campaign.json").read_text())
OUT = Path("/tmp/out")
OUT.mkdir(exist_ok=True)
LO, HI = CAMP["length"]["min"], CAMP["length"]["max"]

LENS = {
    # money, scale, time — the numbers people screenshot
    "numbers": dict(
        rx=r"\$|\d|percent|million|billion|thousand|\bk\b|hours?|weeks?|months?|years?",
        why="hard number"),
    # admissions and mistakes — credibility
    "admission": dict(
        rx=r"mistake|wrong|i was|didn't|did not|admit|learned|regret|failed|should have",
        why="admission"),
    # things said against the consensus
    "contrarian": dict(
        rx=r"never|impossible|nobody|everyone|demolish|kill|replace|disrupt|contrarian|no one|collapse",
        why="contrarian claim"),
    # family, origin, cost — emotional stake
    "personal": dict(
        rx=r"my mother|my father|my son|my wife|my family|parents|immigrant|childhood|home",
        why="personal stake"),
    # the stakes of the business
    "stakes": dict(
        rx=r"churn|margin|valuation|revenue|arr|nrr|retention|spend|burn|billion|growth",
        why="business stake"),
}


def load_words(words_dir: Path):
    pool = []
    for p in sorted(words_dir.glob("words_*.json")):
        pool += json.loads(p.read_text())["words"]
    pool.sort(key=lambda z: (z["t"], z["e"]))
    words = []
    for w in pool:                     # shards overlap by 1 s -> drop repeats
        if words and abs(w["t"] - words[-1]["t"]) < 0.08 and w["w"] == words[-1]["w"]:
            continue
        if words and w["t"] < words[-1]["e"] - 0.25 and w["w"] == words[-1]["w"]:
            continue
        words.append(w)
    return words


def sentences(words):
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        gap = (words[i + 1]["t"] - w["e"]) if i + 1 < len(words) else 1.0
        if w["w"][-1] in ".?!" or gap > 0.75 or len(cur) >= 22:
            out.append({"t": cur[0]["t"], "e": cur[-1]["e"],
                        "text": " ".join(x["w"] for x in cur),
                        "i0": i + 1 - len(cur), "i1": i})
            cur = []
    if cur:
        out.append({"t": cur[0]["t"], "e": cur[-1]["e"],
                    "text": " ".join(x["w"] for x in cur),
                    "i0": len(words) - len(cur), "i1": len(words) - 1})
    return out


def score(text: str, lens_rx: str, dur: float, sents: int):
    low = text.lower()
    s, why = 0, []
    if re.search(lens_rx, low):
        s += 4
        why.append(LENS_MATCH)
    nums = re.findall(r"\$?\d[\d,\.]*\s*(?:%|k|m|million|billion|thousand)?", low)
    if nums:
        s += 3
        why.append("number:" + nums[0].strip())
    if re.search(r"never|impossible|wrong|mistake|nobody|demolish|kill|replace", low):
        s += 2
        why.append("contradiction")
    if abs(dur - 33.0) < 2.0:
        s += 1
        why.append("length-fits")
    if sents <= 4:
        s += 1
        why.append("self-contained")
    return s, why


LENS_MATCH = ""

def main():
    global LENS_MATCH
    LENS_MATCH = LENS[lens]["why"]
    words = load_words(words_dir)
    if not words:
        raise SystemExit("no words")
    sents = sentences(words)
    cands = []
    for a in range(len(sents)):
        for b in range(a, min(len(sents), a + 8)):
            dur = sents[b]["e"] - sents[a]["t"]
            if dur > HI:
                break
            if dur < LO:
                continue
            text = " ".join(s["text"] for s in sents[a:b + 1])
            s, why = score(text, LENS[lens]["rx"], dur, b - a + 1)
            if s < 4:
                continue
            cands.append({"t0": round(sents[a]["t"], 3), "t1": round(sents[b]["e"], 3),
                          "dur": round(dur, 2), "score": round(s, 2), "lens": lens,
                          "reasons": why, "text": text})
    cands.sort(key=lambda c: (-c["score"], abs(c["dur"] - 33)))
    (OUT / f"cand_{lens}.json").write_text(json.dumps(cands[:60], indent=1))
    print(f"[{lens}] {len(cands)} candidates, top:")
    for c in cands[:5]:
        print(f"  {c['score']:5.1f} {c['dur']:5.1f}s {c['t0']:8.1f} {c['text'][:110]}")


if __name__ == "__main__":
    main()
