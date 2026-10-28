# Campaigns

One folder per campaign: `campaigns/<campaign_id>/campaign.json`.

**`target_clips` and `clip_length` are supplied by the user for every campaign.**
The system has no defaults for either, and `store.validate_brief()` refuses to
start without them. Everything else (watermark, captions, audio targets,
delivery format) can be inherited from `_template` and overridden.

Copy the template, fill it in, then:

```bash
python3 orchestrator/boss.py <campaign_id>
```
