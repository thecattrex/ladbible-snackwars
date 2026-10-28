#!/usr/bin/env python3
"""Every clip in a campaign's portfolio, in source order, space separated."""
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
cid = sys.argv[1]
port = json.loads((root / f"state/{cid}/artifacts/portfolio.v1.json").read_text())["payload"]["selected"]
print(" ".join(c["candidate_id"] for c in sorted(port, key=lambda x: x["t0"])))
