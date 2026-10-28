#!/usr/bin/env python3
"""Timeline — the single cut plan every department edits against.

A clip is not one contiguous slice of the source. It is a list of kept source
segments, each cut on a thought boundary, with the pauses and filler between
them closed. This module builds that list once and gives every department the
same source->output mapping, so picture, dialogue, captions and SFX can never
drift apart.

Rules encoded here (from the master prompt):
  * cuts land between sentences, never inside one;
  * self-corrections, "but" and real reactions survive — only pauses, repeats
    and pure filler are dropped, and only when the campaign authorises it;
  * no new sentence is ever manufactured out of the speaker's words: kept
    segments are always contiguous runs of the original audio.
"""
from __future__ import annotations

import math
import re

SENT_END = (".", "?", "!", "…")


def sentences(words):
    """Group word timings into sentences (punctuation or a real pause)."""
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        gap = (words[i + 1]["t"] - w["e"]) if i + 1 < len(words) else 1.0
        if w["w"].endswith(SENT_END) or gap > 0.55 or len(cur) >= 26:
            out.append({"t": cur[0]["t"], "e": cur[-1]["e"],
                        "text": " ".join(x["w"] for x in cur),
                        "words": cur})
            cur = []
    if cur:
        out.append({"t": cur[0]["t"], "e": cur[-1]["e"],
                    "text": " ".join(x["w"] for x in cur), "words": cur})
    return out


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9$% ]", "", s.lower()).strip()


def is_filler(text: str, phrases) -> bool:
    n = _norm(text)
    for p in phrases or []:
        if _norm(p) and _norm(p) in n:
            return True
    return False


def build(words, t0, t1, cfg=None):
    """Return the cut plan for one clip.

    cfg keys (all optional):
      remove_phrases : list[str]  sentences/phrases the editor drops as filler
      max_gap        : float      silence kept between kept segments (default .20)
      pad_in/pad_out : float      air kept either side of a cut (default .07/.10)
      min_dur/max_dur: float      hard band for the finished clip
      punch_on_number: bool       punch in on sentences that carry a number
      punch_phrases  : list[str]  when given, only these sentences are punched
    """
    cfg = cfg or {}
    max_gap = float(cfg.get("max_gap", 0.20))
    punch_on_number = bool(cfg.get("punch_on_number", True))
    punch_phrases = [pl.lower() for pl in (cfg.get("punch_phrases") or [])]
    remove = cfg.get("remove_phrases") or []

    sents = [s for s in sentences(words) if s["e"] > t0 + 0.01 and s["t"] < t1 - 0.01]
    if not sents:
        raise SystemExit("cut plan: no speech inside the window")

    kept = []
    for s in sents:
        a = max(s["t"], t0)
        b = min(s["e"], t1)
        if b - a < 0.25:
            continue
        if is_filler(s["text"], remove):
            continue
        kept.append({"src_in": round(a, 3), "src_out": round(b, 3),
                     "text": s["text"], "removed": False})

    if not kept:
        raise SystemExit("cut plan: every sentence was removed as filler")

    # handles: every cut keeps a few frames of air either side so a word onset or
    # release is never shaved off. Segments may not overlap each other.
    pad_in = float(cfg.get("pad_in", 0.07))
    pad_out = float(cfg.get("pad_out", 0.10))
    for i, k in enumerate(kept):
        lo = kept[i - 1]["src_out"] + 0.02 if i else t0
        hi = kept[i + 1]["src_in"] - 0.02 if i + 1 < len(kept) else t1
        k["src_in"] = round(max(k["src_in"] - pad_in, min(lo, k["src_in"])), 3)
        k["src_out"] = round(min(k["src_out"] + pad_out, max(hi, k["src_out"])), 3)

    # tighten: keep a short, natural pause between segments instead of dead air
    segs, out_t = [], 0.0
    for i, k in enumerate(kept):
        d = k["src_out"] - k["src_in"]
        lead = 0.0 if i == 0 else max_gap
        seg = {"index": i, "src_in": k["src_in"], "src_out": k["src_out"],
               "out_in": round(out_t + lead, 3), "out_out": round(out_t + lead + d, 3),
               "text": k["text"],
               "lead": lead,
               "number": bool(re.search(r"\d|\$|percent", k["text"], re.I)),
               "purpose": "speaker framing"}
        want_punch = seg["number"]
        if punch_phrases:
            want_punch = any(pl in _norm(k["text"]) for pl in punch_phrases)
        if punch_on_number and want_punch:
            seg["purpose"] = "punch-in on the number"
        seg["punch"] = bool(punch_on_number and want_punch)
        segs.append(seg)
        out_t = seg["out_out"]

    total = round(out_t, 3)
    lo = float(cfg.get("min_dur", 0) or 0)
    hi = float(cfg.get("max_dur", 0) or 0)
    if hi and total > hi:                       # drop whole tail sentences, never trim words
        while segs and (segs[-1]["out_out"] > hi) and len(segs) > 1:
            segs.pop()
        # rebuild output clock
        acc = 0.0
        for i, s in enumerate(segs):
            lead = 0.0 if i == 0 else max_gap
            d = s["src_out"] - s["src_in"]
            s["out_in"] = round(acc + lead, 3)
            s["out_out"] = round(s["out_in"] + d, 3)
            acc = s["out_out"]
        total = round(acc, 3)
    return {"t0": t0, "t1": t1, "segments": segs, "duration": total,
            "dropped_sentences": [k["text"] for k in kept if False],
            "band": [lo, hi], "within_band": (not lo or total >= lo) and (not hi or total <= hi)}


def src_to_out(plan, t):
    """Map a source timestamp inside the plan to output time (None if cut)."""
    for s in plan["segments"]:
        if s["src_in"] - 0.001 <= t <= s["src_out"] + 0.001:
            return round(s["out_in"] + (t - s["src_in"]), 3)
    return None


def remap_words(plan, words):
    """Every surviving word, retimed to the output clock."""
    out = []
    for s in plan["segments"]:
        for w in words:
            if s["src_in"] - 0.001 <= w["t"] < s["src_out"]:
                t = round(s["out_in"] + (w["t"] - s["src_in"]), 3)
                e = round(min(s["out_in"] + (w["e"] - s["src_in"]), s["out_out"]), 3)
                out.append({"t": t, "e": max(e, t + 0.04), "w": w["w"],
                            "src_t": w["t"]})
    out.sort(key=lambda z: z["t"])
    return out


def cut_points(plan):
    return [s["out_in"] for s in plan["segments"][1:]]
