#!/usr/bin/env python3
"""Campaign purge — run only when the user says the campaign is finished.

Deletes everything the campaign produced: brief, state, transcripts, renders,
clips, stills, logs. Keeps exactly two things:

  1. `lessons/<campaign_id>.md` — what the campaign taught us, written *before*
     anything is deleted, and only with the user's input on what to keep.
  2. the system itself (departments, orchestrator, schemas, docs).

Nothing is deleted without `--confirmed-perfect`, because the user's approval is
the trigger, not a timer.

  python3 orchestrator/purge.py <campaign_id> --confirmed-perfect
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from orchestrator import isolation, store  # noqa: E402

LESSON_TEMPLATE = """# Lessons — {cid}

Written before purge. Only keep what is reusable on the next campaign; delete
anything that was specific to this source's content.

## What worked
-

## What failed (and the exact defect)
-

## Numbers that mattered
- clip length band:
- target clips vs qualified:
- revisions used:

## Reusable rules to carry forward
-
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("campaign_id")
    ap.add_argument("--confirmed-perfect", action="store_true",
                    help="only after the user has reviewed and approved every clip")
    a = ap.parse_args()
    cid = a.campaign_id
    if not a.confirmed_perfect:
        raise SystemExit("refusing to delete: pass --confirmed-perfect after the "
                         "user has approved the campaign")

    lesson = ROOT / "lessons" / f"{cid}.md"
    lesson.parent.mkdir(parents=True, exist_ok=True)
    if not lesson.exists():
        lesson.write_text(LESSON_TEMPLATE.format(cid=cid))
        print(f"created {lesson} — fill it in before deleting, or keep the template")

    removed = []
    for target in (ROOT / "state" / cid, ROOT / "campaigns" / cid):
        if target.exists():
            shutil.rmtree(target)
            removed.append(str(target))

    ptr = ROOT / "state" / "ACTIVE_CAMPAIGN"
    if ptr.exists() and ptr.read_text().strip() == cid:
        ptr.unlink()
        print("campaign pointer cleared — the next campaign can now be opened")

    print("removed:")
    for r in removed:
        print("  ", r)
    print("kept:", lesson)
    print("kept: system (departments/, orchestrator/, schemas/, docs/)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
