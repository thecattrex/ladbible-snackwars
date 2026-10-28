#!/usr/bin/env python3
"""Bundle what a render job needs, for upload as release assets.

The repo never carries client footage or campaign state (see .gitignore), so a
render job gets everything else from the `clipfarm-media` release:

  state.tar.gz            campaign json + the json artifacts of every department
  media-<clip>.tar.gz     that clip's cut of the master (src.mp4 + offset.txt)

Usage:
  python3 tools/make_bundle.py state            -> build/state.tar.gz
  python3 tools/make_bundle.py media c557 ...   -> build/media-<clip>.tar.gz
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CID = "higgsfield-20vc"
OUT = ROOT / "build"
MEDIA = Path("/var/tmp/clips")


def state_bundle() -> Path:
    OUT.mkdir(exist_ok=True)
    target = OUT / "state.tar.gz"
    st = ROOT / f"state/{CID}"
    camp = ROOT / f"campaigns/{CID}"
    staging = OUT / "stage"
    subprocess.run(["rm", "-rf", str(staging)], check=True)
    (staging / f"state/{CID}").mkdir(parents=True)
    (staging / f"campaigns/{CID}").mkdir(parents=True)
    # json only: the reports, plans and overrides the departments read
    for f in st.rglob("*.json"):
        if any(part in ("clips", "render", "work") for part in f.parts):
            continue
        dest = staging / f"state/{CID}" / f.relative_to(st)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(f.read_bytes())
    for f in camp.glob("*.json"):
        (staging / f"campaigns/{CID}" / f.name).write_bytes(f.read_bytes())
    subprocess.run(["tar", "-czf", str(target), "-C", str(staging), "state", "campaigns"], check=True)
    print(f"{target} {target.stat().st_size/1e6:.1f} MB")
    return target


def media_bundle(clip: str) -> Path:
    OUT.mkdir(exist_ok=True)
    d = MEDIA / clip
    if not (d / "src.mp4").exists():
        raise SystemExit(f"{clip}: no media at {d}")
    target = OUT / f"media-{clip}.tar.gz"
    subprocess.run(["tar", "-czf", str(target), "-C", str(d), "src.mp4", "offset.txt"], check=True)
    print(f"{target} {target.stat().st_size/1e6:.1f} MB")
    return target


if __name__ == "__main__":
    what = sys.argv[1]
    if what == "state":
        state_bundle()
    elif what == "media":
        for c in sys.argv[2:]:
            try:
                media_bundle(c)
            except SystemExit as e:
                print(e)
