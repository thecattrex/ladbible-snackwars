#!/usr/bin/env python3
"""Mock the two ways to turn a 16:9 Twitch stream into a 9:16 short.

A = punch in: crop a 9:16 window out of the 16:9 frame and let it fill the phone.
B = keep the whole 16:9 picture, sit it in the middle, and put the hook and the
    captions in the space above and below it.

The "stream" itself is drawn here (gameplay + facecam + chat), so the mocks show
layout, framing and text placement rather than anyone's real footage.

  python3 tools/mock_reframe.py            -> /home/user/reframe_mock/*.jpg
"""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = Path("/home/user/reframe_mock")
ASSETS = ROOT / "assets"
W, H = 1080, 1920
LIME = (200, 255, 0)
INK = (12, 14, 18)


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(ASSETS / name), size)


def centred(draw, xy, text, f, fill, shadow=True, tracking=0):
    """Draw text centred on x with a soft drop shadow."""
    if tracking:
        widths = [draw.textlength(ch, font=f) for ch in text]
        total = sum(widths) + tracking * (len(text) - 1)
        x = xy[0] - total / 2
        for ch, wd in zip(text, widths):
            if shadow:
                draw.text((x + 4, xy[1] + 5), ch, font=f, fill=(0, 0, 0, 170))
            draw.text((x, xy[1]), ch, font=f, fill=fill)
            x += wd + tracking
        return
    bbox = draw.textbbox((0, 0), text, font=f)
    w = bbox[2] - bbox[0]
    x = xy[0] - w / 2
    if shadow:
        draw.text((x + 4, xy[1] + 5), text, font=f, fill=(0, 0, 0, 170))
    draw.text((x, xy[1]), text, font=f, fill=fill)


def twitch_banner() -> Image.Image:
    """A stand-in for the streamer's Twitch banner: brand purple, handle, stripes.

    The real banner is in the campaign's reference file (locked until the campaign
    is joined), so this placeholder only proves the layout and the safe area for
    the text; the finished clips will use the supplied image.
    """
    img = Image.new("RGB", (W, H), (24, 12, 38))
    d = ImageDraw.Draw(img)
    for i in range(-H, W, 90):                       # diagonal brand stripes
        d.line([(i, 0), (i + H, H)], fill=(34, 18, 54), width=34)
    d.rectangle([0, 0, W, 300], fill=(145, 70, 255))  # twitch purple band
    d.rectangle([0, H - 300, W, H], fill=(145, 70, 255))
    centred(d, (W / 2, 34), "IRUBYANA", font("Anton-Regular.ttf", 84), (255, 255, 255), tracking=4)
    return img


def banner_layout(src: Image.Image) -> Image.Image:
    """The campaign's own layout: banner behind, the 16:9 clip full width on top.

    The banner is artwork we do not control, so the hook and the captions never sit
    straight on it: each gets its own plate, the way a lower third does. That keeps
    the text readable whatever the banner looks like underneath.
    """
    canvas = twitch_banner()
    inner_w = W
    inner_h = int(inner_w * src.size[1] / src.size[0])          # 1080x608
    y = 700
    canvas.paste(src.resize((inner_w, inner_h), Image.LANCZOS), (0, y))
    d = ImageDraw.Draw(canvas)
    d.rectangle([0, y - 4, W, y], fill=(0, 0, 0))
    d.rectangle([0, y + inner_h, W, y + inner_h + 4], fill=(0, 0, 0))
    return canvas


def stream_frame(w=1920, h=1080) -> Image.Image:
    """A 16:9 livestream-looking frame: game, facecam, chat."""
    img = Image.new("RGB", (w, h), (18, 16, 28))
    d = ImageDraw.Draw(img)

    # --- "gameplay": a bright stage with shapes, a HUD and a score
    for i in range(0, w, 8):
        t = i / w
        d.line([(i, 0), (i, h)], fill=(int(24 + 40 * t), int(20 + 26 * t), int(48 + 60 * t)))
    d.ellipse([300, 240, 1180, 900], fill=(36, 92, 160))
    d.ellipse([420, 330, 1060, 830], fill=(52, 132, 210))
    for cx, cy, r, col in ((520, 480, 90, LIME), (900, 520, 120, (255, 120, 60)),
                           (700, 700, 70, (255, 255, 255)), (1120, 700, 60, (255, 70, 140))):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
    d.rectangle([0, 960, w, h], fill=(10, 12, 18))                 # lower HUD
    d.rectangle([40, 985, 520, 1025], fill=(40, 44, 56))
    d.rectangle([40, 985, 380, 1025], fill=LIME)                   # health / progress
    d.text((560, 985), "ROUND 3", font=font("ArchivoBlack-Regular.ttf", 34), fill=(230, 230, 240))
    d.text((1300, 985), "2 : 41", font=font("Anton-Regular.ttf", 44), fill=(255, 255, 255))

    # --- chat column (right edge)
    d.rectangle([1660, 0, w, 940], fill=(14, 14, 22))
    msgs = [("hollow", "LETS GOOO"), ("mika", "no way"), ("zed_", "CLIP IT"),
            ("ana", "he is insane"), ("bo", "W stream"), ("kay", "chat is dead lol")]
    y = 40
    for name, text in msgs:
        d.text((1680, y), name + ":", font=font("Inter.ttf", 22), fill=(150, 150, 170))
        d.text((1680, y + 26), text, font=font("Inter.ttf", 26), fill=(235, 235, 245))
        y += 84

    # --- facecam, bottom left, the way most streamers run it
    cam = (60, 620, 660, 950)
    d.rounded_rectangle(cam, radius=18, fill=(30, 30, 40), outline=(240, 240, 250), width=5)
    d.ellipse([250, 660, 470, 880], fill=(206, 162, 124))          # head
    d.ellipse([300, 735, 340, 775], fill=(20, 20, 25))             # eyes
    d.ellipse([385, 735, 425, 775], fill=(20, 20, 25))
    d.arc([320, 780, 405, 860], 20, 160, fill=(120, 60, 60), width=8)   # mouth open: talking
    d.polygon([(150, 950), (250, 860), (470, 860), (570, 950)], fill=(52, 62, 96))  # shoulders
    d.text((80, 630), "LIVE", font=font("ArchivoBlack-Regular.ttf", 26), fill=(255, 70, 70))
    return img


def punch_in(src: Image.Image, focus=(0.5, 0.5), cam_box=None) -> Image.Image:
    """9:16 crop of the action, with the streamer's camera re-composited on top.

    A plain crop of a 16:9 stream either loses the game or loses the face. The
    editor's move is to fill the phone with the action and paste the camera back
    in as its own small window, which is what this mock shows.
    """
    sw, sh = src.size
    crop_w = int(sh * 9 / 16)
    cx = int(focus[0] * sw)
    x0 = max(0, min(sw - crop_w, cx - crop_w // 2))
    out = src.crop((x0, 0, x0 + crop_w, sh)).resize((W, H), Image.LANCZOS)
    if cam_box:
        cam = src.crop(cam_box)
        cw = 380
        ch = int(cam.size[1] * cw / cam.size[0])
        cam = cam.resize((cw, ch), Image.LANCZOS)
        d = ImageDraw.Draw(out)
        d.rectangle([40 - 6, 420 - 6, 40 + cw + 6, 420 + ch + 6], fill=(255, 255, 255))
        out.paste(cam, (40, 420))
    return out


def letterbox(src: Image.Image, background: str = "black",
              blur: bool = False) -> Image.Image:
    """Whole 16:9 picture in the middle; the space above and below is ours."""
    if background == "black":
        canvas = Image.new("RGB", (W, H), (0, 0, 0))
    else:
        # the same frame, blown up and blurred: no hard black bars, still our area
        big = src.resize((W, int(W * src.size[1] / src.size[0])), Image.LANCZOS)
        canvas = big.crop((0, (big.size[1] - H) // 2, W, (big.size[1] - H) // 2 + H))
        canvas = canvas.filter(ImageFilter.GaussianBlur(46))
        canvas = Image.eval(canvas, lambda v: int(min(255, 40 + v * 0.62)))
    pic_w = W
    pic_h = int(W * src.size[1] / src.size[0])
    canvas.paste(src.resize((pic_w, pic_h), Image.LANCZOS), (0, (H - pic_h) // 2))
    return canvas


def decorate(img: Image.Image, hook: str, hook_sub: str, caption_a: str,
             caption_b: str, corner: str, band_text: bool) -> Image.Image:
    d = ImageDraw.Draw(img, "RGBA")
    hook_f = font("Anton-Regular.ttf", 108 if band_text else 96)
    sub_f = font("ArchivoBlack-Regular.ttf", 40)
    cap_f = font("ArchivoBlack-Regular.ttf", 62)
    if band_text:
        centred(d, (W / 2, 120), hook, hook_f, (255, 255, 255), tracking=2)
        centred(d, (W / 2, 250), hook_sub, sub_f, LIME, tracking=3)
        # caption inside our bottom area
        d.rounded_rectangle([60, 1560, W - 60, 1720], radius=18, fill=(0, 0, 0, 150))
        centred(d, (W / 2, 1592), caption_a, cap_f, (255, 255, 255))
        centred(d, (W / 2, 1662), caption_b, cap_f, LIME)
    else:
        # full-bleed: hook over the top of the picture, captions in the lower lane
        d.rectangle([0, 0, W, 470], fill=(0, 0, 0, 120))
        centred(d, (W / 2, 120), hook, hook_f, (255, 255, 255), tracking=2)
        centred(d, (W / 2, 260), hook_sub, sub_f, LIME, tracking=3)
        centred(d, (W / 2, 1560), caption_a, cap_f, (255, 255, 255))
        centred(d, (W / 2, 1640), caption_b, cap_f, LIME)
    # small corner tag: the campaign's handle rule
    d.rectangle([40, H - 124, 40 + d.textlength(corner, font=font("ArchivoBlack-Regular.ttf", 34)) + 40,
                 H - 40], fill=(0, 0, 0, 170))
    d.text((60, H - 108), corner, font=font("ArchivoBlack-Regular.ttf", 34),
           fill=(255, 255, 255, 235))
    return img


def banner_text(img: Image.Image) -> Image.Image:
    """Text on its own plate, clear of the banner artwork."""
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle([40, 150, W - 40, 520], radius=26, fill=(8, 8, 12, 215))
    centred(d, (W / 2, 175), "HALLOWEEN PARTY", font("Anton-Regular.ttf", 92), (255, 255, 255), tracking=2)
    centred(d, (W / 2, 300), "GONE WRONG", font("ArchivoBlack-Regular.ttf", 54), LIME, tracking=4)
    centred(d, (W / 2, 392), "clip 1 of 20", font("Inter.ttf", 34), (200, 200, 215))

    d.rounded_rectangle([40, 1370, W - 40, 1590], radius=26, fill=(8, 8, 12, 210))
    centred(d, (W / 2, 1392), "chat is dead", font("ArchivoBlack-Regular.ttf", 62), (255, 255, 255))
    centred(d, (W / 2, 1478), "lol", font("ArchivoBlack-Regular.ttf", 62), LIME)

    d.rounded_rectangle([40, 1718, W - 40, 1812], radius=20, fill=(8, 8, 12, 210))
    centred(d, (W / 2, 1738), "@Irubyana   #irubyana   #twitch   #TwitchLivestream",
            font("ArchivoBlack-Regular.ttf", 32), (235, 235, 245))
    return img


def label(img: Image.Image, text: str) -> Image.Image:
    d = ImageDraw.Draw(img, "RGBA")
    d.rectangle([0, 0, W, 78], fill=(0, 0, 0, 210))
    centred(d, (W / 2, 14), text, font("ArchivoBlack-Regular.ttf", 38), LIME, shadow=False)
    return img


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    src = stream_frame()

    a = decorate(punch_in(src, focus=(0.5, 0.5), cam_box=(60, 620, 660, 950)),
                 "HE CLUTCHED IT", "@IRUBYANA", "no way he", "hit that",
                 "@Irubyana  #irubyana #twitch", band_text=False)
    a.save(OUT / "A_916_full_bleed.jpg", quality=92)

    b = decorate(letterbox(src, "black"), "HALLOWEEN PARTY", "GONE WRONG", "chat is dead", "lol",
                 "@Irubyana  #irubyana #twitch", band_text=True)
    b.save(OUT / "B_169_black_bars.jpg", quality=92)

    c = decorate(letterbox(src, "blur", blur=True), "HALLOWEEN PARTY", "GONE WRONG",
                 "chat is dead", "lol", "@Irubyana  #irubyana #twitch", band_text=True)
    c.save(OUT / "C_169_blurred_bars.jpg", quality=92)

    d = banner_text(banner_layout(src))
    d.save(OUT / "D_169_twitch_banner.jpg", quality=92)

    # comparison sheet: the three side by side, labelled
    sheet = Image.new("RGB", (W * 3 // 2, int(H / 2) + 40), (10, 10, 12))
    for i, (im, name) in enumerate(((a, "A  9:16 PUNCH-IN"),
                                    (b, "B  16:9 + BLACK"),
                                    (c, "C  16:9 + BLUR"))):
        thumb = label(im.copy(), name).resize((W // 2, H // 2), Image.LANCZOS)
        sheet.paste(thumb, (i * W // 2, 20))
    sheet.save(OUT / "compare.jpg", quality=92)
    print("wrote", *sorted(p.name for p in OUT.glob("*.jpg")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
