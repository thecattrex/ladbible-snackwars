#!/usr/bin/env python3
"""The locked direction: the footage keeps its own 16:9 frame, her banner sits behind it.

No punch-in, no crop — the stream is shown exactly as it was broadcast, full width.
The Twitch banner fills the phone frame behind it at the chosen blur (18), which is
enough to read as her banner and not enough to fight the clip. Text lives above and
below the picture, and nothing readable goes below 1600 px (where TikTok and Reels
put their own caption and buttons).

  python3 tools/mock_169.py  -> /home/user/reframe_mock/ratio_*.jpg
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from mock_final import banner_backdrop, label
from mock_reframe import H, LIME, W, centred, font, stream_frame

OUT = Path("/home/user/reframe_mock")
BLUR = 18
CLIP_Y = 700
SAFE_BOTTOM = 1600


def plate(d, box, radius=24, alpha=205) -> None:
    d.rounded_rectangle(box, radius=radius, fill=(8, 8, 12, alpha))


def build(clip_w: int = W, hook_scale: float = 1.0) -> Image.Image:
    img = banner_backdrop(BLUR)
    src = stream_frame()
    clip_h = int(clip_w * src.size[1] / src.size[0])
    clip_x = (W - clip_w) // 2
    img.paste(src.resize((clip_w, clip_h), Image.LANCZOS), (clip_x, CLIP_Y))

    d = ImageDraw.Draw(img, "RGBA")
    d.rectangle([clip_x, CLIP_Y - 4, clip_x + clip_w, CLIP_Y], fill=(0, 0, 0))
    d.rectangle([clip_x, CLIP_Y + clip_h, clip_x + clip_w, CLIP_Y + clip_h + 4], fill=(0, 0, 0))

    # hook — the promise of the clip, in the space above the picture
    hook_top = 210
    plate(d, [40, hook_top, W - 40, CLIP_Y - 60])
    centred(d, (W / 2, hook_top + 22), "HALLOWEEN PARTY",
            font("Anton-Regular.ttf", int(96 * hook_scale)), (255, 255, 255), tracking=2)
    centred(d, (W / 2, hook_top + int(150 * hook_scale)), "GONE WRONG",
            font("ArchivoBlack-Regular.ttf", int(56 * hook_scale)), LIME, tracking=4)
    centred(d, (W / 2, hook_top + int(252 * hook_scale)), "wait for the last round",
            font("Inter.ttf", int(38 * hook_scale)), (208, 208, 222))

    # caption — the line being said, plus one key word popped
    cap_top = CLIP_Y + clip_h + 24
    plate(d, [40, cap_top, W - 40, cap_top + 160])
    centred(d, (W / 2, cap_top + 20), "chat is dead", font("ArchivoBlack-Regular.ttf", 56),
            (255, 255, 255))
    centred(d, (W / 2, cap_top + 92), "lol", font("ArchivoBlack-Regular.ttf", 56), LIME)

    # watermark — her handle, on screen the whole clip
    wm_top = cap_top + 176
    plate(d, [W / 2 - 300, wm_top, W / 2 + 300, wm_top + 84], radius=18)
    centred(d, (W / 2, wm_top + 16), "@Irubyana   #irubyana   #twitch",
            font("ArchivoBlack-Regular.ttf", 32), (235, 235, 245))
    assert wm_top + 84 <= SAFE_BOTTOM, "watermark drifted into the app's UI zone"
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    full = label(build(W), "16:9 FULL WIDTH  ·  BLUR 18")
    inset = label(build(1000), "16:9 INSET 1000  ·  BLUR 18")
    full.save(OUT / "ratio_full.jpg", quality=93)
    inset.save(OUT / "ratio_inset.jpg", quality=93)

    sheet = Image.new("RGB", (W, (H + 80) // 2 + 20), (12, 14, 18))
    for i, im in enumerate((full, inset)):
        t = im.resize((W // 2, (H + 80) // 2), Image.LANCZOS)
        sheet.paste(t, (i * W // 2, 10))
    sheet.save(OUT / "ratio_compare.jpg", quality=92)
    print("wrote ratio_full.jpg ratio_inset.jpg ratio_compare.jpg")


if __name__ == "__main__":
    main()
