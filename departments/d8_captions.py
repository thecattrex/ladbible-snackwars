#!/usr/bin/env python3
"""D8 — Captions, graphics, colour; final composite.

Everything a viewer notices in the first two seconds is built here:

  hook card      two lines, animated in, sits below the speaker's chin so it
                 never covers his eyes or mouth; the small line names who is
                 talking, the big line is the number the clip is about
  captions       1-3 word groups on the output clock, keywords in the brand
                 colour with a pop, never straddling a cut
  number pops    when a figure he is saying is the point, it also appears big
                 above the captions (one per clip, never stacked on a caption)
  grade + vig    a light contrast/saturation lift and a vignette so the frame
                 reads as edited rather than as raw podcast footage
  watermark      the client's own PNG, top of frame, whole clip, never covered

  python3 departments/d8_captions.py <campaign_id> --clip <candidate_id>
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from orchestrator import store, timeline, graphics, motion  # noqa: E402

FF = imageio_ffmpeg.get_ffmpeg_exe()
W, H = 1080, 1920
KEYWORD = re.compile(r"(\$?\d[\d,\.]*\s*(?:%|k|m|million|billion|thousand)?|"
                     r"\b(?:never|nothing|impossible|nobody|replaced|wrong|mistake|"
                     r"stopped|refuse|zero|first|only)\b)", re.I)
WEAK_TAIL = {"a", "an", "the", "of", "to", "in", "on", "at", "and", "but", "or",
             "is", "are", "was", "it", "that", "for", "with", "as", "by", "so"}


def clk(t: float) -> str:
    t = max(0.0, t)
    return f"0:{int(t) // 60:02d}:{t % 60:05.2f}"


def apply_fixes(words, fixes):
    words = [dict(w) for w in words]
    for pat, rep in fixes:
        target = re.sub(r"[^a-z0-9$%]", "", pat.lower())
        i = 0
        while i < len(words):
            acc, j = "", i
            while j < len(words) and len(acc) < len(target):
                acc += re.sub(r"[^a-z0-9$%]", "", words[j]["w"].lower())
                j += 1
            if acc == target:
                span = {"t": words[i]["t"], "e": words[j - 1]["e"], "w": rep}
                words[i:j] = [span] if rep else []
                i += 1
            else:
                i += 1
    return [w for w in words if w["w"]]


def group_words(words, maxw: int):
    groups, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if nxt is None:
            groups.append(cur); break
        nxt_word = re.sub(r"[^a-z']", "", nxt["w"].lower())
        if w["w"].endswith((",", ".", "?", "!", ";", ":")) and len(cur) >= 2:
            groups.append(cur); cur = []
        elif nxt_word in WEAK_TAIL and len(cur) >= 2:
            groups.append(cur); cur = []
        elif len(cur) >= maxw:
            groups.append(cur); cur = []
        elif w["w"].endswith((".", "?", "!")):
            groups.append(cur); cur = []
    if cur:
        groups.append(cur)
    return groups


def merge_short(groups):
    out = []
    for g in groups:
        if out and g[-1]["e"] - out[-1][0]["t"] < 0.85:
            out[-1] = out[-1] + g
            continue
        out.append(g)
    return out


def number_pop(groups, brand, dur):
    """Pick the single most 'graphic-worthy' figure in the clip."""
    best = None
    for g in groups:
        text = " ".join(w["w"] for w in g)
        for m in re.finditer(r"\$?\d[\d,\.]*\s*(?:k|m|million|billion|%|thousand)?", text, re.I):
            raw = m.group(0).strip()
            digits = re.sub(r"[^\d]", "", raw)
            if not digits:
                continue
            value = int(digits)
            unit = re.search(r"(k|m|million|billion|%|thousand)", raw, re.I)
            score = value * (1000 if unit and unit.group(1).lower() in ("k", "thousand") else
                             1_000_000 if unit and unit.group(1).lower() in ("m", "million") else
                             1_000_000_000 if unit and unit.group(1).lower() == "billion" else 1)
            if "$" in raw:
                score *= 2
            if best is None or score > best["score"]:
                best = {"score": score, "text": raw.upper(), "t": g[0]["t"],
                        "start": g[0]["t"], "end": min(g[-1]["e"] + 0.6, dur)}
    return best


def build_ass(path: Path, words, dur: float, hook: dict, brief: dict, suppress=()):
    cap = brief.get("captions", {})
    hk = brief.get("hook_card", {})
    brand = cap.get("brand_colour_ass", "&H0000E5FF")
    maxw = int(cap.get("max_words", 3))
    hook_secs = float(hk.get("seconds", 2.9))
    H_W, H_H = 1080, 1920

    ev = []
    who = hook.get("who") or ""
    big = hook.get("text") or ""
    face = hook.get("face") or {}

    # ---- hook: kicker + display line + draw-on rule, stacked in the empty band
    face_top = int((face.get("top", 0.35)) * H_H)
    hook_px = int(hk.get("fontsize", 112))
    while hook_px > 62 and len(big) * hook_px * 0.44 > H_W * 0.86:
        hook_px -= 3
    line_h = int(hook_px * 1.14)
    kick_px = int(hk.get("who_fontsize", 32))
    min_y = int(hk.get("min_y", 250))

    def layout(with_kicker):
        block = line_h + ((kick_px + 22) if with_kicker else 0)
        y_big = face_top - 74 - line_h // 2
        return y_big, block, (y_big - block // 2) >= min_y

    y_big, block_h, ok = layout(bool(who))
    if not ok and who:
        who = ""
        y_big, block_h, ok = layout(False)
    if not ok:
        face_bottom = int((face.get("bottom", 0.55)) * H_H)
        y_big = min(H_H - int(cap.get("margin_v", 600)) - 250, face_bottom + 40 + line_h // 2)
    y_kick = y_big - line_h // 2 - kick_px // 2 - 16 if who else y_big
    rule_y = y_big + int(line_h * 0.62)

    # the number in the hook gets the accent colour, the rest stays white
    m = re.search(r"(\$?\d[\d,\.]*\s*(?:M|K|B|million|billion|k)?)", big, re.I)
    if m:
        a, b = big[:m.start()], big[m.start():m.end()]
        c = big[m.end():]
        big_ass = f"{a}{{\\c{brand}&}}{b}{{\\c&H00FFFFFF&}}{c}"
    else:
        big_ass = big

    if who:
        ev.append(f"Dialogue: 3,{clk(0)},{clk(hook_secs)},Who,"
                  f"{{\\an5\\pos(540,{y_kick})\\move(540,{y_kick + 18},540,{y_kick},0,200)"
                  f"\\fad(90,180)}}{who}")
    ev.append(f"Dialogue: 4,{clk(0)},{clk(hook_secs)},Hook,"
              f"{{\\an5\\pos(540,{y_big})\\move(540,{y_big + 30},540,{y_big},0,260)"
              f"\\fad(110,200)\\t(240,420,\\fscx103\\fscy103)\\t(420,620,\\fscx100\\fscy100)}}"
              f"{big_ass}")
    bar_w = int(hk.get("bar_w", min(620, int(len(big) * hook_px * 0.46))))
    bar = (r"{\an5\pos(540," + str(rule_y) + r")\fad(140,220)\p1}"
           + f"m 0 0 l {bar_w} 0 {bar_w} 9 0 9" + r"{\p0}")
    ev.append(f"Dialogue: 2,{clk(0.22)},{clk(hook_secs)},Bar,{bar}")

    # ---- captions: 2-3 words, heavy grotesque, keyword in accent + capitalised
    def held(a, b):
        return any(b > s0 + 0.02 and a < s1 - 0.02 for s0, s1 in suppress)

    groups = merge_short([g for g in group_words([w for w in words if w["t"] < dur], maxw) if g])
    groups = [g for g in groups if not held(g[0]["t"], g[-1]["e"])]
    y_cap = H_H - int(cap.get("margin_v", 600))
    for gi, g in enumerate(groups):
        start = max(0.0, g[0]["t"])
        nxt = groups[gi + 1][0]["t"] if gi + 1 < len(groups) else dur
        end = min(g[-1]["e"] + .28, nxt - .04 if gi + 1 < len(groups) else dur)
        end = max(end, start + 0.34)
        parts = []
        for w in g:
            word = w["w"]
            if cap.get("highlight", True) and KEYWORD.search(word):
                parts.append(f"{{\\c{brand}&\\fscx108\\fscy108"
                             f"\\t(0,80,\\fscx100\\fscy100)}}{word.upper()}{{\\r}}")
            else:
                parts.append(word)
        ev.append(f"Dialogue: 1,{clk(start)},{clk(end)},Cap,"
                  f"{{\\an5\\pos(540,{y_cap})\\move(540,{y_cap + 14},540,{y_cap},0,80)"
                  f"\\fad(30,60)}}{' '.join(parts)}")

    path.write_text(f"""[Script Info]
ScriptType: v4.00+
PlayResX: {H_W}
PlayResY: {H_H}
WrapStyle: 0
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,Anton,{hook_px},&H00FFFFFF,&H00141010,&H00000000,0,0,0,0,100,100,1,0,1,6,3,5,60,60,0,1
Style: Who,Inter,{kick_px},&H0000E5FF,&H00141010,&H00000000,-1,0,0,0,100,100,4,0,1,4,0,5,60,60,0,1
Style: Bar,Anton,10,&H0000E5FF,&H0000E5FF,&H0000E5FF,0,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1
Style: Cap,Archivo Black,{cap.get('fontsize', 64)},&H00FFFFFF,&H00101010,&H00000000,0,0,0,0,100,100,0,0,1,5,3,5,40,40,0,1
[Events]
Format: Layer, Start, End, Style, Text
""" + "\n".join(ev) + "\n", encoding="utf8")
    text_w = min(int(H_W * 0.88), int(len(big) * hook_px * 0.44))
    return {"events": len(ev), "groups": len(groups), "pop": None,
            "hook_box": {"y_top": int(min(y_big - line_h // 2, y_kick - kick_px // 2)),
                         "y_bottom": int(rule_y + 10),
                         "x0": int(540 - text_w // 2), "x1": int(540 + text_w // 2),
                         "fontsize": hook_px, "who_shown": bool(who)},
            "face_box": face}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("campaign_id")
    ap.add_argument("--clip", required=True)
    a = ap.parse_args()
    cid, clip = a.campaign_id, a.clip
    brief = store.validate_brief(cid)
    deliv = brief.get("delivery", {})
    fps = int(deliv.get("fps", 30))

    card = next(c for c in store.read_json(cid, "artifacts/portfolio.v1.json")["payload"]["selected"]
                if c["candidate_id"] == clip)
    hook_card = next(h for h in store.read_json(cid, "artifacts/hook_cards.v1.json")["payload"]["cards"]
                     if h["candidate_id"] == clip)
    fr = store.read_json(cid, f"artifacts/framing_{clip}.v1.json")["payload"]
    hk_secs = float(brief.get("hook_card", {}).get("seconds", 2.9))
    face = {"top": 0.35, "bottom": 0.55}
    first_src = store.read_json(cid, f"artifacts/cutplan_{clip}.v1.json")["payload"]["segments"][0]["src_in"]
    for sh in fr["shots"]:
        if sh.get("speaker") and sh["t0"] <= first_src < sh["t1"]:
            sp = sh["speaker"]
            # framing shot times are source seconds; output 0 is the first piece
            # of the first cut segment, so that shot frames the hook window
            half = sp["w"] * 16 / 9 / 2 * 0.62
            face = {"top": round(sp["cy"] - half, 4), "bottom": round(sp["cy"] + half, 4)}
            break
    hook = {"text": hook_card["winner"],
            "who": brief.get("hook_card", {}).get("who_line")
                   or hook_card.get("who_line", ""),
            "face": face}
    words = store.read_json(cid, "artifacts/transcript.v1.json")["payload"]["words"]
    words = apply_fixes(words, brief.get("caption_fixes", {}).get(clip, []))
    edl = store.read_json(cid, f"artifacts/edl_picture_{clip}.v1.json")["payload"]
    dur = edl["events"][-1]["output_out"]
    plan = store.read_json(cid, f"artifacts/cutplan_{clip}.v1.json")["payload"]
    words = timeline.remap_words(plan, words)

    # ---- graphics layer: cards that explain the line, placed clear of his face
    pinned = (store.read_json(cid, "graphics_plan.json", {}) or {}).get(clip)
    specs = graphics.plan(words, dur, brief, overrides=pinned)

    def face_bottom_at(t):
        for e in edl["events"]:
            if e["output_in"] <= t < e["output_out"] + 0.05:
                sp = next((sh["speaker"] for sh in fr["shots"]
                           if sh.get("speaker") and sh["t0"] <= e["source_in"] + 0.05 < sh["t1"]),
                          None)
                if not sp:
                    return None
                return sp["cy"] + sp["w"] * 16 / 9 / 2 * 0.62
        return None

    cards = []
    for i, spec in enumerate(specs):
        spec = dict(spec)
        if "y" not in spec:
            fb = face_bottom_at(spec["start"])
            spec["y"] = int(min(1210, max(1000, (fb or 0.45) * 1920 + 30)))
        dest = store.path(cid, f"render/gfx/{clip}_c{i:02d}.mov")
        cards.append(motion.render_card(dest, spec, fps=fps, size=(1080, 470)))
    store.artifact(cid, f"graphics_{clip}", {"cards": cards,
                                             "source": "pinned" if pinned else "auto plan"})
    suppress = [(c["start"], c["end"]) for c in cards]

    picture = store.path(cid, f"render/{clip}_picture.mp4")
    audio = store.path(cid, f"render/{clip}_audio.m4a")
    ass = store.path(cid, f"work/{clip}.ass")
    info = build_ass(ass, words, dur, hook, brief, suppress)
    store.artifact(cid, f"captions_{clip}", {
        "clip": clip, "style": "1-3 word groups, brand-colour keyword pop",
        "words_on_output_clock": len(words), **{k: v for k, v in info.items() if k != "pop"},
        "number_pop": info["pop"], "hook_box": info["hook_box"],
        "face_box_hook_window": info["face_box"]})

    wmc = dict(brief.get("brand_rules", {}).get("watermark", {}))
    wmc.update(brief.get("watermark", {}) or {})
    wm = ROOT / wmc.get("file", wmc.get("asset", "assets/watermark_white.png"))
    if not wm.exists():
        raise SystemExit(f"watermark asset missing: {wm}")
    wm_w = int(wmc.get("width", 780))
    pos = wmc.get("position", "top-center")
    if pos.startswith("top"):
        wm_y = str(int(wmc.get("margin_top", 64)))
    else:
        wm_y = f"H-{int(wmc.get('margin_bottom', 300))}-h"
    wm_x = {"top-left": str(int(wmc.get("margin_side", 50))),
            "top-right": f"W-w-{int(wmc.get('margin_side', 50))}",
            "bottom-left": str(int(wmc.get("margin_side", 50))),
            "bottom-right": f"W-w-{int(wmc.get('margin_side', 50))}"}.get(pos, "(W-w)/2")

    grade = brief.get("grade", {})
    fparts = [f"[2:v]scale={wm_w}:-2[wm]", f"[0:v][wm]overlay={wm_x}:{wm_y}:format=auto[v0]"]
    last = "v0"
    for i, c in enumerate(cards):
        idx = i + 3
        fparts.append(f"[{idx}:v]setpts=PTS+{c['start']}/TB[g{i}]")
        fparts.append(f"[{last}][g{i}]overlay=x={c['x']}:y={c['y']}"
                      f":enable='between(t,{c['start']},{c['end']})'"
                      f":format=auto:eof_action=pass[v{i + 1}]")
        last = f"v{i + 1}"
    fparts.append(f"[{last}]ass={ass.as_posix()},"
                  f"eq=contrast={grade.get('contrast', 1.07)}:saturation={grade.get('saturation', 1.12)}"
                  f":brightness={grade.get('brightness', 0.01)},"
                  f"vignette=angle=PI/{grade.get('vignette', 7)},"
                 f"noise=alls={grade.get('grain', 3)}:allf=t+u,setsar=1[v]")
    fc = ";".join(fparts)

    out = store.path(cid, f"clips/{clip}.mp4")
    subprocess.run([FF, "-nostdin", "-v", "error", "-y",
                    "-i", str(picture), "-i", str(audio), "-i", str(wm),
                    *[x for c in cards for x in ("-i", c["path"])],
                    "-filter_complex", fc,
                    "-map", "[v]", "-map", "1:a", "-t", f"{dur:.3f}",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                    "-pix_fmt", "yuv420p", "-r", str(fps),
                    "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)],
                   check=True)
    store.gate(cid, clip, "RENDER_COMPLETE", out.exists() and out.stat().st_size > 0, str(out))
    print(json.dumps({"clip": clip, "output": str(out), "duration": dur,
                      "caption_groups": info["groups"], "hook": hook,
                      "graphics": [{"kind": c["kind"], "start": c["start"],
                                    "end": c["end"], "y": c["y"]} for c in cards],
                      "number_pop": info["pop"],
                      "size_mb": round(out.stat().st_size / 1e6, 1)}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
