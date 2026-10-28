# Campaign clipper — built to the master prompt

**The governing document is [`docs/MASTER_PROMPT.md`](docs/MASTER_PROMPT.md).**
Every department, schema and gate in this repo exists to satisfy it. If code and
the prompt disagree, the prompt wins.

| Read this | Why |
|---|---|
| `docs/MASTER_PROMPT.md` | the spec (modes, departments, contracts, gates) |
| `docs/ARCHITECTURE.md` | prompt section → file, with honest build status |
| `docs/CAPABILITIES.md` | per-operation truth: SUPPORTED / PARTIAL / UNAVAILABLE / NOT_RUN |
| `docs/RUNBOOK.md` | how to start a campaign |
| `docs/RULES.md` | standing rules: one campaign at a time, purge only on your word |
| `campaigns/<id>/campaign.json` | the brief — clip count and length come from the user, always |
| `schemas/` | campaign, task, review, moment card, hook card, EDL |
| `departments/d1..d9` | the nine production departments |
| `orchestrator/` | store (state/versions/costs), queue (pools/retries), boss (portfolio gate), deliver |
| `legacy/pre_prompt_*` | earlier experiment kept for reference, not used by any job |

Modes: `DESIGN_ONLY` (default, validates only) · `BUILD_WORKFLOW` · `RUN_CAMPAIGN`.
Nothing here publishes, and nothing estimates views or revenue.
