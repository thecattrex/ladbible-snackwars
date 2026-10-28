#!/usr/bin/env python3
"""EDIT DEPARTMENT — one clone per clip, one clip per clone.

Does the whole visual/audio job for its clip and nothing else:
  speaker-follow 9:16 framing -> shot cuts on thought boundaries -> punch-ins
  -> whoosh on every cut + thump on the first number -> low music bed (ducked)
  -> 2-3 word captions with keyword pop -> in-clip hook card -> watermark
  -> light grade -> loudnorm.

  python3 departments/render_bot.py <campaign> <clip_id> <clips.json> <words-all.json>
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import wave
from pathlib import Path

import cv2
import numpy as np
import imageio_ffmpeg

FF = imageio_ffmpeg.get_ffmpeg_exe()
ROOT = Path(__file__).resolve().parent.parent
camp, clip_id, clips_path, words_path = sys.argv[1], sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4])
CAMP = json.loads((ROOT / "campaigns" / camp / "campaign.json").read_text())
import os
SRC = Path(os.environ.get("SRC_OVERRIDE", "/tmp/src.mp4"))
OUT = Path("/tmp/out")
OUT.mkdir(exist_ok=True)
WORK = Path("/tmp/work")
WORK.mkdir(exist_ok=True)
W, H = 1080, 1920
FPS = int(CAMP.get("fps", 30))
FR = CAMP["framing"]
CW, CH = int(FR["crop_w"]), int(FR["crop_h"])
KEY = re.compile(r"(\$?\d[\d,\.]*\s*(?:%|k|m|million|billion|thousand)?|"
                 r"\b(?:never|nothing|impossible|demolish|replaced|wrong|over|close|mistake)\b)", re.I)
cv2.setNumThreads(2)


# ---------------------------------------------------------------- assets
def sfx(dest: Path, kind: str):
    """All sound effects are synthesised here — nothing licensed, nothing struck."""
    sr = 44100
    if kind == "whoosh":
        n = int(0.28 * sr)
        t = np.linspace(0, 1, n)
        noise = np.random.default_rng(7).normal(0, 1, n)
        env = np.sin(np.pi * t) ** 2
        a = noise * env
        a = np.convolve(a, np.ones(24) / 24, mode="same")      # airy, not hissy
        a *= 0.5
    elif kind == "thump":
        n = int(0.35 * sr)
        t = np.linspace(0, 0.35, n)
        a = np.sin(2 * np.pi * 68 * t) * np.exp(-9 * t) + \
            0.4 * np.sin(2 * np.pi * 132 * t) * np.exp(-14 * t)
        a *= 0.8
    elif kind == "riser":
        n = int(0.9 * sr)
        t = np.linspace(0, 0.9, n)
        a = np.sin(2 * np.pi * (180 + 420 * t / 0.9) * t) * (t / 0.9) ** 2
        a *= 0.28
    else:
        raise SystemExit("unknown sfx")
    a = np.clip(a, -1, 1)
    with wave.open(str(dest), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((a * 32767).astype(np.int16).tobytes())


def music_bed(dest: Path, seconds: float):
    """Slow, quiet pad. Two detuned sines + filtered noise, nothing that
    competes with a speaking voice."""
    sr = 22050
    n = int((seconds + 2) * sr)
    t = np.linspace(0, n / sr, n)
    a = (np.sin(2 * np.pi * 110 * t) * 0.5 + np.sin(2 * np.pi * 164.81 * t) * 0.3 +
         np.sin(2 * np.pi * 220.6 * t) * 0.12)
    lfo = 0.55 + 0.45 * np.sin(2 * np.pi * 0.08 * t)
    a = a * lfo
    noise = np.random.default_rng(3).normal(0, 1, n) * 0.05
    a = np.convolve(a + noise, np.ones(400) / 400, mode="same")
    a = a / (np.abs(a).max() + 1e-9) * 0.6
    with wave.open(str(dest), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((a * 32767).astype(np.int16).tobytes())


# ---------------------------------------------------------------- vision
def still(t: float, w: int = 800):
    h = w * 9 // 16 // 2 * 2
    raw = subprocess.run([FF, "-v", "error", "-ss", f"{max(0, t):.2f}", "-i", str(SRC),
                          "-frames:v", "1", "-vf", f"scale={w}:{h}", "-pix_fmt", "gray",
                          "-f", "rawvideo", "-"], capture_output=True).stdout
    if len(raw) < w * h:
        return None
    return np.frombuffer(raw[:w * h], np.uint8).reshape(h, w), 3840 / w


_CAS = None


def cascades():
    global _CAS
    if _CAS is None:
        d = Path(cv2.data.haarcascades)
        _CAS = [cv2.CascadeClassifier(str(d / "haarcascade_frontalface_default.xml")),
                cv2.CascadeClassifier(str(d / "haarcascade_frontalface_alt2.xml"))]
        _CAS = [c for c in _CAS if not c.empty()]
    return _CAS


def faces_at(t: float):
    st = still(t)
    if st is None:
        return []
    g, k = st
    g = cv2.equalizeHist(g)
    out = []
    for det in cascades():
        for (x, y, fw, fh) in det.detectMultiScale(g, 1.08, 5, minSize=(30, 30)):
            out.append((x * k, y * k, fw * k))
    keep = []
    for f in sorted(out, key=lambda z: -z[2]):
        if all(abs(f[0] - c[0]) > f[2] * 0.6 or abs(f[1] - c[1]) > f[2] * 0.6 for c in keep):
            keep.append(f)
    return keep[:2]


def crop_for(t0: float, t1: float, punch: bool = False):
    """Framing on the guest (left face in a 2-shot, biggest face in a close-up).
    Crop height is capped so the source's burned-in logo strip never enters."""
    tm = (t0 + t1) / 2
    faces = []
    for tt in (tm - 0.8, tm, min(t1, tm + 0.8)):
        for (x, y, fw) in faces_at(max(t0, tt)):
            if y < 1150 and fw >= 140:
                faces.append((x, y, fw))
    if not faces:
        return (3840 - CW) // 2, 0, CW, CH
    # the guest (Alex) sits on the left of this studio, so in a 2-shot or a wide
    # we take the left face; a clean solo close-up is taken as-is
    solo = [f for f in faces if f[2] > 420]
    left = [f for f in solo if f[0] + f[2] / 2 < 1700]
    pick = left or solo
    if pick:
        cx, cy, fw = max(pick, key=lambda f: f[2])
    else:
        cx, cy, fw = min(faces, key=lambda f: f[0] + f[2] / 2)
    cw = CW if not punch else int(CW * 0.94)
    ch = int(cw * 16 / 9)
    cw -= cw % 2; ch -= ch % 2
    x = int(max(0, min(3840 - cw, cx + fw / 2 - cw / 2)))
    y = int(max(0, min(2160 - ch, cy - 0.42 * ch)))
    return x, y, cw, ch


def face_cover(path: Path) -> float:
    w, h = 216, 384
    raw = subprocess.run([FF, "-v", "error", "-i", str(path), "-an", "-vf",
                          f"fps=6,scale={w}:{h},format=gray", "-f", "rawvideo",
                          "-pix_fmt", "gray", "-"], capture_output=True).stdout
    n = len(raw) // (w * h)
    if not n:
        return 0.0
    good = 0
    for i in range(n):
        g = cv2.equalizeHist(np.frombuffer(raw[i * w * h:(i + 1) * w * h], np.uint8).reshape(h, w))
        hit = any(len(d.detectMultiScale(g, 1.08, 4, minSize=(18, 18))) for d in cascades())
        good += hit
    return good / n


# ---------------------------------------------------------------- plan
def shots_for(t0: float, t1: float, words):
    """2.5-3.5 s beats, merged while the framing holds, max 4 shots per clip."""
    beats, cur = [], t0
    while cur < t1 - 0.3:
        nxt = min(cur + 3.2, t1)
        beats.append((cur, nxt))
        cur = nxt
    plan, prev = [], None
    for (a, b) in beats:
        box = crop_for(a, b, punch=bool(plan) and len(plan) % 2 == 1)
        if prev and abs(box[0] - prev[0]) < 200:
            plan[-1] = (plan[-1][0], b, plan[-1][2], plan[-1][3])
        else:
            plan.append((a, b, box, False))
        prev = box
    while len(plan) > 4:                       # merge the shortest neighbours
        i = min(range(len(plan) - 1), key=lambda j: plan[j][1] - plan[j][0])
        plan[i] = (plan[i][0], plan[i + 1][1], plan[i][2], plan[i][3])
        del plan[i + 1]
    return plan


def build_ass(path: Path, words, t0: float, t1: float, hook: str):
    cfg = CAMP["captions"]
    ev = [f"Dialogue: 1,{clk(0)},{clk(min(CAMP['hook_card']['seconds'], t1 - t0))},"
          f"Hook,{hook}"]
    grp = []

    def emit(g):
        if not g:
            return
        parts = []
        for w in g:
            if cfg.get("highlight") and KEY.search(w["w"]):
                parts.append("{\\c&H00E5FF&\\fscx108\\fscy108\\t(0,90,\\fscx100\\fscy100)}"
                             + w["w"] + "{\\r}")
            else:
                parts.append(w["w"])
        ev.append(f"Dialogue: 0,{clk(g[0]['t'] - t0)},{clk(g[-1]['e'] - t0 + 0.12)},"
                  f"Cap,{' '.join(parts)}")

    for w in words:
        if not (t0 - 0.05 <= w["t"] < t1):
            continue
        grp.append(w)
        if len(grp) >= cfg["max_words"] or w["w"].endswith((".", "?", "!")):
            emit(grp); grp = []
    emit(grp)
    path.write_text(f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,DejaVu Sans,{CAMP['hook_card']['fontsize']},&H00FFFFFF,&H00101010,&H7F000000,1,8,70,70,{CAMP['hook_card']['margin_v']},3
Style: Cap,DejaVu Sans,{cfg['fontsize']},&H00FFFFFF,&H00101010,&H00000000,1,2,70,70,{cfg['margin_v']},1
[Events]
Format: Layer, Start, End, Style, Text
""" + "\n".join(ev) + "\n", encoding="utf8")


def ensure_source():
    """Each clip job runs on its own machine, so it fetches the footage itself
    (fresh signed link, so a run can never be blocked by an expired one)."""
    if SRC.exists():
        return
    src_cfg = CAMP["source"]
    if src_cfg.get("src_url"):
        url = src_cfg["src_url"]
    else:
        import urllib.request
        body = json.dumps({"security_hash": src_cfg["security_hash"],
                           "intent": "entire_transfer"}).encode()
        req = urllib.request.Request(
            f"https://wetransfer.com/api/v4/transfers/{src_cfg['transfer_id']}/download",
            data=body, headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            url = json.load(r)["direct_link"]
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=900) as r, SRC.open("wb") as f:
        while chunk := r.read(1 << 22):
            f.write(chunk)
    print("source fetched:", SRC.stat().st_size, flush=True)


def clk(t: float) -> str:
    t = max(0.0, t)
    return f"0:{int(t)//60:02d}:{t%60:05.2f}"


def auto_hook(text: str) -> str:
    """Hook = the clip's own opening words (never invented), upper-cased,
    trimmed to one legible line."""
    words = re.sub(r"[^\w\$%\s'.,]", "", text).split()
    out = []
    for w in words[:7]:
        out.append(w)
        if len(" ".join(out)) > 26 and len(out) >= 3:
            break
    hook = " ".join(out).strip(" ,.").upper()
    return hook + ("" if hook.endswith(("!", "?")) else ".")


# ---------------------------------------------------------------- render
def main() -> int:
    clip = next(c for c in json.loads(clips_path.read_text()) if c["id"] == clip_id)
    words_all = json.loads(words_path.read_text())
    t0, t1 = clip["t0"], clip["t1"]
    dur = round(t1 - t0, 3)
    hooks = {}
    hp = ROOT / "campaigns" / camp / "hooks.json"
    if hp.exists():
        hooks = json.loads(hp.read_text())
    hook = clip.get("hook") or hooks.get(clip_id) or auto_hook(clip["text"])
    words = [w for w in words_all if t0 - 0.2 <= w["t"] < t1 + 0.3]

    ensure_source()

    plan = shots_for(t0, t1, words)
    parts = []
    for k, (a, b, box, _) in enumerate(plan):
        x, y, cw, ch = box
        f = WORK / f"{clip_id}_s{k}.mp4"
        subprocess.run([FF, "-nostdin", "-v", "error", "-y", "-ss", f"{a:.3f}",
                        "-t", f"{b - a:.3f}", "-i", str(SRC),
                        "-vf", f"crop={cw}:{ch}:{x}:{y},scale={W}:{H}:flags=lanczos,"
                               f"setsar=1,fps={FPS}", "-an",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                        "-pix_fmt", "yuv420p", str(f)], check=True)
        cov = face_cover(f)
        if cov < FR["face_cover_min"] and k > 0:      # hold the previous framing
            px, py, pcw, pch = plan[k - 1][2]
            subprocess.run([FF, "-nostdin", "-v", "error", "-y", "-ss", f"{a:.3f}",
                            "-t", f"{b - a:.3f}", "-i", str(SRC),
                            "-vf", f"crop={pcw}:{pch}:{px}:{py},scale={W}:{H}:flags=lanczos,"
                                   f"setsar=1,fps={FPS}", "-an",
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                            "-pix_fmt", "yuv420p", str(f)], check=True)
        parts.append(f)

    lst = WORK / f"{clip_id}_list.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts))
    joined = WORK / f"{clip_id}_joined.mp4"
    subprocess.run([FF, "-nostdin", "-v", "error", "-y", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-c", "copy", str(joined)], check=True)

    # ---- sound
    whoosh, thump, riser = WORK / "whoosh.wav", WORK / "thump.wav", WORK / "riser.wav"
    sfx(whoosh, "whoosh"); sfx(thump, "thump"); sfx(riser, "riser")
    bed = WORK / f"{clip_id}_bed.wav"
    music_bed(bed, dur)

    cut_times, acc = [], 0.0
    for (a, b, *_rest) in plan[:-1]:
        acc += b - a
        cut_times.append(acc)
    first_num = next((w["t"] - t0 for w in words if KEY.search(w["w"])
                      and not w["w"].lower() in ("over", "close")), None)

    ass = WORK / f"{clip_id}.ass"
    build_ass(ass, words, t0, t1, hook)
    wm = ROOT / CAMP["watermark"]["file"]
    if not wm.exists():
        raise SystemExit(f"watermark asset missing: {wm} (campaign contract requires it)")

    fc = ["[1:a]loudnorm=I=%s:TP=%s:LRA=11[main]" % (CAMP["audio"]["lufs"], CAMP["audio"]["tp"]),
          f"[2:a]volume={CAMP['audio']['music_gain_db']}dB,atrim=0:{dur},asetpts=N/SR/TB[bed]"]
    mix = ["[main]", "[bed]"]
    idx = 3
    for i, ct in enumerate(cut_times):
        fc.append(f"[{idx}:a]adelay={int(ct*1000)}|{int(ct*1000)},volume={CAMP['audio']['whoosh_gain_db']}dB[w{i}]")
        mix.append(f"[w{i}]"); idx += 1
    if first_num:
        fc.append(f"[{idx}:a]adelay={int(first_num*1000)}|{int(first_num*1000)},volume={CAMP['audio']['thump_gain_db']}dB[th]")
        mix.append("[th]"); idx += 1
    fc.append(f"[{idx}:a]volume=-18dB,atrim=0:0.9[rs]")
    mix.append("[rs]")
    fc.append(f"{''.join(mix)}amix=inputs={len(mix)}:duration=first:normalize=0[aout]")

    # watermark is the last video input, so compute its index properly
    wm_idx = 3 + len(cut_times) + (1 if first_num else 0) + 1
    inputs = ["-i", str(joined), "-ss", f"{t0:.3f}", "-t", f"{dur:.3f}", "-i", str(SRC),
              "-i", str(bed)]
    for _ in cut_times:
        inputs += ["-i", str(whoosh)]
    if first_num:
        inputs += ["-i", str(thump)]
    inputs += ["-i", str(riser), "-i", str(wm)]
    out = OUT / f"{clip_id}.mp4"
    vf = (f"[{wm_idx}:v]scale={CAMP['watermark']['width']}:-1[wm];"
          f"[0:v][wm]overlay=(W-w)/2:H-{CAMP['watermark']['margin_bottom']}:format=auto[v0];"
          f"[v0]ass={ass},eq=contrast=1.05:saturation=1.06,setsar=1[v]")
    cmd = [FF, "-nostdin", "-v", "error", "-y", *inputs,
           "-filter_complex", ";".join([vf, *fc]),
           "-map", "[v]", "-map", "[aout]", "-t", f"{dur:.3f}",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-pix_fmt", "yuv420p", "-r", str(FPS),
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True)

    cov = face_cover(out)
    meta = {"id": clip_id, "len": round(dur, 2), "t0": t0, "t1": t1, "hook": hook,
            "shots": len(parts), "face_cover": round(cov, 3),
            "cuts": [round(c, 2) for c in cut_times], "lens": clip.get("lens"),
            "score": clip.get("score"), "text": clip.get("text")}
    (OUT / f"{clip_id}.json").write_text(json.dumps(meta, indent=1))
    for p in parts + [joined, lst]:
        p.unlink(missing_ok=True)
    print(json.dumps(meta, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
