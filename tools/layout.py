#!/usr/bin/env python3
"""The Irubyana clip layout — no boxes anywhere, type sits straight on the picture.

Locked with the user:
  * the 16:9 footage keeps its ratio and sits in the middle of the 1080x1920 frame;
  * the Twitch banner is the background, Gaussian blur 18;
  * nothing is written inside a rounded rectangle — panels read as a template, and
    a template reads as machine made. Type gets a shadow, an outline and a glow
    instead, the way a title card is actually built;
  * headline in Nosifer (horror, bloody) with real drips, kicker in Creepster;
  * captions in Poppins ExtraBold, white with a red keyword, timed to who is
    speaking, never boxed.

  python3 tools/layout.py  (imported; see tools/mock_gothic.py and demo_compose.py)
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
BANNER = ASSETS / "irubyana" / "banner.jpg"

W, H = 1080, 1920
CLIP_W = 1080
CLIP_H = 608
CLIP_Y = (H - CLIP_H) // 2          # 656 — dead centre, as asked
SAFE_BOTTOM = 1600                  # TikTok/Reels paint their own UI below this

BLOOD_TOP = (255, 42, 42)
BLOOD_BOTTOM = (74, 0, 0)
CREAM = (240, 232, 214)
LIME = (200, 255, 0)


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(ASSETS / name), size)


HEAD = "Nosifer-Regular.ttf"
KICKER = "Creepster-Regular.ttf"
CAP = "Poppins-ExtraBold.ttf"
SMALL = "Poppins-Black.ttf"


# ---------------------------------------------------------------- background
def banner_backdrop(radius: int = 18, brightness: float = 0.86) -> Image.Image:
    art = Image.open(BANNER).convert("RGB")
    scale = max(W / art.size[0], H / art.size[1]) * 1.10
    big = art.resize((int(art.size[0] * scale), int(art.size[1] * scale)), Image.LANCZOS)
    left, top = (big.size[0] - W) // 2, (big.size[1] - H) // 2
    out = big.crop((left, top, left + W, top + H)).filter(ImageFilter.GaussianBlur(radius))
    out = Image.eval(out, lambda v: int(v * brightness))
    return Image.blend(out, Image.new("RGB", (W, H), (16, 8, 22)), 0.20)


# ---------------------------------------------------------------- helpers
def _text_layer(size, xy, text, f, tracking=0):
    """Text drawn once, centred on x, on a transparent canvas."""
    layer = Image.new("L", size, 0)
    d = ImageDraw.Draw(layer)
    if tracking:
        widths = [d.textlength(c, font=f) for c in text]
        total = sum(widths) + tracking * (len(text) - 1)
        x = xy[0] - total / 2
        for c, wd in zip(text, widths):
            d.text((x, xy[1]), c, font=f, fill=255)
            x += wd + tracking
    else:
        bbox = d.textbbox((0, 0), text, font=f)
        d.text((xy[0] - (bbox[2] - bbox[0]) / 2 - bbox[0], xy[1]), text, font=f, fill=255)
    return layer


def _odd(n: int) -> int:
    """MaxFilter accepts only odd sizes in 3..9."""
    n = max(3, min(9, int(round(n))))
    return n if n % 2 else n - 1


def _gradient(size, top_colour, bottom_colour, y0, y1) -> Image.Image:
    grad = Image.new("RGB", (1, size[1]))
    for y in range(size[1]):
        k = min(1.0, max(0.0, (y - y0) / max(1, (y1 - y0))))
        grad.putpixel((0, y), tuple(int(top_colour[i] + (bottom_colour[i] - top_colour[i]) * k)
                                    for i in range(3)))
    return grad.resize(size)


def blood_text(canvas: Image.Image, xy, text, f, tracking=0, drips=9, glow=150) -> None:
    """Headline in a bloody treatment: gradient fill, glow, outline, running drips."""
    mask = _text_layer(canvas.size, xy, text, f, tracking)
    bbox = mask.getbbox()
    if not bbox:
        return

    # glow: the type lit from behind, so it reads over a busy photograph
    if glow:
        halo = mask.filter(ImageFilter.GaussianBlur(22))
        canvas.paste(Image.new("RGB", canvas.size, (150, 0, 0)),
                     (0, 0), halo.point(lambda v: int(v * glow / 255)))

    # outline: a dark edge keeps the letters crisp without drawing a panel
    edge = mask.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(2))
    # (9 is a valid MaxFilter size: odd and <= 9)
    canvas.paste(Image.new("RGB", canvas.size, (10, 0, 0)), (0, 0),
                 edge.point(lambda v: int(v * 0.95)))

    fill = _gradient(canvas.size, BLOOD_TOP, BLOOD_BOTTOM, bbox[1], bbox[3])
    canvas.paste(fill, (0, 0), mask)

    # drips, deterministic so a re-render matches the approved mock
    d = ImageDraw.Draw(canvas)
    span = bbox[2] - bbox[0]
    for i in range(drips):
        k = (i + 0.5) / drips
        x = int(bbox[0] + span * k)
        length = int(26 + 64 * abs(math.sin(i * 2.399)))
        width = 7 + (i % 3) * 3
        top = bbox[3] - 14
        d.rounded_rectangle([x, top, x + width, top + length], radius=width // 2,
                            fill=(150, 8, 8))
        d.ellipse([x - 2, top + length - width // 2, x + width + 2, top + length + width],
                  fill=(120, 4, 4))


def shadowed_text(canvas: Image.Image, xy, text, f, fill, tracking=0, outline=7,
                  shadow=10) -> None:
    """Plain type with a heavy drop shadow and outline — no plate behind it."""
    mask = _text_layer(canvas.size, xy, text, f, tracking)
    if shadow:
        sh = mask.filter(ImageFilter.GaussianBlur(shadow))
        canvas.paste(Image.new("RGB", canvas.size, (0, 0, 0)), (8, 10), sh)
    if outline:
        edge = mask.filter(ImageFilter.MaxFilter(_odd(outline))).filter(ImageFilter.GaussianBlur(1))
        canvas.paste(Image.new("RGB", canvas.size, (0, 0, 0)), (0, 0), edge)
    canvas.paste(Image.new("RGB", canvas.size, fill), (0, 0), mask)


# ---------------------------------------------------------------- pieces
def headline(canvas: Image.Image, title: str, kicker: str, top: int = 130) -> Image.Image:
    """Big horror title in the band above the clip, kicker under it.

    The title is set as large as it can go without touching the sides: a horror
    headline that gets cropped looks like a mistake, not a style.
    """
    measure = ImageDraw.Draw(canvas)
    size = 150
    while size > 60:
        f = font(HEAD, size)
        if measure.textlength(title.upper(), font=f) + 4 * (len(title) - 1) <= 980:
            break
        size -= 4
    f = font(HEAD, size)
    blood_text(canvas, (W / 2, top), title.upper(), f, tracking=4, drips=11)
    kf = font(KICKER, 96)
    shadowed_text(canvas, (W / 2, top + size + 150), kicker.upper(), kf, CREAM,
                  tracking=12, outline=6, shadow=9)
    return canvas


def caption(canvas: Image.Image, line: str, key: str = "") -> Image.Image:
    """The line someone just said, over the lower part of the picture, no plate."""
    f = font(CAP, 74)
    y = CLIP_Y + CLIP_H - 175
    if key and key.lower() in line.lower():
        # draw the line in two runs so the keyword can carry the accent colour
        i = line.lower().index(key.lower())
        left, hot, right = line[:i], line[i:i + len(key)], line[i + len(key):]
        lw = ImageDraw.Draw(canvas).textlength(left, font=f)
        kw = ImageDraw.Draw(canvas).textlength(hot, font=f)
        rw = ImageDraw.Draw(canvas).textlength(right, font=f)
        total = lw + kw + rw
        x = W / 2 - total / 2
        shadowed_text(canvas, (x + lw / 2, y), left, f, (255, 255, 255), outline=9)
        shadowed_text(canvas, (x + lw + kw / 2, y), hot, f, (255, 60, 60), outline=9)
        shadowed_text(canvas, (x + lw + kw + rw / 2, y), right, f, (255, 255, 255), outline=9)
    else:
        shadowed_text(canvas, (W / 2, y), line, f, (255, 255, 255), outline=9)
    return canvas


def watermark(canvas: Image.Image) -> Image.Image:
    f = font(SMALL, 34)
    shadowed_text(canvas, (W / 2, CLIP_Y + CLIP_H + 150), "@Irubyana  ·  #irubyana  ·  #twitch",
                  f, (255, 255, 255), outline=0, shadow=8)
    return canvas


def static_canvas(title: str, kicker: str) -> Image.Image:
    canvas = banner_backdrop()
    headline(canvas, title, kicker)
    watermark(canvas)
    return canvas


# ---------------------------------------------------------------- footage grade
def grade_filter() -> str:
    """The party footage is lit almost entirely in red; lift the shadows, pull the
    cast back toward neutral, then add back a little punch."""
    return ("eq=brightness=0.05:contrast=1.10:saturation=1.10:gamma=1.06,"
            "colorbalance=rm=-0.06:gm=0.02:bm=0.06:rs=-0.04:bs=0.05,"
            "unsharp=5:5:0.5:5:5:0.0")
