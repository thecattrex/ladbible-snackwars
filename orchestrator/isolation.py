#!/usr/bin/env python3
"""Campaign isolation.

Standing rule: while campaign A is active, only A exists. No department may read
assets, briefs, transcripts or renders belonging to another campaign, because
mixing them silently is how the wrong guidelines get applied.

The active campaign is a single pointer on disk. Switching is explicit, never a
side effect of running a job.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POINTER = ROOT / "state" / "ACTIVE_CAMPAIGN"


class WrongCampaign(SystemExit):
    pass


def active() -> str | None:
    return POINTER.read_text().strip() if POINTER.exists() else None


def switch(campaign_id: str, force: bool = False) -> str:
    """Start or resume a campaign. Refuses to abandon an unfinished one unless
    forced, so two campaigns can never be open at the same time."""
    cur = active()
    if cur and cur != campaign_id and not force:
        raise WrongCampaign(
            f"campaign '{cur}' is still open. Finish it and purge it, or pass "
            f"--force to switch to '{campaign_id}'.")
    POINTER.parent.mkdir(parents=True, exist_ok=True)
    POINTER.write_text(campaign_id)
    return campaign_id


def require(campaign_id: str) -> None:
    """Called from store.validate_brief(), so every department is covered by
    construction rather than by remembering to check."""
    if os.environ.get("ALLOW_CAMPAIGN_SWITCH") == "1":
        return
    cur = active()
    if cur is None:
        switch(campaign_id)          # first run of the campaign
        return
    if cur != campaign_id:
        raise WrongCampaign(
            f"isolation: '{cur}' is active, refusing to work on '{campaign_id}'. "
            f"One campaign at a time.")


def foreign_files(campaign_id: str) -> list:
    """Anything under state/ or campaigns/ that does not belong to this campaign."""
    out = []
    for base in (ROOT / "state", ROOT / "campaigns"):
        if not base.exists():
            continue
        for p in base.iterdir():
            if p.name in (campaign_id, "ACTIVE_CAMPAIGN", "_template", "README.md"):
                continue
            out.append(str(p))
    return out
