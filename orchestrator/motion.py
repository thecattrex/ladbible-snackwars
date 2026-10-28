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
GREY = (184, 194, 206)
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


# ------------------------------------------------------------------ card bodies
# What the second cut changed, and why
# ------------------------------------
# The first graphics pass still read as machine output. Three tells, all of them
# software habits rather than editing habits:
#
#   * an icon next to every card (chip, globe, dotted 400-grid, a cartoon
#     banknote) — nothing a podcast editor would cut in;
#   * numbers that count up from zero, so "$10,000" was on screen as "$1,812"
#     for half a second — that is a motion-graphics template, and it can even
#     read as a false claim;
#   * one recipe for every card: kicker + value + underline, on the same beat.
#
# Human editors type on. Type wipes in from its own left edge in about 120 ms,
# sits still, and is cut off. Numbers appear whole. Emphasis is one marker swipe
# behind one word, angled slightly differently every time. No icons at all.

def _tlayer(size, xy, text, font, fill, anchor="lm", tracking=0.0):
    im = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    glyph(d, xy, text, font, fill=fill, anchor=anchor, tracking=tracking)
    return im


def _wipe_mask(w: int, h: int, x: float, soft: int = 18) -> Image.Image:
    a = np.clip((x - np.arange(w)) / max(1, soft), 0.0, 1.0) * 255.0
    return Image.fromarray(np.tile(a.astype(np.uint8), (h, 1)), "L")


def _revealed(layer: Image.Image, p: float, soft: int = 18):
    """Type-on: the layer is uncovered from its own left edge."""
    if p <= 0:
        return None
    if p >= 1:
        return layer
    w, h = layer.size
    mask = _wipe_mask(w, h, w * ease_out_cubic(p) + 1, soft)
    out = layer.copy()
    out.putalpha(Image.composite(out.getchannel("A"), Image.new("L", (w, h), 0), mask))
    return out


def _shadowed(im: Image.Image, blur: int = 9, alpha: int = 170) -> Image.Image:
    """Drop shadow instead of a black box: the type sits in the picture."""
    a = im.getchannel("A")
    sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
    sh.putalpha(a.filter(ImageFilter.GaussianBlur(blur)).point(lambda v: int(v * alpha / 255)))
    out = Image.new("RGBA", im.size, (0, 0, 0, 0))
    out.alpha_composite(sh, (0, 3))
    out.alpha_composite(im)
    return out


def _marker(im, box, p: float, seed: int = 0):
    """A highlighter stroke behind one word: rough edges, slightly off level."""
    if p <= 0:
        return
    w, h = im.size
    x0, y0, x1, y1 = box
    rng = np.random.default_rng(seed)
    lay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    n = 7
    top = [(x0 + (x1 - x0) * i / n, y0 + rng.uniform(-3, 3)) for i in range(n + 1)]
    bot = [(x0 + (x1 - x0) * (n - i) / n, y1 + rng.uniform(-4, 4)) for i in range(n + 1)]
    d.polygon(top + bot, fill=LIME + (210,))
    d.polygon([(x0 - 6, y0 + 2), (x0 + 24, y0 - 2), (x0 + 20, y1), (x0 - 8, y1 - 3)],
              fill=LIME + (180,))
    reveal = _revealed(lay, p, soft=34)
    if reveal is not None:
        im.alpha_composite(reveal)


def _block(d, x, y, lines, sizes, gap=None):
    pass


def fmt(v: float, currency: bool = True) -> str:
    s = f"{int(round(v)):,}"
    return ("$" + s) if currency else s


def _value_card(dur, w, h, *, label, value_s, unit, note, value_px, swipe_word=None,
                seed=0):
    """Shared skeleton: label, one big number, unit, one line of context."""
    def frame(t):
        vpx = value_px
        im = band(w, h, top_alpha=0, bottom_alpha=178)
        # accent tick, left of the number — an editor's mark, not an icon
        tick_p = min(1.0, max(0.0, (t - 0.02) / 0.16))
        if tick_p > 0:
            d = ImageDraw.Draw(im)
            th = int(vpx * 0.58 * ease_out_expo(tick_p))
            d.rectangle([MARGIN, int(h * 0.60) - th // 2, MARGIN + 8,
                         int(h * 0.60) + th // 2], fill=LIME + (255,))
        if label:
            lay = _tlayer((w, h), (MARGIN + 40, int(h * 0.19)), label.upper(),
                          ui(30), WHITE + (238,), tracking=7)
            r = _revealed(lay, (t - 0.00) / 0.14)
            if r is not None:
                im.alpha_composite(_shadowed(r, 8, 215))
        f = display(vpx)
        while vpx > 54 and d_length(im.size, value_s, f) > w * 0.78:
            vpx -= 4
            f = display(vpx)
        lay = _tlayer((w, h), (MARGIN + 40, int(h * 0.60)), value_s, f, WHITE + (255,),
                      anchor="ls")
        r = _revealed(lay, (t - 0.05) / 0.16, soft=14)
        if r is not None:
            im.alpha_composite(_shadowed(r, 10, 185))
        if unit:
            vw = _measure(value_s, f)
            ul = _tlayer((w, h), (MARGIN + 40 + vw + 16, int(h * 0.60) - 6), unit,
                         ui(38), LIME + (255,))
            r = _revealed(ul, (t - 0.17) / 0.14)
            if r is not None:
                im.alpha_composite(_shadowed(r, 7, 160))
        if note:
            nl = _tlayer((w, h), (MARGIN + 40, int(h * 0.82)), note, ui(30),
                         (206, 213, 221, 255))
            r = _revealed(nl, (t - 0.26) / 0.16)
            if r is not None:
                im.alpha_composite(_shadowed(r, 7, 150))
        return grain(im, 2.4, seed=int(t * 30) % 97)
    return frame


def d_length(size, text, font):
    tmp = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    return tmp.textlength(text, font=font)


def _measure(text, font):
    return ImageDraw.Draw(Image.new("RGB", (8, 8))).textlength(text, font=font)


def card_counter(dur, w, h, *, label, value, unit, currency=True, accent_note=""):
    return _value_card(dur, w, h, label=label, value_s=fmt(value, currency), unit=unit,
                       note=accent_note, value_px=150)


def card_cost(dur, w, h, *, value, label, sub):
    return _value_card(dur, w, h, label=label, value_s=fmt(value), unit="/mo",
                       note=sub, value_px=150)


def card_people(dur, w, h, *, total, label, sub):
    return _value_card(dur, w, h, label=label, value_s=str(int(total)), unit="people",
                       note=sub, value_px=150)


def card_math(dur, w, h, *, left, right, result, label):
    """Two facts and the answer, typing on one beat at a time."""
    def frame(t):
        im = band(w, h, top_alpha=0, bottom_alpha=120)
        if label:
            lay = _tlayer((w, h), (MARGIN, int(h * 0.22)), label.upper(), ui(30),
                          WHITE + (238,), tracking=7)
            r = _revealed(lay, t / 0.14)
            if r is not None:
                im.alpha_composite(_shadowed(r, 8, 215))
        y = int(h * 0.66)
        x = MARGIN
        seq = [(left, display(72), WHITE, 0.00), ("÷", grotesk(70), GREY, 0.10),
               (right, display(72), WHITE, 0.16), ("=", grotesk(70), GREY, 0.26),
               (result, display(92), LIME, 0.32)]
        for text, f, col, at in seq:
            r = _revealed(_tlayer((w, h), (x, y), text, f, col + (255,), anchor="ls"),
                          (t - at) / 0.13, soft=12)
            if r is not None:
                im.alpha_composite(_shadowed(r, 9, 175))
            x += _measure(text, f) + 18
        nl = _tlayer((w, h), (MARGIN, int(h * 0.90)), "per person, per month", ui(30),
                     (206, 213, 221, 255))
        r = _revealed(nl, (t - 0.5) / 0.16)
        if r is not None:
            im.alpha_composite(_shadowed(r, 7, 150))
        return grain(im, 2.4, seed=int(t * 30) % 97)
    return frame


def card_chip(dur, w, h, *, label, sub, icon=None):
    """A question with its second half landing a beat later. No icon: the type
    is the graphic, which is what the reference edit does."""
    def frame(t):
        im = band(w, h, top_alpha=0, bottom_alpha=110)
        f = grotesk(64)
        while f.size > 38 and d_length(im.size, label, f) > w * 0.84:
            f = grotesk(f.size - 3)
        lay = _tlayer((w, h), (MARGIN, int(h * 0.52)), label, f, WHITE + (255,), anchor="ls")
        r = _revealed(lay, t / 0.15, soft=14)
        if r is not None:
            im.alpha_composite(_shadowed(r, 10, 185))
        if sub:
            fs = grotesk(52)
            while fs.size > 32 and d_length(im.size, sub, fs) > w * 0.84:
                fs = grotesk(fs.size - 3)
            sw_w = _measure(sub, fs)
            _marker(im, (MARGIN - 8, int(h * 0.74) - 46, MARGIN + sw_w + 8, int(h * 0.74)),
                    (t - 0.22) / 0.18, seed=len(sub))
            lay = _tlayer((w, h), (MARGIN, int(h * 0.74)), sub, fs, INK + (255,), anchor="ls")
            r = _revealed(lay, (t - 0.22) / 0.16, soft=14)
            if r is not None:
                im.alpha_composite(r)
        return grain(im, 2.4, seed=int(t * 30) % 97)
    return frame


def card_quote(dur, w, h, *, text_line, who):
    """One line, one marked word, attribution underneath."""
    def frame(t):
        im = band(w, h, top_alpha=0, bottom_alpha=130)
        words = text_line.split()
        f = grotesk(54)
        while f.size > 30 and d_length(im.size, text_line, f) > w * 0.86:
            f = grotesk(f.size - 2)
        mark_n = min(3, max(1, len(words) // 2))
        pre = " ".join(words[:-mark_n])
        mark = " ".join(words[-mark_n:])
        base = int(h * 0.50)
        pick = display(f.size + 2)          # the marked words in the display face
        x_pre = MARGIN + (_measure(pre + " ", grotesk(f.size)) if pre else 0)
        lay = _tlayer((w, h), (MARGIN, base), pre or " ", grotesk(f.size),
                      WHITE + (255,), anchor="ls")
        r = _revealed(lay, t / 0.16, soft=14)
        if r is not None:
            im.alpha_composite(_shadowed(r, 10, 180))
        mw = _measure(mark, pick)
        _marker(im, (x_pre - 8, base - int(pick.size * 0.94), x_pre + mw + 12, base + 6),
                (t - 0.18) / 0.16, seed=len(text_line))
        lay = _tlayer((w, h), (x_pre, base), mark, pick, INK + (255,), anchor="ls")
        r = _revealed(lay, (t - 0.16) / 0.15, soft=12)
        if r is not None:
            im.alpha_composite(r)
        if who:
            d = _measure("—  ", ui(28))
            lay = _tlayer((w, h), (MARGIN, int(h * 0.70)), who.upper(), ui(28),
                          (208, 215, 223, 255), tracking=5)
            r = _revealed(lay, (t - 0.24) / 0.16)
            if r is not None:
                im.alpha_composite(_shadowed(r, 6, 150))
        return grain(im, 2.4, seed=int(t * 30) % 97)
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
