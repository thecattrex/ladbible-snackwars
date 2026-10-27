# 20 clips in ~6 minutes — GitHub Actions version

Local box = 2 cores / 2 GB. It runs **2 render bots at a time** (that already
saturates both cores: ~190 % CPU). More bots locally = OOM, not speed.

GitHub Actions gives **one 4-core / 16 GB runner per clip**, free on a public
repo → all 20 clips at once, no memory limit.

## Setup (5 minutes, one time)

1. github.com → **New repository** → name `ladbible-snackwars` → **Public** →
   Create.
2. Upload everything in this folder except `src/`, `clips*/`, `assets/*.wav`
   (the workflow re-downloads the source itself). Easiest: drag-and-drop in the
   browser, or `git push` if you have git.
3. Repo → **Actions** tab → enable workflows.
4. **render-clips → Run workflow** → leave the box empty (all 20) → Run.
5. ~6 minutes later each job shows a **clip-epXX** artifact; download all as zip.

## After that

Drop the 20 files in `LADbible FINAL — 20 clips` on Drive (or tell me and I'll
upload them — Drive stays connected).

## Cost / limits

* Public repo: unlimited minutes on standard runners, 20 jobs in parallel.
* Private repo: 2 000 free minutes/month → 20 clips × ~6 min = ~120 min. Fine.
* Nothing paid, no credit card, no API key.

## Why it is safe for the campaign

The workflow is byte-for-byte the same pipeline used here (`edit_lad_v3.py` +
`bots/render_bot.py` + `bots/review_bot.py`), so the hooks, speaker-follow
crops, punch-ins, captions, music/whoosh and the face-coverage gate are
identical. Only the machine is bigger.
