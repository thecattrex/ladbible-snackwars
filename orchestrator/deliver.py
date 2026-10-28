#!/usr/bin/env python3
"""Delivery — manifest, posting sheet, provenance, honest gaps.

Only clips that reached QA_APPROVED are listed as delivered. Everything else is
listed with its actual status, because a plan is not a deliverable.

  python3 orchestrator/deliver.py <campaign_id>
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from orchestrator import store  # noqa: E402


def main() -> int:
    cid = sys.argv[1]
    brief = store.validate_brief(cid)
    portfolio = (store.read_json(cid, "artifacts/portfolio.v1.json") or {}).get("payload", {})
    hooks = {h["candidate_id"]: h for h in
             ((store.read_json(cid, "artifacts/hook_cards.v1.json") or {}).get("payload", {}).get("cards", []))}
    gates = store.read_json(cid, "gates.json", {}) or {}
    reviews_log = store.reviews(cid)

    rows, clips, delivered = [], [], 0
    for card in portfolio.get("selected", []):
        clip = card["candidate_id"]
        out = store.path(cid, f"clips/{clip}.mp4")
        g = gates.get(clip, {})
        approved = bool(g.get("QA_APPROVED", {}).get("passed")) and out.exists()
        delivered += approved
        hook = hooks.get(clip, {})
        rows.append({
            "clip": clip, "file": f"{clip}.mp4" if out.exists() else "",
            "length_s": card.get("dur", ""), "lens": card.get("lens", ""),
            "hook": hook.get("winner", ""), "hook_basis": "editorial text over native quote",
            "native_quote": hook.get("native_quote", ""),
            "payoff": hook.get("payoff", ""),
            "score": card.get("score", {}).get("total", ""),
            "confidence": card.get("confidence", ""),
            "source_in": card.get("t0", ""), "source_out": card.get("t1", ""),
            "qa": "PASS" if approved else "NOT_APPROVED",
        })
        clips.append({"id": clip, "t0": card["t0"], "t1": card["t1"],
                      "takeaway": card.get("takeaway", ""),
                      "rendered_file": str(out) if out.exists() else None,
                      "qc": "PASS" if approved else "NOT_APPROVED"})

    out_dir = store.path(cid, "delivery")
    with open(out_dir.with_suffix(".csv"), "w", newline="", encoding="utf8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["clip"])
        w.writeheader(); w.writerows(rows)

    manifest = {
        "campaign_id": cid,
        "mode": brief["mode"],
        "requested_clips": brief["target_clips"],
        "qualified_clips": delivered,
        "clip_length_band": brief["clip_length"],
        "clips": clips,
        "candidate_register": "state/%s/artifacts/candidate_register.v1.json" % cid,
        "costs": store.costs(cid),
        "reviews": len(reviews_log),
        "unexecuted": {
            "motion_review": "no motion pass performed — visual checks are sampled, not frame-by-frame",
            "diarization": "no speaker-embedding model on this box; speaker labels marked UNAVAILABLE",
            "broll": "not used: campaign restricts media to the supplied source",
            "publish": "false — publishing is a separate authorization",
        },
        "provenance": {
            "source": "supplied by the campaign owner; see brief.source",
            "music": "synthesised locally (D7)",
            "sfx": "synthesised locally (D7)",
            "watermark": brief.get("watermark", {}).get("file"),
        },
    }
    store.write_json(cid, "manifest.json", manifest)
    print(json.dumps({k: manifest[k] for k in ("campaign_id", "requested_clips",
                                               "qualified_clips", "unexecuted")}, indent=1))
    if delivered < brief["target_clips"]:
        print(f"SHORTFALL: {brief['target_clips'] - delivered} clips did not reach QA_APPROVED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
