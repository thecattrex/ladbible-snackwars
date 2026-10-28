#!/usr/bin/env python3
"""Campaign store — durable state outside any single chat or job.

Everything the company learns about a campaign lives here: the brief, the
source fingerprint, every artifact version, every review finding, the cost
ledger and the rework history. Jobs read and write through this module so no
department depends on a previous job's memory.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_ROOT = Path(os.environ.get("CAMPAIGN_STATE", ROOT / "state"))


def campaign_dir(campaign_id: str) -> Path:
    return STATE_ROOT / campaign_id


def brief(campaign_id: str) -> dict:
    p = ROOT / "campaigns" / campaign_id / "campaign.json"
    if not p.exists():
        raise SystemExit(f"no campaign brief at {p}")
    return json.loads(p.read_text())


def validate_brief(campaign_id: str) -> dict:
    """The brief must name the clip count and the length band itself. The system
    never invents either: they change per campaign.

    Also enforces campaign isolation: only one campaign can be open at a time.
    """
    from orchestrator import isolation
    isolation.require(campaign_id)
    b = brief(campaign_id)
    missing = [k for k in ("campaign_id", "mode", "source", "target_clips",
                           "clip_length", "structure", "target_format") if k not in b]
    if missing:
        raise SystemExit(f"brief missing required fields: {missing}")
    if b["campaign_id"] != campaign_id:
        raise SystemExit("campaign_id mismatch between folder and brief")
    lo, hi = b["clip_length"]["min"], b["clip_length"]["max"]
    if not (0 < lo < hi):
        raise SystemExit("clip_length band invalid")
    if b["source"]["rights"] not in ("OWNED", "LICENSED", "OTHER_AUTHORIZED_BASIS"):
        raise SystemExit("source rights must be stated before any media work")
    return b


def path(campaign_id: str, *parts: str) -> Path:
    p = campaign_dir(campaign_id).joinpath(*parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def write_json(campaign_id: str, name: str, obj) -> Path:
    p = path(campaign_id, name)
    p.write_text(json.dumps(obj, indent=1))
    return p


def read_json(campaign_id: str, name: str, default=None):
    p = campaign_dir(campaign_id) / name
    return json.loads(p.read_text()) if p.exists() else default


def fingerprint(file_path: Path) -> dict:
    h = hashlib.sha256()
    size = 0
    with file_path.open("rb") as f:
        while chunk := f.read(1 << 22):
            h.update(chunk)
            size += len(chunk)
    st = file_path.stat()
    return {"sha256": h.hexdigest(), "bytes": size, "mtime": int(st.st_mtime)}


def artifact(campaign_id: str, artifact_id: str, payload: dict, version: str = "v1") -> dict:
    """Versioned artifact. A later version never overwrites an earlier one."""
    rec = {"artifact_id": artifact_id, "version": version,
           "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "payload": payload}
    write_json(campaign_id, f"artifacts/{artifact_id}.{version}.json", rec)
    return rec


def review(campaign_id: str, finding: dict) -> Path:
    log = path(campaign_id, "reviews.jsonl")
    with log.open("a") as f:
        f.write(json.dumps(finding) + "\n")
    return log


def reviews(campaign_id: str) -> list:
    p = campaign_dir(campaign_id) / "reviews.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def revision_count(campaign_id: str, artifact_id: str) -> int:
    return sum(1 for r in reviews(campaign_id)
               if r.get("artifact_id") == artifact_id and r.get("verdict") == "REVISE")


def cost(campaign_id: str, item: dict) -> None:
    log = path(campaign_id, "cost_ledger.jsonl")
    item = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **item}
    with log.open("a") as f:
        f.write(json.dumps(item) + "\n")


def costs(campaign_id: str) -> list:
    p = campaign_dir(campaign_id) / "cost_ledger.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def job_id(campaign_id: str, department: str, key: str, attempt: int = 1) -> str:
    """Idempotent: the same work asked twice maps to the same id, so a retry can
    never create a duplicate render or a duplicate charge."""
    return f"{campaign_id}:{department}:{key}:a{attempt}"


def gate(campaign_id: str, clip_id: str, name: str, passed: bool, note: str = "") -> dict:
    """Named acceptance gate from the playbook (SOURCE_VALID ... DELIVERED)."""
    g = read_json(campaign_id, "gates.json", {})
    g.setdefault(clip_id, {})[name] = {"passed": bool(passed), "note": note,
                                       "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    write_json(campaign_id, "gates.json", g)
    return g[clip_id][name]
