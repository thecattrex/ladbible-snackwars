#!/usr/bin/env python3
"""
LADbible x John Cena & Jessica Biel — Snack Wars clipping builder.

Follows the campaign guidelines:
  * every frame from the one episode           (src/snackwars.mp4)
  * vertical 9:16, faces centred               (cv2 face detect -> crop window)
  * hook on screen in the first 2 s            (campaign hook copy)
  * guest NAME on screen in the first second   (auto speaker check by pitch)
  * big burned-in captions, spelled right      (whisper small.en, swears masked)
  * @ladbible watermark bottom-left,整 clip    (supplied PNG, never covered)
  * 15 s minimum                               (every clip >= 18 s)
  * no flashy transitions, no filters          (single hard cut, no colour work)

Output: clips/ep01.mp4 ... ep20.mp4  +  clips/hooks.csv
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import imageio_ffmpeg

FF = imageio_ffmpeg.get_ffmpeg_exe()
ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src" / "snackwars.mp4"
WM = ROOT / "assets" / "watermark.png"
OUT = ROOT / "clips"
W, H = 1080, 1920

# ------------------------------------------------------------------ plan
# The 15 moments LADbible lists + 5 extra moments found in the same episode.
# hook  = on-screen hook card (campaign copy, max 8 words)
# cap   = caption hook line for the post
# name  = None -> auto speaker detection
PLAN = [
    # ep, start, dur, on-screen hook, caption line, guest name on screen
    (3 * 60 + 2.6,  24, "SHE WAS NOT READY FOR SALTY LIQUORICE", "Jessica Biel vs salty liquorice. Liquorice won.", "JESSICA BIEL"),
    (3 * 60 + 15,   22, "SHE BEGGED HIM NOT TO EAT IT",          "She begged John Cena not to eat it", "JESSICA BIEL"),
    (3 * 60 + 35,   28, "THE SALTY LIQUORICE VERDICT",           "John Cena's honest review of salty liquorice", "JOHN CENA"),
    (0 * 60 + 35,   22, "SHE DOESN'T KNOW HIS THEME SONG",       "Jessica Biel vs John Cena's theme song", "JESSICA BIEL"),
    (1 * 60 + 57,   25, "IS THAT A SEAL OR A WALRUS?",           "Is that a seal or a walrus?", "JESSICA BIEL"),
    (1 * 60 + 3,    22, "OWL. DARTH VADER. TURKEY.",             "Owl, Darth Vader, turkey. Guess the sound.", "JOHN CENA & JESSICA BIEL"),
    (1 * 60 + 30,   20, "HIS SNORING IMPRESSION",                "John Cena's snoring impression. His poor wife.", "JOHN CENA"),
    (4 * 60 + 24,   30, "JOHN CENA HAD A STRATEGY",              "John Cena had a cup flip strategy", "JOHN CENA"),
    (5 * 60 + 54,   22, "YOU TALKING TO ME?",                    "You talking to me? Snack Wars edition", "JOHN CENA & JESSICA BIEL"),
    (6 * 60 + 14,   20, "THEY'VE NEVER SEEN MEAN GIRLS",         "One of them has never seen Mean Girls", "JOHN CENA & JESSICA BIEL"),
    (6 * 60 + 30,   34, "FREEDOM! WHAT MOVIE IS THAT?",          "Blanking on Braveheart mid quote", "JOHN CENA"),
    (7 * 60 + 5,    32, "YOU GUYS TOTALLY RIGGED THIS",          "Was the movie quiz rigged?", "JESSICA BIEL"),
    (7 * 60 + 36,   26, "THE LUNCH TRADE",                       "The pickle vs Percy Pig lunch trade", "JOHN CENA & JESSICA BIEL"),
    (8 * 60 + 49,   28, "THIS GAME IS HARDER THAN IT LOOKS",     "Hoops on a chopstick is pure chaos", "JOHN CENA & JESSICA BIEL"),
    (10 * 60 + 12,  24, "JOHN CENA CROWNS THE CHAMPION",         "John Cena crowns the Snack Wars champion", "JOHN CENA"),
    # --- extra moments mined from the same episode (hooks never reused)
    (0 * 60 + 54,   18, "SHE DOESN'T KNOW HIS WRESTLING LIFE",   "Jessica Biel knew nothing about his wrestling life", "JESSICA BIEL"),
    (5 * 60 + 31,   18, "NO, I'VE EARNED THIS",                  "She earned her snack and she is not sharing", "JESSICA BIEL"),
    (8 * 60 + 14,   20, "THE PERCY PIG TASTE TEST",              "Percy Pigs got a better review than the liquorice", "JESSICA BIEL"),
    (9 * 60 + 43,   20, "IT FELT LIKE A CLAW MACHINE",           "Hoops on a chopstick felt like a claw machine", "JESSICA BIEL"),
    (2 * 60 + 19,   20, "FIRST ROUND GOES TO JESSICA",           "Round one went to Jessica Biel", "JESSICA BIEL"),
]

CENSOR = [("fuck", "f***"), ("fucking", "f***ing"), ("shit", "sh**"),
          ("bitch", "b****"), ("asshole", "a**hole"), ("dick", "d***")]


def censor(t: str) -> str:
    low = t
    for bad, good in CENSOR:
        low = low.replace(bad, good).replace(bad.capitalize(), good.capitalize())
    return low


# ------------------------------------------------------------------ helpers
def clock(t: float) -> str:
    n = round(max(0.0, t) * 100)
    return f"{n // 360000}:{(n // 6000) % 60:02}:{(n // 100) % 60:02}.{n % 100:02}"


def name_of(f0: float) -> str:
    """low pitch = John, high = Jessica, in-between = both guests on screen.
    Checked against the episode's own burned-in name labels (1:17 John,
    0:35 Jessica) - pitch and their labels agree."""
    if not f0:
        return "JOHN CENA & JESSICA BIEL"
    if f0 < 150:
        return "JOHN CENA"
    if f0 > 175:
        return "JESSICA BIEL"
    return "JOHN CENA & JESSICA BIEL"


def speaker(src: Path, t: float, dur: float = 2.5) -> str:
    """Median pitch of the hook line -> which guest is talking."""
    raw = subprocess.run([FF, "-v", "error", "-ss", f"{t:.2f}", "-t", f"{dur:.2f}",
                          "-i", str(src), "-vn", "-ac", "1", "-ar", "16000",
                          "-f", "s16le", "-"], capture_output=True).stdout
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    fr, hop, vals = 1024, 512, []
    for i in range(0, max(0, len(a) - fr), hop):
        w = a[i:i + fr]
        if np.sqrt((w ** 2).mean()) < 0.02:
            continue
        w = w - w.mean()
        ac = np.correlate(w, w, "full")[fr - 1:]
        lo, hi = int(16000 / 300), int(16000 / 70)
        seg = ac[lo:hi]
        if not seg.size:
            continue
        p = int(np.argmax(seg)) + lo
        if ac[p] > 0.35 * ac[0]:
            vals.append(16000.0 / p)
    med = float(np.median(vals)) if vals else 0.0
    if med > 280:                      # octave error
        med /= 2
    return name_of(med)


def pick_name(hook: str, measured: str) -> str:
    """If the campaign hook itself names a guest, that name must be on screen;
    otherwise trust the measured pitch of the opening line."""
    h = hook.upper()
    if "JOHN CENA" in h:
        return "JOHN CENA"
    if h.startswith(("SHE ", "HER ")) or " SHE " in h[:16]:
        return "JESSICA BIEL"
    if h.startswith("HIS ") or h.startswith("HE "):
        return "JOHN CENA"
    return measured


def face_cx(src: Path, t: float, dur: float) -> float:
    """Average face centre x across the clip, for a centred 9:16 crop."""
    cap = cv2.VideoCapture(str(src))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    cas = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    xs = []
    for k in range(9):
        tt = t + dur * (k + 0.5) / 9
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(tt * fps))
        ok, fr = cap.read()
        if not ok:
            continue
        g = cv2.cvtColor(cv2.resize(fr, (960, 540)), cv2.COLOR_BGR2GRAY)
        faces = cas.detectMultiScale(g, 1.15, 5, minSize=(50, 50))
        for (x, y, w, h) in faces:
            xs.append((x + w / 2) * 2)          # back to 1920 scale
    cap.release()
    return float(np.median(xs)) if xs else 960.0


def captions(segs, a: float, b: float, max_words: int = 6):
    """Real ASR lines for [a, b], re-timed, chunked big and readable."""
    out = []
    for s in segs:
        if s["end"] <= a or s["start"] >= b:
            continue
        words = censor(s["text"]).split()
        if not words:
            continue
        s0, s1 = max(s["start"], a), min(s["end"], b)
        groups = [words[i:i + max_words] for i in range(0, len(words), max_words)]
        span = max(0.4, s1 - s0) / len(groups)
        for gi, g in enumerate(groups):
            gs = s0 + gi * span - a
            out.append((max(0.0, gs), min(b - a, gs + span), " ".join(g)))
    return out


def ass_file(path: Path, dur: float, hook: str, name: str, caps):
    hook = hook.upper()
    lines = [hook] if len(hook) <= 20 else [hook[:len(hook) // 2] + "\n" + hook[len(hook) // 2:]] if False else [hook]
    hsize = int(max(52, min(104, 104 - (len(hook) - 20) * 2.0)))
    ev = [
        # guest name, first second (guideline requirement)
        f"Dialogue: 2,0:00:00.00,0:00:02.60,Name,{name}",
        # hook card, first 3 s
        f"Dialogue: 3,0:00:00.00,{clock(min(3.0, dur))},Hook,{{\\fs{hsize}}}{hook}",
    ]
    for gs, ge, txt in caps:
        ev.append(f"Dialogue: 0,{clock(gs)},{clock(ge)},Cap,{txt}")
    path.write_text(f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,DejaVu Sans,96,&H0000E5FF,&H00101010,&H00000000,1,8,90,90,250,1
Style: Name,DejaVu Sans,50,&H00FFFFFF,&H00000000,&H80000000,1,8,90,90,110,3
Style: Cap,DejaVu Sans,72,&H00FFFFFF,&H00101010,&H00000000,1,2,80,80,430,1
[Events]
Format: Layer, Start, End, Style, Text
""" + "\n".join(ev) + "\n", encoding="utf8")


def render(ep: int, start: float, dur: float, hook: str, cap: str, name: str, segs, src=SRC):
    cx = face_cx(src, start, dur)
    crop_w = 608                      # 608x1080 -> exactly 9:16
    x = int(max(0, min(1920 - crop_w, cx - crop_w / 2)))
    x -= x % 2
    a = ROOT / "assets" / f"ep{ep:02d}.ass"
    ass_file(a, dur, hook, name, captions(segs, start, start + dur))
    out = OUT / f"ep{ep:02d}.mp4"
    wm_w = 330
    fc = (f"[0:v]crop={crop_w}:1080:{x}:0,scale={W}:{H}:flags=lanczos,"
          f"setsar=1,fps=30[base];"
          f"[1:v]scale={wm_w}:-1[wm];"
          f"[base][wm]overlay=46:{H - 190}:format=auto,ass={a}[v]")
    subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y",
                    "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(src),
                    "-i", str(WM), "-filter_complex", fc,
                    "-map", "[v]", "-map", "0:a",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
                    "-movflags", "+faststart", str(out)], check=True)
    return out, cx, x


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (ROOT / "assets").mkdir(exist_ok=True)
    segs = json.load(open(ROOT / "assets" / "transcript_small.json"))
    only = [int(x) for x in sys.argv[1:]] if len(sys.argv) > 1 else list(range(1, len(PLAN) + 1))
    rows = []
    for ep, (start, dur, hook, cap, name) in enumerate(PLAN, start=1):
        if ep not in only:
            continue
        who = pick_name(hook, speaker(SRC, start, 2.2) or name)
        out, cx, x = render(ep, start, dur, hook, cap, who, segs)
        rows.append(dict(ep=f"ep{ep:02d}", file=out.name, start=f"{start:.1f}",
                         length=dur, speaker=who, hook=hook, caption=cap,
                         face_cx=int(cx), crop_x=x))
        print(f"ep{ep:02d}  {start:6.1f}s +{dur}s  {who:<13} crop_x={x:4d}  {hook}")
    if len(only) == len(PLAN):
        with open(OUT / "hooks.csv", "w", newline="", encoding="utf8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    print(f"\n{len(rows)} clips -> {OUT}")


if __name__ == "__main__":
    main()
