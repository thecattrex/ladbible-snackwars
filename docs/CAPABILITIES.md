# Capability check (prompt section B)

| Operation | Tool actually used | Status | Notes |
|---|---|---|---|
| source access (local) | Python file API | SUPPORTED | path must exist |
| source access (direct URL / WeTransfer) | `urllib` + WeTransfer v4 transfer API | SUPPORTED | signed link expires ~4 h; fetched per run |
| source access (YouTube) | not automated here | UNAVAILABLE | needs an authorized file; no DRM/paywall bypass |
| media probe | bundled ffmpeg (`imageio-ffmpeg`) | SUPPORTED | duration, codec, size, fps, audio |
| ASR | `faster-whisper small.en` int8, CPU | SUPPORTED | word timings; English only on this box |
| forced alignment | — | UNAVAILABLE | word timings come from ASR |
| diarization | — | UNAVAILABLE | no speaker-embedding model; labels marked so |
| visual sampling | ffmpeg frames + OpenCV Haar | SUPPORTED (PARTIAL) | 1 frame / 20 s by default, not frame-by-frame |
| scene-cut detection | histogram change on 2 fps proxy | SUPPORTED | approximate |
| moment selection | rule lenses + rubric | PARTIAL | not an LLM editorial agent; editor can override |
| hook drafting | rule templates + rubric | PARTIAL | 6 drafts → 3 → 1; override file supported |
| B-roll / stock | — | UNAVAILABLE | campaign restricts media to supplied source |
| picture edit / reframe | ffmpeg crop + OpenCV face detect | SUPPORTED | speaker-follow, punch-in, EDL |
| music / SFX | synthesised locally (numpy) | SUPPORTED | no licensed assets involved |
| ducking | static bed level under speech | PARTIAL | not per-word keyframes |
| captions | ASS via libass | SUPPORTED | retimed to output clock |
| colour | ffmpeg `eq` | PARTIAL | contrast/saturation only; no grading LUT |
| loudness | `loudnorm` | SUPPORTED | measured again in D9 |
| QA technical | ffprobe/loudnorm/OpenCV | SUPPORTED | measured on the real file |
| QA motion / full watch | — | NOT_RUN | reported as unperformed |
| delivery | files + CSV + manifest | SUPPORTED | Drive upload is a separate manual step |
| publishing / analytics | — | NOT AUTHORIZED | `publish: false` in every brief |
