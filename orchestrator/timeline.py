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

    A clip is a set of *contiguous* source ranges. Adjacent sentences are kept
    together whenever the pause between them is short, so the picture and the
    dialogue cover exactly the same frames — the way an editor cuts: dead air is
    removed, not replaced with silence or a freeze. Only pauses longer than
    `max_gap` become a cut.

    cfg keys (all optional):
      remove_phrases : list[str]  sentences the editor drops as filler
      max_gap        : float      longest pause kept inline (default .60)
      min_dur/max_dur: float      hard band for the finished clip
      punch_on_number: bool       punch in on sentences that carry a number
      punch_phrases  : list[str]  when given, only these sentences are punched
      pad_in/pad_out : float      air kept either side of a hard cut
      avoid          : list[[a,b]]  source spans the picture cannot use (the
                     camera is on an empty room there) — the plan cuts around
                     them and keeps the speech on either side
    """
    cfg = cfg or {}
    max_gap = float(cfg.get("max_gap", 0.60))
    punch_on_number = bool(cfg.get("punch_on_number", True))
    punch_phrases = [pl.lower() for pl in (cfg.get("punch_phrases") or [])]
    remove = cfg.get("remove_phrases") or []

    sents = [s for s in sentences(words) if s["e"] > t0 + 0.01 and s["t"] < t1 - 0.01]
    if not sents:
        raise SystemExit("cut plan: no speech inside the window")

    avoid = [tuple(x) for x in (cfg.get("avoid") or [])]

    def usable(a, b):
        """Longest part of [a, b] the picture can actually show."""
        parts = [(a, b)]
        for x0, x1 in avoid:
            nxt = []
            for p0, p1 in parts:
                if x1 <= p0 or x0 >= p1:
                    nxt.append((p0, p1))
                    continue
                if x0 > p0:
                    nxt.append((p0, x0))
                if x1 < p1:
                    nxt.append((x1, p1))
            parts = nxt
        return max(parts, key=lambda q: q[1] - q[0]) if parts else None

    kept = []
    for s in sents:
        a = max(s["t"], t0)
        b = min(s["e"], t1)
        keep = usable(a, b)
        if not keep or keep[1] - keep[0] < 0.25 or is_filler(s["text"], remove):
            continue
        kept.append({"src_in": keep[0], "src_out": keep[1], "text": s["text"]})
    if not kept:
        raise SystemExit("cut plan: every sentence was removed as filler")

    # contiguous runs: keep the pause inline while it is short enough to hold
    runs = [dict(kept[0])]
    for k in kept[1:]:
        if k["src_in"] - runs[-1]["src_out"] <= max_gap:
            runs[-1]["src_out"] = max(runs[-1]["src_out"], k["src_out"])
            runs[-1]["text"] += " " + k["text"]
        else:
            runs.append(dict(k))

    # handles: keep a few frames either side of a hard cut so no word onset or
    # release is shaved; runs may not grow into each other
    pad_in = float(cfg.get("pad_in", 0.07))
    pad_out = float(cfg.get("pad_out", 0.10))
    for i, r in enumerate(runs):
        lo = runs[i - 1]["src_out"] + 0.02 if i else t0
        hi = runs[i + 1]["src_in"] - 0.02 if i + 1 < len(runs) else t1
        r["src_in"] = round(max(r["src_in"] - pad_in, min(lo, r["src_in"])), 3)
        r["src_out"] = round(min(r["src_out"] + pad_out, max(hi, r["src_out"])), 3)

    # a pad handle must never reach back into a span the picture cannot show: cut
    # handles short at the dead edge rather than smuggling two frames of wall in
    for r in runs:
        for x0, x1 in avoid:
            if x0 < r["src_in"] < x1:
                r["src_in"] = round(x1, 3)
            if x0 < r["src_out"] < x1:
                r["src_out"] = round(x0, 3)
    runs = [r for r in runs if r["src_out"] - r["src_in"] > 0.05]

    segs, out_t = [], 0.0
    for i, r in enumerate(runs):
        d = r["src_out"] - r["src_in"]
        number = bool(re.search(r"\d|\$|percent", r["text"], re.I))
        want_punch = number
        if punch_phrases:
            want_punch = any(pl in _norm(r["text"]) for pl in punch_phrases)
        seg = {"index": i, "src_in": round(r["src_in"], 3), "src_out": round(r["src_out"], 3),
               "out_in": round(out_t, 3), "out_out": round(out_t + d, 3),
               "text": r["text"].strip(), "number": number,
               "punch": bool(punch_on_number and want_punch),
               "purpose": ("punch-in on the number" if (punch_on_number and want_punch)
                           else "speaker framing")}
        segs.append(seg)
        out_t = seg["out_out"]

    total = round(out_t, 3)
    lo = float(cfg.get("min_dur", 0) or 0)
    hi = float(cfg.get("max_dur", 0) or 0)
    if hi and total > hi:                       # drop whole segments, never trim words
        while len(segs) > 1 and segs[-1]["out_out"] > hi:
            segs.pop()
        acc = 0.0
        for s in segs:
            d = s["src_out"] - s["src_in"]
            s["out_in"] = round(acc, 3)
            s["out_out"] = round(acc + d, 3)
            acc = s["out_out"]
        total = round(acc, 3)
    return {"t0": t0, "t1": t1, "segments": segs, "duration": total,
            "band": [lo, hi], "within_band": (not lo or total >= lo) and (not hi or total <= hi),
            "max_gap": max_gap}


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


def verify_tiling(plan):
    """The plan must be internally consistent: segments tile the output clock."""
    acc = 0.0
    for s in plan["segments"]:
        if abs(s["out_in"] - acc) > 0.01:
            return False
        acc = s["out_out"]
    return abs(acc - plan["duration"]) <= 0.01
