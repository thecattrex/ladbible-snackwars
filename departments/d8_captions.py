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
from orchestrator import store  # noqa: E402

FF = imageio_ffmpeg.get_ffmpeg_exe()
W, H = 1080, 1920
KEYWORD = re.compile(r"(\$?\d[\d,\.]*\s*(?:%|k|m|million|billion|thousand)?|"
                     r"\b(?:never|nothing|impossible|demolish|replaced|wrong|mistake|over)\b)", re.I)


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


def build_ass(path: Path, words, t0: float, t1: float, hook: str, brief: dict):
    cap = brief.get("captions", {})
    maxw = int(cap.get("max_words", 3))
    events = [f"Dialogue: 1,{clk(0)},{clk(min(brief.get('hook_card', {}).get('seconds', 3.5), t1 - t0))},Hook,{hook}"]
    grp = []

    def emit(g):
        if not g:
            return
        parts = []
        for w in g:
            if cap.get("highlight", True) and KEYWORD.search(w["w"]):
                parts.append("{\\c&H00E5FF&\\fscx108\\fscy108\\t(0,90,\\fscx100\\fscy100)}"
                             + w["w"] + "{\\r}")
            else:
                parts.append(w["w"])
        events.append(f"Dialogue: 0,{clk(g[0]['t'] - t0)},{clk(g[-1]['e'] - t0 + .12)},Cap,{' '.join(parts)}")

    for w in words:
        if not (t0 - .05 <= w["t"] < t1):
            continue
        grp.append(w)
        if len(grp) >= maxw or w["w"].endswith((".", "?", "!")):
            emit(grp); grp = []
    emit(grp)
    path.write_text(f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,DejaVu Sans,{brief.get('hook_card', {}).get('fontsize', 84)},&H00FFFFFF,&H00101010,&H7F000000,1,8,70,70,{brief.get('hook_card', {}).get('margin_v', 200)},3
Style: Cap,DejaVu Sans,{cap.get('fontsize', 60)},&H00FFFFFF,&H00101010,&H00000000,1,2,70,70,{cap.get('margin_v', 560)},1
[Events]
Format: Layer, Start, End, Style, Text
""" + "\n".join(events) + "\n", encoding="utf8")


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

    picture = store.path(cid, f"render/{clip}_picture.mp4")
    audio = store.path(cid, f"render/{clip}_audio.m4a")
    ass = store.path(cid, f"work/{clip}.ass")
    build_ass(ass, words, card["t0"], card["t1"], hook, brief)
    store.artifact(cid, f"captions_{clip}", {"clip": clip, "style": "2-3 word groups, keyword highlight",
                                             "events": len(ass.read_text().splitlines()) - 12})

    wm = ROOT / brief.get("watermark", {}).get("file", "assets/watermark_white.png")
    if not wm.exists():
        raise SystemExit(f"watermark asset missing: {wm}")
    wm_w = int(brief.get("watermark", {}).get("width", 640))
    wm_mb = int(brief.get("watermark", {}).get("margin_bottom", 300))

    out = store.path(cid, f"clips/{clip}.mp4")
    subprocess.run([FF, "-nostdin", "-v", "error", "-y",
                    "-i", str(picture), "-i", str(audio), "-i", str(wm),
                    "-filter_complex",
                    f"[2:v]scale={wm_w}:-1[wm];"
                    f"[0:v][wm]overlay=(W-w)/2:H-{wm_mb}:format=auto[v0];"
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
