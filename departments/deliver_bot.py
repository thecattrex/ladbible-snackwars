#!/usr/bin/env python3
"""DELIVERY DEPARTMENT.

Takes every clip that reached the end of the company, writes the posting sheet
(caption / title / handles / hashtags per clip) and a single summary the boss
reads back. No clip leaves without a row here.

  python3 departments/deliver_bot.py <campaign> <clips_dir> <qc_dir>
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
camp, clips_dir, qc_dir = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
CAMP = json.loads((ROOT / "campaigns" / camp / "campaign.json").read_text())
TAGS = {
    "higgsfield": ["#Higgsfield", "#AI", "#AIvideo", "#Startups", "#20VC"],
}
HANDLES = CAMP["platforms"]


def clean(t: str) -> str:
    t = re.sub(r"\s*-\s*", "-", t)
    t = re.sub(r"\s+([,\.\?!])", r"\1", t)
    t = re.sub(r"\s{2,}", " ", t)
    return t.strip()


def main() -> int:
    rows, summary = [], {"clips": [], "failed": []}
    for mp4 in sorted(clips_dir.glob("*.mp4")):
        cid = mp4.stem
        meta = {}
        m = clips_dir / f"{cid}.json"
        if m.exists():
            meta = json.loads(m.read_text())
        qc = qc_dir / f"qc_{cid}.json"
        verdict = json.loads(qc.read_text())["verdict"] if qc.exists() else "MISSING"
        text = clean(meta.get("text", ""))
        hook = meta.get("hook", "")
        caption = text[:280] if text else hook
        rows.append({
            "clip": cid,
            "file": mp4.name,
            "length_s": meta.get("len", ""),
            "hook_on_screen": hook,
            "caption": caption,
            "title": hook.title() if hook else "",
            "instagram": HANDLES["instagram"],
            "youtube": HANDLES["youtube"],
            "hashtags": " ".join(TAGS.get(camp, [])),
            "qc": verdict,
            "face_cover": meta.get("face_cover", ""),
        })
        summary["clips"].append({"id": cid, "len": meta.get("len"), "qc": verdict})
        if verdict != "PASS":
            summary["failed"].append(cid)

    with (clips_dir / "posting_sheet.csv").open("w", newline="", encoding="utf8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["clip"])
        w.writeheader()
        w.writerows(rows)
    (clips_dir / "delivery_summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))
    print(f"{len(rows)} clips delivered, {len(summary['failed'])} failed QC")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
