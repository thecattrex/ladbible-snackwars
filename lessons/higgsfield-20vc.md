# Lessons — higgsfield-20vc (Alex Mashrabov, 20VC)

Written before purge. Kept because these rules carry to the next campaign; the
footage, transcript, moments and renders are deleted.

## What worked
- Demo-first gate: two approved demos (c557 30 s, c1407 47 s) defined the craft
  before a 20-clip run; they are the reference for sync, camera, graphics, grade.
- One crop per camera shot, speaker-centred, with a moving window on wide
  two-shots — the client's "camera moves, it is not cut-cut" note.
- Numbers parsed across tokens ("$30" + ",000", "4" + "million", "30K") so the
  strongest figure in a clip is never silently dropped.
- Graphics chosen from the clip's own words: one card per distinct figure, kicker
  from the spoken unit (PER WEEK) or topic (THE SPEND); a question card only for a
  real question. Twenty clips with the same template card is the machine look that
  was rejected in v5/v6.
- Rendering each clip as an independent CI job: 20 clips in ~3 minutes wall clock
  instead of ~2 hours serial, and an environment reset cannot lose the batch.
- Media per clip: only the seconds a clip needs, `SRC_OFFSET` keeps every seek in
  absolute episode time so the EDL, face track and audio never drift.

## What failed (and the exact defect)
- Free-proxy 4K download of the whole master: dropped every few hundred MB; the
  sandbox also resets and wipes /var/tmp (three times in one session).
- Framing track is a summary, not the truth: a 9:16 box can land between two
  people on a wide shot. Fix: verify the *cropped* picture with a face detector
  (4 probes per piece), hold the last good box for sub-0.8 s gaps, and cut the
  span out of the plan (timeline `avoid`) when a second or more has nobody.
- Hook numbers were compared as digit strings, so "1M" failed against "1 million"
  and "3 months" was read as 3 million. Fix: compare values, read number words.
- D9 prints pretty JSON; a driver that reads the last stdout line records
  "UNPARSED" — parse the verdict out of the report.

## Numbers that mattered
- source: 1:15:42 at 2160p (av01, format 401) + opus 251-3; deliver 1080x1920 30 fps
- clip band for this campaign: 30-60 s; 20 clips, 30.0-46.8 s delivered
- loudness -16 LUFS / -1 dBTP; watermark probe >= 0.9; decode errors 0
- face coverage after crop verification: 1.0 on every delivered clip

## Reusable rules to carry forward
- Never ship a second where the cropped frame has no person: cut it, do not crop
  around it. Measure on decoded crops, not on the face track.
- One idea per card, labels from the spoken context, no repeated figure.
- A hook number must be a number he actually says; compare values, not spellings.
- Batch renders belong in CI (one job per clip), media as release assets.
- Purge on completion; keep the lessons only.
