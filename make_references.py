#!/usr/bin/env python3
"""Builds the two reference videos we check every new clip against.

  references/GALAT_bad_example.mp4    -> v2 (rejected): speaker often off frame
  references/SAHI_good_example.mp4    -> v3 (approved): same scene, done right
  references/COMPARE_bad_vs_good.mp4  -> both side by side, numbers burned in

Both examples are the SAME episode (ep14), so the only variable is the editing.
Numbers come from bots/review_bot.py, not from opinion.
This build has no ffmpeg drawtext filter, so labels are drawn with PIL and the
frames are piped into ffmpeg as raw BGR.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import cv2
import numpy as np
import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
FF = imageio_ffmpeg.get_ffmpeg_exe()
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
REF = ROOT / "references"
BAD = ROOT / "clips_v2" / "ep14.mp4"      # rejected framing
GOOD = ROOT / "clips_v3" / "ep14.mp4"     # approved
W, H = 1080, 1920


def frames(path: Path, w: int, h: int):
    cap = cv2.VideoCapture(str(path))
    while True:
        ok, f = cap.read()
        if not ok:
            break
        if f.shape[1] != w or f.shape[0] != h:
            f = cv2.resize(f, (w, h), interpolation=cv2.INTER_AREA)
        yield f
    cap.release()


def draw(img, lines, color):
    im = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    d = ImageDraw.Draw(im, "RGBA")
    y = 110
    for text, size in lines:
        f = ImageFont.truetype(FONT, size)
        tw = d.textlength(text, font=f)
        x = (im.width - tw) / 2
        d.rectangle([x - 16, y - 10, x + tw + 16, y + size + 12], fill=(0, 0, 0, 180))
        d.text((x, y), text, font=f, fill=color)
        y += size + 60
    return cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)


def encode(gen, out: Path, audio_from: Path | None, w: int, h: int, fps: int = 30):
    cmd = [FF, "-hide_banner", "-loglevel", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", str(fps),
           "-i", "-"]
    if audio_from:
        cmd += ["-i", str(audio_from), "-map", "0:v", "-map", "1:a", "-c:a", "aac",
                "-b:a", "160k", "-shortest"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for f in gen:
        p.stdin.write(f.tobytes())
    p.stdin.close()
    p.wait()


def main():
    REF.mkdir(exist_ok=True)
    rec = json.loads((ROOT / "assets" / "bot_status" / "reference_stats.json").read_text())
    b, g = rec["bad"], rec["good"]

    red, green = (255, 70, 70), (140, 255, 120)
    encode((draw(f, [("GALAT  v2  (reject)", 62),
                     (f"face {b['face_pct']*100:.0f}% frames", 46),
                     (f"{b['max_gap']:.1f}s frame me koi nahi", 46),
                     ("koi bol raha hai, frame khaali", 40)], red) for f in frames(BAD, W, H)),
           REF / "GALAT_bad_example.mp4", BAD, W, H)

    encode((draw(f, [("SAHI  v3  (approved)", 62),
                     (f"face {g['face_pct']*100:.0f}% frames", 46),
                     (f"{g['max_gap']:.1f}s frame me koi nahi", 46),
                     ("speaker frame me + cuts + hook + captions", 40)], green)
            for f in frames(GOOD, W, H)),
           REF / "SAHI_good_example.mp4", GOOD, W, H)

    # side by side: 540x960 each
    def gen():
        gb = frames(BAD, 540, 960)
        gg = frames(GOOD, 540, 960)
        while True:
            try:
                a, c = next(gb), next(gg)
            except StopIteration:
                return
            a = draw(a, [("GALAT", 44), (f"{b['face_pct']*100:.0f}%  gap {b['max_gap']:.1f}s", 26)], red)
            c = draw(c, [("SAHI", 44), (f"{g['face_pct']*100:.0f}%  gap {g['max_gap']:.1f}s", 26)], green)
            yield np.hstack([a, c])
    encode(gen(), REF / "COMPARE_bad_vs_good.mp4", GOOD, 1080, 960)
    for p in sorted(REF.glob("*.mp4")):
        print(f"{p.name:28s} {p.stat().st_size/1e6:5.1f} MB")


if __name__ == "__main__":
    main()
