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


SUFFIX_UNITS = {",000": 1_000, "k": 1_000, "thousand": 1_000, "m": 1_000_000,
                "million": 1_000_000, "billion": 1_000_000_000}


def spoken_numbers(words, dur):
    """Numbers on the output clock, parsed the way people actually say them.

    Transcription splits "$30,000" into "$30" + ",000" and "4 million" into two
    tokens, so a number is read across neighbouring words instead of per word;
    otherwise the strongest figure in a clip is silently dropped.
    """
    out = []
    i, n = 0, len(words)
    while i < n:
        w = words[i]
        raw = w["w"]
        if not re.search(r"\d", raw):
            i += 1
            continue
        m = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*([kKmM]\b|thousand|million|billion|%)?", raw)
        if not m:
            i += 1
            continue
        value = float(m.group(1).replace(",", ""))
        inline = (m.group(2) or "").lower().rstrip(".")
        if inline in ("k", "thousand"):
            value *= 1_000
        elif inline in ("m", "million"):
            value *= 1_000_000
        elif inline == "billion":
            value *= 1_000_000_000
        currency = "$" in raw or bool(re.search(r"dollar", raw, re.I))
        percent = "%" in raw or "percent" in raw.lower()
        text = raw
        j = i
        # absorb a split thousands group or a spoken magnitude
        while j + 1 < n and j - i < 2 and (words[j + 1]["t"] - words[j]["e"]) < 0.5:
            nxt = words[j + 1]["w"]
            key = nxt.lower().strip(".,")
            if re.fullmatch(r",\d{3}", nxt.strip(".")):
                value = value * 1000 + float(nxt.strip(".,")[1:])
                text += nxt
                j += 1
                continue
            if key in SUFFIX_UNITS:
                value *= SUFFIX_UNITS[key]
                text += " " + nxt
                j += 1
                continue
            if key in ("%", "percent"):
                percent = True
                text += " " + nxt
                j += 1
                continue
            break
        if value < 100 and not (percent or currency):
            ctx = " ".join(x["w"] for x in words[max(0, i - 1):j + 2]).lower()
            if not re.search(r"percent|%|million|thousand|people|dollars|k\b", ctx):
                i = j + 1
                continue
        ctx = " ".join(x["w"] for x in words[max(0, i - 2):j + 3])
        out.append({"t": w["t"], "end": words[j]["e"], "value": value, "raw": text.strip(),
                    "currency": currency, "percent": percent, "ctx": ctx,
                    "i0": i, "i1": j})
        i = j + 1
    return [x for x in out if x["t"] < dur]


def sentences(words):
    """Split the output-clock word list into sentences (punctuation or a pause)."""
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        gap = (words[i + 1]["t"] - w["e"]) if i + 1 < len(words) else 1.0
        if w["w"][-1:] in ".?!" or gap > 0.55 or len(cur) >= 18:
            out.append({"t": cur[0]["t"], "e": cur[-1]["e"],
                        "text": " ".join(x["w"] for x in cur), "words": list(cur)})
            cur = []
    if cur:
        out.append({"t": cur[0]["t"], "e": cur[-1]["e"],
                    "text": " ".join(x["w"] for x in cur), "words": list(cur)})
    return out


FILLER = {"like", "yeah", "so", "and", "just", "really", "actually", "basically", "okay",
          "well", "uh", "um", "you", "know", "i", "we", "it", "that", "the", "a", "an"}


def _clean(s: str) -> str:
    return " ".join(w for w in s.replace("\n", " ").split() if w.strip())


def _short(s: str, max_chars: int = 58) -> str:
    s = _clean(s).strip(" ,.-")
    if len(s) <= max_chars:
        return s
    cut = s[:max_chars].rsplit(" ", 1)[0]
    return cut.rstrip(" ,.-")


UNIT_WORDS = ("week", "month", "year", "day", "person", "head", "team", "user",
              "customer", "employee", "minute", "hour", "night")


def _unit_kicker(sentence_words, i1: int) -> str:
    """'in a week' / 'per person' -> 'PER WEEK' / 'PER PERSON'; else ''."""
    tail = " ".join(w["w"] for w in sentence_words[i1 + 1:i1 + 5]).lower()
    for u in UNIT_WORDS:
        if re.search(r"\b(?:in|a|an|per|each|every|one)\b\W*" + u, tail) or \
           re.search(r"\b" + u + r"\b", tail):
            return "PER " + u.upper()
    return ""


TOPICS = (
    (r"spend|spending|cost|costs|bill|burn|burned|burning", "THE SPEND"),
    (r"usage|consume|consumption|using|used|tokens", "THE USAGE"),
    (r"revenue|arr|sales|turnover|mrr", "THE REVENUE"),
    (r"deal|contract|signed|closed", "THE DEAL"),
    (r"raise|raised|round|seed|invest|funding", "THE RAISE"),
    (r"people|person|team|head|employee|hire|hired|staff", "THE TEAM"),
    (r"retention|churn|conversion|resolution|rate|percent|%", "THE RATE"),
    (r"valuation|valued|worth|billion dollars", "THE VALUATION"),
    (r"users|customers|subscribers|accounts", "THE BASE"),
    (r"prompt|prompts|token|tokens|image references", "THE WORK"),
    (r"content|footage|hours|minutes|video|drama", "THE OUTPUT"),
)


def _topic(ctx: str) -> str:
    """Name the figure from the words around it, never from a campaign template."""
    low = " " + ctx.lower() + " "
    for rx, name in TOPICS:
        if re.search(rx, low):
            return name
    return ""


def _label_after(sentence_words, i, take: int = 4) -> str:
    """The few words after a number are what give it a unit: 'in a week', 'per person'."""
    tail = []
    for w in sentence_words[i + 1:i + 1 + take]:
        if w["w"][-1:] in ".?!":
            break
        tail.append(w["w"])
    return " ".join(tail).strip(" ,.")


def _label_before(sentence_words, i, take: int = 3) -> str:
    head = [w["w"] for w in sentence_words[max(0, i - take):i]
            if w["w"].lower().strip(" ,.") not in FILLER]
    return " ".join(head).strip(" ,.")


def plan(words, dur, brief, face_at=None, overrides=None) -> list[dict]:
    """Return card specs: type, window, params, placement.

    The labels are built from the words actually spoken around the number, never
    from a campaign-wide template: twenty clips that all say "internal AI spend"
    read as one machine output, which is exactly what the client rejected.
    """
    if overrides:
        return overrides

    hk = float(brief.get("hook_card", {}).get("seconds", 2.9))
    nums = spoken_numbers(words, dur)
    sents = sentences(words)
    specs = []
    taken = []                          # cards may not enter the hook window
    gap = float(brief.get("graphics", {}).get("gap_seconds", 0.8))
    max_cards = int(brief.get("graphics", {}).get("max_cards", 5))

    def free(a, b):
        if a < 1.2:                      # never in the first breath of the clip
            return False
        return all(b + gap <= t0 or a >= t1 + gap for t0, t1 in taken)

    def place(start, length):
        start = max(hk + 0.2, start)
        if start + length > dur - 0.15:          # a line spoken at the tail: pull the card back
            start = max(1.2, dur - 0.15 - length)
        end = min(dur - 0.15, start + length)
        return round(start, 2), round(end, 2)

    # ---- 1. numbers, strongest first
    def weight(n):
        ctx = n["ctx"].lower()
        w = 0
        if n["value"] >= 1_000_000:
            w += 4
        elif n["value"] >= 1_000:
            w += 3
        if n["percent"]:
            w += 3
        if re.search(r"people|person|team|head|engineer|creative", ctx):
            w += 2
        if re.search(r"week|month|year|day", ctx):
            w += 1
        return w

    # one card per distinct figure: the same number repeated three times in a clip
    # is the clearest sign that a machine chose the graphics
    seen_vals, unique = set(), []
    for n in sorted(nums, key=lambda x: -weight(x)):
        key = round(n["value"])
        if key in seen_vals:
            continue
        seen_vals.add(key)
        unique.append(n)

    for n in unique[:5]:
        if n["t"] < 0.5:                  # the clip opens mid-sentence: the figure is cut
            continue
        start, end = place(max(n["t"] - 0.30, hk + 0.05), 2.8)
        if end - start < CARD_MIN or not free(start, end):
            continue
        sent = next((x for x in sents if x["t"] - 0.25 <= n["t"] <= x["e"]), None)
        sw = sent["words"] if sent else []
        i1 = next((k for k, w in enumerate(sw) if abs(w["t"] - n["t"]) < 0.02), None)
        kick = _unit_kicker(sw, i1) if i1 is not None else ""
        note = _short(sent["text"] if sent else "", 56)
        ctx = n["ctx"].lower()
        v = n["value"]
        after = " ".join(w["w"] for w in sw[(i1 or 0) + 1:(i1 or 0) + 3]).lower() if sw else ""
        counted = re.search(r"people|person|team|head|engineer|employee", ctx) and \
            not n["currency"] and not re.match(r"(per|a|an|each|every)\b", after.strip())
        if counted and 20 <= v <= 200_000:
            spec = {"type": "people", "start": start, "end": end,
                    "label": f"{int(v)} people",
                    "params": {"total": int(v), "label": kick.replace("PER ", "PER ") or "THE TEAM",
                               "sub": note}}
        elif n["percent"] or re.search(r"percent|churn|retention", ctx):
            if any(s2["params"].get("label") in ("THE RATE",) for s2 in specs):
                spec_label = "THE SHARE"
            else:
                spec_label = "THE RATE"
            spec = {"type": "counter", "start": start, "end": end, "label": f"{v:g}%",
                    "params": {"label": spec_label, "value": v, "unit": "%",
                               "currency": False, "accent_note": note}}
        elif v >= 1_000:
            money = n["currency"] or bool(re.search(r"spend|cost|pay|price|revenue|\$", ctx))
            used = {s2["params"].get("label") for s2 in specs}
            label = kick or _topic(ctx) or ("THE SPEND" if money else "THE NUMBER")
            if label in used:                 # a clip should not wear the same label twice
                label = next((alt for alt in (kick, "THE SPEND", "THE NUMBER",
                                              "THE FIGURE") if alt and alt not in used), label)
            spec = {"type": "counter", "start": start, "end": end,
                    "label": f"{v:,.0f}",
                    "params": {"label": label,
                               "value": v, "unit": kick.replace("PER ", "/").lower() if kick else "",
                               "currency": money, "accent_note": note}}
        else:
            continue
        specs.append(spec)
        taken.append((spec["start"], spec["end"]))

    # ---- 2. one question, if the clip asks one in its first half
    WH_TAIL = {"what", "which", "who", "how", "why", "when", "was", "is", "it"}

    def is_question(x):
        t = _clean(x["text"])
        ws = t.split()
        if not 4 <= len(ws) <= 14:
            return False
        if "?" in t:
            return ws[-1].lower().strip("?,.") not in WH_TAIL
        return bool(re.match(r"^(how much|how many|how do|what do|what is|what was|why do|why is|"
                             r"did you|do you|would you|could you|are you)\b", t, re.I))

    q = next((x for x in sents if is_question(x) and x["t"] < dur * 0.6), None)
    if q and len(specs) < max_cards:
        start, end = place(q["t"] - 0.15, min(3.2, max(2.7, q["e"] - q["t"] + 0.4)))
        if end - start >= CARD_MIN and free(start, end):
            ws = [w["w"] for w in q["words"]]
            split = max(2, int(len(ws) * 0.45))
            specs.append({"type": "chip", "start": start, "end": end,
                          "label": "the question",
                          "params": {"label": _short(" ".join(ws[:split]), 34),
                                     "sub": _short(" ".join(ws[split:]), 40)}})
            taken.append((start, end))

    # ---- 3. one statement card on the line that actually carries the point
    KEY = re.compile(r"because|we learned|the reason|biggest|mistake|instead|"
                     r"turned out|net positive|the point|what happened|"
                     r"nobody|everyone|never|always|crazy|insane", re.I)
    def usable_statement(x):
        t = _clean(x["text"])
        ws = t.split()
        if not 5 <= len(ws) <= 16 or x["e"] - x["t"] < 1.2:
            return False
        if any(a.lower() == b.lower().rstrip(".,") for a, b in zip(ws, ws[1:])):
            return False                       # "what we What we learned" is not a quote
        return bool(KEY.search(t))

    st = next((x for x in reversed(sents) if usable_statement(x)), None)
    if not st:                            # no flagged line: take the clip's longest clean one
        cand = [x for x in sents if x["t"] > 0.4 and 6 <= len(_clean(x["text"]).split()) <= 16
                and not any(a.lower() == b.lower().rstrip(".,")
                            for a, b in zip(_clean(x["text"]).split(), _clean(x["text"]).split()[1:]))]
        st = max(cand, key=lambda x: x["e"] - x["t"]) if cand else None
    if st and len(specs) < max_cards:
        start, end = place(st["t"] - 0.15, min(3.3, max(2.7, st["e"] - st["t"] + 0.3)))
        if end - start >= CARD_MIN and free(start, end):
            line = re.sub(r"^(and|but|so|look|i mean|well|yeah)[ ,]+", "",
                          _clean(st["text"]), flags=re.I)
            specs.append({"type": "quote", "start": start, "end": end,
                          "label": "the point",
                          "params": {"text_line": _short(line, 54), "who": ""}})
            taken.append((start, end))

    # ---- 4. a clip with nothing numeric still earns one card: the strongest question
    if not specs:
        q2 = next((x for x in sents if is_question(x)), None)
        if q2:
            start, end = place(q2["t"] - 0.15, 3.0)
            if end - start >= CARD_MIN:
                ws = [w["w"] for w in q2["words"]]
                split = max(2, int(len(ws) * 0.45))
                specs.append({"type": "chip", "start": start, "end": end, "label": "the question",
                              "params": {"label": _short(" ".join(ws[:split]), 34),
                                         "sub": _short(" ".join(ws[split:]), 40)}})

    specs.sort(key=lambda s: s["start"])
    specs = specs[:max_cards]
    for s in specs:
        y = 990
        if face_at:
            fb = face_at(s["start"])
            if fb:
                y = int(min(1180, max(980, fb * 1920 + 26)))
        s["y"] = y
    return specs
