# Directory map

```
campaigns/            one folder per campaign; the brief lives here
  _template/          copy this for a new campaign
departments/          D1..D9, one file per department (master prompt C)
  d1_source.py        acquire + probe + shard audio
  d2_transcribe.py    shard worker + merge & boundary report
  d3_index.py         whole-video map + coverage map
  d4_moments.py       moment discovery, Moment Cards, portfolio
  d5_hooks.py         hooks, Hook Cards, story beats
  d6_edit.py          picture lock + EDL
  d7_audio.py         dialogue-first mix, cue sheet
  d8_captions.py      captions retimed to output, watermark, grade, composite
  d9_qa.py            independent QA on the real file
orchestrator/         the company itself
  store.py            durable state, artifacts, reviews, costs, gates
  queue.py            resource pools + retry policy
  boss.py             portfolio gate
  deliver.py          manifest, posting sheet, provenance
schemas/              campaign, task, review, moment card, hook card, EDL
docs/                 MASTER_PROMPT.md (spec) + ARCHITECTURE, CAPABILITIES, RUNBOOK
.github/workflows/    campaign.yml — mode gate -> D1..D9 -> deliver -> boss
assets/               campaign assets (watermark)
state/                runtime output, gitignored, produced per run
```
