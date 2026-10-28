# Architecture — built to `docs/MASTER_PROMPT.md`

The master prompt is the system of record. This file maps it to code, and is
honest about what is built, what is partial, and what is not built.

## Mapping

| Prompt | Code | Status |
|---|---|---|
| A. Mode + inputs | `campaigns/<id>/campaign.json`, `orchestrator/store.validate_brief` | ✅ built — `target_clips` and `clip_length` are **required from the user**, never defaulted |
| B. Capability check | `docs/CAPABILITIES.md` | ✅ written (honest per-operation table) |
| C. Nine departments + superbot + boss | `departments/d1..d9`, `orchestrator/boss.py` | ✅ department split built; superbot = the per-department merge/job, boss = portfolio gate |
| D. Shared state, job contracts, review schema | `orchestrator/store.py`, `schemas/*.json` | ✅ built |
| E. Two source routes | `departments/d1_source.py` | ✅ LOCAL_FILE, DIRECT_URL, WETRANSFER, YOUTUBE_URL |
| F. Transcription, chunk ownership, boundary repair | `departments/d2_transcribe.py` | ✅ shards + 10 s overlap + merge report. Diarization **UNAVAILABLE** and labelled so |
| G. Whole-video map, coverage map | `departments/d3_index.py` | ✅ scene cuts, face sampling, transcript windows, coverage statuses |
| H. Moment discovery, Moment Cards, 100-pt rubric | `departments/d4_moments.py` | ✅ 10 lenses, evidence fields, rubric, hard-reject field, portfolio by distinct takeaway |
| I. Hooks, Hook Cards, rubric | `departments/d5_hooks.py` | ✅ native-quote discovery, editorial headline, 6 drafts → 3 → 1 + alternate, hook rubric. Patterns are rule-based, not an LLM |
| J. Editing passes, EDL | `departments/d6_edit.py` | ✅ picture lock + EDL events (purpose per event). J/L cuts and B-roll **not used** (campaign restricts to source) |
| K. Dialogue-first audio, ducking, cue sheet | `departments/d7_audio.py` | ✅ loudnorm, ducked bed, cue sheet with purpose + provenance |
| L. Captions, hierarchy, colour | `departments/d8_captions.py` | ✅ retimed to output clock, 2–3 word groups, keyword highlight, grade, watermark, composite |
| M. Independent QA | `departments/d9_qa.py` | ✅ technical + source-fidelity + content checks; unperformed checks are `NOT_RUN`, never PASS |
| N. Review loop, ≤2 revisions | `orchestrator/store.review`, `queue.MAX_ATTEMPTS` | ✅ findings logged with acceptance tests; retries target the failing department |
| O/P. Research, analytics | — | ⛔ not built (needs publishing authorization) |
| R. Deliverables | `orchestrator/deliver.py` | ✅ manifest, posting sheet, provenance, unexecuted list |
| S. Gates | `orchestrator/store.gate`, `boss.py` | ✅ SOURCE_VALID → DELIVERED |
| T. Pilot | `workflows/campaign.yml` matrix | ✅ pilot by setting `target_clips` low first |

## What is deliberately *not* claimed

- **No virality prediction.** Nothing here estimates views or revenue.
- **No full visual review.** Frames are sampled in D3 and D6; motion is not reviewed.
- **No diarization.** Speaker labels are marked unavailable rather than guessed.
- **No LLM editorial agent inside CI.** D5's drafting is rule-based; the editor
  (me) can override the winner via `campaigns/<id>/hook_overrides.json`, and the
  rubric still runs, so an override that breaks source fidelity fails review.
- **No real concurrent "40 agents".** Logical slots are declared, real
  concurrency is in `orchestrator/queue.POOLS` and the CI matrix.

## Run order

```
D1 → D2 (×N shards) → D2 merge → D3 → D4 (--select) → D5
   → per clip: D6 → D7 → D8 → D9
   → deliver → boss
```

Mode gate: `DESIGN_ONLY` validates the brief and starts no media job.
