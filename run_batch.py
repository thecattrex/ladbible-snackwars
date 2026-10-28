#!/usr/bin/env python3
"""Render the selected portfolio: D6 -> D7 -> D8 -> D9, clip by clip.

Each clip is independent. A failure is recorded in state/<cid>/batch_log.json and
the batch moves to the next clip, so one bad moment never costs the campaign.
Media for a clip is its own cut of the master under /var/tmp/clips/<clip>/ and
SRC_OFFSET tells the departments which source second that cut starts at.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CID = sys.argv[1]
ONLY = sys.argv[2:] or None
port = json.load(open(ROOT / f"state/{CID}/artifacts/portfolio.v1.json"))["payload"]["selected"]
order = [c["candidate_id"] for c in sorted(port, key=lambda x: x["t0"])]
if ONLY:
    order = [c for c in order if c in ONLY]
def _verdict(out: str) -> str:
    """D9 prints its report as pretty JSON; read the verdict, not the last line."""
    try:
        return json.loads(out[out.index("{"):out.rindex("}") + 1]).get("verdict", "?")
    except Exception:
        import re
        m = re.search(r'"verdict"\s*:\s*"(\w+)"', out)
        return m.group(1) if m else "UNPARSED"


log_path = ROOT / f"state/{CID}/batch_log.json"
log = json.loads(log_path.read_text()) if log_path.exists() else {}

for clip in order:
    if log.get(clip, {}).get("qa") == "PASS":
        print(f"[skip] {clip} already PASS", flush=True)
        continue
    media = Path("/var/tmp/clips") / clip
    if not (media / "src.mp4").exists():
        print(f"[{clip}] no media yet — skipping", flush=True)
        continue
    offset = (media / "offset.txt").read_text().strip()
    env = dict(os.environ, MEDIA_ROOT=str(media), SRC_OFFSET=offset)
    entry = {"started": time.strftime("%H:%M:%S"), "offset": offset}
    for dept, script in (("d6", "departments/d6_edit.py"), ("d7", "departments/d7_audio.py"),
                         ("d8", "departments/d8_captions.py"), ("d9", "departments/d9_qa.py")):
        t0 = time.time()
        r = subprocess.run([sys.executable, script, CID, "--clip", clip],
                           cwd=ROOT, capture_output=True, text=True, env=env)
        entry[dept] = {"rc": r.returncode, "secs": round(time.time() - t0)}
        if r.returncode != 0:
            entry[dept]["tail"] = (r.stderr or r.stdout)[-900:]
            entry["qa"] = "ERROR"
            print(f"[{clip}] {dept} failed: {(r.stderr or r.stdout)[-300:]}", flush=True)
            break
        if dept == "d9":
            entry["qa"] = _verdict(r.stdout)
    log[clip] = entry
    log_path.write_text(json.dumps(log, indent=1) + "\n")
    print(f"[{clip}] {entry.get('qa')}  " + " ".join(
        f"{k}:{v.get('secs')}s" for k, v in entry.items() if isinstance(v, dict)), flush=True)
print("BATCH DONE", flush=True)
