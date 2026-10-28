# Tests

Run all three before a campaign render; they are cheap and they cover the rule the
client corrected most often.

| test | what it proves |
|---|---|
| `python3 tools/test_content.py` | the content judge separates dead frames (black, plain wall, static curtain) from meaningful ones (screen playing, busy room, movement), and a face always qualifies |
| `python3 tools/test_meaningful_frame.py` | on a synthesised 1080x1920 clip, a busy scene with **no person at all** passes the content checks, while the same clip with one second of black wall fails |
| `python3 tools/test_pipeline_content.py` | the judge drives the cut: dead spans are found on the source, and `timeline.build(..., avoid=...)` removes them, keeps the clip in band and does not let a cut handle reach back into the dead edge |

`docs/CRAFT.md` §2 and §6 state the rule these tests enforce; `docs/RULES.md` R7 records it.
