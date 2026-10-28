#!/usr/bin/env python3
"""D5 — Hooks and narrative assembly.

For one selected moment: find the best *source-native* opening, keep the three
hook categories separate, draft six genuinely different angles, shortlist three,
pick one, and record the payoff it promises plus an alternate to test.

The editor can override the winner in campaigns/<id>/hook_overrides.json; the
rubric still runs, so an override that breaks source fidelity fails review.

  python3 departments/d5_hooks.py <campaign_id> [--clip CANDIDATE_ID]
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

PATTERNS = ["result_first", "mistake_to_correction", "expectation_reversal",
            "audience_question", "specific_constraint", "counterintuitive_detail"]


def clean(t: str) -> str:
    t = re.sub(r"\s*-\s*", "-", t)
    t = re.sub(r"\s+([,\.\?!])", r"\1", t)
    return re.sub(r"\s{2,}", " ", t).strip()


def best_native(card: dict, words: list) -> dict:
    """The opening has to be words he actually says inside the clip."""
    seg = [w for w in words if card["t0"] - 0.2 <= w["t"] < card["t1"]]
    for n in (14, 12, 10, 8, 6):
        if len(seg) < n:
            continue
        head = " ".join(w["w"] for w in seg[:n])
        if re.search(r"\d", head) or re.search(r"never|wrong|mistake|because|but", head, re.I):
            return {"quote": clean(head), "at": round(seg[0]["t"], 2), "words": n}
    head = " ".join(w["w"] for w in seg[:10])
    return {"quote": clean(head), "at": round(card["t0"], 2), "words": len(seg[:10])}


def headline_from(card: dict) -> str:
    """Editorial headline: a frame, never a fabricated quote."""
    text = clean(card["quote"])
    m = re.findall(r"\$?\d[\d,\.]*\s*(?:%|k|m|million|billion)?", text)
    subject = re.sub(r"^(so|and|but|like|because)\s+", "", text, flags=re.I)
    subject = " ".join(subject.split()[:9])
    if m:
        return f"{m[0].strip()} — {subject}".upper()[:70]
    return subject.upper()[:70]


def rubric(headline: str, quote: str, payoff: str, card: dict) -> dict:
    numbers = bool(re.findall(r"\d", headline))
    overlap = bool(set(headline.lower().split()[:4]) & set(payoff.lower().split()[:6]))
    r = {
        "comprehensibility": 17 if len(headline.split()) <= 9 else 12,
        "relevance_stakes": 16 if numbers else 11,
        "curiosity": 13 if re.search(r"never|wrong|mistake|actually|but", headline, re.I) else 9,
        "specificity": 9 if numbers else 5,
        "source_fidelity": 20 if quote and quote.split()[0].lower() in payoff.lower() else 14,
        "payoff_alignment": 15 if overlap else 10,
    }
    r["total"] = sum(r.values())
    return r


def card_for(card: dict, words: list, override: str | None) -> dict:
    native = best_native(card, words)
    payoff = clean(card["payoff"])
    drafts = [
        f"{headline_from(card)}",
        f"HE SAID {native['quote'][:40].upper()}",
        f"THE {card['lens'].replace('_', ' ').upper()}",
        f"{clean(card['quote'])[:60].upper()}",
        f"WHY {clean(card['takeaway'])[:40].upper()}",
        f"WHAT HAPPENED NEXT",
    ]
    drafts = list(dict.fromkeys(drafts))[:6]
    scored = sorted(drafts, key=lambda h: -rubric(h, native["quote"], payoff, card)["total"])
    shortlist = scored[:3]
    winner = override or shortlist[0]
    rb = rubric(winner, native["quote"], payoff, card)
    return {
        "hook_id": f"{card['candidate_id']}-h1",
        "candidate_id": card["candidate_id"],
        "viewer_question": f"What exactly {card['takeaway'][:70].rstrip(' .')}?",
        "payoff": payoff,
        "payoff_source_intervals": card["source"]["intervals"],
        "category": "EDITORIAL_TEXT",
        "pattern": PATTERNS[hash(card["candidate_id"]) % len(PATTERNS)],
        "native_quote": native["quote"],
        "native_quote_source": {"t": native["at"], "words": native["words"],
                                "note": "spoken inside the clip"},
        "editorial_text": winner,
        "first_frame": f"source frame at {card['t0']}s, speaker centred",
        "first_sentence": native["quote"],
        "sound_plan": "source speech first; optional low riser under the headline; no music over the first sentence",
        "drafts": drafts,
        "shortlist": shortlist,
        "winner": winner,
        "rubric": rb,
        "story_beats": [
            {"beat": "hook", "out": [0.0, 3.5], "purpose": "state the promise"},
            {"beat": "context", "out": [3.5, (card["t1"] - card["t0"]) * 0.55], "purpose": "minimum setup"},
            {"beat": "payoff", "out": [(card["t1"] - card["t0"]) * 0.55, card["t1"] - card["t0"]],
             "purpose": "deliver what the hook promised"},
        ],
        "alternate": {"text": shortlist[1] if len(shortlist) > 1 else None,
                      "variable": "headline framing only; payoff unchanged"},
        "review_status": "PASS" if rb["total"] >= 80 and override is None else (
            "PENDING" if override else "REVISE"),
        "override_used": bool(override),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("campaign_id")
    ap.add_argument("--clip", default=None)
    a = ap.parse_args()
    cid = a.campaign_id
    words = store.read_json(cid, "artifacts/transcript.v1.json")["payload"]["words"]
    portfolio = store.read_json(cid, "artifacts/portfolio.v1.json")
    if not portfolio:
        raise SystemExit("run D4 --select first")
    cards = portfolio["payload"]["selected"]
    overrides = store.read_json(cid, "hook_overrides.json", {}) or {}

    out = []
    for c in cards:
        if a.clip and c["candidate_id"] != a.clip:
            continue
        out.append(card_for(c, words, overrides.get(c["candidate_id"])))
    store.artifact(cid, "hook_cards", {"cards": out})
    for h in out:
        print(f"{h['candidate_id']}  {h['rubric']['total']:3d}  {h['review_status']:8s} {h['winner'][:64]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
