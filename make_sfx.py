"""Original bed music + whoosh, synthesized with numpy (no licensing, no downloads)."""
import numpy as np
import wave
from pathlib import Path

SR = 44100
OUT = Path("assets")
OUT.mkdir(exist_ok=True)


def write(path, x):
    x = np.clip(x, -1, 1)
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((x * 32767).astype(np.int16).tobytes())


def kick(dur=0.22):
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = 120 * np.exp(-t * 28) + 48
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 16) * 0.9


def hat(dur=0.06):
    n = int(dur * SR)
    return np.random.randn(n) * np.exp(-np.arange(n) / SR * 70) * 0.18


def bass(f, dur=0.30):
    n = int(dur * SR)
    t = np.arange(n) / SR
    x = np.sin(2 * np.pi * f * t) + 0.3 * np.sin(4 * np.pi * f * t)
    return x * np.exp(-t * 7) * 0.22


def build_music(bpm=96, bars=16):
    beat = 60 / bpm
    total = int(bars * 4 * beat * SR) + SR
    buf = np.zeros(total)
    roots = [55.0, 55.0, 65.4, 49.0]
    K, Hh = kick(), hat()
    for b in range(bars):
        for k in range(4):
            i = int((b * 4 + k) * beat * SR)
            buf[i:i + len(K)] += K * 0.55
            hi = i + int(beat / 2 * SR)
            buf[hi:hi + len(Hh)] += Hh
            if k % 2 == 0:
                bs = bass(roots[b % 4])
                buf[i:i + len(bs)] += bs
    t = np.arange(total) / SR
    pad = 0.05 * np.sin(2 * np.pi * 220 * t) + 0.03 * np.sin(2 * np.pi * 330 * t)
    pad *= 0.5 + 0.5 * np.sin(2 * np.pi * 0.08 * t)
    buf += pad
    return buf / (np.abs(buf).max() + 1e-6)


def lowpass(x, f):
    a = np.exp(-2 * np.pi * f / SR)
    y = np.zeros_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc = a * acc + (1 - a) * x[i]
        y[i] = acc
    return y


def build_whoosh(dur=0.42):
    n = int(dur * SR)
    t = np.arange(n) / SR
    noise = np.random.randn(n)
    out = np.zeros(n)
    for f, w in [(700, 0.5), (1600, 0.35), (3400, 0.15)]:
        out += lowpass(noise, f) * w
    e = np.exp(-((t - dur * 0.62) ** 2) / (2 * (dur * 0.13) ** 2))
    out = out * e
    return out / (np.abs(out).max() + 1e-6)


write(OUT / "music_bed.wav", build_music())
write(OUT / "whoosh.wav", build_whoosh())
print("ok", (OUT / "music_bed.wav").stat().st_size, (OUT / "whoosh.wav").stat().st_size)
