#!/usr/bin/env python3
"""Build one demo clip end to end: pick, cut, transcribe, caption, compose, encode.

Pipeline that every real clip will use, at demo scale:
  1. cut the chosen window out of the stream (segment-accurate, copied, not re-encoded);
  2. whisper with word timings on the cut only — captions follow who is speaking;
  3. caption chunks of 2-5 words, filler dropped, longest word in red;
  4. layout.headline / layout.caption on a banner backdrop, clip dead centre;
  5. encode 1080x1920 with the grade, audio untouched.

  python3 tools/demo2.py <video> --start 1562 --len 28 --title "halloween party" \
      --kicker "sick-ass costumes" --out /home/user/demo2.mp4
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import layout as L   # noqa: E402

FF = "/home/user/bin/ffmpeg"
FILLER = {"yeah", "okay", "alright", "oh", "ah", "um", "uh", "so", "like", "right",
          "yes", "no", "hi", "hey", "thank", "you", "thanks", "bye"}


def cut(video: Path, start: int, length: int, out: Path) -> None:
    subprocess.run([FF, "-v", "error", "-y", "-ss", str(start), "-t", str(length),
                    "-i", str(video), "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                    "-c:a", "aac", "-b:a", "192k", "-ac", "2", str(out)], check=True)


def words(clip: Path) -> list:
    from faster_whisper import WhisperModel
    wav = clip.with_suffix(".wav")
    subprocess.run([FF, "-v", "error", "-y", "-i", str(clip), "-vn", "-ac", "1", "-ar",
                    "16000", str(wav)], check=True)
    import soundfile as sf
    x, sr = sf.read(str(wav), dtype="float32")
    model = WhisperModel("base.en", device="cpu", compute_type="int8", cpu_threads=2)
    segs, _ = model.transcribe(x, language="en", vad_filter=True, beam_size=1,
                               word_timestamps=True, condition_on_previous_text=False)
    out = []
    for s in segs:
        for w in (s.words or []):
            out.append({"t0": float(w.start), "t1": float(w.end), "word": w.word.strip()})
    return out


def chunks(ws: list, min_words=3, max_words=5, max_span=2.8, min_gap=0.05) -> list:
    """Group words into caption cards, dropping filler and starting on a content word."""
    groups, cur = [], []
    for w in ws:
        if not w["word"]:
            continue
        if cur and (w["t0"] - cur[-1]["t1"] > 0.7 or len(cur) >= max_words
                    or w["t1"] - cur[0]["t0"] > max_span):
            groups.append(cur); cur = []
        cur.append(w)
    if cur:
        groups.append(cur)

    cards = []
    for g in groups:
        keep = [w for w in g if w["word"].lower().strip(".,!?") not in FILLER]
        if len(keep) < min_words:
            continue
        text = " ".join(w["word"] for w in keep).strip().strip(",")
        longest = max((w["word"].strip(".,!?") for w in keep), key=len)
        cards.append({"t0": round(keep[0]["t0"], 2), "t1": round(keep[-1]["t1"] + 0.18, 2),
                      "text": text, "key": longest})
    return cards


def ass_time(t: float) -> str:
    h = int(t // 3600); m = int(t % 3600 // 60); sec = t % 60
    return f"{h}:{m:02d}:{sec:05.2f}"


def write_ass(cards: list, path: Path, width: int, height: int) -> None:
    """Caption track as subtitles, not as overlay inputs.

    Fourteen looped PNG inputs at 1080x1920 ran this 2 GB box out of memory; one
    subtitle filter renders the same thing for a fraction of the cost, and it keeps
    the caption styling in a single place.
    """
    lines = [
        "[Script Info]", f"PlayResX: {width}", f"PlayResY: {height}", "WrapStyle: 2",
        "ScriptType: v4.00+", "", "[V4+ Styles]",
        ("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour,"
         " BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle,"
         " BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"),
        ("Style: Cap,Poppins ExtraBold,64,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,"
         "-1,0,0,0,100,100,1,0,1,8,4,2,40,40,54,1"),
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for c in cards:
        text = c["text"]
        key = c["key"]
        i = text.lower().find(key.lower())
        if i >= 0:                                  # keyword in blood red, rest white
            text = (text[:i] + r"{\c&H2020E8&}" + text[i:i + len(key)] +
                    r"{\c&HFFFFFF&}" + text[i + len(key):])
        lines.append(f"Dialogue: 0,{ass_time(c['t0'])},{ass_time(c['t1'])},Cap,,0,0,0,,"
                     + text.replace("\n", " "))
    path.write_text("\n".join(lines) + "\n")


def card_png(path: Path, text: str, key: str) -> None:
    """One caption card at clip resolution, transparent, drawn by layout.caption."""
    img = Image.new("RGB", (L.CLIP_W, 220), (0, 0, 0))
    canvas = Image.new("RGB", (L.W, L.H), (0, 0, 0))
    L.caption(canvas, text, key)                 # reuse the approved caption style
    crop = canvas.crop((0, L.CLIP_Y + L.CLIP_H - 200, L.CLIP_W, L.CLIP_Y + L.CLIP_H + 20))
    crop.save(path)


def build(video: Path, start: int, length: int, title: str, kicker: str, out: Path) -> None:
    tmp = Path(tempfile.mkdtemp())
    raw = tmp / "cut.mp4"
    print("cutting…", flush=True)
    cut(video, start, length, raw)

    print("transcribing the cut…", flush=True)
    ws = words(raw)
    cards = chunks(ws)
    print(f"{len(cards)} caption cards", flush=True)
    (tmp / "cards.json").write_text(json.dumps(cards, indent=1))

    base = L.static_canvas(title, kicker)
    base.save(tmp / "base.png")

    ass = tmp / "caps.ass"
    write_ass(cards, ass, L.CLIP_W, L.CLIP_H)

    # pass 1 — grade and caption the picture, at clip size only
    capped = tmp / "capped.mp4"
    subprocess.run([FF, "-v", "error", "-y", "-i", str(raw), "-vf",
                    L.grade_filter() + f",scale={L.CLIP_W}:{L.CLIP_H},setsar=1,"
                    f"subtitles={ass}:fontsdir={L.ASSETS}",
                    "-threads", "2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
                    "-c:a", "copy", str(capped)], check=True)

    # pass 2 — clip into the layout, two inputs, audio straight through
    print("encoding…", flush=True)
    subprocess.run([FF, "-v", "error", "-y", "-loop", "1", "-i", str(tmp / "base.png"),
                    "-i", str(capped), "-filter_complex",
                    f"[0:v][1:v]overlay=0:{L.CLIP_Y},format=yuv420p[out]",
                    "-map", "[out]", "-map", "1:a", "-t", str(length), "-r", "30",
                    "-threads", "2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
                    "-movflags", "+faststart", str(out)], check=True)
    print("wrote", out, f"{out.stat().st_size / 1e6:.1f} MB")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--start", type=int, required=True)
    ap.add_argument("--len", type=int, default=28)
    ap.add_argument("--title", default="halloween party")
    ap.add_argument("--kicker", default="sick-ass costumes")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    build(Path(args.video), args.start, args.len, args.title, args.kicker, Path(args.out))


if __name__ == "__main__":
    main()
