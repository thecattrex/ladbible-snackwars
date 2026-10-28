#!/usr/bin/env python3
"""Motion graphics — the "explain what he is saying" layer, built to editor craft.

What makes a graphic read as human-made rather than machine-made (all four come
from how editors actually work, see docs/CRAFT.md):

  1. typography — a condensed display face for numbers, a grotesque for labels,
     never the default system sans;
  2. hierarchy — kicker, value, unit, rule. A viewer reads it in one glance;
  3. motion — ease-out-expo entries with a stagger between layers, exits fast and
     short; nothing fades in linearly;
  4. restraint — a scrim and a single accent rule instead of a heavy black box,
     plus a light grain so the card sits in the same film as the footage.

Every card is drawn from primitives at render time (the campaign forbids outside
footage) and emitted as an alpha video for the compositor.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FF = imageio_ffmpeg.get_ffmpeg_exe()
ASSETS = Path(__file__).resolve().parent.parent / "assets"
LIME = (198, 255, 0)
WHITE = (255, 255, 255)
INK = (8, 10, 13)
GREY = (176, 186, 198)
MARGIN = 46


def _font(file: str, size: int):
    for base in (ASSETS, Path("/usr/share/fonts/truetype/dejavu")):
        p = base / file
        if p.exists():
            return ImageFont.truetype(str(p), size)
    raise SystemExit(f"font missing: {file}")


def display(size: int):
    return _font("Anton-Regular.ttf", size)


def grotesk(size: int, bold: bool = True):
    return _font("ArchivoBlack-Regular.ttf" if bold else "Inter.ttf", size)


def ui(size: int):
    return _font("Inter.ttf", size)


# ------------------------------------------------------------------ easing
def ease_out_expo(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1.0 if t >= 1 else 1 - 2 ** (-10 * t)


def ease_out_cubic(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def ease_inout_cubic(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def spring(t: float, damp: float = 0.55) -> float:
    """A small settle overshoot — the difference between 'moved' and 'animated'."""
    t = max(0.0, min(1.0, t))
    if t >= 1:
        return 1.0
    return 1 - (2.718 ** (-6 * t)) * np.cos(9 * t) * damp - (1 - damp)


# ------------------------------------------------------------------ surfaces
def scrim(w: int, h: int, radius: int = 26, strength: int = 158) -> Image.Image:
    """Dark glass card: soft shadow, no hard box, one lime registration rule."""
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ds = ImageDraw.Draw(sh)
    ds.rounded_rectangle([8, 16, w - 8, h - 8], radius=radius, fill=(0, 0, 0, 150))
    im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(14)))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, w - 16, h - 20], radius=radius,
                        fill=(INK[0], INK[1], INK[2], strength))
    d.rounded_rectangle([6, 6, w - 22, h - 26], radius=radius - 6,
                        outline=(255, 255, 255, 16), width=1)
    # registration rule: reads as a designer's mark, not a template border
    d.rounded_rectangle([0, 26, 7, h - 46], radius=4, fill=LIME + (255,))
    return im


def band(w: int, h: int, from_bottom: float = 0.55, top_alpha: int = 0,
         bottom_alpha: int = 205) -> Image.Image:
    """A soft vertical gradient over the footage — no hard box, no player chrome."""
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = im.load()
    for y in range(h):
        f = y / max(1, h - 1)
        a = int(top_alpha + (bottom_alpha - top_alpha) * (f ** 1.6))
        for x in range(w):
            px[x, y] = (6, 8, 11, a)
    d = ImageDraw.Draw(im)
    d.rectangle([MARGIN, int(h * 0.10), MARGIN + 92, int(h * 0.10) + 8], fill=LIME + (255,))
    return im


def grain(im: Image.Image, amount: float = 5.0, seed: int = 0) -> Image.Image:
    """A little film grain so the card belongs to the same image as the footage."""
    rng = np.random.default_rng(seed)
    a = np.array(im).astype(np.int16)
    n = rng.normal(0, amount, a.shape[:2])[:, :, None]
    a[:, :, :3] = np.clip(a[:, :, :3] + n, 0, 255)
    return Image.fromarray(a.astype(np.uint8), "RGBA")


def draw_underline(d: ImageDraw.ImageDraw, x0: int, y: int, w: int, progress: float,
                   thickness: int = 7, colour=LIME):
    """Hand-drawn feel: the line grows from the left with a gentle wobble."""
    if progress <= 0:
        return
    steps = max(2, int(28 * progress))
    pts = []
    for i in range(steps + 1):
        f = i / steps
        pts.append((x0 + int(w * progress * f), y + int(2.2 * np.sin(f * 7.5))))
    d.line(pts, fill=colour + (255,), width=thickness, joint="curve")


def glyph(d, xy, s, f, fill=WHITE, anchor="lm", tracking: float = 0.0,
          stroke: int = 0, stroke_fill=(0, 0, 0, 200)):
    """Text with optional letter-spacing (PIL has none, so draw char by char)."""
    if tracking == 0:
        d.text(xy, s, font=f, fill=fill, anchor=anchor, stroke_width=stroke,
               stroke_fill=stroke_fill)
        return
    x, y = xy
    total = sum(d.textlength(c, font=f) + tracking for c in s) - tracking
    if anchor[0] == "m":
        x -= total / 2
    for c in s:
        d.text((x, y), c, font=f, fill=fill, anchor="l" + anchor[1], stroke_width=stroke,
               stroke_fill=stroke_fill)
        x += d.textlength(c, font=f) + tracking


def kicker(d, xy, s, colour=LIME, size=30):
    glyph(d, xy, s.upper(), ui(size), fill=colour + (255,), anchor="lm", tracking=6)


def money_note(w: int, h: int, t: float) -> Image.Image:
    """A banknote with a proper isometric tilt and engraved detail."""
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    k = ease_out_cubic(min(1.0, t / 0.5))
    tilt = 0.13 * (1 - k)
    cx, cy = w / 2, h / 2
    bw, bh = w * 0.74, h * 0.50

    def quad(scale, dy):
        half_w = bw * scale / 2
        half_h = bh * scale / 2
        return [(cx - half_w + tilt * 26, cy - half_h + dy),
                (cx + half_w + tilt * 26, cy - half_h + dy + tilt * 30),
                (cx + half_w - tilt * 18, cy + half_h + dy + tilt * 8),
                (cx - half_w - tilt * 18, cy + half_h + dy - tilt * 16)]

    for i, (scale, dy) in enumerate([(0.88, 30), (0.94, 15), (1.0, 0)]):
        col = (24 + i * 6, 62 + i * 12, 40 + i * 10, 255) if i < 2 else (30, 118, 70, 255)
        d.polygon(quad(scale, dy), fill=col, outline=(150, 220, 175, 90))
    pts = quad(1.0, 0)
    d.polygon(pts, fill=(36, 140, 82, 255), outline=(196, 245, 210, 180))
    cx2 = sum(p[0] for p in pts) / 4
    cy2 = sum(p[1] for p in pts) / 4
    r = bh * 0.26
    d.ellipse([cx2 - r, cy2 - r * 0.92, cx2 + r, cy2 + r * 0.92],
              outline=(210, 250, 220, 210), width=4)
    d.text((cx2, cy2 + 1), "$", font=display(int(bh * 0.42)), fill=(225, 250, 232, 235),
           anchor="mm")
    return im


def icon_chip(im, box, t):
    d = ImageDraw.Draw(im)
    x0, y0, x1, y1 = box
    s = min(x1 - x0, y1 - y0)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    r = s * 0.26
    k = ease_out_cubic(min(1.0, t / 0.45))
    r *= 0.85 + 0.15 * k
    d.rounded_rectangle([cx - r, cy - r, cx + r, cy + r], radius=r * 0.26,
                        outline=LIME + (245,), width=5)
    d.rounded_rectangle([cx - r * 0.40, cy - r * 0.40, cx + r * 0.40, cy + r * 0.40],
                        radius=r * 0.16, fill=LIME + (210,))
    for f in (-0.45, 0.0, 0.45):
        for sgn in (-1, 1):
            d.line([cx + f * r, cy + sgn * r * 1.02, cx + f * r, cy + sgn * r * 1.40],
                   fill=LIME + (220,), width=4)
            d.line([cx + sgn * r * 1.02, cy + f * r, cx + sgn * r * 1.40, cy + f * r],
                   fill=LIME + (220,), width=4)


def icon_globe(im, box, t):
    d = ImageDraw.Draw(im)
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    r = (x1 - x0) / 2 * (0.86 + 0.14 * ease_out_cubic(min(1.0, t / 0.45)))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=LIME + (240,), width=5)
    d.ellipse([cx - r * 0.44, cy - r, cx + r * 0.44, cy + r], outline=LIME + (150,), width=3)
    d.line([cx - r, cy, cx + r, cy], fill=LIME + (150,), width=3)
    d.arc([cx - r, cy - r * 0.92, cx + r, cy + r * 0.92], 200, 340, fill=LIME + (130,), width=3)
    d.arc([cx - r, cy - r * 0.92, cx + r, cy + r * 0.92], 20, 160, fill=LIME + (130,), width=3)


# ------------------------------------------------------------------ card bodies
def _layout(w: int, h: int, kicker_text: str, value: str, unit: str, sub: str,
            value_px: int = 120, unit_px: int = 38, sub_px: int = 29):
    """Draw the shared hierarchy: kicker / value + unit / rule / sub."""
    im = scrim(w, h)
    d = ImageDraw.Draw(im)
    if kicker_text:
        kicker(d, (MARGIN + 16, 54), kicker_text)
    f = display(value_px)
    while value_px > 56 and d.textlength(value, font=f) > w * 0.80:
        value_px -= 4
        f = display(value_px)
    vy = int(h * 0.50)
    d.text((MARGIN, vy), value, font=f, fill=WHITE + (255,), anchor="lm")
    vw = d.textlength(value, font=f)
    if unit:
        d.text((MARGIN + vw + 14, vy + value_px * 0.20), unit, font=ui(unit_px),
               fill=LIME + (255,), anchor="lm")
    if sub:
        d.text((MARGIN, h - 52), sub, font=ui(sub_px), fill=GREY + (255,), anchor="lm")
    return im, d, vy + value_px * 0.42, vw


def fmt(v: float, currency: bool = True) -> str:
    s = f"{int(round(v)):,}"
    return ("$" + s) if currency else s


def card_counter(dur, w, h, *, label, value, unit, currency=True, accent_note=""):
    def frame(t):
        k = ease_out_expo(min(1.0, t / max(0.55, dur * 0.38)))
        im = band(w, h)
        d = ImageDraw.Draw(im)
        if label:
            kicker(d, (MARGIN, int(h * 0.26)), label)
        value_s = fmt(value * k, currency)
        px = 132
        f = display(px)
        while px > 64 and d.textlength(value_s, font=f) > w * 0.74:
            px -= 4
            f = display(px)
        d.text((MARGIN, int(h * 0.58)), value_s, font=f, fill=WHITE + (255,), anchor="lm")
        vw = d.textlength(value_s, font=f)
        if unit:
            d.text((MARGIN + vw + 16, int(h * 0.58) + px * 0.18), unit, font=ui(36),
                   fill=LIME + (255,), anchor="lm")
        if accent_note:
            d.text((MARGIN, h - 46), accent_note, font=ui(29), fill=(205, 212, 220, 255),
                   anchor="lm")
        draw_underline(d, MARGIN, int(h * 0.58 + px * 0.52), int(w * 0.26),
                       ease_inout_cubic(min(1.0, t / 0.7)))
        return grain(im, 3.0, seed=int(t * 30) % 97)
    return frame


def card_cost(dur, w, h, *, value, label, sub):
    def frame(t):
        k = ease_out_expo(min(1.0, t / max(0.5, dur * 0.34)))
        im = band(w, h)
        d = ImageDraw.Draw(im)
        kicker(d, (MARGIN, int(h * 0.26)), label)
        value_s = fmt(value * k)
        px = 126
        f = display(px)
        while px > 60 and d.textlength(value_s, font=f) > w * 0.52:
            px -= 4
            f = display(px)
        d.text((MARGIN, int(h * 0.60)), value_s, font=f, fill=WHITE + (255,), anchor="lm")
        vw = d.textlength(value_s, font=f)
        d.text((MARGIN + vw + 14, int(h * 0.60) + px * 0.18), "/mo", font=ui(36),
               fill=LIME + (255,), anchor="lm")
        if sub:
            d.text((MARGIN, h - 46), sub, font=ui(29), fill=(205, 212, 220, 255), anchor="lm")
        draw_underline(d, MARGIN, int(h * 0.60 + px * 0.52), int(w * 0.22),
                       ease_inout_cubic(min(1.0, t / 0.7)))
        note = money_note(int(w * 0.22), int(h * 0.62), t)
        im.alpha_composite(note, (int(w * 0.72), int(h * 0.22)))
        return grain(im, 3.0, seed=int(t * 30) % 97)
    return frame


def card_people(dur, w, h, *, total, label, sub):
    def frame(t):
        k = ease_inout_cubic(min(1.0, t / max(0.8, dur * 0.55)))
        im = band(w, h)
        d = ImageDraw.Draw(im)
        kicker(d, (MARGIN, int(h * 0.26)), label)
        value_s = str(int(total * k))
        f = display(124)
        d.text((MARGIN, int(h * 0.60)), value_s, font=f, fill=WHITE + (255,), anchor="lm")
        vw = d.textlength(value_s, font=f)
        d.text((MARGIN + vw + 14, int(h * 0.60) + 22), "people", font=ui(36),
               fill=LIME + (255,), anchor="lm")
        if sub:
            d.text((MARGIN, h - 46), sub, font=ui(29), fill=(205, 212, 220, 255), anchor="lm")
        draw_underline(d, MARGIN, int(h * 0.60 + 64), int(w * 0.22),
                       ease_inout_cubic(min(1.0, t / 0.7)))
        gw, gh = int(w * 0.26), int(h * 0.50)
        g = Image.new("RGBA", (gw, gh), (0, 0, 0, 0))
        gd = ImageDraw.Draw(g)
        cols, rows, pad = 20, 20, 3
        cw = (gw - pad * (cols + 1)) / cols
        ch = (gh - pad * (rows + 1)) / rows
        r = min(cw, ch) * 0.34
        shown = int(400 * k)
        for i in range(400):
            c, rr = i % cols, i // cols
            cx = pad + c * (cw + pad) + cw / 2
            cy = pad + rr * (ch + pad) + ch / 2
            if i < shown:
                gd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=LIME + (230,))
            else:
                gd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, 26))
        im.alpha_composite(g, (int(w * 0.70), int(h * 0.22)))
        return grain(im, 3.0, seed=int(t * 30) % 97)
    return frame


def card_math(dur, w, h, *, left, right, result, label):
    def frame(t):
        im = band(w, h)
        d = ImageDraw.Draw(im)
        kicker(d, (MARGIN, int(h * 0.26)), label)
        parts = [(left, display(62), WHITE), ("÷", display(52), GREY),
                 (right, display(62), WHITE), ("=", display(52), GREY),
                 (result, display(78), LIME)]
        x = MARGIN
        base_y = int(h * 0.56)
        for i, (p, f, col) in enumerate(parts):
            appear = ease_out_expo(min(1.0, max(0.0, (t - 0.10 * i) / 0.28)))
            if appear <= 0:
                break
            d.text((x, base_y + int((1 - appear) * 20)), p, font=f,
                   fill=col + (int(255 * appear),), anchor="lm")
            x += d.textlength(p, font=f) + 16
        d.text((MARGIN, h - 46), "per person, per month", font=ui(29),
               fill=(205, 212, 220, 255), anchor="lm")
        draw_underline(d, MARGIN, int(base_y + 58), int(w * 0.34),
                       ease_inout_cubic(min(1.0, max(0.0, (t - 0.45) / 0.6))))
        return grain(im, 3.0, seed=int(t * 30) % 97)
    return frame


def card_chip(dur, w, h, *, label, sub, icon="ai"):
    def frame(t):
        im = band(w, h, top_alpha=0, bottom_alpha=190)
        d = ImageDraw.Draw(im)
        (icon_chip if icon == "ai" else icon_globe)(
            im, (int(w * 0.72), int(h * 0.18), int(w * 0.95), int(h * 0.78)), t)
        f = display(66)
        while f.size > 40 and d.textlength(label, font=f) > w * 0.54:
            f = display(f.size - 3)
        d.text((MARGIN, int(h * 0.52)), label, font=f, fill=WHITE + (255,), anchor="lm")
        d.text((MARGIN, int(h * 0.74)), sub, font=ui(34), fill=LIME + (245,), anchor="lm")
        draw_underline(d, MARGIN, int(h * 0.84), int(w * 0.22),
                       ease_inout_cubic(min(1.0, t / 0.6)))
        return grain(im, 3.0, seed=int(t * 30) % 97)
    return frame


def card_quote(dur, w, h, *, text_line, who):
    def frame(t):
        im = band(w, h, top_alpha=0, bottom_alpha=200)
        d = ImageDraw.Draw(im)
        k = ease_out_expo(min(1.0, t / 0.4))
        f = grotesk(48)
        while f.size > 26 and d.textlength(text_line, font=f) > w * 0.82:
            f = grotesk(f.size - 2)
        d.text((MARGIN, int(h * 0.50)), text_line, font=f,
               fill=WHITE + (int(255 * k),), anchor="lm")
        d.line([MARGIN, int(h * 0.66), MARGIN + int(34 * k), int(h * 0.66)],
               fill=LIME + (255,), width=5)
        d.text((MARGIN + 50, int(h * 0.66)), who.upper(), font=ui(26), fill=(205, 212, 220, 255),
               anchor="lm")
        return grain(im, 3.0, seed=int(t * 30) % 97)
    return frame


CARD_TYPES = {"counter": card_counter, "cost": card_cost, "people": card_people,
              "math": card_math, "chip": card_chip, "quote": card_quote}


def _composite_move(im: Image.Image, dy: int, k: float) -> Image.Image:
    out = Image.new("RGBA", im.size, (0, 0, 0, 0))
    out.alpha_composite(im, (0, dy))
    return out if k >= 1 else _alpha(out, k)


def _alpha(im: Image.Image, a: float) -> Image.Image:
    if a >= 0.999:
        return im
    im = im.copy()
    im.putalpha(im.getchannel("A").point(lambda v: int(v * a)))
    return im


def _scale(im: Image.Image, k: float) -> Image.Image:
    if abs(k - 1.0) < 0.002:
        return im
    w, h = im.size
    nw, nh = max(2, int(w * k)), max(2, int(h * k))
    small = im.resize((nw, nh), Image.LANCZOS)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.paste(small, ((w - nw) // 2, (h - nh) // 2), small)
    return out


def render_card(path: Path, spec: dict, fps: int = 30, size=(1080, 470)) -> dict:
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
        # entry: 26 px rise + 4% scale settle over 240 ms, opacity in 160 ms
        if t < 0.24:
            k = ease_out_expo(t / 0.24)
            im = _composite_move(im, int(26 * (1 - k)), 1.0)
            im = _scale(im, 0.965 + 0.035 * spring(t / 0.30))
        # exit: 8 px lift, fast fade — a slow exit reads as a slideshow
        if t > dur - 0.20:
            k = (dur - t) / 0.20
            im = _alpha(im, ease_out_cubic(k))
            im = _composite_move(im, -int(8 * (1 - k)), 1.0)
        if t < 0.16:
            im = _alpha(im, ease_out_cubic(t / 0.16))
        p.stdin.write(np.array(im, dtype=np.uint8).tobytes())
    p.stdin.close()
    p.wait()
    return {"path": str(path), "start": spec["start"], "end": spec["end"],
            "x": spec.get("x", 0), "y": spec.get("y", 925), "w": w, "h": h,
            "kind": spec["type"], "label": spec.get("label", spec["type"])}
