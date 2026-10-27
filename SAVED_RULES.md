# Locked rules — every NEW clip is built this way

Saved 2026-10-27. Do not change these without the user saying so.

## Pipeline (one bot per job, one process per clip)
source bot → transcriber bot (word cache) → render bot per clip → reviewer bot
→ fixer bot (strict re-render on fail) → final gate.

## Clip rules
- Hook = real transcript words, <=8 words, spoken INSIDE the clip, unique (never reused).
- Clip opens on the hook line; burned hook card on top + name card in the first second.
- Speaker-follow crop: whoever talks is the one in frame, face fully inside the frame.
- Editing: 2.5-4 s cuts, jump cuts on silence, punch-ins on the punchline (max 2-3),
  listener reaction L-cut 0.7 s, hook flash 1 s, loop tail 0.6 s.
- Hard cuts only: no filters, no colour work, no flashy transitions, no AI/b-roll.
- Captions: 3-word chunks, timed, keyword highlighted. Wrong word = reject.
- Audio: original speech untouched, loudnorm -15 dB, music 10 %, whoosh on every cut,
  70 Hz thump on the hook.
- 1080x1920, 30 fps, >=15 s, watermark bottom-left untouched, +faststart.

## Acceptance gate (reviewer bot, no exceptions)
face in >=90 % of frames - longest "nobody on screen" stretch <=0.7 s -
>=15 s - 1080x1920 - 30 fps - audio not silent - unique real hook.

## Reference pair (measured)
| file | verdict | face | nobody-gap |
|---|---|---|---|
| references/GALAT_bad_example.mp4 (v2) | REJECT | 61 % | 2.7 s |
| references/SAHI_good_example.mp4 (v3) | PASS | 99.4 % | 0.1 s |
| references/COMPARE_bad_vs_good.mp4 | side by side | - | - |

## Speed
Candidate crops are scored on stills first, only the winner gets a real render
(~3x faster than rendering every candidate). 2 workers on this 2-core box,
one GitHub runner per clip for 20-way parallel.
