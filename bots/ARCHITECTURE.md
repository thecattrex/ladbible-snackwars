# Multi-bot system — clip mining + editing + QC (saved spec)

Two halves: **finding** the moments (ClipHarvest) and **building** them (edit
bots), then a QC chain that can reject a clip. Nothing is allowed to ship
without passing every gate below.

---

## 1. CLIP BOTS (ClipHarvest) — "kaunsa moment clip banega"

| bot | count | job | passes when |
|---|---|---|---|
| `ingest` | 1 | video / YouTube link / channel → local 1080p + audio | duration + fps readable |
| `slice` | 1 | cut the timeline into **~90 s units**, whole units only (never mid-sentence) | unit has ≥1 full spoken run |
| `transcribe` | 1 | word-level timings, cached to `assets/words_all.json` | ≥100 words |
| `judge_*` | **40** | each judge scores every unit on one axis: hook strength, emotion, reaction shot, quotability, replay value, "hook line inside the unit?", "is anyone on camera?", pacing, laugh/gaffe, story completeness | score 0–1 per unit per judge |
| `heatmap` | 1 (YouTube only) | most-replayed peaks → weight the judges | peaks mapped to units |
| `superbot` | 1 | sums judges + heatmap, **approve / reject**, enforces **spread** (no 10 clips from one scene; clips across the whole video) | one ordered list, no duplicate hook lines |
| `assign` | 1 | approved units → N render jobs (`ep01…ep20`) | each job has start/end/hook |

Spread rule: approved units are bucketed over the whole timeline (start → end)
and picked round-robin, so the 20 clips are never from one corner of the video.

---

## 2. EDIT BOTS — "clip ko kaise banana hai"

| bot | uses | job | hard rule |
|---|---|---|---|
| `hook_bot` | transcript | hook = real words, ≤8 words, spoken **inside** the clip, unique across all clips | no invented line, no undelivered hook |
| `cut_bot` | word timings | 2.5–4 s cuts, jump cuts on silence >0.45 s, hook flash 1.0 s, loop tail 0.6 s | hard cuts only |
| `framing_bot` | face tracker | crop follows **whoever is speaking**; punch-ins (max 2–3); tight/mid/wide rotation | face fully inside frame, never an empty wall |
| `caption_bot` | word timings | 3-word chunks, timed, keyword highlighted, name card | wrong/mis-timed word = reject |
| `sfx_bot` | music bed + whoosh | low music 10 %, **whoosh on every cut**, 70 Hz thump on the hook | original speech untouched |
| `render_bot` | all above | 1080×1920 @30 fps, watermark bottom-left, loudnorm −15 dB, `+faststart` | one clip = one process |

Each render bot is a separate OS process (own memory, own 1-thread encode) →
N clips in parallel instead of one serial job.

---

## 3. QC BOTS — "isse reject karna hai ya nahi"

| bot | checks | fail → |
|---|---|---|
| `review_bot` | 1080×1920, 30 fps, ≥15.0 s, audio not silent, **face in ≥90 % of frames**, **longest stretch with nobody on screen ≤0.7 s** | fixer bot |
| `fixer_bot` | re-renders that clip in **strict mode** (coverage 0.75→0.82, stop-at 0.92→0.96, crop anchors 3→4), then re-reviews | 2 rounds max |
| `gate` | only PASS clips move to `clips_final/` | rejects stay behind, never uploaded |

Face detector is frontal + alt2 + **profile + mirrored profile + ±30° rotated**
head — a real person looking away must not be scored "empty frame".

---

## 4. Reference pair (measured, not opinion)

Same episode (ep14), only the editing changed:

| file | verdict | face in frames | longest "nobody" gap |
|---|---|---|---|
| `references/GALAT_bad_example.mp4` (v2) | REJECT | 61 % | 2.7 s |
| `references/SAHI_good_example.mp4` (v3) | PASS | 99.4 % | 0.1 s |
| `references/COMPARE_bad_vs_good.mp4` | side by side | — | — |

Other rejected v2 takes: ep09 57 % / 1.8 s, ep01 81 % / 1.2 s.

**Acceptance bar for every future clip:** face ≥90 %, nobody-gap ≤0.7 s,
≥15 s, 1080×1920, audio present, watermark intact, unique real hook.

---

## 5. Run it

```bash
python3 bots/orchestrator.py                  # all 20 clips, 2 at a time
python3 bots/orchestrator.py --eps 3 7 11      # only some
python3 bots/orchestrator.py --render-slots 4  # bigger machine
python3 bots/review_bot.py 7                  # one clip
python3 make_references.py                    # rebuild the reference pair
```

`.github/workflows/render.yml` runs the same bots on GitHub: one 4-core/16 GB
runner per clip → all 20 in parallel, ~6 min.
