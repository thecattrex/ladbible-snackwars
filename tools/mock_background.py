#!/usr/bin/env python3
"""Compare the ways to put the streamer's Twitch banner behind a 9:16 clip.

The campaign asks for the banner in the background. Three treatments, same clip,
same text, so only the background decision changes:

  1 COVER  the banner is zoomed to fill the phone and dimmed (what D does today).
           The artwork reads as texture; the name and the channel link get cropped.
  2 BAND-T the banner sits uncropped as a 1080x432 band at the top, the rest of the
           background is one flat brand colour.
  3 BAND-B like 2 but the band is at the bottom, hook has the clean top.

  python3 tools/mock_background.py    -> /home/user/reframe_mock/bg_*.jpg + bg_compare.jpg
"""
from pathlib import Path

from PIL import Image, ImageDraw

from mock_reframe import (ASSETS, H, INK, LIME, W, BANNER, banner_text, centred,
                          font, stream_frame)

OUT = Path("/home/user/reframe_mock")
PLUM = (34, 12, 40)
CLIP_Y = 700
# TikTok / Reels paint their caption and buttons over the bottom ~300 px, so nothing
# that has to be read goes below this line.
SAFE_BOTTOM = 1600
TAG_Y = 1505


def base_fill(colour) -> Image.Image:
    img = Image.new("RGB", (W, H), colour)
    d = ImageDraw.Draw(img)
    # a faint vignette so a flat colour still has some depth
    d.rectangle([0, 0, W, H], outline=(0, 0, 0), width=0)
    return img


def cover() -> Image.Image:
    art = Image.open(BANNER).convert("RGB")
    scale = max(W / art.size[0], H / art.size[1])
    big = art.resize((int(art.size[0] * scale + 0.5), int(art.size[1] * scale + 0.5)),
                     Image.LANCZOS)
    top = max(0, int((big.size[1] - H) * 0.78))
    left = (big.size[0] - W) // 2
    return big.crop((left, top, left + W, top + H))


def band(at_top=True) -> Image.Image:
    art = Image.open(BANNER).convert("RGB")
    band_h = int(W * art.size[1] / art.size[0])          # 432
    art = art.resize((W, band_h), Image.LANCZOS)
    img = base_fill(PLUM)
    y = 0 if at_top else H - band_h
    img.paste(art, (0, y))
    d = ImageDraw.Draw(img)
    edge = y + band_h if at_top else y
    d.rectangle([0, edge - 3, W, edge + 3], fill=(230, 30, 120))
    return img


def hook_plate(d, y: int, h: int) -> None:
    """Hook on its own plate; the type scales with the plate it was given."""
    k = h / 370
    d.rounded_rectangle([40, y, W - 40, y + h], radius=26, fill=(8, 8, 12, 218))
    centred(d, (W / 2, y + 25 * k), "HALLOWEEN PARTY", font("Anton-Regular.ttf", int(92 * k)),
            (255, 255, 255), tracking=2)
    centred(d, (W / 2, y + 150 * k), "GONE WRONG", font("ArchivoBlack-Regular.ttf", int(54 * k)),
            LIME, tracking=4)
    centred(d, (W / 2, y + 242 * k), "clip 1 of 20", font("Inter.ttf", int(34 * k)),
            (200, 200, 215))


def caption_plate(d, y: int, h: int) -> None:
    k = h / 220
    d.rounded_rectangle([40, y, W - 40, y + h], radius=26, fill=(8, 8, 12, 212))
    centred(d, (W / 2, y + 22 * k), "chat is dead", font("ArchivoBlack-Regular.ttf", int(62 * k)),
            (255, 255, 255))
    centred(d, (W / 2, y + 108 * k), "lol", font("ArchivoBlack-Regular.ttf", int(62 * k)), LIME)


def compose(bg: Image.Image, hook_geom, caption_geom) -> Image.Image:
    """The 16:9 clip full width + the three text plates, on the given background."""
    img = bg.copy()
    src = stream_frame()
    inner_h = int(W * src.size[1] / src.size[0])
    img.paste(src.resize((W, inner_h), Image.LANCZOS), (0, CLIP_Y))
    d = ImageDraw.Draw(img)
    d.rectangle([0, CLIP_Y - 4, W, CLIP_Y], fill=(0, 0, 0))
    d.rectangle([0, CLIP_Y + inner_h, W, CLIP_Y + inner_h + 4], fill=(0, 0, 0))

    d = ImageDraw.Draw(img, "RGBA")
    hook_plate(d, *hook_geom)
    caption_plate(d, *caption_geom)

    d.rounded_rectangle([40, TAG_Y, W - 40, TAG_Y + 94], radius=20, fill=(8, 8, 12, 210))
    centred(d, (W / 2, TAG_Y + 20), "@Irubyana   #irubyana   #twitch   #TwitchLivestream",
            font("ArchivoBlack-Regular.ttf", 32), (235, 235, 245))
    return img


def label(img: Image.Image, text: str) -> Image.Image:
    out = Image.new("RGB", (W, H + 80), INK)
    out.paste(img, (0, 80))
    d = ImageDraw.Draw(out)
    centred(d, (W / 2, 22), text, font("Anton-Regular.ttf", 62), LIME, tracking=3)
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    one = label(compose(Image.eval(cover(), lambda v: int(v * 0.78)), (150, 370), (1325, 165)),
                "1  COVER ZOOM")
    two = label(compose(band(True), (452, 232), (1325, 165)), "2  BANNER BAND TOP")
    three = label(compose(band(False), (150, 370), (1325, 165)), "3  BANNER BAND BOTTOM")

    one.save(OUT / "bg_1_cover.jpg", quality=92)
    two.save(OUT / "bg_2_band_top.jpg", quality=92)
    three.save(OUT / "bg_3_band_bottom.jpg", quality=92)

    sheet = Image.new("RGB", (3 * W // 2, (H + 80) // 2 + 20), INK)
    for i, im in enumerate((one, two, three)):
        t = im.resize((W // 2, (H + 80) // 2), Image.LANCZOS)
        sheet.paste(t, (i * W // 2, 10))
    sheet.save(OUT / "bg_compare.jpg", quality=90)
    print("wrote bg_1_cover.jpg bg_2_band_top.jpg bg_3_band_bottom.jpg bg_compare.jpg")


if __name__ == "__main__":
    main()
