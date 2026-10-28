# CRAFT — locked rules for the CLIPFARM pipeline

Approved reference: `DEMO_c557_v6.mp4` and `DEMO_c1407_v1.mp4`.
Every rule below was confirmed on a rendered clip and measured in D9. The master prompt
(`system/MASTER_PROMPT.md`, section J9) points here; nothing in this file is optional.

## 1. Sync — one clock for picture and sound
- Snap every cut to the source frame grid (`edit.source_fps`, 24 here). An un-snapped cut
  renders one frame long per piece and the error accumulates: that is heard as the video
  dragging behind the voice, worst at the end of the clip.
- Render an exact frame count per piece (`-frames:v N`), concatenate at the source rate,
  then convert the frame rate **once** on the finished timeline.
- Cut the audio from the same EDL (`atrim` on the same boundaries) so it is sample-locked
  to the picture by construction.
- QA gate: picture duration == timeline duration to the frame, cut positions within one
  frame of the plan, and a correlation check of the clip audio against the mix (target 0 ms).
- A clip's media may be a cut of the master (only the seconds the clip needs are pulled
  from the 75-minute source); `SRC_OFFSET` tells every seek which source second frame 0 is,
  so the EDL, the face track and the audio stay in absolute episode time and nothing
  downstream knows the media was cut.

## 2. Camera — follow the speaker, keep the frame alive
- **The frame must contain something meaningful, every second.** A person talking, an
  animation playing on a monitor, a busy room, a reaction, a prop in use — anything that
  is actually happening. What is banned is a *dead* frame: black wall, plain studio
  backdrop, or the moment the camera swings past the curtain between two people.
- A face is **not** required in every second. The test is measured on decoded pixels
  (`orchestrator/content.py`: contrast, edge detail, colour spread, motion, plus face
  detection), not on "is there a head in this shot".
- When a stretch is dead, an editor cuts it out — so does the plan: D6 scans the window at
  4 fps, drops dead spans from the timeline (`timeline.build(..., avoid=...)`), extends the
  window to stay inside the clip band, and never lets a cut handle reach back into one.
- One crop per shot, placed on the person who is speaking when there is one.
- A wide two-shot is a **moving window**: ease-out glide (~0.5 s) from the speaker who
  finished to the one who answers, plus a slow drift (14 px) on static pieces. A locked-off
  crop per shot reads as a photo slideshow.
- A long take gets a punch-in at its midpoint so the frame changes size every ~4 s.
- Movement follows the turn-taking; robotic drift unrelated to the speech is just as wrong.
- **Split frame** only when both people genuinely talk at once: two panels, panels zoomed to
  the face (a full-height slice leaves dead curtain above both heads), 5 px brand-colour
  divider that reads as a deliberate lens line.
- **Crop audit before render**: the face track is a summary, so every planned box is
  re-checked on decoded frames and moved onto the nearest face. A stretch with no face is
  allowed as long as something is happening in it — its planned framing stands.
  Never split anything shorter than 0.6 s.
- **Full-bleed.** The picture fills 1080×1920. No bands, no smaller frame inside the frame.

## 3. Graphics — type is the graphic
- One idea per card: kicker (white small caps), value in the display face, unit in brand
  colour, one line of context. Nothing else.
- Numbers appear **whole**, cut in. Never count up from zero.
- Type **wipes on** from its own left edge in 120–160 ms, sits still, is cut away.
- One marker swipe per card, behind the operative words only, dark text on the brand
  colour, edges slightly rough. Never underline a whole line.
- No icons, no dotted "data" grids, no illustrated banknotes, no stock photos as
  decoration. Lime on a grey suit disappears — labels are white with a drop shadow.
- Layout varies by card kind (value / statement / question / equation). Seven cards on one
  skeleton reads as a template whatever the typeface is.
- Cards sit in a lane that clears the face, the caption lane and the source's own lower
  third. Gaps between cards; never one card after another on a metronome.
- Light grain and the same grade on picture and cards, so graphics sit inside the footage.
- **Cards come from this clip's own words.** A number is read across tokens because the
  transcript splits "$30,000" into `$30` + `,000` and "4 million" into two words; one card
  per distinct figure; the kicker is the unit actually spoken ("in a week" -> `PER WEEK`)
  or the topic actually named ("internal usage of models" -> `THE USAGE`). Repeating one
  figure three times, or printing the same card on every clip in a campaign, is the
  machine-made look the client rejected in v5/v6.
- A question card needs a real question (interrogative opening or `?` in the clip's first
  half); a statement card needs a clean line, never an ASR fragment ("what we What we
  learned"). If the clip has nothing that earns a card, it gets fewer cards — not filler.

## 4. Captions and colour
- Three-word groups, heavy grotesque (Archivo Black), keyword in the brand colour with a
  small pop, outline only (a shadow smears on a dark suit).
- One consistent lane that clears the source's lower third and the graphic lane.
- Highlight selectively; a caption that never changes weight reads as machine output.
- Grade: contrast ~1.08, saturation ~1.10, vignette, light grain. No crushed blacks, no
  plastic skin, no heavy sharpening.

## 5. Sound
- Dialogue-led clips are mixed **clean**: no music bed (the client's "annoying background
  sound"), denoise + high-pass, then loudness to −16 LUFS / −1 dBTP.
- Purposeful SFX only, on picture events (card lands, punch-in, split frame): a soft impact
  at about −21 dB, ~8 cues on a 30 s clip. No riser on claims, no whoosh on every cut.
- Leave silence where the sentence needs it.

## 6. Watermark and delivery
- The client watermark is composited for the **whole clip**. A still image input must be
  looped (`-loop 1 -framerate <fps>`); a one-frame stream silently stops compositing
  after ~12 s.
- 1080×1920 H.264, 30 fps, AAC, `+faststart`, frame-locked to the timeline.
- QA with instruments, not opinions: EBU loudness and true peak, full decode-error pass,
  watermark colour probe, text-over-face check, crop-audit result, and the content
  measure: `alive` ratio, longest dead run, whether the hook window is alive. A clip fails
  if more than half a second of it shows nothing happening — a face is not required.
  Report the numbers; never claim a check that was not run.

## 7. Banned — rejected by the client or proven wrong in execution
- Letterbox / black bands ("looks compressed"); the band module is deleted, not disabled.
- Locked-off crop per shot; cutting between faces inside one wide shot.
- A dead second: black wall, empty backdrop, camera swinging past a curtain. A face-less
  but busy frame (screen playing, room full of people working) is fine; emptiness is not.
- Icon sets, dotted grids, illustrated banknotes, decorative stock photos.
- Numbers that count up from zero.
- A synthesised music bed under speech.
- Un-snapped cuts, per-piece frame-rate conversion, forcing segment joints closed across a
  cut (that re-inserts the dialogue the editor removed).
- A one-frame still image as a compositing input without a loop.
- Claiming a QA check that was not measured.
