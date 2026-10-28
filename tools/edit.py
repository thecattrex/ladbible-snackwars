#!/usr/bin/env python3
"""Edit a clip: several shots, real moves, cuts on the beat — not one continuous take.

A "clip" here is an edit, not a slice:

  shots   — 4-6 pieces pulled from different moments, so the clip shows what was
            actually happening (dancing, costumes, crowd) instead of one held shot
  moves   — every shot carries a camera move: a slow push-in, a pull-out, or a
            hard punch-in. A static 16:9 stream reads as screen recording; a move
            reads as an edit
  cuts    — each cut is snapped to the nearest onset in the source audio, so cuts
            land on the music instead of fighting it
  sfx     — a soft whoosh on the cuts and a low thump on the punch-ins, mixed well
            under the stream audio. Restrained: a whoosh every cut is noise
  captions— only where somebody actually speaks, timed off the cut audio, and only
            when whisper is confident. A dancing clip gets no invented dialogue
  grade   — the party is lit almost entirely in red; shadows lifted, cast pulled
            back to neutral, a little punch added

  python3 tools/edit.py <video> plan.json --out clip.mp4
  plan = {"title": str, "kicker": str, "shots": [{"in": 3600, "len": 5.0, "move": "push"}]}
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import layout as L   # noqa: E402

FF = "/home/user/bin/ffmpeg"
FPS = 30
FILLER = {"yeah", "okay", "alright", "oh", "ah", "um", "uh", "so", "like", "right",
          "yes", "no", "hi", "hey", "thank", "you", "thanks", "bye", "yea", "huh"}


# ---------------------------------------------------------------- audio helpers
def load_wav(path: Path, sr: int = 16000) -> np.ndarray:
    with wave.open(str(path)) as w:
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0


def onsets(x: np.ndarray, sr: int = 16000, hop: int = 256) -> np.ndarray:
    """Onset strength per hop — where the music hits."""
    n = len(x) // hop
    if n < 4:
        return np.zeros(2)
    frames = x[:n * hop].reshape(n, hop)
    energy = np.sqrt((frames ** 2).mean(axis=1))
    flux = np.diff(energy, prepend=energy[0])
    flux = np.clip(flux, 0, None)
    return flux


def snap(t: float, strength: np.ndarray, sr: int = 16000, hop: int = 256,
         window: float = 0.35) -> float:
    """Move a cut to the nearest onset within `window` seconds, if there is one."""
    if strength.size < 4:
        return t
    i = int(t * sr / hop)
    lo, hi = max(0, i - int(window * sr / hop)), min(len(strength), i + int(window * sr / hop))
    if hi <= lo:
        return t
    seg = strength[lo:hi]
    if seg.max() <= 0:
        return t
    peak = lo + int(seg.argmax())
    return peak * hop / sr


def riser(path: Path, dur: float = 0.42, sr: int = 44100, seed: int = 11) -> None:
    """A soft swell that ends exactly on the cut.

    The old whoosh was a broadband swoosh — it hisses and calls attention to
    itself. This is a low-passed noise swell that rises into the cut and stops
    dead on it, so the ear feels the edit land instead of hearing an effect.
    """
    rng = np.random.default_rng(seed)
    n = int(sr * dur)
    noise = rng.standard_normal(n)
    out = np.zeros(n)
    y = 0.0
    for i in range(n):
        k = i / n
        cutoff = 0.010 + 0.055 * (k ** 2)          # stays dark, never hissy
        y += cutoff * (noise[i] - y)
        out[i] = y * (k ** 2.2)                     # rises to the cut, then stops
    out[-int(0.004 * sr):] *= np.linspace(1, 0, int(0.004 * sr))   # no click
    out = out / (np.abs(out).max() + 1e-9) * 0.22
    st = np.stack([out, out], axis=1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((st * 32767).astype(np.int16).tobytes())


def kb_click(path: Path, sr: int = 48000, seed: int = 5) -> None:
    """A mechanical keyboard clack: a dry noise tick with a tiny plastic body.

    Two parts — a bright noise burst that dies in ~25 ms, and a very short
    low click that gives it weight. Nothing sustained, nothing tonal, so it
    reads as a cut landing rather than as a sound effect.
    """
    import numpy as _np
    rng = _np.random.default_rng(seed)
    n = int(sr * 0.055)
    t = _np.arange(n) / sr
    tick = rng.standard_normal(n) * _np.exp(-t * 190)
    # keep only the bright part of the tick: first difference = a crude high-pass
    tick = _np.diff(tick, prepend=tick[0])
    body = _np.sin(2 * _np.pi * 210 * t) * _np.exp(-t * 260) * 0.35
    out = tick / (_np.abs(tick).max() + 1e-9) * 0.55 + body
    out[-int(0.003 * sr):] *= _np.linspace(1, 0, int(0.003 * sr))
    out = out / (_np.abs(out).max() + 1e-9) * 0.30
    st = _np.stack([out, out], axis=1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((st * 32767).astype(_np.int16).tobytes())


def thump(path: Path, sr: int = 44100) -> None:
    """Low hit for a punch-in — felt more than heard."""
    n = int(sr * 0.30)
    t = np.arange(n) / sr
    body = np.sin(2 * math.pi * 58 * t) * np.exp(-t * 22)
    out = body * 0.32
    st = np.stack([out, out], axis=1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((st * 32767).astype(np.int16).tobytes())


# ---------------------------------------------------------------- captions
def ass_time(t: float) -> str:
    h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def captions_from_audio(clip: Path, tmp: Path) -> list:
    """Transcribe the finished edit; keep only lines whisper is sure about.

    A party clip is mostly music. Asked to caption music, whisper invents
    "yeah yeah yeah", so confidence is checked and repeats are dropped.
    """
    from faster_whisper import WhisperModel
    import soundfile as sf
    wav = tmp / "audio.wav"
    subprocess.run([FF, "-v", "error", "-y", "-i", str(clip), "-vn", "-ac", "1",
                    "-ar", "16000", str(wav)], check=True)
    x, sr = sf.read(str(wav), dtype="float32")
    model = WhisperModel("small.en", device="cpu", compute_type="int8", cpu_threads=2)
    segs, _ = model.transcribe(x, language="en", vad_filter=True, beam_size=1,
                               condition_on_previous_text=False)
    cards = []
    for s in segs:
        text = " ".join(s.text.split())
        words = [w for w in text.split() if w.strip(".,!?").lower() not in FILLER]
        if len(words) < 3:
            continue
        if getattr(s, "avg_logprob", 0) < -0.65 or getattr(s, "no_speech_prob", 0) > 0.5:
            continue
        toks = text.split()
        if len({w.lower() for w in toks}) / len(toks) < 0.5:      # repeated = music
            continue
        # a card is 2-4 words: a whole sentence runs off a phone screen
        toks = text.split()
        span = max(0.4, s.end - s.start)
        step = span / len(toks)
        for i in range(0, len(toks), 4):
            part = toks[i:i + 4]
            if len(part) < 2:
                continue
            k = max(part, key=len).strip(".,!?")
            cards.append({"t0": round(s.start + i * step, 2),
                          "t1": round(min(s.end, s.start + (i + len(part)) * step) + 0.12, 2),
                          "text": " ".join(part), "key": k})
    return cards


def write_ass(cards: list, path: Path, w: int, h: int) -> None:
    lines = ["[Script Info]", f"PlayResX: {w}", f"PlayResY: {h}", "WrapStyle: 2",
             "ScriptType: v4.00+", "", "[V4+ Styles]",
             ("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour,"
              " BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle,"
              " BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"),
             ("Style: Cap,Bangers,84,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,"
              "-1,0,0,0,100,100,3,0,1,8,3,2,40,40,66,1"),
             "", "[Events]",
             "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    for c in cards:
        text, key = c["text"], c["key"]
        i = text.lower().find(key.lower())
        if i >= 0:
            text = (text[:i] + r"{\c&H2020E8&}" + text[i:i + len(key)] +
                    r"{\c&HFFFFFF&}" + text[i + len(key):])
        lines.append(f"Dialogue: 0,{ass_time(c['t0'])},{ass_time(c['t1'])},Cap,,0,0,0,,{text}")
    path.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------- picture
def move_filter(move: str, dur: float) -> str:
    """Camera move per shot. Everything is upscaled first so the move stays sharp."""
    up = "scale=1620:912:flags=lanczos"
    centre = "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
    if move == "push":
        z = f"min(1.02+{0.16 / max(dur, 0.1):.5f}*on,1.20)"
    elif move == "pull":
        z = f"max(1.20-{0.16 / max(dur, 0.1):.5f}*on,1.02)"
    elif move == "punch":
        z = "1.24"
    elif move == "tight":
        z = "1.36"
    else:                                    # static, but still not a raw screen grab
        z = "1.06"
    return f"{up},zoompan=z='{z}':{centre}:d=1:s={L.CLIP_W}x{L.CLIP_H}:fps={FPS}"


def build(video: Path, plan: dict, out: Path) -> None:
    tmp = Path(tempfile.mkdtemp())
    shots = plan["shots"]
    total = sum(s["len"] for s in shots)

    # cut points snapped to onsets in the source audio
    src_wav = tmp / "src.wav"
    lo = min(s["in"] for s in shots) - 1
    hi = max(s["in"] + s["len"] for s in shots) + 1
    subprocess.run([FF, "-v", "error", "-y", "-ss", str(lo), "-t", str(hi - lo),
                    "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(src_wav)],
                   check=True)
    x = load_wav(src_wav)
    st = onsets(x)
    for s in shots:
        s["in"] = round(snap(s["in"] - lo, st) + lo, 3)

    print("shots:", ", ".join(f'{s["in"]:.1f}+{s["len"]}s {s["move"]}' for s in shots))

    # video: one trim + move per shot, then hard cuts
    parts, graphs = [], []
    for i, s in enumerate(shots):
        parts += ["-ss", str(s["in"]), "-t", str(s["len"]), "-i", str(video)]
        graphs.append(f"[{i}:v]{move_filter(s['move'], s['len'])},setsar=1[v{i}]")
    graphs.append("".join(f"[v{i}]" for i in range(len(shots))) +
                  f"concat=n={len(shots)}:v=1:a=0[vc]")

    # audio: the same pieces, joined, then the stream audio is what you hear
    aparts, agraphs = [], []
    for i, s in enumerate(shots):
        aparts += ["-ss", str(s["in"]), "-t", str(s["len"]), "-i", str(video)]
        agraphs.append(f"[{i}:a]aresample=48000,asetpts=PTS-STARTPTS[a{i}]")
    agraphs.append("".join(f"[a{i}]" for i in range(len(shots))) +
                   f"concat=n={len(shots)}:v=0:a=1[ac]")

    # sfx: none unless the plan asks for a click on the cuts. No swells, no
    # whooshes — the user does not want to hear an effect at the edit point.
    mode = plan.get("sfx", "none")
    sfx_dir = tmp / "sfx"; sfx_dir.mkdir()
    sfx_inputs, sfx_graph = [], []
    base = len(shots)
    if mode == "click":
        kb_click(sfx_dir / "click.wav")
        for k, shot in enumerate(shots[1:]):
            at = sum(q["len"] for q in shots[:k + 1])
            sfx_inputs += ["-i", str(sfx_dir / "click.wav")]
            sfx_graph.append(f"[{base + k}:a]adelay={int(at * 1000)}|{int(at * 1000)},"
                             f"volume=0.55[c{k}]")

    # gain staging: the source is already loud, so pull it down before summing and
    # limit, otherwise the peak goes over 1.0 and the whole clip distorts
    n_sfx = len(sfx_graph)
    if n_sfx:
        mix = ("[ac]volume=0.72[acg];[acg]" + "".join(f"[c{k}]" for k in range(n_sfx)) +
               f"amix=inputs={1 + n_sfx}:duration=first:normalize=0,"
               "alimiter=limit=0.89[aout]")
    else:
        mix = "[ac]volume=0.80,alimiter=limit=0.89[aout]"

    clip = tmp / "clip.mp4"
    graph = ";".join(graphs + agraphs + sfx_graph + [mix])
    cmd = [FF, "-v", "error", "-y", *parts, *aparts[:0], *sfx_inputs,
           "-filter_complex", graph, "-map", "[vc]", "-map", "[aout]",
           "-t", f"{total:.3f}", "-r", str(FPS), "-threads", "2",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000", str(clip)]
    print("editing…", flush=True)
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print("ffmpeg said:\n" + res.stderr[-1500:])
        raise SystemExit(1)

    # a dance or costume clip has nobody talking over it; transcribing music only
    # invents words and costs memory this box does not have
    cards = []
    if plan.get("captions", True):
        print("captioning…", flush=True)
        cards = captions_from_audio(clip, tmp)
    print(f"{len(cards)} caption cards")
    ass = tmp / "caps.ass"
    write_ass(cards, ass, L.CLIP_W, L.CLIP_H)

    graded = tmp / "graded.mp4"
    sub = f",subtitles={ass}:fontsdir={L.ASSETS}" if cards else ""
    subprocess.run([FF, "-v", "error", "-y", "-i", str(clip), "-vf",
                    L.grade_filter() + ",setsar=1" + sub,
                    "-threads", "2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
                    "-c:a", "copy", str(graded)], check=True)

    base = L.static_canvas(plan.get("title", "halloween party"),
                           plan.get("kicker", "halloween party"))
    base.save(tmp / "base.png")
    print("compositing…", flush=True)
    subprocess.run([FF, "-v", "error", "-y", "-loop", "1", "-i", str(tmp / "base.png"),
                    "-i", str(graded), "-filter_complex",
                    f"[0:v][1:v]overlay=0:{L.CLIP_Y},format=yuv420p[out]",
                    "-map", "[out]", "-map", "1:a", "-t", f"{total:.3f}", "-r", str(FPS),
                    "-threads", "2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "176k",
                    "-movflags", "+faststart", str(out)], check=True)
    print("wrote", out, f"{out.stat().st_size / 1e6:.1f} MB  {total:.1f}s")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("plan")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    build(Path(args.video), json.loads(Path(args.plan).read_text()), Path(args.out))


if __name__ == "__main__":
    main()
