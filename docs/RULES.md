# Standing rules (do not break)

## R1 — One campaign at a time
While campaign A is open, **only A exists**. Every department works on A's source,
A's brief, A's guidelines, A's assets. No reading briefs, transcripts, renders or
assets from another campaign.

Enforced in code, not by memory: `orchestrator/isolation.py` keeps a single
pointer (`state/ACTIVE_CAMPAIGN`), and `store.validate_brief()` calls
`isolation.require()` — every department goes through it. A job for a different
campaign fails loudly instead of quietly mixing material.

## R2 — Purge only on the user's word
When the user says the campaign is **done and perfect**, everything that campaign
produced is deleted: brief, state, transcripts, renders, clips, stills, logs.

```bash
python3 orchestrator/purge.py <campaign_id> --confirmed-perfect
```

Kept, deliberately:
- `lessons/<campaign_id>.md` — the reusable learning, written **before** deletion,
  and only the parts the user agrees to keep.
- the system itself (departments, orchestrator, schemas, docs, workflow).

Nothing is deleted on a timer or on my own judgment.

## R3 — Per-campaign inputs, never defaults
`target_clips` and `clip_length` come from the campaign every single time. The
system refuses a brief that leaves them empty. Same for source rights.

## R4 — Modes
`DESIGN_ONLY` validates and starts no media job. `BUILD_WORKFLOW` validates the
orchestration with authorized fixtures. `RUN_CAMPAIGN` processes the supplied
campaign only.

## R5 — Approved craft is the default, not a preference
The craft rules agreed with the client live in `docs/CRAFT.md` and in section J9 of
`docs/MASTER_PROMPT.md`. Every department reads them before it renders: frame-locked
cuts, speaker-follow framing with a crop audit, a moving camera, split frame only for
real overlap, full-bleed picture, type-led graphics, captions in one lane, clean dialogue
with no music bed, watermark for the whole clip.

Rejected approaches are not "off by default" — they are deleted from the tree, so a later
bot cannot switch them back on by adding a config key.

## R6 — Numbers or it did not happen
D9 reports measured values (loudness, true peak, decode errors, faces per frame, watermark
probe, picture duration against the timeline). A check that could not be measured is
reported as unperformed, never as passed.
