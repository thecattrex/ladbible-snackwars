#!/usr/bin/env python3
"""Resource pools and retry policy.

Separate pools exist because they fail for different reasons: ASR dies from
memory pressure, renders queue on CPU, downloads on network. One global
"40 workers" number would be a lie about the machine.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

POOLS = {
    "asr": int(os.environ.get("POOL_ASR", 4)),
    "vision": int(os.environ.get("POOL_VISION", 2)),
    "render": int(os.environ.get("POOL_RENDER", 2)),
    "net": int(os.environ.get("POOL_NET", 3)),
    "text": int(os.environ.get("POOL_TEXT", 8)),
}

MAX_ATTEMPTS = 3          # initial + 2 corrective revisions (prompt N)


def plan(clips: int, shards: int) -> dict:
    """What actually runs where. Logical slots are declared, concurrency is real."""
    return {
        "logical_workers": {"D2_asr_shards": shards, "D4_lenses": 5, "D5_hook_drafts": 6,
                            "D6_picture": clips, "D7_audio": clips, "D8_captions": clips,
                            "D9_qa": clips},
        "actual_concurrency": POOLS,
        "retry": {"max_attempts": MAX_ATTEMPTS,
                  "rule": "targeted repair of the affected artifact only; "
                          "dependent artifacts are invalidated, not rebuilt blindly"},
    }


def attempt_dir(campaign_id: str, task: str, attempt: int) -> Path:
    p = ROOT / "state" / campaign_id / "attempts" / task / f"a{attempt}"
    p.mkdir(parents=True, exist_ok=True)
    return p


def can_retry(attempt: int) -> bool:
    return attempt < MAX_ATTEMPTS


def record(campaign_id: str, task: str, attempt: int, status: str, note: str = "") -> None:
    p = ROOT / "state" / campaign_id / "job_log.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "task": task, "attempt": attempt,
                            "status": status, "note": note}) + "\n")
