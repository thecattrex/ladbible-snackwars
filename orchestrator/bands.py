#!/usr/bin/env python3
"""Title bands — the blank space above and below the picture.

Layout (1080x1920):
   0 -  360   top band    : brand kicker + the clip's headline, key word marked
 360 - 1480   picture     : the edit itself, letterboxed
1480 - 1920   bottom band : one line saying what the clip is about, key word marked

The marked word is drawn the way a person marks a script: a highlighter swash
that overshoots the word slightly and sits at a small angle, with the text
reversed out of it. That reads as a human annotation; a coloured word alone
reads as a template variable.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ASSETS = Path(__file__).resolve().parent.parent / "assets"
LIME = (198, 255, 0)
WHITE = (245, 247, 250)
INK = (8, 10, 13)
MUTED = (150, 160, 172)


def _f(name: str, size: int):
    return ImageFont.truetype(str(ASSETS / name), size)


def display(size: int):
    return _f("Anton-Regular.ttf", size)


def grotesk(size: int):
    return _f("ArchivoBlack-Regular.ttf", size)


def ui(size: int):
    return _f("Inter.ttf", size)


def _swash(d: ImageDraw.ImageDraw, x0: int, y0: int, x1: int, y1: int,
           colour=LIME, angle: float = -0.7):
    """A highlighter stroke: slightly rotated, ends overshooting the word."""
    pad_x, pad_y = 16, 10
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    hw, hh = (x1 - x0) / 2 + pad_x, (y1 - y0) / 2 + pad_y
    th = math.tan(math.radians(angle))
    pts = []
    for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        px, py = cx + sx * hw, cy + sy * hh
        pts.append((px, py + (px - cx) * th))
    d.polygon(pts, fill=colour + (255,))


def line_with_marker(d: ImageDraw.ImageDraw, text: str, keyword: str, font,
                     x: int, y: int, fill=WHITE, marker=LIME,
                     ink_text=None, tracking: int = 0):
    """Draw `text`, but the first occurrence of `keyword` sits in a marker swash."""
    kw = keyword.strip()
    before, kw_txt, after = text, "", ""
    if kw and kw.lower() in text.lower():
        i = text.lower().index(kw.lower())
        before, kw_txt, after = text[:i], text[i:i + len(kw)], text[i + len(kw):]

    def width(s):
        if not s:
            return 0
        return sum(d.textlength(c, font=font) + tracking for c in s) - tracking

    def draw_run(s, xx, colour):
        if not s:
            return xx
        for c in s:
            d.text((xx, y), c, font=font, fill=colour, anchor="lm")
            xx += d.textlength(c, font=font) + tracking
        return xx

    x_end = draw_run(before, x, fill)
    if kw_txt:
        w_kw = width(kw_txt)
        bx0, by0, bx1, by1 = d.textbbox((x_end, y), kw_txt, font=font, anchor="lm")
        _swash(d, int(bx0), int(by0), int(bx1), int(by1), marker)
        draw_run(kw_txt, x_end, ink_text or INK + (255,))
        x_end += w_kw
    x_end = draw_run(after, x_end, fill)
    return x_end, width(text)


def band(size, bg=INK, alpha=255) -> Image.Image:
    return Image.new("RGBA", size, (bg[0], bg[1], bg[2], alpha))


def make_top(title: str, keyword: str, kicker: str = "", size=(1080, 360),
             accent=LIME) -> Image.Image:
    w, h = size
    im = band(size)
    d = ImageDraw.Draw(im)
    d.rectangle([0, h - 3, w, h], fill=(255, 255, 255, 14))
    if kicker:
        kx = 64
        for c in kicker.upper():
            d.text((kx, 74), c, font=ui(26), fill=accent + (255,), anchor="lm")
            kx += d.textlength(c, font=ui(26)) + 5
        d.line([64, 96, 64 + 44, 96], fill=accent + (255,), width=4)
    # fit the headline to the band
    px = 96
    f = display(px)
    probe = ImageDraw.Draw(im)
    while px > 44:
        total = sum(probe.textlength(c, font=f) + 1 for c in title)
        if total <= w - 128:
            break
        px -= 4
        f = display(px)
    line_with_marker(d, title, keyword, f, 72, int(h * 0.66), fill=WHITE + (255,),
                     marker=accent)
    return im


def make_bottom(line: str, keyword: str, note: str = "", size=(1080, 440),
                accent=LIME) -> Image.Image:
    w, h = size
    im = band(size)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, w, 3], fill=(255, 255, 255, 14))
    px = 66
    f = display(px)
    probe = ImageDraw.Draw(im)
    while px > 34:
        total = sum(probe.textlength(c, font=f) + 1 for c in line)
        if total <= w - 128:
            break
        px -= 3
        f = display(px)
    line_with_marker(d, line, keyword, f, 72, int(h * 0.38), fill=WHITE + (255,),
                     marker=accent)
    if note:
        d.text((64, int(h * 0.68)), note, font=ui(28), fill=MUTED + (255,), anchor="lm")
    d.line([64, h - 74, 140, h - 74], fill=accent + (255,), width=5)
    return im


def render(cid_dir: Path, clip: str, spec: dict) -> dict:
    top = make_top(spec.get("title", ""), spec.get("title_keyword", ""),
                   spec.get("kicker", ""))
    bot = make_bottom(spec.get("bottom", ""), spec.get("bottom_keyword", ""),
                      spec.get("note", ""))
    tp = cid_dir / f"render/gfx/{clip}_band_top.png"
    bp = cid_dir / f"render/gfx/{clip}_band_bottom.png"
    tp.parent.mkdir(parents=True, exist_ok=True)
    top.save(tp)
    bot.save(bp)
    return {"top": str(tp), "bottom": str(bp), "top_h": top.size[1],
            "bottom_h": bot.size[1], "video_y": top.size[1],
            "video_h": 1920 - top.size[1] - bot.size[1]}
