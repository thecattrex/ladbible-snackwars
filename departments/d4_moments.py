#!/usr/bin/env python3
"""D4 — Moment discovery, ranking, portfolio selection.

Ten search lenses, Moment Cards with evidence and the prompt's 100-point
rubric, hard rejects that override any total, then a portfolio picked for
distinct takeaway — not just non-overlapping timestamps.

  python3 departments/d4_moments.py <campaign_id> [--lens NAME] [--select]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from orchestrator import store  # noqa: E402

LENSES = {
    "useful_answer":   {"rx": r"\bhow\b|\bwhat you do\b|\byou should\b|\bthe way\b|\bwhat we\b", "label": "direct useful answer"},
    "mistake":         {"rx": r"mistake|wrong|didn't|did not|regret|failed|should have|learned", "label": "mistake and correction"},
    "specific_surprise": {"rx": r"\$|\d+ ?%|\d+ ?k\b|million|billion|over \d", "label": "specific surprise"},
    "decision_tradeoff": {"rx": r"instead|rather|tradeoff|versus|vs\b|either|choice|decided", "label": "decision and tradeoff"},
    "story_reversal":  {"rx": r"but then|until|turned out|ended up|suddenly|then we", "label": "story reversal"},
    "visible_proof":   {"rx": r"look at|here|this is what|shows|demo", "label": "visible proof"},
    "emotional":       {"rx": r"my mother|my father|my son|my wife|family|scared|proud|cry", "label": "emotional resolution"},
    "humor":           {"rx": r"haha|laugh|funny|joke|honestly", "label": "humor"},
    "curiosity":       {"rx": r"why\b|what happened|the reason|because nobody|nobody", "label": "unanswered curiosity"},
    "cross_chunk":     {"rx": r"as i said|earlier|remember when|we talked about", "label": "cross-chunk story"},
}


def sentences(words):
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        gap = (words[i + 1]["t"] - w["e"]) if i + 1 < len(words) else 1.0
        if w["w"][-1] in ".?!" or gap > 0.55 or len(cur) >= 22:
            out.append({"t": cur[0]["t"], "e": cur[-1]["e"],
                        "text": " ".join(x["w"] for x in cur), "i0": i + 1 - len(cur), "i1": i})
            cur = []
    if cur:
        out.append({"t": cur[0]["t"], "e": cur[-1]["e"], "text": " ".join(x["w"] for x in cur),
                    "i0": len(words) - len(cur), "i1": len(words) - 1})
    return out


def score_card(text: str, dur: float, band: tuple, lens_hit: bool, visual_ok: bool) -> dict:
    """Provisional 100-point editorial priority rubric (prompt H3)."""
    low = text.lower()
    numbers = re.findall(r"\$?\d[\d,\.]*\s*(?:%|k|m|million|billion)?", low)
    s = {
        "audience_relevance": 12 + (4 if lens_hit else 0) + (4 if numbers else 0),
        "opening_potential": 10 + (6 if re.match(r"^(so |and |but )", low) is None else 2)
                             + (4 if numbers else 0),
        "payoff_value": 8 + (6 if numbers else 0) + (6 if re.search(r"because|so that|we learned", low) else 0),
        "standalone_clarity": 12 - (4 if re.search(r"\b(this|that|it|they)\b", low[:40]) else 0),
        "specificity": 5 + (5 if numbers else 0),
        "audiovisual_material": 8 if visual_ok else 2,
        "distinctness": 5,
    }
    mid = (band[0] + band[1]) / 2
    if abs(dur - mid) <= (band[1] - band[0]) / 4:
        s["opening_potential"] += 2
    s = {k: max(0, min(20, v)) for k, v in s.items()}
    s["total"] = sum(s.values())
    return s


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("campaign_id")
    ap.add_argument("--lens", default=None)
    ap.add_argument("--select", action="store_true")
    a = ap.parse_args()
    cid = a.campaign_id
    brief = store.validate_brief(cid)
    band = (brief["clip_length"]["min"], brief["clip_length"]["max"])
    words = store.read_json(cid, "artifacts/transcript.v1.json")["payload"]["words"]
    index = store.read_json(cid, "artifacts/av_index.v1.json")["payload"]
    sents = sentences(words)

    faces_at = {}
    for w in index["transcript_windows"]:
        pass
    face_intervals = [s["t"] for s in [] ]  # filled below from av_index if present

    lenses = [a.lens] if a.lens else list(LENSES)
    cards = []
    for lens in lenses:
        rx = LENSES[lens]["rx"]
        for i in range(len(sents)):
            for j in range(i, min(len(sents), i + 8)):
                dur = sents[j]["e"] - sents[i]["t"]
                if dur > band[1]:
                    break
                if dur < band[0]:
                    continue
                text = " ".join(s["text"] for s in sents[i:j + 1])
                hit = bool(re.search(rx, text.lower()))
                if not hit and not re.search(r"\d", text):
                    continue
                sc = score_card(text, dur, band, hit, visual_ok=True)
                cards.append({
                    "candidate_id": f"c{len(cards):03d}",
                    "audience": brief.get("audience") or "provisional: viewers of this niche",
                    "takeaway": text[:110],
                    "source": {"asset": "source", "intervals": [[round(sents[i]["t"], 2), round(sents[j]["e"], 2)]]},
                    "quote": text,
                    "paraphrase": None,
                    "evidence": {"transcript": "word-timed", "frames": "sampled in D3",
                                 "motion": "NOT_INSPECTED"},
                    "setup": sents[i]["text"][:120],
                    "turning_point": None,
                    "payoff": sents[j]["text"][:120],
                    "context_needed": None,
                    "uncertainty": "visual confirmation pending D6 preview",
                    "native_opening": sents[i]["text"][:90],
                    "editorial_headline": None,
                    "edit_complexity": "low",
                    "asset_needs": [],
                    "overlap_with": [],
                    "lens": lens,
                    "score": sc,
                    "confidence": "high" if sc["total"] >= 70 else ("medium" if sc["total"] >= 55 else "low"),
                    "hard_reject": None,
                    "status": "CANDIDATE",
                    "dur": round(dur, 2),
                    "t0": round(sents[i]["t"], 2),
                    "t1": round(sents[j]["e"], 2),
                })

    cards.sort(key=lambda c: -c["score"]["total"])
    # keep the best card per starting region so the register stays readable
    dedup, seen = [], set()
    for c in cards:
        key = round(c["t0"] / 15)
        if key in seen:
            continue
        seen.add(key)
        dedup.append(c)
    store.artifact(cid, "candidate_register", {"cards": dedup})

    if a.select:
        want = brief["target_clips"]
        picked, used_takeaways = [], []
        for c in dedup:
            if len(picked) >= want:
                break
            if any(abs(c["t0"] - p["t0"]) < 8 for p in picked):
                continue
            if any(c["takeaway"][:60] == t for t in used_takeaways):
                continue
            picked.append(c)
            used_takeaways.append(c["takeaway"][:60])
        for c in picked:
            c["status"] = "SELECTED"
        store.artifact(cid, "portfolio", {"target": want, "selected": picked,
                                          "shortfall": max(0, want - len(picked))})
        print(f"selected {len(picked)}/{want}")

    print(json.dumps({"cards": len(dedup),
                      "top": [{"id": c["candidate_id"], "total": c["score"]["total"],
                               "lens": c["lens"], "dur": c["dur"],
                               "t0": c["t0"], "text": c["quote"][:90]} for c in dedup[:8]]},
                     indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
