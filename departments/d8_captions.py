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
from orchestrator import store, timeline  # noqa: E402

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


def build_ass(path: Path, words, dur: float, hook: dict, brief: dict):
    cap = brief.get("captions", {})
    hk = brief.get("hook_card", {})
    brand = cap.get("brand_colour_ass", "&H0000E5FF")   # lime in ASS BGR
    maxw = int(cap.get("max_words", 3))
    hook_secs = float(hk.get("seconds", 2.8))

    ev = []
    # ---- hook card: placed in the empty band above the speaker's head, sized to
    # the frame, never over his face. The face box comes from the framing
    # department, so the card follows the actual picture instead of a guess.
    who = hook.get("who") or ""
    big = hook.get("text") or ""
    face = hook.get("face") or {}
    fs_big = int(hk.get("fontsize", 104))
    # fit the big line to 86% of the frame width (0.60 em per caps char, bold)
    while fs_big > 54 and len(big) * fs_big * 0.60 > W * 0.86:
        fs_big -= 4
    line_h = int(fs_big * 1.18)
    fs_who = int(hk.get("who_fontsize", 44))
    face_top = int((face.get("top", 0.35)) * H)
    min_y = int(hk.get("min_y", 292))
    gap_who = 14

    def fit(with_who):
        bh = line_h + ((fs_who + gap_who) if with_who else 0) + 20
        yb = face_top - 78 - line_h // 2
        return yb, bh, (yb - bh // 2) >= min_y

    y_big, block_h, ok = fit(bool(who))
    if not ok and who:
        who = ""                                    # drop the credit line, keep the hook
        y_big, block_h, ok = fit(False)
    if not ok:                                      # no room above: sit under the face
        face_bottom = int((face.get("bottom", 0.55)) * H)
        y_big = min(H - int(cap.get("margin_v", 520)) - 210, face_bottom + 34 + line_h // 2)
    y_who = y_big - line_h // 2 - fs_who // 2 - 18 if who else y_big
    if who:
        ev.append(f"Dialogue: 3,{clk(0)},{clk(hook_secs)},Who,"
                  f"{{\\an5\\pos(540,{y_who})\\move(540,{y_who + 30},540,{y_who},0,220)"
                  f"\\fad(120,220)}}{who}")
    ev.append(f"Dialogue: 4,{clk(0)},{clk(hook_secs)},Hook,"
              f"{{\\an5\\pos(540,{y_big})\\move(540,{y_big + 44},540,{y_big},0,260)"
              f"\\fad(140,240)\\t(260,420,\\fscx104\\fscy104)\\t(420,600,\\fscx100\\fscy100)}}{big}")
    bar_w = int(hk.get("bar_w", min(660, int(len(big) * fs_big * 0.58))))
    bar_y = y_big + line_h // 2 - 4
    bar = (r"{\an5\pos(540," + str(bar_y) + r")\fad(120,200)\p1}"
           + f"m 0 0 l {bar_w} 0 {bar_w} 12 0 12" + r"{\p0}")
    ev.append(f"Dialogue: 2,{clk(0.25)},{clk(hook_secs)},Bar,{bar}")
    text_w = min(int(W * 0.88), int(len(big) * fs_big * 0.60))
    hook_box = {"y_top": int(min(y_big - line_h // 2, y_who - fs_who // 2)),
                "y_bottom": int(bar_y + 12),
                "x0": int(540 - text_w // 2), "x1": int(540 + text_w // 2),
                "fontsize": fs_big, "who_shown": bool(who)}

    groups = merge_short([g for g in group_words([w for w in words if w["t"] < dur], maxw) if g])
    for gi, g in enumerate(groups):
        start = max(0.0, g[0]["t"])
        nxt = groups[gi + 1][0]["t"] if gi + 1 < len(groups) else dur
        end = min(g[-1]["e"] + .30, nxt - .03 if gi + 1 < len(groups) else dur)
        end = max(end, start + 0.35)
        parts = []
        for w in g:
            word = w["w"]
            if cap.get("highlight", True) and KEYWORD.search(word):
                parts.append(f"{{\\c{brand}&\\fscx112\\fscy112"
                             f"\\t(0,90,\\fscx100\\fscy100)}}{word}{{\\r}}")
            else:
                parts.append(word)
        ev.append(f"Dialogue: 1,{clk(start)},{clk(end)},Cap,"
                  f"{{\\fad(50,50)}}{' '.join(parts)}")

    pop = number_pop(groups, brand, dur)
    if pop and pop["start"] > hook_secs + 0.8:
        ev.append(f"Dialogue: 3,{clk(pop['start'])},{clk(min(pop['start'] + 1.6, dur))},Pop,"
                  f"{{\\an5\\pos(540,{int(cap.get('pop_y', 1090))})\\fad(90,200)"
                  f"\\t(0,140,\\fscx112\\fscy112)\\t(140,320,\\fscx100\\fscy100)}}{pop['text']}")

    path.write_text(f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,DejaVu Sans,{fs_big},&H00FFFFFF,&H00101010,&H00000000,1,0,0,0,100,100,0,0,3,14,0,5,60,60,0,1
Style: Who,DejaVu Sans,{hk.get('who_fontsize', 46)},&H0000E5FF,&H00101010,&H00000000,1,0,0,0,100,100,2,0,3,10,0,5,60,60,0,1
Style: Bar,DejaVu Sans,10,&H0000E5FF,&H0000E5FF,&H0000E5FF,1,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1
Style: Pop,DejaVu Sans,{cap.get('pop_fontsize', 96)},&H0000E5FF,&H00101010,&H00000000,1,0,0,0,100,100,1,0,3,10,0,5,50,50,0,1
Style: Cap,DejaVu Sans,{cap.get('fontsize', 74)},&H00FFFFFF,&H00101010,&H44000000,1,0,0,0,100,100,0,0,1,5,3,2,50,50,{cap.get('margin_v', 560)},1
[Events]
Format: Layer, Start, End, Style, Text
""" + "\n".join(ev) + "\n", encoding="utf8")
    return {"events": len(ev), "groups": len(groups), "pop": pop,
            "hook_box": hook_box, "face_box": face}


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

    picture = store.path(cid, f"render/{clip}_picture.mp4")
    audio = store.path(cid, f"render/{clip}_audio.m4a")
    ass = store.path(cid, f"work/{clip}.ass")
    info = build_ass(ass, words, dur, hook, brief)
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
    fc = (f"[2:v]scale={wm_w}:-1[wm];"
          f"[0:v][wm]overlay={wm_x}:{wm_y}:format=auto[v0];"
          f"[v0]ass={ass.as_posix()},"
          f"eq=contrast={grade.get('contrast', 1.07)}:saturation={grade.get('saturation', 1.12)}"
          f":brightness={grade.get('brightness', 0.01)},"
          f"vignette=angle=PI/{grade.get('vignette', 7)},setsar=1[v]")

    out = store.path(cid, f"clips/{clip}.mp4")
    subprocess.run([FF, "-nostdin", "-v", "error", "-y",
                    "-i", str(picture), "-i", str(audio), "-i", str(wm),
                    "-filter_complex", fc,
                    "-map", "[v]", "-map", "1:a", "-t", f"{dur:.3f}",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                    "-pix_fmt", "yuv420p", "-r", str(fps),
                    "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)],
                   check=True)
    store.gate(cid, clip, "RENDER_COMPLETE", out.exists() and out.stat().st_size > 0, str(out))
    print(json.dumps({"clip": clip, "output": str(out), "duration": dur,
                      "caption_groups": info["groups"], "hook": hook,
                      "number_pop": info["pop"],
                      "size_mb": round(out.stat().st_size / 1e6, 1)}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
