# What the client taught, and how each rule was taken

Locked deliverable: `DEMO_c557_v6.mp4` (30.13 s, QA PASS, gate `QA_APPROVED` in
`state/higgsfield-20vc/gates.json`, approval logged in `reviews.jsonl`).

## Positive — taken 1:1, and it changed the output

| # | Lesson | Where it landed | Measured effect |
|---|--------|-----------------|-----------------|
| 1 | Picture and sound must run at the same speed; a clip that drags behind the voice is dead | cuts snapped to the 24 fps source grid, exact frame count per piece, one 24→30 conversion for the whole timeline (`d6_edit.py`) | picture 30.93 s → 30.13 s; cut positions land on the plan; clip audio matches the mix at 0 ms |
| 2 | The camera **moves** to the next speaker, it is not cut-cut | per-piece `crop` path: ease-out glide when two faces share a wide shot, 14 px drift otherwise (`d6_edit.py`) | 4 glides + 5 drifts across 9 pieces; no still frame |
| 3 | No top/bottom black bands — the clip looks compressed | bands removed from `campaign.json`, full-bleed 1080x1920, captions moved to `margin_v 300` | full-frame picture, title over the picture |
| 4 | Big text about the video, with the explaining word highlighted | captions: 3 words max, keyword in brand lime; cards: marker swipe behind the operative words | readable muted, one marked phrase per card |
| 5 | Remove the annoying background sound | music bed deleted from `d7_audio.py`, denoise + loudnorm only, SFX on 8–9 cues | clean dialogue, −16.03 LUFS |
| 6 | Must look human-made, not AI-made | icons/dotted grids/illustrated money deleted, no count-up numbers, type wipes on in ~140 ms, layout varies per card kind, white small-caps labels | every "template" tell removed; see `docs/CRAFT.md` third pass |
| 7 | Study the reference properly, do not assume cut-by-cut | reference re-scanned at 0.25 s spacing | established that the reference glides inside the wide shot |
| 8 | No voiceover from the client | source audio only, every claim from the transcript | no TTS anywhere in the pipeline |
| 9 | Clip length changes per campaign; clip count is stated by the client | `campaign.json → clip_length{min,max}` validated, `count` user-supplied | this campaign 30–60 s × 20 |
| 10 | One campaign at a time; purge A except lessons | `orchestrator/isolation.py`, `orchestrator/purge.py` | workspace 1.1 GB → 62 MB |
| 11 | Free tier only, no paid APIs, slow laptop | everything local: ffmpeg + PIL + OpenCV, `veryfast` presets | no cloud render, no paid model |
| 12 | Workspace minimal, purge media after delivery | card MOVs, per-piece renders and shards deleted after each pass | repo 1.1 GB → 62 MB |
| 13 | Never claim a check that was not performed | D9 prints real numbers (face track, lime probe, decode pass, EBU loudness) | caught the dead watermark and the empty-desk frame by instrument, not by eye |
| 14 | Truthful hooks, no virality promises, no outside footage | hook numbers traced to the transcript, no engagement claims | QA `hook_numbers_supported`, `payoff_present` true |

## Negative — where the instruction was not taken as given

| # | Instruction | What I did instead, and why |
|---|-------------|------------------------------|
| 1 | "If it looks like an image, take one from the web" | Not done. (a) The client brief forbids outside footage. (b) The "AI" read came from template motion — icon sets, count-ups, one layout — not from missing imagery. Fixed the cause: type-only graphics, no stock images. If specific photos are wanted, say so and I will add them with licence notes. |
| 2 | Sound | The reference short actually carries loud music; the instruction is no background sound. Instruction wins: no bed. Flagged because it departs from the reference. |
| 3 | Cuts | The reference does hard-cut between single / two-shot / three-up. Instruction is "the camera moves". Instruction wins: glide inside a wide shot, a cut only where the source itself changes setup. |
| 4 | "Everything through the master prompt, multi-bot" + "LLM agents only on a free Gemini key you were never given" | The two rules conflict. Taken as: deterministic, measured pipeline (YuNet face track, rubric scoring, ffmpeg graph) instead of LLM-driven agents, so no "AI agent" claim is made. |
| 5 | Virality, reach, "will perform" | Refused by standing rule — no promises in the hook copy or the report. |

## Where the miss was mine, not a taught rule

- **Letterbox bands** were my invention, read into the brief. Client rejected them
  as "compressed" — reversed in `docs/CRAFT.md`.
- **Per-shot one-crop** framing was mine; it produced a slideshow. Fixed by the
  moving-window camera.
- **Off-grid cuts** were mine; they caused the A/V drift the client heard.
- Two bugs the instrumentation caught that no one had reported: the watermark
  dying after 12 s (one-frame still + `overlay` EOF) and 0.3 s of empty desk in
  the middle of the clip (face track disagreeing with a real setup change).
