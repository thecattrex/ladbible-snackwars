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
- **Cut on the speaker, not on the clock.** Hard cut to whoever is talking; when
  both talk at once, go to a **split frame with a divider** instead of picking one.
  The divider should read as a deliberate line (brand colour), not a seam.
- **No music bed.** The reference runs clean dialogue plus a few transition
  effects. A synthesised bed under speech was the "annoying background sound";
  ambience that is not the source audio is out.
- **Effects only where a picture event happens** — one soft impact as a card
  lands. No riser on claims, no whoosh on every cut (the reference has none).
- **Letterbox bands**: blank space above and below the picture carries the
  headline and the one-line summary, with the operative word marked. That keeps
  text off the speaker entirely and makes the clip legible muted.
