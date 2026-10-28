#!/usr/bin/env python3
"""Re-run the independent QA on every finished clip and record the verdict.

D9 is the only department allowed to call a clip good, so the batch log is filled
from D9's own report rather than from whether the render happened to exit 0.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CID = "higgsfield-20vc"
log_path = ROOT / f"state/{CID}/batch_log.json"
log = json.loads(log_path.read_text()) if log_path.exists() else {}
port = json.load(open(ROOT / f"state/{CID}/artifacts/portfolio.v1.json"))["payload"]["selected"]

for c in sorted(port, key=lambda x: x["t0"]):
    clip = c["candidate_id"]
    if not (ROOT / f"state/{CID}/clips/{clip}.mp4").exists():
        print(f"{clip}: no render", flush=True)
        continue
    media = Path("/var/tmp/clips") / clip
    env = dict(__import__("os").environ, MEDIA_ROOT=str(media),
               SRC_OFFSET=(media / "offset.txt").read_text().strip()
               if (media / "offset.txt").exists() else "0")
    r = subprocess.run([sys.executable, "departments/d9_qa.py", CID, "--clip", clip],
                       cwd=ROOT, capture_output=True, text=True, env=env)
    try:
        rep = json.loads(r.stdout[r.stdout.index("{"):r.stdout.rindex("}") + 1])
    except Exception:
        m = re.search(r'"verdict"\s*:\s*"(\w+)"', r.stdout)
        rep = {"verdict": m.group(1) if m else "UNPARSED", "checks": {}}
    entry = log.setdefault(clip, {})
    entry["qa"] = rep["verdict"]
    entry["d9"] = {"rc": r.returncode}
    entry["failed_checks"] = [k for k, v in (rep.get("checks") or {}).items() if v is False]
    entry["visual"] = rep.get("visual")
    log_path.write_text(json.dumps(log, indent=1) + "\n")
    print(f"{clip}: {rep['verdict']} {entry['failed_checks']}", flush=True)
print("FINALIZE DONE", flush=True)
