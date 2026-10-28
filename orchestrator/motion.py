#!/usr/bin/env python3
"""Motion graphics — the "explain what he is saying" layer.

Retention editing research (and every strong podcast edit) agrees on the same
three moves:

  * a visual change every 2-3 s, not a static talking head;
  * graphics that *illustrate the line* — an animated counter on the number, a
    compare card on the comparison, avatars on "400 people";
  * captions that move with the speech.

The campaign brief forbids outside footage, so nothing here is stock: every
card is drawn from primitives (rects, polygons, text) at render time, animated
frame by frame, and emitted as an alpha video that the compositor drops over the
talking head. Cards are region renders, so a card only ever touches its own
band of the frame — it cannot cover the speaker's face.

Card vocabulary (each returns frames for a set of local times):
  counter   one number, rolling from 0 to its value, with a unit
  cost      "cost per person / month" with a money illustration
  people    an N-dot avatar grid that fills as the number counts up
  math      an equation that assembles term by term ("4,000,000 / 400 = 10,000")
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FF = imageio_ffmpeg.get_ffmpeg_exe()
FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
LIME = (198, 255, 0)
INK = (10, 12, 16)
WHITE = (255, 255, 255)
GREY = (168, 178, 190)


def font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    return ImageFont.truetype(str(FONT_DIR / name), size)


def ease_out(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def ease_back(t: float) -> float:
    t = max(0.0, min(1.0, t))
    c = 1.9
    return 1 + (c + 1) * (t - 1) ** 3 + c * (t - 1) ** 2


def ease_inout(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 3 * t * t - 2 * t * t * t


def panel(w: int, h: int, alpha: int = 188, radius: int = 34) -> Image.Image:
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([6, 10, w - 6, h - 6], radius=radius, fill=(0, 0, 0, 120))
    im = im.filter(ImageFilter.GaussianBlur(10))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, w - 12, h - 16], radius=radius,
                        fill=(INK[0], INK[1], INK[2], alpha))
    d.rounded_rectangle([0, 0, w - 12, h - 16], radius=radius,
                        outline=(255, 255, 255, 34), width=2)
    d.rounded_rectangle([34, 0, 34 + 96, 7], radius=4, fill=LIME + (255,))
    return im


def text(d: ImageDraw.ImageDraw, xy, s, f, fill=WHITE, anchor="mm", stroke=0,
         stroke_fill=(0, 0, 0, 220)):
    d.text(xy, s, font=f, fill=fill, anchor=anchor,
           stroke_width=stroke, stroke_fill=stroke_fill)


def money_icon(w: int, h: int, t: float) -> Image.Image:
    """A banknote drawn with a fake 3D tilt: two offset quads plus a face."""
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    k = ease_out(t)
    tilt = 0.10 * (1 - k) + 0.02 * np.sin(t * 6)
    cx, cy = w / 2, h / 2
    bw, bh = w * 0.80, h * 0.58

    def quad(scale, dy, skew):
        left = cx - bw * scale / 2 + skew * 14
        right = cx + bw * scale / 2 + skew * 14
        top = cy - bh * scale / 2 + dy
        bot = cy + bh * scale / 2 + dy
        return [(left + skew * 8, top), (right - skew * 8, top + tilt * 26),
                (right - skew * 8, bot + tilt * 10), (left + skew * 8, bot)]

    for i, (scale, dy) in enumerate([(0.90, 24), (0.96, 12), (1.0, 0)]):
        pts = quad(scale, dy, i - 1)
        col = (28 + i * 8, 74 + i * 10, 46 + i * 8, 255) if i < 2 else (36, 132, 76, 255)
        d.polygon(pts, fill=col, outline=(200, 255, 210, 120))
    pts = quad(1.0, 0, 0)
    d.polygon(pts, fill=(44, 156, 90, 255), outline=(220, 255, 225, 160))
    cx2 = sum(p[0] for p in pts) / 4
    cy2 = sum(p[1] for p in pts) / 4
    r = bh * 0.22 * k
    d.ellipse([cx2 - r, cy2 - r, cx2 + r, cy2 + r], outline=(220, 255, 225, 220), width=4)
    f = font(int(bh * 0.30))
    text(d, (cx2, cy2 + 1), "$", f, fill=(230, 255, 235, 235), stroke=0)
    return im


def bars(w: int, h: int, t: float, values, labels=None) -> Image.Image:
    """Isometric bar chart: each bar grows, top face gives the 3D read."""
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    n = len(values)
    gap = w * 0.10 / max(1, n - 1)
    bw = (w * 0.90 - gap * (n - 1)) / n
    base = h * 0.86
    mx = max(values) or 1
    for i, v in enumerate(values):
        local = ease_out(max(0.0, min(1.0, (t - 0.12 * i) / 0.5)))
        bh = (v / mx) * h * 0.66 * local
        x0 = w * 0.05 + i * (bw + gap)
        top = base - bh
        depth = 16 * local
        d.polygon([(x0, top), (x0 + depth, top - depth * 0.55),
                   (x0 + bw + depth, top - depth * 0.55), (x0 + bw, top)],
                  fill=(170, 220, 0, 235) if i == n - 1 else (86, 96, 108, 235))
        d.rectangle([x0, top, x0 + bw, base],
                    fill=LIME + (240,) if i == n - 1 else (52, 60, 70, 230))
    return im


def dots_grid(w: int, h: int, t: float, total: int, shown: int) -> Image.Image:
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cols = 20
    rows = int(np.ceil(total / cols))
    pad = 6
    cw = (w - pad * (cols + 1)) / cols
    ch = (h - pad * (rows + 1)) / rows
    r = min(cw, ch) * 0.30
    for i in range(total):
        c, rr = i % cols, i // cols
        cx = pad + c * (cw + pad) + cw / 2
        cy = pad + rr * (ch + pad) + ch / 2
        on = i < shown
        pop = 1.0
        if on:
            age = (shown - i) / max(1, total * 0.25)
            pop = 1.0 + 0.55 * max(0.0, 0.25 - age) / 0.25
        elif i >= shown:
            pop = 1.0
        rr2 = r * pop
        if on:
            d.ellipse([cx - rr2, cy - rr2, cx + rr2, cy + rr2], fill=LIME + (245,))
        else:
            d.ellipse([cx - rr2, cy - rr2, cx + rr2, cy + rr2],
                      fill=(255, 255, 255, 26), outline=(255, 255, 255, 40))
    return im


def fade(im: Image.Image, a: float) -> Image.Image:
    if a >= 0.999:
        return im
    im = im.copy()
    alpha = im.getchannel("A").point(lambda v: int(v * a))
    im.putalpha(alpha)
    return im


def scale_in(im: Image.Image, k: float) -> Image.Image:
    if k >= 0.999:
        return im
    w, h = im.size
    nw, nh = max(2, int(w * k)), max(2, int(h * k))
    small = im.resize((nw, nh), Image.LANCZOS)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.paste(small, ((w - nw) // 2, (h - nh) // 2), small)
    return out


def fmt_money(v: float, currency: bool = True) -> str:
    s = f"{int(round(v)):,}"
    return ("$" + s) if currency else s


# ----------------------------------------------------------------- card renderers
def card_counter(dur: float, w: int, h: int, *, label: str, value: float, unit: str,
                 currency: bool = True, accent_note: str = ""):
    def frame(t: float) -> Image.Image:
        base = panel(w, h)
        d = ImageDraw.Draw(base)
        text(d, (44, 58), label.upper(), font(34), fill=LIME + (255,), anchor="lm")
        k = ease_out(min(1.0, t / max(0.9, dur * 0.45)))
        num = value * k
        size = 128
        f = font(size)
        while size > 60 and d.textlength(fmt_money(num, currency), font=f) > w * 0.86:
            size -= 6
            f = font(size)
        text(d, (44, h * 0.52), fmt_money(num, currency), f, fill=WHITE + (255,), anchor="lm")
        tw = d.textlength(fmt_money(num, currency), font=f)
        text(d, (44 + tw + 16, h * 0.52 + size * 0.22), unit, font(44), fill=LIME + (255,),
             anchor="lm")
        if accent_note:
            text(d, (44, h * 0.80), accent_note, font(32, False), fill=GREY + (255,), anchor="lm")
        return base
    return frame


def card_cost(dur: float, w: int, h: int, *, value: float, label: str, sub: str):
    def frame(t: float) -> Image.Image:
        base = panel(w, h)
        d = ImageDraw.Draw(base)
        text(d, (44, 56), label.upper(), font(33), fill=LIME + (255,), anchor="lm")
        k = ease_out(min(1.0, t / max(0.8, dur * 0.4)))
        num = value * k
        f = font(120)
        while d.textlength(fmt_money(num), font=f) > w * 0.52:
            f = font(f.size - 6)
        text(d, (44, h * 0.50), fmt_money(num), f, fill=WHITE + (255,), anchor="lm")
        tw = d.textlength(fmt_money(num), font=f)
        text(d, (44 + tw + 14, h * 0.50 + 20), "/mo", font(44), fill=LIME + (255,), anchor="lm")
        text(d, (44, h * 0.76), sub, font(31, False), fill=GREY + (255,), anchor="lm")
        icon = money_icon(int(w * 0.30), int(h * 0.46), min(1.0, t / 0.6))
        base.alpha_composite(icon, (int(w * 0.66), int(h * 0.34)))
        return base
    return frame


def card_people(dur: float, w: int, h: int, *, total: int, label: str, sub: str):
    def frame(t: float) -> Image.Image:
        base = panel(w, h)
        d = ImageDraw.Draw(base)
        text(d, (44, 56), label.upper(), font(33), fill=LIME + (255,), anchor="lm")
        k = ease_inout(min(1.0, t / max(1.0, dur * 0.62)))
        shown = int(total * k)
        f = font(112)
        text(d, (44, h * 0.48), str(int(total * k)), f, fill=WHITE + (255,), anchor="lm")
        tw = d.textlength(str(int(total * k)), font=f)
        text(d, (44 + tw + 14, h * 0.48 + 18), "people", font(44), fill=LIME + (255,), anchor="lm")
        text(d, (44, h * 0.74), sub, font(31, False), fill=GREY + (255,), anchor="lm")
        g = dots_grid(int(w * 0.44), int(h * 0.62), min(1.0, t / 0.5), 400, int(shown / max(1, total) * 400))
        base.alpha_composite(g, (int(w * 0.52), int(h * 0.24)))
        return base
    return frame


def card_math(dur: float, w: int, h: int, *, left: str, right: str, result: str, label: str):
    def frame(t: float) -> Image.Image:
        base = panel(w, h)
        d = ImageDraw.Draw(base)
        text(d, (44, 56), label.upper(), font(33), fill=LIME + (255,), anchor="lm")
        parts = [left, "÷", right, "=", result]
        x = 44
        for i, p in enumerate(parts):
            appear = min(1.0, max(0.0, (t - 0.22 * i) / 0.30))
            if appear <= 0:
                break
            col = LIME + (int(255 * appear),) if i == 4 else WHITE + (int(255 * appear),)
            f = font(72 if i == 4 else 62)
            d.text((x, h * 0.50), p, font=f, fill=col, anchor="lm")
            x += d.textlength(p, font=f) + 20
        text(d, (44, h * 0.78), "per person, per month", font(31, False),
             fill=GREY + (255,), anchor="lm")
        return base
    return frame


def icon_globe(im: Image.Image, box, t: float):
    d = ImageDraw.Draw(im)
    x0, y0, x1, y1 = box
    cx, cy, r = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=LIME + (235,), width=6)
    d.ellipse([cx - r * 0.45, cy - r, cx + r * 0.45, cy + r], outline=LIME + (170,), width=4)
    d.line([cx - r, cy, cx + r, cy], fill=LIME + (170,), width=4)
    for f in (0.45, -0.45):
        d.arc([cx - r, cy - r * abs(f) * 2.2, cx + r, cy + r * abs(f) * 2.2],
              start=200 if f > 0 else 20, end=340 if f > 0 else 160,
              fill=LIME + (150,), width=3)
    d.line([cx - r * 1.15, cy + r * 0.55, cx + r * 1.15, cy + r * 0.55],
           fill=(255, 255, 255, 60), width=2)


def icon_ai(im: Image.Image, box, t: float):
    d = ImageDraw.Draw(im)
    x0, y0, x1, y1 = box
    s = min(x1 - x0, y1 - y0)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    r = s * 0.30
    d.rounded_rectangle([cx - r, cy - r, cx + r, cy + r], radius=r * 0.28,
                        outline=LIME + (240,), width=6)
    d.rounded_rectangle([cx - r * 0.42, cy - r * 0.42, cx + r * 0.42, cy + r * 0.42],
                        radius=r * 0.18, fill=LIME + (200,))
    for k in (-0.5, 0.0, 0.5):
        for sgn in (-1, 1):
            d.line([cx + k * r, cy + sgn * r * 1.0, cx + k * r, cy + sgn * r * 1.45],
                   fill=LIME + (230,), width=5)
            d.line([cx + sgn * r * 1.0, cy + k * r, cx + sgn * r * 1.45, cy + k * r],
                   fill=LIME + (230,), width=5)


ICONS = {"globe": icon_globe, "ai": icon_ai}


def card_chip(dur: float, w: int, h: int, *, label: str, sub: str, icon: str = "ai"):
    def frame(t: float) -> Image.Image:
        base = panel(w, h)
        d = ImageDraw.Draw(base)
        ICONS.get(icon, icon_ai)(base, (int(w * 0.60), int(h * 0.22),
                                        int(w * 0.94), int(h * 0.80)), t)
        f = font(64)
        while f.size > 40 and d.textlength(label, font=f) > w * 0.52:
            f = font(f.size - 3)
        text(d, (44, h * 0.42), label, f, fill=WHITE + (255,), anchor="lm")
        text(d, (44, h * 0.68), sub, font(40, False), fill=LIME + (240,), anchor="lm")
        return base
    return frame


def card_quote(dur: float, w: int, h: int, *, text_line: str, who: str):
    def frame(t: float) -> Image.Image:
        base = panel(w, h)
        d = ImageDraw.Draw(base)
        text(d, (58, 96), "\u201c", font(104), fill=LIME + (255,), anchor="lm")
        f = font(58)
        while f.size > 34 and d.textlength(text_line, font=f) > w * 0.80:
            f = font(f.size - 3)
        text(d, (116, h * 0.40), text_line, f, fill=WHITE + (255,), anchor="lm")
        text(d, (116, h * 0.66), who.upper(), font(30), fill=GREY + (255,), anchor="lm")
        return base
    return frame


CARD_TYPES = {"counter": card_counter, "cost": card_cost, "people": card_people,
              "math": card_math, "chip": card_chip, "quote": card_quote}


def render_card(path: Path, spec: dict, fps: int = 30, size=(1080, 470)) -> dict:
    """Render one card to an alpha video (qtrle) and return its manifest."""
    w, h = size
    dur = float(spec["end"]) - float(spec["start"])
    n = max(2, int(round(dur * fps)))
    maker = CARD_TYPES[spec["type"]](dur, w, h, **spec["params"])
    cmd = [FF, "-nostdin", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba",
           "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
           "-c:v", "qtrle", "-pix_fmt", "argb", str(path)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(n):
        t = i / fps
        im = maker(t)
        a = 1.0
        if t < 0.28:
            a = t / 0.28
        if t > dur - 0.22:
            a = max(0.0, (dur - t) / 0.22)
        im = fade(im, ease_out(a) if t < 0.28 else a)
        if t < 0.42:
            im = scale_in(im, 0.90 + 0.10 * ease_back(t / 0.42))
        p.stdin.write(np.array(im, dtype=np.uint8).tobytes())
    p.stdin.close()
    p.wait()
    return {"path": str(path), "start": spec["start"], "end": spec["end"],
            "x": spec.get("x", 0), "y": spec.get("y", 925), "w": w, "h": h,
            "kind": spec["type"], "label": spec.get("label", spec["type"])}
