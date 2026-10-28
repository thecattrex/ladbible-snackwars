#!/usr/bin/env python3
"""D8 — Captions, graphics, colour; final composite.

Captions are retimed to the *output* clock of the locked picture (never pasted
from source timestamps), corrected for names and numbers, and grouped so a name
or a number is never split. Then watermark, grade and the hook card are
composited with the D7 audio into the delivered file.

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
                     r"stopped|refuse|zero)\b)", re.I)


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


WEAK_TAIL = {"a", "an", "the", "of", "to", "in", "on", "at", "and", "but", "or",
             "is", "are", "was", "it", "that", "for", "with", "as", "by", "so"}


def group_words(words, maxw: int):
    """2-3 word caption groups that never strand a determiner.

    A group is closed at punctuation, after `maxw` words, or when the next word
    would leave a stray "a/the/of" hanging at the end of the line.
    """
    groups, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if nxt is None:
            groups.append(cur); break
        nxt_word = re.sub(r"[^a-z']", "", nxt["w"].lower())
        at_punct = w["w"].endswith((",", ".", "?", "!", ";", ":"))
        if at_punct and len(cur) >= 2:
            groups.append(cur); cur = []
        elif nxt_word in WEAK_TAIL and len(cur) >= 2:
            groups.append(cur); cur = []        # never end a line on "a/the/of"
        elif len(cur) >= maxw:
            groups.append(cur); cur = []
        elif w["w"].endswith((".", "?", "!")):
            groups.append(cur); cur = []
    if cur:
        groups.append(cur)
    return groups


def build_ass(path: Path, words, t0: float, t1: float, hook: str, brief: dict):
    cap = brief.get("captions", {})
    hk = brief.get("hook_card", {})
    maxw = int(cap.get("max_words", 3))
    hook_secs = float(hk.get("seconds", 3.2))

    events = []
    events.append(f"Dialogue: 2,{clk(0)},{clk(min(hook_secs, t1 - t0))},Hook,"
                  f"{{\\fad(90,180)}}{hook}")

    groups = [g for g in group_words([w for w in words if t0 - .05 <= w["t"] < t1], maxw) if g]
    # merge any group too short to read into the one that follows, so two
    # captions are never on screen at once and nothing flashes for 0.2 s
    merged = []
    for g in groups:
        if merged:
            prev = merged[-1]
            if g[-1]["e"] - prev[0]["t"] < 0.85:
                merged[-1] = prev + g
                continue
        merged.append(g)
    groups = merged
    for gi, g in enumerate(groups):
        start = max(0.0, g[0]["t"] - t0)
        nxt_start = (groups[gi + 1][0]["t"] - t0) if gi + 1 < len(groups) else (t1 - t0)
        end = min(g[-1]["e"] - t0 + .30, nxt_start - .03 if gi + 1 < len(groups) else t1 - t0)
        end = max(end, start + 0.35)
        parts = []
        for w in g:
            word = w["w"]
            if cap.get("highlight", True) and KEYWORD.search(word):
                parts.append("{\\c&H0000E5FF&\\fscx106\\fscy106\\t(0,90,\\fscx100\\fscy100)}"
                             + word + "{\\r}")
            else:
                parts.append(word)
        events.append(f"Dialogue: 1,{clk(start)},{clk(end)},Cap,{{\\fad(40,40)}}{' '.join(parts)}")

    path.write_text(f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,DejaVu Sans,{hk.get('fontsize', 88)},&H00FFFFFF,&H00202020,&H00000000,1,0,0,0,100,100,0,0,3,14,0,8,60,60,{hk.get('margin_v', 430)},1
Style: Cap,DejaVu Sans,{cap.get('fontsize', 72)},&H00FFFFFF,&H00101010,&H00000000,1,0,0,0,100,100,0,0,1,5,2,2,50,50,{cap.get('margin_v', 660)},1
[Events]
Format: Layer, Start, End, Style, Text
""" + "\n".join(events) + "\n", encoding="utf8")
    return len(events)


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
    hooks = {h["candidate_id"]: h for h in store.read_json(cid, "artifacts/hook_cards.v1.json")["payload"]["cards"]}
    hook = hooks[clip]["winner"]
    words = store.read_json(cid, "artifacts/transcript.v1.json")["payload"]["words"]
    words = apply_fixes(words, brief.get("caption_fixes", {}).get(clip, []))
    edl = store.read_json(cid, f"artifacts/edl_picture_{clip}.v1.json")["payload"]
    dur = edl["events"][-1]["output_out"]
    # captions live on the output clock: every word is retimed through the same
    # cut plan the picture was built from, so a cut never leaves a caption behind
    plan = store.read_json(cid, f"artifacts/cutplan_{clip}.v1.json")["payload"]
    words = timeline.remap_words(plan, words)
    cap_word_count = len(words)

    picture = store.path(cid, f"render/{clip}_picture.mp4")
    audio = store.path(cid, f"render/{clip}_audio.m4a")
    ass = store.path(cid, f"work/{clip}.ass")
    build_ass(ass, words, 0.0, dur, hook, brief)
    store.artifact(cid, f"captions_{clip}", {"clip": clip, "style": "2-3 word groups, keyword highlight",
                                             "words_on_output_clock": cap_word_count,
                                             "events": len(ass.read_text().splitlines()) - 12})

    wmc = dict(brief.get("brand_rules", {}).get("watermark", {}))
    wmc.update(brief.get("watermark", {}) or {})
    wm = ROOT / wmc.get("file", wmc.get("asset", "assets/watermark_white.png"))
    if not wm.exists():
        raise SystemExit(f"watermark asset missing: {wm}")
    wm_w = int(wmc.get("width", 640))
    pos = wmc.get("position", "bottom-center")
    if pos.startswith("top"):
        wm_y = int(wmc.get("margin_top", 70))
    else:
        wm_y = f"H-{int(wmc.get('margin_bottom', 300))}-h"
    wm_x = {"top-left": str(int(wmc.get("margin_side", 50))),
            "top-right": f"W-w-{int(wmc.get('margin_side', 50))}",
            "bottom-left": str(int(wmc.get("margin_side", 50))),
            "bottom-right": f"W-w-{int(wmc.get('margin_side', 50))}"}.get(pos, "(W-w)/2")

    out = store.path(cid, f"clips/{clip}.mp4")
    subprocess.run([FF, "-nostdin", "-v", "error", "-y",
                    "-i", str(picture), "-i", str(audio), "-i", str(wm),
                    "-filter_complex",
                    f"[2:v]scale={wm_w}:-1[wm];"
                    f"[0:v][wm]overlay={wm_x}:{wm_y}:format=auto[v0];"
                    f"[v0]ass={ass},eq=contrast=1.05:saturation=1.06,setsar=1[v]",
                    "-map", "[v]", "-map", "1:a", "-t", f"{dur:.3f}",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                    "-pix_fmt", "yuv420p", "-r", str(fps),
                    "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)],
                   check=True)
    store.gate(cid, clip, "RENDER_COMPLETE", out.exists() and out.stat().st_size > 0, str(out))
    print(json.dumps({"clip": clip, "output": str(out), "duration": dur,
                      "size_mb": round(out.stat().st_size / 1e6, 1)}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
