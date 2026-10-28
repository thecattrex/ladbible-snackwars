# Runbook

## 1. New campaign
```bash
mkdir -p campaigns/my-campaign
cp campaigns/_template/campaign.json campaigns/my-campaign/
```
Fill in — **required, no defaults**: `campaign_id`, `mode`, `source`, `source.rights`,
`target_clips`, `clip_length.min/max`.
Set `mode` to `DESIGN_ONLY` first and run the gate:
```bash
python3 orchestrator/boss.py my-campaign
```

## 2. Scale rule
`target_clips` and `clip_length` come from the campaign brief every time. Nothing
in the code assumes 12 clips or 31–35 s.

## 3. GitHub
Actions → **campaign** → Run workflow:
`campaign_id`, `mode` (`DESIGN_ONLY` | `BUILD_WORKFLOW` | `RUN_CAMPAIGN`), `shards`.

The brief gate refuses `RUN_CAMPAIGN` when rights are unstated or the clip count /
length band is missing.

## 4. Overrides
- `campaigns/<id>/hook_overrides.json` — `{ "<candidate_id>": "HEADLINE TEXT" }`
- `campaigns/<id>/caption_fixes` inside the brief — ASR corrections per clip

## 5. Outputs
`state/<id>/clips/*.mp4`, `delivery.csv`, `manifest.json`, `boss_report.json`,
`reviews.jsonl`, `gates.json`, `cost_ledger.jsonl`.

## 6. Campaign lifecycle (enforced)

```bash
# open a campaign (only one can be open at a time)
python3 orchestrator/boss.py campaign-a          # sets state/ACTIVE_CAMPAIGN

# switching to another campaign is refused while one is open:
#   isolation: 'campaign-a' is active, refusing to work on 'campaign-b'

# when the user says it is finished and perfect:
python3 orchestrator/purge.py campaign-a --confirmed-perfect
```

Purge deletes the brief, state, transcripts, renders, clips and stills for that
campaign, and keeps `lessons/campaign-a.md` + the system. The lesson file is
created before anything is removed.
