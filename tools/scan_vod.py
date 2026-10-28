#!/usr/bin/env python3
"""Pick clip-worthy moments from a long stream using the picture AND the words.

Transcript alone is not enough: a calm conversation can read well and look dead,
and a loud room can be nothing but a lights show. So this measures both, per
second, over the whole VOD:

  picture — motion between frames, edge density, colour spread, brightness, and
            how many faces the detector finds (people on screen is the campaign's
            own ask: "big engaging moments with other people")
  sound   — loudness against the stream's own baseline, high-frequency energy
            (screams, laughter) and zero-crossing rate
  words   — optional whisper transcript: laughs, shouts, fast exchange

The three are combined into candidate 15-60 s windows, and the list is written
with the reason for every score, so the pick can be argued with.

  python3 tools/scan_vod.py <video> --out scan.json [--transcript t.json]
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
MODEL = ROOT / "assets" / "face_detection_yunet.onnx"
FF = "/home/user/bin/ffmpeg"
FW, FH = 192, 108          # metric frame
PW, PH = 640, 360          # proxy frame for face detection


def _read(pipe, nbytes):
    buf = pipe.read(nbytes)
    return buf if len(buf) == nbytes else None


def audio_curve(path: Path, sr: int = 16000) -> dict:
    p = subprocess.Popen([FF, "-v", "error", "-i", str(path), "-vn", "-ac", "1",
                          "-ar", str(sr), "-f", "f32le", "-"], stdout=subprocess.PIPE)
    n = sr
    db, zcr, hi = [], [], []
    freqs = np.fft.rfftfreq(n, 1 / sr)
    while True:
        buf = _read(p.stdout, n * 4)
        if buf is None:
            break
        x = np.frombuffer(buf, np.float32).astype(np.float64)
        db.append(20 * np.log10(np.sqrt((x ** 2).mean()) + 1e-9))
        zcr.append(float(np.abs(np.diff(np.signbit(x))).mean()))
        spec = np.abs(np.fft.rfft(x * np.hanning(n)))
        hi.append(float(spec[freqs > 2500].sum() / (spec[freqs <= 2500].sum() + 1e-9)))
    p.stdout.close(); p.wait()
    return {"db": db, "zcr": zcr, "bright": hi}


def video_curve(path: Path, fps: float = 2.0) -> dict:
    """Motion, edges, colour, brightness per frame-second, from the picture alone."""
    import cv2
    p = subprocess.Popen([FF, "-v", "error", "-i", str(path), "-an", "-vf",
                          f"fps={fps},scale={FW}:{FH}", "-pix_fmt", "bgr24",
                          "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
    size = FW * FH * 3
    motion, edges, colour, lum = [], [], [], []
    prev = None
    while True:
        buf = _read(p.stdout, size)
        if buf is None:
            break
        f = np.frombuffer(buf, np.uint8).reshape(FH, FW, 3)
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        lum.append(float(g.mean()))
        edges.append(float(cv2.Canny(g, 60, 140).mean()))
        # colour spread: how far the frame is from grey
        colour.append(float(np.abs(f.astype(np.int16) - g[..., None].astype(np.int16)).mean()))
        motion.append(0.0 if prev is None else float(np.abs(g.astype(np.int16)
                                                           - prev.astype(np.int16)).mean()))
        prev = g
    p.stdout.close(); p.wait()
    return {"fps": fps, "motion": motion, "edges": edges, "colour": colour, "lum": lum}


def face_curve(path: Path, fps: float = 1.0) -> list:
    """How many faces, at 1 fps, on a 640x360 proxy — people on screen matters."""
    import cv2
    if not MODEL.exists():
        return []
    det = cv2.FaceDetectorYN.create(str(MODEL), "", (PW, PH), 0.6, 0.3, 500)
    p = subprocess.Popen([FF, "-v", "error", "-i", str(path), "-an", "-vf",
                          f"fps={fps},scale={PW}:{PH}", "-pix_fmt", "bgr24",
                          "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
    size = PW * PH * 3
    out = []
    while True:
        buf = _read(p.stdout, size)
        if buf is None:
            break
        f = np.frombuffer(buf, np.uint8).reshape(PH, PW, 3)
        det.setInputSize((PW, PH))
        _, faces = det.detect(f)
        out.append(0 if faces is None else len(faces))
    p.stdout.close(); p.wait()
    return out


def per_second(curves: dict, seconds: int) -> dict:
    fps = curves["video"]["fps"]
    def agg(key, fn=np.mean):
        arr = np.array(curves["video"][key], dtype=float)
        n = max(1, int(fps))
        return [float(fn(arr[i:i + n])) if len(arr[i:i + n]) else 0.0
                for i in range(0, min(len(arr), seconds * n), n)]

    vis = {k: agg(k) for k in ("motion", "edges", "colour", "lum")}
    faces = curves["faces"] + [0] * (seconds - len(curves["faces"]))
    audio = {k: [float(v) for v in curves["audio"][k][:seconds]] for k in ("db", "zcr", "bright")}
    return {"video": vis, "faces": faces[:seconds], "audio": audio}


def normalise(v: list) -> np.ndarray:
    a = np.array(v, dtype=float)
    if a.size == 0:
        return a
    lo, hi = np.percentile(a, 5), np.percentile(a, 95)
    return np.clip((a - lo) / (hi - lo + 1e-9), 0, 1)


def windows(sec: dict, speech: list | None, min_len=20.0, max_len=45.0):
    motion = normalise(sec["video"]["motion"])
    edges = normalise(sec["video"]["edges"])
    colour = normalise(sec["video"]["colour"])
    lum = normalise(sec["video"]["lum"])
    db = normalise(sec["audio"]["db"])
    bright = normalise(sec["audio"]["bright"])
    zcr = normalise(sec["audio"]["zcr"])
    faces = np.clip(np.array(sec["faces"], dtype=float) / 3.0, 0, 1)
    n = len(motion)

    visual = 0.40 * motion + 0.20 * edges + 0.20 * colour + 0.20 * faces
    audible = 0.55 * db + 0.25 * bright + 0.20 * zcr

    LAUGH = ("haha", "hahaha", "lol", "laugh", "holy", "oh my god", "no way",
             "what", "stop", "bro", "dude", "let's go", "lets go", "wait")
    rows = []
    for length in (20, 25, 30, 35, 40, 45):
        for t in range(0, max(1, n - length), 5):
            b = slice(t, t + length)
            v, a = float(visual[b].mean()), float(audible[b].mean())
            f = float(faces[b].mean())
            text, kw = "", 0
            if speech:
                hits = [s for s in speech if s["t1"] > t and s["t0"] < t + length]
                text = " ".join(s["text"] for s in hits).strip()
                low = text.lower()
                kw = sum(low.count(w) for w in LAUGH)
            score = 1.0 * v + 0.8 * a + 0.15 * kw
            # a clip with nobody on screen is not a clip, however loud it is
            if f < 0.10:
                score *= 0.55
            rows.append({"t0": t, "len": length, "visual": round(v, 3),
                         "sound": round(a, 3), "faces": round(f, 2), "kw": kw,
                         "score": round(score, 4), "text": text[:200]})
    rows.sort(key=lambda r: -r["score"])
    picked = []
    for r in rows:
        if any(r["t0"] < p["t0"] + p["len"] and p["t0"] < r["t0"] + r["len"] for p in picked):
            continue
        picked.append(r)
        if len(picked) >= 20:
            break
    return picked


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--out", default="scan.json")
    ap.add_argument("--transcript", default=None)
    args = ap.parse_args()

    path = Path(args.video)
    probe = subprocess.run([FF, "-i", str(path)], capture_output=True, text=True).stderr
    dur = 0
    for line in probe.splitlines():
        if "Duration:" in line:
            h, m, s = line.split("Duration:")[1].split(",")[0].strip().split(":")
            dur = int(int(h) * 3600 + int(m) * 60 + float(s))
    print("duration", dur, "s")

    curves = {"video": video_curve(path), "audio": audio_curve(path)}
    curves["faces"] = face_curve(path)
    print("curves: video", len(curves["video"]["motion"]), "faces", len(curves["faces"]))

    sec = per_second(curves, dur)
    speech = json.loads(Path(args.transcript).read_text()) if args.transcript else None
    wins = windows(sec, speech)

    Path(args.out).write_text(json.dumps({"duration": dur, "seconds": sec,
                                          "windows": wins}, indent=1))
    print(f"{len(wins)} candidates -> {args.out}")
    for w in wins[:10]:
        print(f"  {w['t0']//60:>2}:{w['t0']%60:02d} +{w['len']}s  score {w['score']}  "
              f"visual {w['visual']} sound {w['sound']} faces {w['faces']} kw {w['kw']}"
              f"  | {w['text'][:60]}")


if __name__ == "__main__":
    main()
