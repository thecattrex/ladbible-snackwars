#!/usr/bin/env python3
"""Sound design — synthesised, placed the way an editor places it.

Reference rules (docs/CRAFT.md has the sources):
  * a whoosh straddles a transition: it starts just before the cut, peaks on the
    frames that change, and tails off after;
  * an impact lands exactly on the cut or on the frame a card appears — even
    50 ms early reads as sloppy;
  * a riser builds into the moment and stops dead where the line lands; the
    abrupt stop is the effect;
  * effects sit about half the level of the voice (roughly -6 dB relative), and
    only the cuts that matter are sounded — sounding every join turns the mix
    into a percussion track.

Everything is generated here (no sample library, no licence to clear) with a
small additive/subtractive engine: filtered noise sweeps, pitch-dropping subs and
bell-free transients.
"""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

SR = 48000


def _write(path: Path, x: np.ndarray) -> str:
    x = np.clip(x, -1.0, 1.0)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        stereo = np.stack([x, x], axis=1)
        w.writeframes((stereo * 32767).astype(np.int16).tobytes())
    return str(path)


def _bandpass(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """Cheap FFT band-pass — enough for air and body shaping."""
    X = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(len(x), 1 / SR)
    mask = np.ones_like(freqs)
    mask[freqs < lo] = 0
    mask[freqs > hi] = 0
    # soft shoulders so the sweep does not ring
    lo2, hi2 = lo * 0.7, hi * 1.3
    edge = (freqs >= lo2) & (freqs < lo)
    mask[edge] = np.linspace(0, 1, edge.sum()) if edge.sum() else mask[edge]
    edge = (freqs > hi) & (freqs <= hi2)
    mask[edge] = np.linspace(1, 0, edge.sum()) if edge.sum() else mask[edge]
    return np.fft.irfft(X * mask, n=len(x))


def whoosh(dest: Path, dur: float = 0.62, bright: float = 1.0) -> str:
    """Air moving through a transition: noise whose band sweeps up then falls."""
    n = int(dur * SR)
    t = np.linspace(0, dur, n)
    noise = np.random.default_rng(11).normal(0, 1, n)
    # sweep the band with a few overlapping passes
    out = np.zeros(n)
    steps = 6
    for i in range(steps):
        c = i / (steps - 1)
        lo = 260 + 900 * c * bright
        hi = 1800 + 5200 * c * bright
        seg = _bandpass(noise, lo, hi)
        env = np.exp(-((t - dur * 0.52) ** 2) / (2 * (dur * 0.22) ** 2))
        out += seg * env / steps
    out *= 0.9 / (np.abs(out).max() + 1e-9)
    return _write(dest, out)


def impact(dest: Path, dur: float = 0.42, pitch: float = 62.0) -> str:
    """A soft thud with a click on the front: lands on the cut, not near it."""
    n = int(dur * SR)
    t = np.linspace(0, dur, n)
    body = np.sin(2 * np.pi * pitch * t) * np.exp(-9 * t)
    sub = np.sin(2 * np.pi * (pitch / 2) * t) * np.exp(-5 * t) * 0.7
    click = np.random.default_rng(5).normal(0, 1, n) * np.exp(-90 * t) * 0.35
    air = _bandpass(np.random.default_rng(7).normal(0, 1, n), 900, 6000) * np.exp(-40 * t) * 0.18
    out = body + sub + click + air
    out *= 0.92 / (np.abs(out).max() + 1e-9)
    return _write(dest, out)


def riser(dest: Path, dur: float = 1.4, stop_hard: bool = True) -> str:
    """A build that cuts off dead where the claim lands."""
    n = int(dur * SR)
    t = np.linspace(0, dur, n)
    noise = np.random.default_rng(3).normal(0, 1, n)
    sweep = np.zeros(n)
    steps = 8
    for i in range(steps):
        c = i / (steps - 1)
        seg = _bandpass(noise, 400 + 1500 * c, 2200 + 6500 * c)
        sweep += seg / steps
    tone = np.sin(2 * np.pi * (140 + 420 * (t / dur) ** 2) * t) * 0.35
    env = (t / dur) ** 2.4
    out = (sweep * 0.8 + tone) * env
    if stop_hard:
        cut = int(0.018 * SR)
        out[-cut:] *= np.linspace(1, 0, cut)
    out *= 0.85 / (np.abs(out).max() + 1e-9)
    return _write(dest, out)


def bed(dest: Path, dur: float, bpm: float = 82.0, key_hz: float = 55.0) -> str:
    """A quiet, dark bed: two detuned sines, a slow pulse, filtered noise."""
    n = int((dur + 1.0) * SR)
    t = np.linspace(0, n / SR, n)
    a = (np.sin(2 * np.pi * key_hz * t) * 0.5
         + np.sin(2 * np.pi * key_hz * 1.5 * t) * 0.26
         + np.sin(2 * np.pi * key_hz * 2.0 * t) * 0.12)
    beat = 60.0 / bpm
    pulse = 0.82 + 0.18 * (np.sin(2 * np.pi * t / beat) > 0)
    noise = _bandpass(np.random.default_rng(9).normal(0, 1, n), 120, 900) * 0.12
    out = (a * pulse + noise)
    out *= 1.0 / (np.abs(out).max() + 1e-9)
    return _write(dest, out)


def level_db(x_path: Path, target_db: float) -> float:
    """Gain needed to bring a mono file to target RMS-ish level."""
    with wave.open(str(x_path)) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    rms = np.sqrt((x ** 2).mean() + 1e-12)
    return 20 * np.log10((10 ** (target_db / 20)) / max(rms, 1e-6))
