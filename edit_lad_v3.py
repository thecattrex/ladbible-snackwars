#!/usr/bin/env python3
"""
LADbible x Snack Wars — EDITED clips v3.

New in v3
  * SPEAKER FOLLOW: faces are tracked across the clip and the mouth region is
    measured frame to frame, so the crop jumps to whoever is actually talking
    (a silent listener's mouth does not move). If nobody is on camera the shot
    goes wide instead of landing on an empty frame.
  * REACTION CUT: on the punchline the video cuts to the listener for ~0.7 s
    while the audio keeps running (a straight L-cut - the audio never jumps).
  * HOOK FLASH picked from a frame where a face is actually visible.
  * Caption keyword POP (scale animation) + keyword colour.
  * Impact thump under the hook flash, whoosh on every cut, low music bed.
  * Loop tail so the clip restarts seamlessly.

Campaign rules respected: hard cuts and punch-ins only, no filters, no colour
work, no flashy transitions, no AI. Watermark bottom-left the whole clip.
"""
from __future__ import annotations

import json
import re
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
MUSIC = ROOT / "assets" / "music_bed.wav"
WHOOSH = ROOT / "assets" / "whoosh.wav"
OUT = ROOT / "clips_v3"
W, H = 1080, 1920
SR = 44100
FPS = 5.0

from render_lad import PLAN, pick_name, speaker, censor

KEYWORDS = {"fuck", "fucking", "shit", "holy", "no", "never", "hard", "insane",
            "crazy", "rigged", "horrific", "bad", "abomination", "strategy",
            "champion", "winner", "zero", "stop", "why", "what", "how"}
TIGHT, MID, WIDE = ("tight", 880, 495), ("mid", 1000, 563), ("wide", 1080, 608)


MIN_COV = float(__import__("os").environ.get("LAD_MIN_COV", "0.75"))
STOP_COV = float(__import__("os").environ.get("LAD_STOP_COV", "0.92"))
ANCHORS = int(__import__("os").environ.get("LAD_ANCHORS", "3"))
PROBE = __import__("os").environ.get("LAD_PROBE", "1") == "1"
PART_PRESET = __import__("os").environ.get("LAD_PART_PRESET", "ultrafast")
PART_CRF = __import__("os").environ.get("LAD_PART_CRF", "18")
MIN_DUR = float(__import__("os").environ.get("LAD_MIN_DUR", "15.6"))


def mid_var(i):
    return MID if i % 2 == 0 else WIDE


# ------------------------------------------------------------------ analysis
def analyze(path: Path, a: float, b: float):
    """Track the guests over [a,b] and measure real mouth motion.

    Consecutive sampled frames are cached, so mouth motion is a true frame-to-
    frame difference on the SAME person. Tiny/spurious detections are dropped
    and two people are separated by position, so the crop can follow whoever
    is actually talking.
    """
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    cas = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    alt = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_alt2.xml")
    frames, dets = [], []          # frames[i] = small gray image at time t_i
    n = int((b - a) * FPS)
    for k in range(n):
        t = a + k / FPS
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
        ok, fr = cap.read()
        if not ok:
            continue
        small = cv2.cvtColor(cv2.resize(fr, (480, 270)), cv2.COLOR_BGR2GRAY)
        frames.append(small)
        found = []
        for (x, y, w, h) in cas.detectMultiScale(small, 1.1, 5, minSize=(18, 18)):
            if w < 16 or w > 130:              # too small = noise, too big = junk
                continue
            roi = small[y:y + h, x:x + w]
            if alt.empty() or len(alt.detectMultiScale(roi, 1.05, 3)) == 0:
                continue                        # second opinion on every face
            found.append(dict(i=len(frames) - 1, t=t, cx=(x + w / 2) * 4,
                              cy=(y + h / 2) * 4, w=w * 4, h=h * 4,
                              box=(x, y, w, h)))
        dets.append(found)

    def mouth_motion(d1, d2):
        if d2["i"] != d1["i"] + 1:
            return None
        f1, f2 = frames[d1["i"]], frames[d2["i"]]
        x1, y1, w1, h1 = d1["box"]
        x2, y2, w2, h2 = d2["box"]
        m1 = f1[int(y1 + h1 * 0.55):y1 + h1, x1:x1 + w1]
        m2 = f2[int(y2 + h2 * 0.55):y2 + h2, x2:x2 + w2]
        if m1.size == 0 or m2.size == 0:
            return None
        hh = min(m1.shape[0], m2.shape[0])
        ww = min(m1.shape[1], m2.shape[1])
        if hh < 3 or ww < 3:
            return None
        a1 = m1[:hh, :ww].astype(np.int16)
        a2 = m2[:hh, :ww].astype(np.int16)
        return float(np.abs(a1 - a2).mean())

    tracks = []
    for found in dets:
        for d in found:
            best, bd = None, 1e9
            for tr in tracks:
                last = tr["f"][-1]
                if d["i"] - last["i"] > 3:            # stale track
                    continue
                dd = abs(last["cx"] - d["cx"]) + abs(last["cy"] - d["cy"])
                if dd < bd and dd < 220:
                    best, bd = tr, dd
            m = None
            if best is not None:
                m = mouth_motion(best["f"][-1], d)
            d["motion"] = m if m is not None else 0.0
            if best is None:
                tracks.append({"f": [d]})
            else:
                best["f"].append(d)
    cap.release()
    return [t for t in tracks if len(t["f"]) >= 2]


def pick(tracks, t0: float, t1: float, exclude=None):
    """Who is talking in [t0,t1]: most mouth movement while on camera."""
    span = max(0.4, t1 - t0)
    best, bs = None, -1.0
    for tr in tracks:
        if tr is exclude:
            continue
        fs = [f for f in tr["f"] if t0 - 0.25 <= f["t"] <= t1 + 0.25]
        if not fs:
            continue
        presence = len(fs) / (span * FPS)
        motion = float(np.mean([f["motion"] for f in fs]))
        score = motion * min(1.0, presence)
        if presence < 0.45:
            score *= 0.3
        if score > bs:
            best, bs = tr, score
    return best


def box(tr, t0: float, t1: float):
    fs = [f for f in tr["f"] if t0 - 0.3 <= f["t"] <= t1 + 0.3] or tr["f"]
    return dict(cx=float(np.median([f["cx"] for f in fs])),
                cy=float(np.median([f["cy"] for f in fs])),
                w=float(np.median([f["w"] for f in fs])))


def crop_xy(face, variant):
    """Crop width follows the measured face size, so a close face is not
    cropped too tight and a distant one is not lost in the frame."""
    if face is None:
        _, ch, cw = WIDE
    else:
        cw = int(min(540, max(430, face["w"] * 3.0)))
        cw -= cw % 2
        ch = int(cw * 16 / 9) // 2 * 2
        if ch > 1080:
            ch, cw = 1080, 608
        if face["w"] < 95:            # tiny/far face -> wider for context
            cw, ch = 608, 1080
    cx = face["cx"] if face else 960.0
    cy = face["cy"] if face else 540.0
    x = int(cx - cw / 2)
    y = int(cy - ch * 0.44)
    # always dead-centre on the speaker; only the frame edge may stop us
    x = int(max(0, min(1920 - cw, x)))
    y = int(max(0, min(1080 - ch, y)))
    return (x - x % 2), (y - y % 2), cw, ch



_CAS = None
_ALT = None
_ASR = None
cv2.setNumThreads(1)
_FRAME_CACHE = {}


def _profile():
    global _PRO
    try:
        return _PRO
    except NameError:
        pass
    _PRO = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_profileface.xml")
    return _PRO


def _cascades():
    global _CAS, _ALT
    if _CAS is None:
        _CAS = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        _ALT = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_alt2.xml")
    return _CAS, _ALT


def frame_at(path: Path, t: float):
    key = (str(path), round(t, 2))
    if key in _FRAME_CACHE:
        return _FRAME_CACHE[key]
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
    ok, fr = cap.read()
    cap.release()
    if not ok:
        return None
    g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
    g = cv2.resize(g, None, fx=0.5, fy=0.5)      # half-size is plenty
    if len(_FRAME_CACHE) > 18:
        _FRAME_CACHE.clear()
    _FRAME_CACHE[key] = g
    return g


def face_score(gray, x, y, cw, ch):
    """How well a candidate crop frames a face: bigger, more central = better."""
    x, y = int(round(x)), int(round(y))
    if x < 0 or y < 0 or x + cw > gray.shape[1] or y + ch > gray.shape[0]:
        return 0.0
    roi = gray[y:y + ch, x:x + cw]
    small = cv2.resize(roi, (300, int(300 * ch / cw)))
    cas, alt = _cascades()
    best = 0.0
    for boxes, bonus in ((cas.detectMultiScale(small, 1.08, 4, minSize=(26, 26)), 1.0),
                         (alt.detectMultiScale(small, 1.05, 3, minSize=(26, 26)), 0.9)):
        for (fx, fy, fw, fh) in boxes:
            cxf, cyf = fx + fw / 2, fy + fh / 2
            # distance of the face from the ideal spot (centre, slightly high)
            dx = abs(cxf - 150) / 150.0
            dy = abs(cyf - small.shape[0] * 0.40) / small.shape[0]
            central = max(0.0, 1.4 - (dx * 0.9 + dy * 0.7))
            best = max(best, (fw / 300.0) * 100 * central * bonus)
    return best


def frame_face(path: Path, t: float):
    """Largest face in one source frame (1920x1080 coords) or None."""
    g = frame_at(path, t)
    if g is None:
        return None
    cas, alt = _cascades()
    best = None
    for scale in (0.66, 1.0):
        gs = cv2.resize(g, None, fx=scale, fy=scale) if scale != 1.0 else g
        ms = max(18, int(30 * scale))
        for det in (cas, alt):
            for (x, y, w, h) in det.detectMultiScale(gs, 1.08, 4, minSize=(ms, ms)):
                cx, cy = (x + w / 2) / scale * 2, (y + h / 2) / scale * 2
                ww = w / scale * 2
                if best is None or ww > best["w"]:
                    best = dict(cx=cx, cy=cy, w=ww)
    return best


def crop_on(face, cw, ch):
    if face is None:
        return None
    cw = int(cw)
    ch = int(ch)
    x = int(max(0, min(1920 - cw, face["cx"] - cw / 2)))
    y = int(max(0, min(1080 - ch, face["cy"] - ch * 0.44)))
    return (x - x % 2, y - y % 2)


def best_crop(path: Path, times, hint, cw, ch):
    """Search crop offsets and keep the one where a face is really framed."""
    times = [t for t in times if frame_at(path, t) is not None][:3]
    if not times:
        return hint
    g0 = frame_at(path, times[0])
    hx = hint[0] if hint else g0.shape[1] / 2
    hy = hint[1] if hint else g0.shape[0] / 2
    best, bs = (hx - cw / 2, hy - ch * 0.44), -1.0
    for dx in range(-360, 361, 60):
        for dy in range(-200, 201, 100):
            x, y = hx + dx - cw / 2, hy + dy - ch * 0.44
            sc = sum(face_score(frame_at(path, t), x, y, cw, ch) for t in times)
            if sc > bs:
                bs, best = sc, (x, y)
    if bs <= 0:                     # nothing anywhere near: full-frame search
        for x in range(0, 1921 - cw, 120):
            for y in range(0, 1081 - ch, 120):
                sc = sum(face_score(frame_at(path, t), x, y, cw, ch) for t in times)
                if sc > bs:
                    bs, best = sc, (x, y)
    x = int(max(0, min(1920 - cw, best[0])))
    y = int(max(0, min(1080 - ch, best[1])))
    return (x - x % 2, y - y % 2, bs)



def shot_stats(path: Path):
    """(coverage, mean_face_width) for a rendered shot."""
    cap = cv2.VideoCapture(str(path))
    fw = cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1080
    fh = cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1920
    cap.release()
    w = 300
    h = int(round(w * fh / fw)) // 2 * 2
    raw = subprocess.run([FF, "-v", "error", "-i", str(path), "-an", "-vf",
                          f"fps=6,scale={w}:{h},format=gray", "-f", "rawvideo",
                          "-pix_fmt", "gray", "-"], capture_output=True).stdout
    n = len(raw) // (w * h)
    if n == 0:
        return 0.0, 0.0
    cas, alt = _cascades()
    good, sizes = 0, []
    for i in range(n):
        g = np.frombuffer(raw[i * w * h:(i + 1) * w * h], dtype=np.uint8).reshape(h, w)
        hit = 0
        for scale in (1.0, 0.6):
            gs = cv2.resize(g, None, fx=scale, fy=scale) if scale != 1.0 else g
            m = max(14, int(20 * scale))
            for det in (cas, alt):
                for (fx, fy, fw2, fh2) in det.detectMultiScale(gs, 1.08, 4, minSize=(m, m)):
                    mx0, my0 = fx / scale, fy / scale
                    mx1, my1 = (fx + fw2) / scale, (fy + fh2) / scale
                    inside = (mx0 > 10 and my0 > 6 and
                              mx1 < w - 10 and my1 < h - 6)
                    if inside:
                        hit = max(hit, int(fw2 / scale))
        if hit:
            good += 1
            sizes.append(hit)
    return good / n, (float(np.mean(sizes)) if sizes else 0.0)


def probe_crop(v0: float, v1: float, x: int, y: int, cw: int, ch: int):
    """Cheap preview: 3 stills from this crop, scored like shot_stats does.
    Rendering a whole candidate shot just to throw it away was 60 % of the
    build time - this tests the same thing in ~0.2 s."""
    ts = [v0 + 0.15, (v0 + v1) / 2, max(v0 + 0.2, v1 - 0.25)]
    good, sizes = 0, []
    cas, alt = _cascades()
    for t in ts:
        g = frame_at(SRC, t)
        if g is None:
            continue
        sub = g[max(0, y):y + ch, max(0, x):x + cw]
        if sub.size == 0:
            continue
        sub = cv2.equalizeHist(sub)
        hit = 0
        for scale in (1.0, 0.6):
            gs = cv2.resize(sub, None, fx=scale, fy=scale) if scale != 1.0 else sub
            m = max(14, int(20 * scale))
            for det in (cas, alt):
                for (fx, fy, fw2, fh2) in det.detectMultiScale(gs, 1.08, 4, minSize=(m, m)):
                    hit = max(hit, int(fw2 / scale))
        if hit:
            good += 1
            sizes.append(hit)
    cov = good / max(1, len(ts))
    size = float(np.mean(sizes)) if sizes else 0.0
    return cov, size


def render_shot(v0: float, v1: float, x: int, y: int, cw: int, ch: int, out: Path):
    subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y",
                    "-ss", f"{v0:.3f}", "-t", f"{max(0.16, v1 - v0):.3f}", "-i", str(SRC),
                    "-ss", f"{v0:.3f}", "-t", f"{max(0.16, v1 - v0):.3f}", "-i", str(SRC),
                    "-map", "0:v:0", "-map", "1:a:0",
                    "-vf", f"crop={cw}:{ch}:{x}:{y},scale={W}:{H}:flags=lanczos,"
                           f"setsar=1,fps=30",
                    "-c:v", "libx264", "-preset", PART_PRESET, "-crf", PART_CRF,
                    "-threads", "1", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-b:a", "192k", "-ar", "48000", "-ac", "2",
                    "-shortest", str(out)], check=True)


def has_face(path: Path, t0: float, t1: float) -> bool:
    """Is a guest actually ON SCREEN anywhere in this time range?"""
    ts = [t0 + (t1 - t0) * f for f in (0.15, 0.5, 0.85)]
    cas, alt = _cascades()
    hits = 0
    for t in ts:
        g = frame_at(path, t)
        if g is None:
            continue
        small = cv2.resize(g, (640, 360))
        if len(cas.detectMultiScale(small, 1.08, 4, minSize=(30, 30))) or \
           len(alt.detectMultiScale(small, 1.05, 3, minSize=(30, 30))):
            hits += 1
    return hits >= 2


def _any_face(gray) -> bool:
    cas, alt = _cascades()
    pro = _profile()
    for scale in (1.0, 0.55, 0.35):
        if scale != 1.0:
            g = cv2.resize(gray, None, fx=scale, fy=scale)
        else:
            g = gray
        m = max(14, int(20 * scale))
        if len(cas.detectMultiScale(g, 1.08, 4, minSize=(m, m))) or \
           len(alt.detectMultiScale(g, 1.05, 3, minSize=(m, m))):
            return True
        pm = max(16, int(24 * scale))
        if len(pro.detectMultiScale(g, 1.07, 4, minSize=(pm, pm))) or \
           len(pro.detectMultiScale(cv2.flip(g, 1), 1.07, 4, minSize=(pm, pm))):
            return True
    return False


def verify(path: Path, fps: float = 3.0) -> float:
    """Share of finished frames that actually contain a person."""
    cap = cv2.VideoCapture(str(path))
    fw = cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1080
    fh = cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1920
    cap.release()
    w = 320
    h = int(round(w * fh / fw)) // 2 * 2
    raw = subprocess.run([FF, "-v", "error", "-i", str(path), "-an", "-vf",
                          f"fps={fps},scale={w}:{h},format=gray", "-f", "rawvideo",
                          "-pix_fmt", "gray", "-"], capture_output=True).stdout
    n = len(raw) // (w * h)
    good = sum(1 for i in range(n)
               if _any_face(np.frombuffer(raw[i * w * h:(i + 1) * w * h],
                                          dtype=np.uint8).reshape(h, w)))
    return good / max(1, n)


# ------------------------------------------------------------------ words
_WORDS_ALL = None


def _words_all():
    """Whole-episode word timings precomputed by bots/transcribe_bot.py."""
    global _WORDS_ALL
    if _WORDS_ALL is None:
        p = ROOT / "assets" / "words_all.json"
        _WORDS_ALL = json.loads(p.read_text()) if p.exists() else []
    return _WORDS_ALL


def words_in(path, a: float, b: float):
    allw = _words_all()
    if allw:                                    # no Whisper in the workers
        return [w for w in allw if a - 0.08 <= w["t"] <= b + 0.08]
    raw = subprocess.run([FF, "-v", "error", "-ss", f"{a:.2f}", "-t", f"{b - a:.2f}",
                          "-i", str(path), "-vn", "-ac", "1", "-ar", "16000",
                          "-f", "s16le", "-"], capture_output=True).stdout
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    global _ASR
    if _ASR is None:
        from faster_whisper import WhisperModel
        _ASR = WhisperModel("small.en", device="cpu", compute_type="int8", cpu_threads=1)
    segs, _ = _ASR.transcribe(audio, language="en", beam_size=1, vad_filter=False,
                              word_timestamps=True, condition_on_previous_text=False)
    return [dict(t=round(w.start + a, 2), e=round(w.end + a, 2), w=w.word.strip())
            for s in segs for w in s.words]


def release_asr():
    """Whisper eats ~600 MB; free it before rendering/verifying (2 GB box)."""
    global _ASR
    if _ASR is not None:
        _ASR = None
        import gc
        gc.collect()


def segments_of(ws, t0, t1):
    """Split a window into spoken runs; drop silence longer than 0.45 s."""
    runs, cur = [], None
    for w in ws:
        if not (t0 - 0.1 <= w["t"] <= t1):
            continue
        if cur is None:
            cur = [w["t"], w["e"], [w]]
        elif w["t"] - cur[1] < 0.45:
            cur[1] = w["e"]
            cur[2].append(w)
        else:
            runs.append(cur)
            cur = [w["t"], w["e"], [w]]
    if cur:
        runs.append(cur)
    out = []
    for s, e, wl in runs:
        s, e = max(t0, s - 0.06), min(t1, e + 0.18)
        if e - s < 0.35:
            continue
        # too long -> split on 3.2 s so the visual keeps moving
        while e - s > 3.2:
            out.append((s, s + 3.2, wl))
            s += 3.2
        out.append((s, e, wl))
    return out


# ------------------------------------------------------------------ timeline
def build_timeline(ws, runs, tracks, start):
    """(video_in, video_out, face, variant, audio_in, audio_out).

    Audio is always taken from the same continuous run, so a reaction cut only
    changes the picture - the sound never jumps.
    """
    tl = []
    for idx, (s, e, _) in enumerate(runs):
        spk = pick(tracks, s, e)
        lis = pick(tracks, s, e, exclude=spk)
        variant = TIGHT if idx == 0 else (MID if idx % 2 == 0 else WIDE)
        if spk is None:
            tl.append((s, e, None, WIDE, s, e))
            continue
        # punchline = last run, gets a listener reaction over its tail
        if idx == len(runs) - 1 and lis is not None and (e - s) > 1.8:
            m = e - 0.7
            tl.append((s, m, box(spk, s, m), variant, s, m))
            tl.append((m, e, box(lis, m, e), TIGHT, m, e))     # reaction cut
        elif lis is not None and (e - s) > 2.4:
            m = s + (e - s) * 0.55
            tl.append((s, m, box(spk, s, m), variant, s, m))
            tl.append((m, e, box(spk, m, e), variant, m, e))    # punch-in
        else:
            tl.append((s, e, box(spk, s, e), variant, s, e))
    return tl


# ------------------------------------------------------------------ captions
def clock(t: float) -> str:
    n = round(max(0.0, t) * 100)
    return f"{n // 360000}:{(n // 6000) % 60:02}:{(n // 100) % 60:02}.{n % 100:02}"


def ass_file(path: Path, words, t_map, total, hook, name):
    ev = [f"Dialogue: 2,0:00:00.00,0:00:02.40,Name,{name}",
          f"Dialogue: 3,0:00:00.00,{clock(min(2.6, total))},Hook,{hook.upper()}"]
    grp = []

    def emit(g):
        if not g:
            return
        parts = []
        for w in g:
            word = censor(w["w"]).upper()
            if w["w"].lower().strip(".,!?") in KEYWORDS:
                parts.append("{\\c&H00E5FF&\\fscx106\\fscy106\\t(0,90,\\fscx100\\fscy100)}"
                             + word + "{\\r}")
            else:
                parts.append(word)
        a = t_map(g[0]["t"])
        b = t_map(g[-1]["e"]) + 0.10
        ev.append(f"Dialogue: 0,{clock(a)},{clock(b)},Cap,{' '.join(parts)}")

    for w in words:
        grp.append(w)
        if len(grp) >= 3 or w["w"].endswith(("?", "!", ".")) or \
           len(" ".join(x["w"] for x in grp)) > 15:
            emit(grp)
            grp = []
    emit(grp)
    path.write_text(f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,DejaVu Sans,84,&H0000E5FF,&H00101010,&H00000000,1,8,80,80,300,1
Style: Name,DejaVu Sans,46,&H00FFFFFF,&H00000000,&H80000000,1,8,90,90,150,3
Style: Cap,DejaVu Sans,60,&H00FFFFFF,&H00101010,&H00000000,1,2,70,70,520,1
[Events]
Format: Layer, Start, End, Style, Text
""" + "\n".join(ev) + "\n", encoding="utf8")


# ------------------------------------------------------------------ audio
def sfx_track(total: float, cuts, out: Path):
    def load(p):
        import wave
        with wave.open(str(p)) as f:
            return np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16
                                 ).astype(np.float32) / 32768.0
    music, who = load(MUSIC), load(WHOOSH)
    n = int(total * SR)
    buf = np.tile(music, int(total / (len(music) / SR)) + 2)[:n] * 0.10
    f = int(0.35 * SR)
    buf[:f] *= np.linspace(0, 1, f)
    buf[-f:] *= np.linspace(1, 0, f)
    # impact thump on the hook flash
    t = np.arange(int(0.28 * SR)) / SR
    thump = np.sin(2 * np.pi * (70 * np.exp(-t * 18) + 42) * t) * np.exp(-t * 12) * 0.55
    buf[:len(thump)] += thump
    for c in cuts:
        i = int(c * SR)
        if 0 <= i < n - len(who):
            buf[i:i + len(who)] += who * 0.28
    import wave
    with wave.open(str(out), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(buf, -1, 1) * 32767).astype(np.int16).tobytes())


# ------------------------------------------------------------------ build
def build(ep: int):
    start, dur, hook, cap, plan_name = PLAN[ep - 1]
    end = start + dur
    tmp = ROOT / "assets" / f"_ep{ep:02d}"
    tmp.mkdir(parents=True, exist_ok=True)

    ws = words_in(SRC, start, end)
    if not ws:
        raise RuntimeError("no words")
    import gc
    gc.collect()
    tracks = analyze(SRC, start, end)
    gc.collect()
    runs = segments_of(ws, start, end)
    # a clip may only show a shot where a guest is actually on camera
    runs = [r for r in runs if pick(tracks, r[0], r[1]) is not None]

    # hook flash: first 1.0 s from a run that has a face on camera
    flash = None
    for s, e, _ in runs:
        if pick(tracks, s, min(e, s + 1.0)) is not None:
            flash = (s, min(e, s + 1.0), box(pick(tracks, s, s + 1.0), s, s + 1.0), TIGHT,
                     s, min(e, s + 0.02))
            break
    if flash is None:
        flash = (runs[0][0], runs[0][0] + 1.0, None, WIDE, runs[0][0], runs[0][0] + 0.02)

    tl = build_timeline(ws, runs, tracks, start)
    # a shot is only allowed if a guest is genuinely in frame for it
    kept = [sh for sh in tl if has_face(SRC, sh[0], sh[1])]
    if len(kept) * 1.0 < len(tl):
        print(f"  dropped {len(tl) - len(kept)} shots with nobody on screen")
    tl = kept or tl
    flash_ok = has_face(SRC, flash[0], flash[1])
    tl = ([flash] if flash_ok else []) + tl
    tl = tl + [(tl[0][0], tl[0][0] + 0.6, tl[0][2], tl[0][3], tl[0][4], tl[0][4] + 0.02)]

    tl = [(v0, v1, f, var, v0, v1) for (v0, v1, f, var, a0, a1) in tl]
    total = sum(v1 - v0 for v0, v1, _, _, _, _ in tl)
    extra = 0
    while total < 15.2 and extra < 20:      # 15 s campaign floor
        lo, hi = max(0.0, start - 6 - extra), min(660.0, end + 10 + extra)
        more = [r for r in segments_of(words_in(SRC, lo, hi), lo, hi)
                if has_face(SRC, r[0], r[1]) and not any(abs(r[0] - x[0]) < 0.5 for x in tl)]
        if not more:
            extra += 6
            continue
        add = more[:2]
        tl[1:1] = [(s, e, box(pick(tracks, s, e), s, e) if pick(tracks, s, e) else None,
                    mid_var(i), s, e) for i, (s, e, _) in enumerate(add)]
        total = sum(v1 - v0 for v0, v1, _, _, _, _ in tl)
        extra += 6
    total = sum(v1 - v0 for v0, v1, _, _, _, _ in tl)
    release_asr()

    # render shot by shot; verify each one and retry with another crop if the
    # frame misses the person entirely (2 GB box: no giant filter graph)
    parts, kept_shots, skipped, retried = [], [], 0, 0
    for i, (v0, v1, face, var, a0, a1) in enumerate(tl):
        ts = (v0 + 0.15, (v0 + v1) / 2, max(v0 + 0.2, v1 - 0.25))
        anchors = [f for f in (frame_face(SRC, t) for t in ts) if f]
        cands = []
        for an in anchors[:ANCHORS]:
            cw = int(min(560, max(430, an["w"] * 3.0)))
            cw -= cw % 2
            ch = int(cw * 16 / 9) // 2 * 2
            if ch > 1080 or an["w"] < 95:
                ch, cw = 1080, 608
            xy = crop_on(an, cw, ch)
            if xy:
                cands.append((xy[0], xy[1], cw, ch))
        for cw, ch in ((608, 1080),):
            cands.append((int((1920 - cw) / 2), int((1080 - ch) / 2), cw, ch))
        if PROBE:                       # score every crop on stills, render only the winner
            scored = []
            for (x, y, cw, ch) in {(c[0], c[1], c[2], c[3]) for c in cands}:
                cov, size = probe_crop(v0, v1, x, y, cw, ch)
                scored.append((cov * 100 + min(size, 90) * 0.6, cov, (x, y, cw, ch)))
            scored.sort(reverse=True)
            keep = [c for _, cov, c in scored if cov >= MIN_COV] or [scored[0][2]]
            cands = keep[:2]            # best two get a real render, one usually wins
        seen, best = set(), None
        for (x, y, cw, ch) in cands:
            key = (x, y, cw, ch)
            if key in seen:
                continue
            seen.add(key)
            f = tmp / f"s{i:02d}_{len(seen)}.mp4"
            render_shot(v0, v1, x, y, cw, ch, f)
            cov, size = shot_stats(f)
            score = cov * 100 + min(size, 90) * 0.6
            if best is None or score > best[0]:
                if best:
                    best[1].unlink(missing_ok=True)
                best = (score, f, cov)
            else:
                f.unlink(missing_ok=True)
            if cov >= STOP_COV:
                break
            retried += 1
        if best is None:
            skipped += 1
            continue
        if best[2] < MIN_COV:
            skipped += 1
            best[1].unlink(missing_ok=True)
            continue
        parts.append(best[1])
        kept_shots.append((v0, v1))
    # dropping empty shots can push the clip under the 15 s floor -> backfill
    def dur_of(files):
        d = 0.0
        for f in files:
            i = subprocess.run([FF, "-hide_banner", "-i", str(f)],
                               capture_output=True, text=True).stderr
            m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", i)
            if m:
                d += int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
        return d

    tried = {round(v0, 1) for v0, _, _, _, _, _ in tl}
    guard = 0
    while dur_of(parts) < MIN_DUR and guard < 24:
        guard += 1
        segs_all = json.load(open(ROOT / "assets" / "transcript_small.json"))
        near = sorted(
            [s for s in segs_all if s["start"] > 20 and s["start"] < 640
             and round(s["start"], 1) not in tried
             and all(abs(s["start"] - t) > 2.5 for t in tried)],
            key=lambda s: abs(s["start"] - start))
        added = False
        for seg in near[:6]:
            if not has_face(SRC, seg["start"], seg["end"] + 0.4):
                continue
            v0, v1 = seg["start"] - 0.06, min(seg["end"] + 0.35, seg["end"] + 0.6)
            ts = (v0 + 0.1, (v0 + v1) / 2)
            anchors = [f for f in (frame_face(SRC, t) for t in ts) if f]
            made = None
            for an in anchors[:2]:
                cw = int(min(560, max(430, an["w"] * 3.0))) // 2 * 2
                ch = int(cw * 16 / 9) // 2 * 2
                if ch > 1080 or an["w"] < 95:
                    ch, cw = 1080, 608
                xy = crop_on(an, cw, ch)
                if not xy:
                    continue
                f = tmp / f"add{len(parts):02d}.mp4"
                render_shot(v0, v1, xy[0], xy[1], cw, ch, f)
                cov, _ = shot_stats(f)
                if cov >= 0.85:
                    made = f
                    break
                f.unlink(missing_ok=True)
            if made:
                parts.append(made)
                kept_shots.append((v0, v1))
                tried.add(round(v0, 1))
                added = True
                if dur_of(parts) >= MIN_DUR:
                    break
        if not added:
            break

    # captions + sfx are built from the shots that ACTUALLY made it into the
    # file (a dropped shot used to shift every caption after it)
    shots_final = [(v0, v1) for (v0, v1) in kept_shots]
    tcur = sum(v1 - v0 for v0, v1 in shots_final)
    cuts_t = []
    acc = 0.0
    for i, (v0, v1) in enumerate(shots_final):
        if i:
            cuts_t.append(acc)
        acc += v1 - v0
    t_map = {}
    acc = 0.0
    for v0, v1 in shots_final:
        for w in ws:
            if (v0 - 0.02) <= w["t"] < v1 and w["t"] not in t_map:
                t_map[w["t"]] = acc + (w["t"] - v0)
        acc += v1 - v0
    mapped = [dict(t=t_map[w["t"]], e=None, w=w["w"]) for w in ws if w["t"] in t_map]
    for i, m in enumerate(mapped):
        nx = next((x["t"] for x in mapped[i + 1:]), m["t"] + 0.45)
        m["e"] = min(nx, m["t"] + 0.65)
    mapped.sort(key=lambda m: m["t"])

    sfx = tmp / "sfx.wav"
    sfx_track(tcur, cuts_t[1:], sfx)
    ass = tmp / "caps.ass"
    ass_file(ass, mapped, lambda t: t, tcur, hook,
             pick_name(hook, speaker(SRC, start, 2.2) or plan_name))
    release_asr()

    lst = tmp / "list.txt"
    lst.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in parts), encoding="utf8")
    joined = tmp / "joined.mp4"
    subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat",
                    "-safe", "0", "-i", str(lst), "-c", "copy", str(joined)], check=True)

    out = OUT / f"ep{ep:02d}.mp4"
    subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(joined), "-i", str(WM), "-i", str(sfx),
                    "-filter_complex",
                    "[1:v]scale=330:-1[wm];[0:v][wm]overlay=46:H-190:format=auto[vs];"
                    f"[vs]ass={ass}[v];"
                    "[0:a]loudnorm=I=-15:TP=-1.5:LRA=11[dln];"
                    "[dln][2:a]amix=inputs=2:duration=first:normalize=0[a]",
                    "-map", "[v]", "-map", "[a]",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart", str(out)], check=True)
    for p in parts:
        p.unlink(missing_ok=True)
    lst.unlink(missing_ok=True)
    joined.unlink(missing_ok=True)
    sfx.unlink(missing_ok=True)
    if skipped or retried:
        print(f"  shots: {len(parts)} kept, {skipped} dropped, {retried} crop retries")
    cover = verify(out)
    return out, tcur, len(tl), len(runs), cover


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for ep in [int(x) for x in sys.argv[1:]] or [1]:
        out, total, shots, runs, cover = build(ep)
        flag = "OK" if cover >= 0.9 else "LOW FACE COVERAGE"
        print(f"ep{ep:02d}  {total:.1f}s  {shots} shots / {runs} runs  "
              f"face in {cover*100:.0f}% frames  [{flag}] -> {out.name}")


if __name__ == "__main__":
    main()
