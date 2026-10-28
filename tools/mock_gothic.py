#!/usr/bin/env python3
"""Render one still of the new layout on a real frame, so it can be approved
before a single clip is encoded.

  python3 tools/mock_gothic.py <frame.png> <out.jpg> [--title .. --kicker .. --line .. --key ..]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import layout as L   # noqa: E402

FF = "/home/user/bin/ffmpeg"


def graded_clip(frame: Path) -> Image.Image:
    """Apply the same grade the video will get, so the mock tells the truth."""
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "g.png"
        subprocess.run([FF, "-v", "error", "-y", "-i", str(frame), "-vf",
                        L.grade_filter() + f",scale={L.CLIP_W}:{L.CLIP_H}", str(out)],
                       check=True)
        return Image.open(out).convert("RGB")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("frame")
    ap.add_argument("out")
    ap.add_argument("--title", default="halloween party")
    ap.add_argument("--kicker", default="cursed in 4k")
    ap.add_argument("--line", default="wait till you see her face")
    ap.add_argument("--key", default="her face")
    args = ap.parse_args()

    canvas = L.static_canvas(args.title, args.kicker)
    canvas.paste(graded_clip(Path(args.frame)), (0, L.CLIP_Y))
    L.caption(canvas, args.line, args.key)
    canvas.save(args.out, quality=94)
    print("wrote", args.out)


if __name__ == "__main__":
    main()
