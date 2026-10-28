#!/usr/bin/env python3
"""Test the content judge on frames whose answer we know.

The rule the client stated: anything meaningful in the frame is fine — a person,
an animation on a monitor, a busy room. A black wall, an empty backdrop or a
camera swinging past a curtain is not. If this test does not separate those two
groups, D6 will cut the wrong seconds and D9 will pass dead frames.

  python3 tools/test_content.py
"""
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from orchestrator import content  # noqa: E402

W, H = 540, 960
rng = np.random.default_rng(7)


def studio_black():
    img = np.full((H, W, 3), 6, np.uint8)
    return img


def plain_wall():
    """A grey/dark wall with a soft gradient: no detail, no colour."""
    y = np.linspace(40, 70, H)[:, None]
    img = np.repeat(y, W, axis=1).astype(np.uint8)
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)


def curtain():
    """The striped studio backdrop: texture, but no scene, no colour, no motion."""
    x = np.arange(W)
    stripes = (60 + 18 * np.sin(x / 7.0)).astype(np.uint8)
    img = np.tile(stripes, (H, 1))
    img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    return img


def animation_on_tv():
    """Colourful cartoon-ish shapes on a dark screen: meaningful, no face."""
    img = np.full((H, W, 3), 12, np.uint8)
    cv2.rectangle(img, (80, 200), (460, 620), (40, 90, 200), -1)
    for _ in range(14):
        c = (int(rng.integers(0, 256)), int(rng.integers(0, 256)), int(rng.integers(0, 256)))
        p = (int(rng.integers(60, 480)), int(rng.integers(180, 640)))
        cv2.circle(img, p, int(rng.integers(20, 70)), c, -1)
    cv2.putText(img, "PLAY", (120, 760), cv2.FONT_HERSHEY_SIMPLEX, 2.4, (255, 255, 255), 6)
    return img


def busy_room():
    """People working at desks: shapes everywhere, warm colours, detail."""
    img = np.full((H, W, 3), 30, np.uint8)
    for i in range(9):
        x, y = 40 + (i * 55) % 460, 300 + (i * 70) % 500
        cv2.rectangle(img, (x, y), (x + 46, y + 90), (60 + i * 12, 90, 150), -1)
        cv2.circle(img, (x + 23, y - 12), 18, (150, 170, 200), -1)
    cv2.line(img, (0, 820), (W, 820), (200, 200, 210), 6)
    return img


def moving_on_plain():
    """A plain wall with something small moving across it (a hand, a prop)."""
    a = plain_wall()
    b = a.copy()
    cv2.rectangle(b, (200, 400), (330, 520), (180, 180, 190), -1)
    return a, b


def main() -> int:
    fails = []

    def check(name, got, want):
        ok = got == want
        print(f"  {'ok  ' if ok else 'FAIL'} {name:34s} alive={got} (wanted {want})")
        if not ok:
            fails.append(name)

    print("frames that must be DEAD (nothing happening):")
    for name, img in (("studio black", studio_black()),
                      ("plain wall", plain_wall()),
                      ("striped curtain, static", curtain())):
        v = content.judge(img, prev=img)
        print(f"       metrics {v}")
        check(name, v["alive"], False)

    print("frames that must be ALIVE (something to watch):")
    tv = animation_on_tv()
    v = content.judge(tv, prev=tv)
    print(f"       metrics {v}")
    check("animation on a screen", v["alive"], True)

    room = busy_room()
    v = content.judge(room, prev=room)
    print(f"       metrics {v}")
    check("busy room, no face detected", v["alive"], True)

    a, b = moving_on_plain()
    v = content.judge(b, prev=a)
    print(f"       metrics {v}")
    check("plain wall + movement", v["alive"], True)

    print("face wins even on a plain frame:")
    v = content.judge(plain_wall(), prev=plain_wall(), face=True)
    print(f"       metrics {v}")
    check("face on plain wall", v["alive"], True)

    print()
    if fails:
        print("FAILED:", ", ".join(fails))
        return 1
    print("all content checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
