# Craft notes — what makes an edit read as human

Collected while building the graphics and sound layers. Sources are listed so the
reasoning can be re-checked, not repeated from memory.

## Picture
- **Change the frame every 2-3 s.** One static talking-head shot gives a
  scrolling viewer nothing to stay for; a meaningful visual shift (zoom, insert,
  overlay, angle) beats a jump cut every 2 s, which causes fatigue.
- **Progressive zoom**: tighten 1.5-2 % per second over a clip instead of holding
  one size (`clip-forge.io` retention playbook).
- **Punch-in on the line that matters**, not on every line.
- **B-roll / graphics on the lines that earn it** — two or three per clip, not a
  carpet (`quickreel.io`). A number gets a counter; a comparison gets a card.
- **Keep the face in the upper-middle third**; text goes under the chin, never
  over the eyes or mouth.
- Documentary lower-thirds read as human: a soft gradient over the footage, a
  kicker, one big value, a thin accent rule. A hard rounded panel with a border
  reads as app UI — i.e. as machine output.

## Type
- One condensed display face for numbers (Anton), one grotesque for labels
  (Archivo Black / Inter). Never the system default.
- Kicker + value + unit + rule: a viewer reads it in one glance.
- Kinetic captions: 1-3 words, heavy, keyword in the brand colour, and a small
  rise on entry (~80 ms) rather than a fade.
- Stagger layered elements ~100-150 ms apart; ease-in-out, never linear
  (`trydemotion.com` kinetic typography notes).

## Sound
- **Whoosh straddles** a transition: starts before the cut, peaks on the frame
  change, tails after.
- **Impact lands exactly on** the cut or the frame a card appears. 50 ms early
  reads as sloppy.
- **Riser builds into the moment and stops dead on it.** The abrupt stop is the
  effect.
- Effects sit at roughly half the voice level (about -6 dB relative); if a viewer
  notices the whoosh, it is too loud.
- Sound only the cuts that matter — section changes, punch-ins, reveals. Sounding
  every join turns the mix into a percussion track.
- Bed gets sidechained off the voice, not just turned down.

## What still reads as "AI made this"
- Cards that appear on a metronome; human editors leave gaps.
- Generic icon sets and templates.
- Captions that never change weight or size.
- A whoosh on every single cut.

## Second pass — reference-driven corrections

After watching a reference short the client supplied (multi-cam podcast clip):
- **Follow the speaker with the camera, not with cuts.** Re-watching the
  reference frame by frame (0.25 s apart) shows there is no cut inside the wide
  shot: the frame **glides** from whoever was talking to whoever answers, then
  keeps drifting. A cut is a last resort — reserve it for a genuine change of
  setup in the source (wide → close-up).
- **A wide two-shot with two faces = a moving window.** One crop per speaker, and
  the crop travels across the shot in ~0.5 s with an ease-out. Static per-shot
  crops look like a photo slideshow, which is what got the first cut rejected.
- **Split frame only for genuine overlap** (both people talking at once): two
  tight panels with a brand-colour divider. Panel crops are zoomed to the face —
  a full-height slice leaves a band of empty curtain above both heads.
- **No music bed.** The reference runs clean dialogue plus a few transition
  effects. A synthesised bed under speech was the "annoying background sound";
  ambience that is not the source audio is out.
- **Effects only where a picture event happens** — one soft impact as a card
  lands. No riser on claims, no whoosh on every cut (the reference has none).
- **No letterbox bands.** Blank bands above and below the picture were tried and
  the client rejected them: sub-9:16 picture inside a 9:16 frame reads as
  "compressed". Delivery is full-bleed 1080x1920 — the whole frame is picture.
  Title/watermark live over the picture at the top, cards mid-frame, captions low.
- **Crop audit is mandatory.** A face track sampled at 4 fps is a summary; when
  the source cuts to a new setup between two samples the planned crop lands on an
  empty desk. Every crop is checked against the real frames before render and
  moved onto the nearest face (see `orchestrator/cropaudit.py`).
- **A still image input to ffmpeg must be looped** (`-loop 1 -framerate <fps>`).
  A one-frame stream composited with `overlay` silently stops appearing after
  ~12 s, which took the watermark off the back half of a render.

## Third pass — sync and the "still looks AI" tell

**Sound and picture must be cut on the same frame.**
- Every cut is snapped to the source frame grid before anything renders
  (`source_fps`, 24 here). Off-grid cuts made every piece render one frame long,
  and nine pieces stacked 0.4 s of picture lag against the audio — heard as a
  clip that drags behind the voice, worst at the end.
- Each piece renders an exact frame count (`-frames:v N`), the pieces are
  concatenated at the source rate, and the 24 → 30 conversion happens **once**
  on the finished timeline. Converting per piece rounds per piece.
- Audio is cut from the same EDL with `atrim` on the same boundaries, so it is
  sample-locked to the picture by construction, not by eye.

**Type, not icons.**
- No icon sets, no dotted grids, no illustrated banknotes, no neon chips. The
  graphics are type + the footage, which is what a podcast editor cuts.
- Numbers appear whole on a cut. Counting up from zero looks like a template and
  can flash a wrong number on screen (`$1,812` on the way to `$10,000`).
- Type **wipes on** from its own left edge in ~120–160 ms, sits still, and is cut
  off. Fades and rise-ins are the software look.
- One marker swipe per card, behind the operative words only, dark text on the
  lime, edges slightly rough and angled a few degrees. Never underline the whole
  line.
- Labels are white small caps with a drop shadow, not lime: lime on a grey suit
  disappears. Lime stays for the accent tick, the unit, and the swipe.
- Layout varies by card kind (value / statement / question / equation). One
  skeleton repeated seven times reads as a template regardless of the typeface.
