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

## R7 - meaningful frame, not "a face in every frame"
The client's rule is that something must be happening in the frame: a person, a screen
playing, a busy room, a reaction. A dead frame (black wall, plain backdrop, the camera
passing the curtain) is the defect. Measured by `orchestrator/content.py` on decoded
pixels; D6 removes dead spans from the plan, D9 fails a clip with more than half a second
of nothing. Tests: `tools/test_content.py`, `tools/test_meaningful_frame.py`,
`tools/test_pipeline_content.py`.

## R8 — Sound at a cut

- **No effect on a cut by default.** Whooshes, risers and swells are banned: the
  user hears them as noise over the stream audio, not as editing.
- The only allowed cut sound is a **dry keyboard click** (~55 ms, high-passed noise
  plus a short 210 Hz body), and only when a plan asks for it (`"sfx": "click"`).
- Everything else stays out: no music beds, no impact hits, no transitions.
- **Gain staging is part of the rule.** Stream audio is loud already: pull it to
  0.80, sum effects (if any) at ≤0.55, then `alimiter=limit=0.89`. A peak over 1.0
  is a defect — demo7 peaked at 1.08 and distorted through the whole clip.
- **Check the source is audible before cutting.** This VOD's audio is muted from
  54:20 to 57:20 (copyright mute); a plan built only from the visuals there
  delivers a silent clip. Measure RMS across the VOD first and keep every shot
  inside a live span.
