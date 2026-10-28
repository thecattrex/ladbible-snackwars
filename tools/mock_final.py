#!/usr/bin/env python3
"""The chosen direction: A-style 9:16 punch-in over her Twitch banner, lightly blurred.

A = the action fills the phone: the clip is cropped to 9:16 and the streamer's own
facecam is re-composited on top of it, so the game and the reaction are both visible.

The campaign wants her Twitch banner in the background, and the answer to "how much
blur" is: enough to stop the artwork competing with the clip, not so much that you
cannot tell it is her banner. So the banner is scaled to cover, blurred at a chosen
radius, and left recognisable behind a card that holds the punch-in.

  python3 tools/mock_final.py  -> /home/user/reframe_mock/final_blur_*.jpg + final_compare.jpg
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from mock_reframe import BANNER, H, INK, LIME, W, centred, font, stream_frame

OUT = Path("/home/user/reframe_mock")

CARD_W = 800                       # 9:16 card, so 1422 tall
CARD_H = int(CARD_W * 16 / 9)
CARD_X = (W - CARD_W) // 2
CARD_Y = 250                       # banner breathes: 250 above, 248 below, 140 a side
CAM_BOX = (60, 620, 660, 950)      # her camera inside the 1920x1080 stream frame


def banner_backdrop(radius: int, brightness: float = 0.88) -> Image.Image:
    art = Image.open(BANNER).convert("RGB")
    scale = max(W / art.size[0], H / art.size[1]) * 1.10
    big = art.resize((int(art.size[0] * scale), int(art.size[1] * scale)), Image.LANCZOS)
    left = (big.size[0] - W) // 2
    top = (big.size[1] - H) // 2
    out = big.crop((left, top, left + W, top + H))
    if radius:
        out = out.filter(ImageFilter.GaussianBlur(radius))
    out = Image.eval(out, lambda v: int(v * brightness))
    veil = Image.new("RGB", (W, H), (16, 8, 22))
    return Image.blend(out, veil, 0.18)


def punch_card(src: Image.Image) -> Image.Image:
    """9:16 crop of the action with her camera pasted back in, at card size."""
    sw, sh = src.size
    crop_w = int(sh * 9 / 16)
    x0 = (sw - crop_w) // 2
    card = src.crop((x0, 0, x0 + crop_w, sh)).resize((CARD_W, CARD_H), Image.LANCZOS)

    # her camera, kept big and low-left so the face is as readable as the game
    k = CARD_W / W
    cam = src.crop(CAM_BOX)
    cw = int(430 * k)
    ch = int(cam.size[1] * cw / cam.size[0])
    cam = cam.resize((cw, ch), Image.LANCZOS)
    x, y = int(40 * k), int(40 * k)
    d = ImageDraw.Draw(card)
    d.rectangle([x - 6, y - 6, x + cw + 6, y + ch + 6], fill=(255, 255, 255))
    card.paste(cam, (x, y))
    return card


def compose(radius: int) -> Image.Image:
    img = banner_backdrop(radius)
    card = punch_card(stream_frame())

    # drop shadow, so the card sits on the banner instead of floating
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        [CARD_X - 8, CARD_Y - 8, CARD_X + CARD_W + 8, CARD_Y + CARD_H + 8], radius=32,
        fill=(0, 0, 0, 160))
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    img = Image.alpha_composite(img.convert("RGBA"), shadow).convert("RGB")

    mask = Image.new("L", (CARD_W, CARD_H), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, CARD_W, CARD_H], radius=26, fill=255)
    img.paste(card, (CARD_X, CARD_Y), mask)

    d = ImageDraw.Draw(img, "RGBA")
    # hook in the top banner margin, on its own plate
    d.rounded_rectangle([40, 30, W - 40, 148], radius=22, fill=(8, 8, 12, 195))
    centred(d, (W / 2, 40), "HALLOWEEN PARTY", font("Anton-Regular.ttf", 58), (255, 255, 255),
            tracking=2)
    centred(d, (W / 2, 104), "GONE WRONG", font("ArchivoBlack-Regular.ttf", 32), LIME, tracking=4)

    # caption inside the clip, the way a subtitled reel reads
    cap_top = CARD_Y + CARD_H - 300
    d.rounded_rectangle([CARD_X + 26, cap_top, CARD_X + CARD_W - 26, cap_top + 170], radius=22,
                        fill=(8, 8, 12, 190))
    centred(d, (W / 2, cap_top + 12), "chat is dead", font("ArchivoBlack-Regular.ttf", 54),
            (255, 255, 255))
    centred(d, (W / 2, cap_top + 86), "lol", font("ArchivoBlack-Regular.ttf", 54), LIME)

    # watermark in the bottom banner margin
    d.rounded_rectangle([W / 2 - 280, CARD_Y + CARD_H + 56, W / 2 + 280, CARD_Y + CARD_H + 136],
                        radius=20, fill=(8, 8, 12, 190))
    centred(d, (W / 2, CARD_Y + CARD_H + 74), "@Irubyana  #irubyana  #twitch",
            font("ArchivoBlack-Regular.ttf", 32), (235, 235, 245))
    return img


def label(img: Image.Image, text: str) -> Image.Image:
    out = Image.new("RGB", (W, H + 80), INK)
    out.paste(img, (0, 80))
    centred(ImageDraw.Draw(out), (W / 2, 22), text, font("Anton-Regular.ttf", 62), LIME, tracking=3)
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    shots = [(0, "NO BLUR"), (8, "BLUR 8"), (12, "BLUR 12"), (18, "BLUR 18")]
    labelled = [label(compose(r), name) for r, name in shots]
    for (r, name), im in zip(shots, labelled):
        im.save(OUT / f"final_blur_{r}.jpg", quality=93)

    sheet = Image.new("RGB", (4 * W // 3, (H + 80) // 3 + 20), INK)
    for i, im in enumerate(labelled):
        t = im.resize((W // 3, (H + 80) // 3), Image.LANCZOS)
        sheet.paste(t, (i * W // 3, 10))
    sheet.save(OUT / "final_compare.jpg", quality=91)
    print("wrote final_blur_0/8/12/18.jpg + final_compare.jpg")


if __name__ == "__main__":
    main()
