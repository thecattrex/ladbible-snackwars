#!/usr/bin/env python3
"""Boss — the portfolio gate.

The Boss does not re-do departmental work. It checks the campaign as a whole:
is every requested clip qualified, is anything a duplicate of anything else, are
the gates actually green, is the budget honest, and what is still unexecuted.

  python3 orchestrator/boss.py <campaign_id> [--mode DESIGN_ONLY|BUILD_WORKFLOW|RUN_CAMPAIGN]
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from orchestrator import store  # noqa: E402

GATES = ["SOURCE_VALID", "MOMENT_VALID", "HOOK_VALID", "STORY_LOCKED",
         "TIMELINE_LOCKED", "RENDER_COMPLETE", "QA_APPROVED", "DELIVERED"]


def dup_check(portfolio: list) -> list:
    """Two clips can use different sentences and still say the same thing, so
    takeaways are compared as well as timestamps."""
    problems = []
    for i, a in enumerate(portfolio):
        for b in portfolio[i + 1:]:
            ov = max(0.0, min(a["t1"], b["t1"]) - max(a["t0"], b["t0"]))
            if ov > 0.5 * min(a["t1"] - a["t0"], b["t1"] - b["t0"]):
                problems.append({"pair": [a["id"], b["id"]], "reason": "time overlap", "detail": round(ov, 2)})
            elif a.get("takeaway") and a.get("takeaway") == b.get("takeaway"):
                problems.append({"pair": [a["id"], b["id"]], "reason": "same takeaway"})
    return problems


def main() -> int:
    cid = sys.argv[1]
    brief = store.validate_brief(cid)
    mode = brief["mode"]
    report = {"campaign_id": cid, "mode": mode, "requested_clips": brief["target_clips"],
              "clip_length": brief["clip_length"], "structure": brief["structure"]}

    manifest = store.read_json(cid, "manifest.json", {}) or {}
    clips = manifest.get("clips", [])
    gates = store.read_json(cid, "gates.json", {}) or {}

    report["qualified_clips"] = sum(1 for c in clips if c.get("qc") == "PASS")
    report["rendered"] = sum(1 for c in clips if c.get("rendered_file"))
    report["duplicates"] = dup_check([c for c in clips if c.get("qc") == "PASS"])
    report["missing_gates"] = {c["id"]: [g for g in GATES if not gates.get(c["id"], {}).get(g, {}).get("passed")]
                               for c in clips}
    report["costs"] = store.costs(cid)
    report["unexecuted"] = [k for k, v in (manifest.get("unexecuted") or {}).items() if v]

    ok = (report["qualified_clips"] >= brief["target_clips"]
          and not report["duplicates"]
          and all(not v for v in report["missing_gates"].values()))
    report["verdict"] = "APPROVED" if ok and mode == "RUN_CAMPAIGN" else (
        "PLAN_ONLY" if mode != "RUN_CAMPAIGN" else "REVISE")
    if mode == "RUN_CAMPAIGN" and report["qualified_clips"] < brief["target_clips"]:
        report["shortfall"] = f"{brief['target_clips'] - report['qualified_clips']} clips short — reasons per candidate are in the candidate register"
    store.write_json(cid, "boss_report.json", report)
    print(json.dumps(report, indent=1))
    return 0 if report["verdict"] in ("APPROVED", "PLAN_ONLY") else 1


if __name__ == "__main__":
    raise SystemExit(main())
