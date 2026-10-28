#!/usr/bin/env python3
"""Graphics plan — decide which card explains which line, and where it sits.

The rule from the retention research is "graphics on the lines that earn it",
not carpet-bombing: a card appears on a number or a comparison, lasts ~3 s,
never covers the speaker's face, never collides with another card, and captions
are held back while it is on screen so the frame stays readable.

An editor can pin the plan per clip in state/<cid>/graphics_plan.json.
"""
from __future__ import annotations

import json
import re

CARD_MIN, CARD_MAX = 2.6, 3.8


def _num_value(raw: str) -> float:
    s = raw.replace(",", "").replace("$", "").lower()
    m = re.search(r"([\d.]+)\s*(k|m|million|billion|thousand)?", s)
    if not m:
        return 0.0
    v = float(m.group(1))
    unit = (m.group(2) or "").lower()
    if unit in ("k", "thousand"):
        v *= 1_000
    elif unit in ("m", "million"):
        v *= 1_000_000
    elif unit == "billion":
        v *= 1_000_000_000
    return v


def spoken_numbers(words, dur):
    """Numbers on the output clock, with the words that surround them."""
    out = []
    for i, w in enumerate(words):
        raw = w["w"]
        if not re.search(r"\d", raw):
            continue
        v = _num_value(raw)
        if v < 100:                                  # '2', '20' alone is rarely the point
            # allow small numbers only when they carry a unit word next to them
            ctx = " ".join(x["w"] for x in words[max(0, i - 1):i + 2]).lower()
            if not re.search(r"percent|%|million|thousand|people|dollars|k\b", ctx):
                continue
        ctx = " ".join(x["w"] for x in words[max(0, i - 2):i + 3])
        out.append({"t": w["t"], "end": w["e"], "value": v, "raw": raw, "ctx": ctx})
    # merge "4" + "million"
    merged = []
    for n in out:
        if merged and n["t"] - merged[-1]["end"] < 0.35:
            prev = merged[-1]
            combo = f"{prev['raw']} {n['raw']}"
            if re.search(r"million|thousand|k\b|%|billion", n["raw"], re.I):
                prev["value"] = _num_value(combo)
                prev["raw"] = combo
                prev["end"] = n["end"]
                prev["ctx"] += " " + n["ctx"]
                continue
        merged.append(dict(n))
    return [n for n in merged if n["t"] < dur]


def plan(words, dur, brief, face_at=None, overrides=None) -> list[dict]:
    """Return card specs: type, window, params, placement."""
    if overrides:
        return overrides

    hk = float(brief.get("hook_card", {}).get("seconds", 2.9))
    nums = spoken_numbers(words, dur)
    specs = []
    taken = [(0.0, hk + 0.15)]            # the hook owns the opening

    def free(a, b):
        return all(b <= t0 or a >= t1 for t0, t1 in taken)

    for n in nums:
        start = max(hk + 0.2, n["t"] - 0.25)
        length = min(CARD_MAX, max(CARD_MIN, 3.0))
        end = min(dur - 0.1, start + length)
        if end - start < CARD_MIN or not free(start, end):
            continue
        ctx = n["ctx"].lower()
        v = n["value"]
        if re.search(r"people|person|team|head", ctx) and 50 <= v <= 100_000:
            spec = {"type": "people", "start": round(start, 2), "end": round(end, 2),
                    "label": f"{int(v)} people",
                    "params": {"total": int(v), "label": "the team",
                               "sub": "at Higgsfield, split US + Asia"}}
        elif v >= 1_000:
            spec = {"type": "counter", "start": round(start, 2), "end": round(end, 2),
                    "label": f"${v:,.0f}",
                    "params": {"label": "internal AI spend", "value": v, "unit": "/ month",
                               "currency": True, "accent_note": "on models, every month"}}
        else:
            continue
        specs.append(spec)
        taken.append((spec["start"], spec["end"]))

    # a closing maths card when the clip states a big number, a headcount and a
    # per-head figure: it is the clearest way to land the takeaway
    big = next((s for s in specs if s["type"] == "counter"), None)
    ppl = next((s for s in specs if s["type"] == "people"), None)
    per_head = next((n for n in nums if 1_000 <= n["value"] <= 100_000
                     and n not in [x for x in nums if x["value"] >= 1_000_000]), None)
    if big and ppl and dur - 3.4 > max(s["end"] for s in specs):
        total = big["params"]["value"]
        count = ppl["params"]["total"]
        each = per_head["value"] if per_head else round(total / count, -2)
        start = round(max(s["end"] for s in specs) + 0.25, 2)
        end = round(min(dur - 0.15, start + 3.4), 2)
        if free(start, end) and end - start >= CARD_MIN:
            specs.append({"type": "math", "start": start, "end": end, "label": "the maths",
                          "params": {"left": f"${total:,.0f}", "right": f"{count:,}",
                                     "result": f"${each:,.0f}", "label": "what it works out to"}})

    specs.sort(key=lambda s: s["start"])
    for s in specs:
        y = 1080
        if face_at:
            fb = face_at(s["start"])
            if fb:
                y = int(min(1180, max(980, fb * 1920 + 26)))
        s["y"] = y
    return specs
