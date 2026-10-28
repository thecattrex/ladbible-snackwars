# Higgsfield x 20VC — campaign contract

Everything the bots need, in one place:

| file | what it holds |
|---|---|
| `campaign.json` | length window (31–35 s), aspect, fps, watermark, caption style, audio targets, framing, platforms, banned list |
| `hooks.json` | boss-approved on-screen hook per clip id (must be supported by what the clip actually says) |

Run it with **Actions → campaign → Run workflow** (`campaign: higgsfield`, `shards: 12`).

Departments (each its own job, chained with `needs:`):

`source → transcribe × 12 → hook × 5 lenses → cut → render × clips → qc × clips → deliver`

A clip that fails QC lands in `rework-dispatch`, never in `delivery`.
