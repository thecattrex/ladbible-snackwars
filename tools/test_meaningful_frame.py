#!/usr/bin/env python3
"""End-to-end check of the client's rule on a synthesised clip.

Builds two 6 s 1080x1920 clips with ffmpeg — real footage shapes, our watermark
band and a caption lane — and runs D9's vision checks on them:

  clip A: a busy scene the whole way (a screen playing, moving shapes, a face-sized
          blob) — must PASS the content checks even though nothing is a person.
  clip B: the same, but with one second of black wall in the middle — must FAIL,
          because a second where nothing happens is what the client rejected.

  python3 tools/test_meaningful_frame.py
"""
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from departments import d9_qa  # noqa: E402

FF = imageio_ffmpeg.get_ffmpeg_exe()
OUT = Path("/tmp/content_test")
OUT.mkdir(exist_ok=True)


def make(name: str, dead_from: float | None = None) -> Path:
    """A busy, colourful scene, optionally with one second of flat wall.

    Frames are drawn here rather than with ffmpeg's drawing filters, so the test
    exercises exactly the pixels D9 will see: moving colour shapes and text
    (something is happening) versus a flat dark wall (nothing is).
    """
    import cv2
    import numpy as np

    p = OUT / name
    w, h, fps, secs = 1080, 1920, 30, 6
    proc = subprocess.Popen([FF, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
                             "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
                             "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                             "-pix_fmt", "yuv420p", str(p)], stdin=subprocess.PIPE)
    for i in range(fps * secs):
        t = i / fps
        if dead_from is not None and dead_from <= t < dead_from + 1.0:
            frame = np.full((h, w, 3), 9, np.uint8)          # black wall
        else:
            frame = np.full((h, w, 3), (54, 36, 27), np.uint8)   # dark studio blue
            x = int(100 + 200 * np.sin(t * 3))
            cv2.rectangle(frame, (x, 500), (x + 520, 880), (255, 160, 58), -1)
            x2 = int(500 + 180 * np.cos(t * 2))
            cv2.rectangle(frame, (x2, 900), (x2 + 300, 1160), (58, 106, 255), -1)
            cx = int(540 + 260 * np.sin(t * 2.5))
            cy = int(760 + 200 * np.cos(t * 1.7))
            cv2.circle(frame, (cx, cy), 110, (0, 255, 200), -1)
            cv2.putText(frame, "PLAY", (120, 1420), cv2.FONT_HERSHEY_SIMPLEX, 3.0,
                        (255, 255, 255), 8)
            cv2.line(frame, (0, 1700), (w, 1700), (210, 210, 210), 6)
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    proc.wait()
    return p


def main() -> int:
    fails = []
    print("clip A — something happening the whole way (no person at all):")
    a = make("content_busy.mp4")
    va = d9_qa.visual(a)
    print("   ", {k: va[k] for k in ("alive", "longest_dead_run_s", "dead_in_first_2s", "faces")})
    ok = va["longest_dead_run_s"] <= 0.5 and not va["dead_in_first_2s"]
    print(f"    {'ok  ' if ok else 'FAIL'} meaningful content accepted without a face")
    if not ok:
        fails.append("busy scene judged dead")

    print("clip B — same scene with one second of black wall:")
    b = make("content_dead.mp4", dead_from=2.5)
    vb = d9_qa.visual(b)
    print("   ", {k: vb[k] for k in ("alive", "longest_dead_run_s", "dead_in_first_2s", "faces")})
    ok = vb["longest_dead_run_s"] > 0.5
    print(f"    {'ok  ' if ok else 'FAIL'} dead second detected")
    if not ok:
        fails.append("black wall not detected")

    print()
    if fails:
        print("FAILED:", ", ".join(fails))
        return 1
    print("meaningful-frame checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
