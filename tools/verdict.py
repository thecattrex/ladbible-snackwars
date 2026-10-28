#!/usr/bin/env python3
"""Print the D9 verdict from a QA report file."""
import json
import re
import sys

text = open(sys.argv[1]).read()
try:
    print(json.loads(text[text.index("{"):text.rindex("}") + 1]).get("verdict", "UNPARSED"))
except Exception:
    m = re.search(r'"verdict"\s*:\s*"(\w+)"', text)
    print(m.group(1) if m else "UNPARSED")
