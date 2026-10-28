#!/usr/bin/env python3
"""Compose the demo short: 16:9 footage untouched over her blurred Twitch banner.

Layout locked with the user:
  1080x1920, banner background at Gaussian blur 18 (lightness .88, 18% veil),
  the 16:9 clip at full width y=700, hook plate above, caption card inside the
  clip, watermark below — nothing readable below y=1600 (app UI zone).

  python3 tools/demo_compose.py <clip.mp4> <out.mp4> [--hook "..." --sub "..." --cap "..."]
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from mock_reframe import BANNER, H, W, centred, font   # noqa: E402

LIME = (200, 255, 0)
CLIP_Y = 700
CLIP_H = 608
SAFE_BOTTOM = 1600
FF = "/home/user/bin/ffmpeg"


def banner_bg(radius: int = 18, brightness: float = 0.88) -> Image.Image:
    art = Image.open(BANNER).convert("RGB")
    scale = max(W / art.size[0], H / art.size[1]) * 1.10
    big = art.resize((int(art.size[0] * scale), int(art.size[1] * scale)), Image.LANCZOS)
    left, top = (big.size[0] - W) // 2, (big.size[1] - H) // 2
    out = big.crop((left, top, left + W, top + H)).filter(ImageFilter.GaussianBlur(radius))
    out = Image.eval(out, lambda v: int(v * brightness))
    return Image.blend(out, Image.new("RGB", (W, H), (16, 8, 22)), 0.18)


def hook_card(hook: str, sub: str, kicker: str) -> Image.Image:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([40, 210, W - 40, CLIP_Y - 60], radius=26, fill=(8, 8, 12, 210))
    size = 96 if len(hook) <= 16 else 78
    centred(d, (W / 2, 236), hook.upper(), font("Anton-Regular.ttf", size), (255, 255, 255),
            tracking=2)
    centred(d, (W / 2, 236 + size + 26), sub.upper(), font("ArchivoBlack-Regular.ttf", 54),
            LIME, tracking=4)
    centred(d, (W / 2, 236 + size + 110), kicker, font("Inter.ttf", 38), (208, 208, 222))
    return img


def caption_card(line: str, key: str) -> Image.Image:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    top = CLIP_Y + CLIP_H - 250
    d.rounded_rectangle([90, top, W - 90, top + 170], radius=24, fill=(8, 8, 12, 200))
    centred(d, (W / 2, top + 18), line, font("ArchivoBlack-Regular.ttf", 56), (255, 255, 255))
    centred(d, (W / 2, top + 96), key, font("ArchivoBlack-Regular.ttf", 56), LIME)
    return img


def watermark_card() -> Image.Image:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    top = CLIP_Y + CLIP_H + 24 + 176
    d.rounded_rectangle([W / 2 - 300, top, W / 2 + 300, top + 84], radius=18,
                        fill=(8, 8, 12, 205))
    centred(d, (W / 2, top + 16), "@Irubyana   #irubyana   #twitch",
            font("ArchivoBlack-Regular.ttf", 32), (235, 235, 245))
    assert top + 84 <= SAFE_BOTTOM
    return img


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("clip")
    ap.add_argument("out")
    ap.add_argument("--hook", default="halloween party")
    ap.add_argument("--sub", default="gone wrong")
    ap.add_argument("--kicker", default="wait for the end")
    ap.add_argument("--cap", default="i don't wanna make fun")
    ap.add_argument("--key", default="of kingoo")
    ap.add_argument("--cap-in", type=float, default=6.3)
    ap.add_argument("--cap-out", type=float, default=10.4)
    args = ap.parse_args()

    out = Path(args.out)
    tmp = out.parent / "_layers"
    tmp.mkdir(parents=True, exist_ok=True)
    # static layers are baked into one image: this box has 2 GB of RAM, and every
    # extra looped input costs another decoder in the filter graph
    base = banner_bg().convert("RGBA")
    base = Image.alpha_composite(base, hook_card(args.hook, args.sub, args.kicker))
    base = Image.alpha_composite(base, watermark_card())
    base.convert("RGB").save(tmp / "base.png")
    caption_card(args.cap, args.key).save(tmp / "cap.png")

    dur = float(subprocess.run(
        [FF.replace("ffmpeg", "ffprobe") if Path(FF.replace("ffmpeg", "ffprobe")).exists() else FF,
         "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", args.clip],
        capture_output=True, text=True).stdout.strip() or 24)

    graph = (
        f"[1:v]scale={W}:{CLIP_H}:flags=bicubic,setsar=1[v];"
        f"[0:v][v]overlay=0:{CLIP_Y}[b];"
        f"[b][2:v]overlay=0:0:enable='between(t,{args.cap_in},{args.cap_out})',"
        f"format=yuv420p[out]"
    )
    cmd = [FF, "-v", "error", "-y",
           "-loop", "1", "-i", str(tmp / "base.png"),
           "-i", args.clip,
           "-loop", "1", "-i", str(tmp / "cap.png"),
           "-filter_complex", graph,
           "-map", "[out]", "-map", "1:a",
           "-t", f"{dur:.2f}", "-r", "30", "-threads", "2",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True)
    print("wrote", out, f"{out.stat().st_size/1e6:.1f} MB", f"{dur:.1f}s")


if __name__ == "__main__":
    main()
