#!/usr/bin/env bash
# Put this box back in a working state after a reset.
# The sandbox drops installed binaries and the ffmpeg symlink between sessions;
# dependencies and the symlink are what every other tool assumes.
set -e
mkdir -p /home/user/bin
FF=$(python3 -c "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())" 2>/dev/null || true)
if [ -z "$FF" ]; then
  pip install -q imageio-ffmpeg
  FF=$(python3 -c "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())")
fi
ln -sf "$FF" /home/user/bin/ffmpeg
python3 - <<'PY'
import importlib.util
need = ["numpy", "cv2", "PIL", "soundfile", "imageio_ffmpeg", "yt_dlp", "faster_whisper", "requests"]
missing = [m for m in need if not importlib.util.find_spec(m)]
print("missing:", missing or "none")
raise SystemExit(0 if not missing else 1)
PY
[ $? -eq 0 ] || pip install -q yt-dlp faster-whisper soundfile opencv-python-headless pillow numpy requests
echo "ffmpeg: $(/home/user/bin/ffmpeg -version | head -1)"
python3 -c "import faster_whisper, yt_dlp; print('yt-dlp + faster-whisper ready')"
