---
name: gta6-meme-narrator
description: Turn a gameplay or stream clip (GTA 6 or any game) into a narrated meme short for YouTube Shorts, TikTok or Reels (1080x1920): a cold open on the funniest moment, a rewind, then the whole clip with a deadpan narrator who gets everything hilariously wrong on purpose, arrows that follow people and cars, freeze frames, memes and sound effects (vine boom style boom, dings, record scratch). Claude watches the frames and writes the jokes; a script renders it with a free local voice (Kokoro). Use when the user says "narrate this clip", "make a meme edit", "add a funny narrator", "turn this GTA clip into a short", "meme this", "add arrows and vine booms", or hands over a gameplay or stream clip and wants it funny.
---

# gta6-meme-narrator

Turns one clip into a narrated meme short. You are the editor: you watch the clip's frames, write the edit as a JSON file, and the script
checks and renders it. The voice is Kokoro's "am_michael" (deadpan, male), every text is white with a black outline.

The structure of every short:
1. **Cold open:** 2.5 to 4.5 seconds of the peak (the punch, the crash, the fail) with a hook on screen and the narrator's first line.
2. **Rewind:** the cold open plays backwards at 4x with a washed-out look and a record scratch (automatic).
3. **The whole moment:** the main window, narrated line by line, with arrows, freeze frames, memes cut in or in a corner, sound effects.

## Setup (once)

The scripts are in `scripts/` next to this file; fonts and sounds are bundled.

1. **ffmpeg** with libass on PATH (`ffmpeg -version`; Windows `winget install ffmpeg`, macOS `brew install ffmpeg`).
2. **Python 3.10+ with Pillow**: `python -m pip install pillow`.
3. **The voice, Kokoro** (free, runs locally; needs Python 3.10 to 3.12): `python -m pip install kokoro soundfile`. If the main Python is
   newer, make a venv with 3.11 or 3.12, install it there and pass that interpreter to render with `--python`. Without it, `--voice none`
   renders the narration as text only.
4. Optional, **faster-whisper** for the words said in the clip (captions, and knowing what the streamer says): `python -m pip install faster-whisper`.

Check everything with `python tests/selftest.py` (no footage needed, about two minutes).

## Workflow

1. **Ask only what you need:** the clip (a file), whether to use the wrong-name joke (below), and the user's meme folder if they have one
   (video and audio files; the bundled sounds are always there). Use clips the user has the right to use.
2. **Watch it:** `python scripts/narrator.py frames CLIP WORK [--memes DIR]`, and if faster-whisper is installed
   `python scripts/words.py CLIP WORK`. Then read **every** `WORK/sheet-*.jpg` with the Read tool (one frame a second, each with its time and a
   percent grid), `WORK/words.txt` and `WORK/catalog.txt`. Do not write a single joke before you have seen all the frames.
3. **The layout:** find the facecam (if any) on the frames and note its box in percent `[left, top, right, bottom]`, tight around the
   camera picture (no chat, no borders). Note where the action is across the frame (`focus_x`, percent).
4. **Write `edit.json`** in the work folder: the format is in [references/edit-format.md](references/edit-format.md), the comedy rules in
   [references/comedy.md](references/comedy.md) (read both the first time). The main window, the cold open, 6 to 12 narrator lines, 1 to 4
   arrows with a point for every second they show, 4 to 10 sounds, 0 to 2 freezes, memes when the user has them, a title.
5. **Check:** `python scripts/narrator.py check CLIP WORK/edit.json --work WORK [--memes DIR]`. Fix every problem it lists. Then open
   `WORK/layout.jpg`: the first tile shows the vertical layout (the facecam must fill its area with nothing but the camera picture), the
   others show every arrow point as a red dot on its own frame. Every dot must sit on its target (a person's head or chest, a car's middle);
   move the wrong ones and check again.
6. **Render:** `python scripts/narrator.py render CLIP WORK/edit.json OUT [--memes DIR] [--python PATH_TO_KOKORO_PYTHON] [--words WORK/words.json]`.
   It takes a few minutes and writes `OUT/short.mp4`, `OUT/keys.jpg` and `OUT/plan.json`. `--clip-volume 0` mutes the clip's own sound (a
   clip with copyrighted music, or a voice the user does not want heard); the narrator and the sounds stay.
7. **Look at `OUT/keys.jpg`** (key moments of the finished short) before you call it done: a label cut at an edge, an arrow pointing at
   nothing, a corner meme over the action, text over a face. Fix the edit and render again.
8. **Deliver:** the path of `short.mp4`, its length, the title, and one line on the joke.

## Rules

- Every text is white; the script does that. Never change the structure (cold open, rewind, whole moment).
- The narrator never explains a joke and never simply describes. Read references/comedy.md.
- No slurs, nothing sexual about real people, no claim that a real person did something illegal outside the game, no hate. Light swearing
  at most. The wrong-name joke is always obviously a joke.
- Lengths: `--min-seconds` (30) and `--max-seconds` (59) by default; under the minimum the script widens the window and adds a slow replay of
  the peak. For a channel with its own rule (say 40 s), pass it.

## Example

User: "here's a clip from my GTA 6 stream, make it funny" (stream.mp4, facecam bottom left).

You run frames and words, read the 6 sheets, see an NPC shove the player's character at 9 s and a cop arrive at 18 s; you write edit.json
with the facecam `[2, 64, 24, 98]`, a cold open on the shove, "When Taylor Swift was playing GTA 6" as the hook line, nine lines ("This kind
man saw a fly on her shoulder and decided to get rid of it."), arrows on the NPC and the cop, a freeze on the player's face, a boom and a
buzzer; check, fix one arrow that pointed at the wall, render, open keys.jpg, and answer with the file, 47 s, and the title.
