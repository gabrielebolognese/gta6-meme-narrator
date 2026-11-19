# edit.json

One JSON object. Every time is in **seconds of the clip** (the times printed on the frame sheets), every position in **percent of the clip's
frame** (0 to 100 across and down, the grid on the sheets). `python scripts/narrator.py check` validates it and prints the timeline.

| Key | Required | What |
|---|---|---|
| `layout` | yes | `{"facecam": [left, top, right, bottom] or null, "focus_x": 50}`. The facecam box in percent, tight around the camera picture; `null` when there is none. `focus_x`: where the action is across the frame (the game is cropped around it). A vertical clip ignores both. Without a facecam, `"game_width": 62` sets how much of the frame's width is shown |
| `start_s`, `end_s` | yes | the main window: the whole moment, from the build-up (never dead air) to after the reaction |
| `hook_from_s`, `hook_to_s` | yes | the cold open: 2.5 to 4.5 s of the peak, inside the main window |
| `hook_text` | yes | 2 to 7 words on screen over the cold open (capitals) |
| `hook_line` | yes | the narrator's first line, over the cold open: 4 to 14 words |
| `wrong_name` | no | the wrong name on purpose ("Taylor Swift"); when set, the hook line must say it |
| `narration` | yes | 6 to 12 lines: `{"at_s": 12.5, "text": "..."}`, each 4 to 16 words, inside the main window. A line of N words lasts about N/3 s: never put two lines closer than that (the script moves a line that would overlap to after the one before) |
| `pointers` | no | 1 to 4 arrows: `{"from_s": 8.0, "to_s": 10.6, "label": "THE KIND MAN", "track": [[8.2, 63, 35], [9.2, 70, 55], [10.2, 60, 57]]}`. `track` is [time, x, y] for every frame time the arrow shows, the point its tip touches; the script smooths between the points. 0.8 to 5 s each. An arrow during the cold open's time also shows in the cold open |
| `memes` | no | `{"at_s": 19.5, "meme": "<id from catalog.txt>", "mode": "insert" or "corner"}`. insert stops the clip and plays the meme full screen with its sound (at most 2); corner pops it over the clip |
| `sfx` | no | `{"at_s": 15.5, "sfx": "boom"}`, ids from catalog.txt, 4 to 10. The dings of the arrows, the rewind's scratch, the whoosh before an inserted meme and the boom of a freeze are added automatically |
| `freezes` | no | 0 to 2: `{"at_s": 22.0, "seconds": 1.0, "x": 50, "y": 45}`: the picture stops 0.6 to 1.6 s with a zoom on (x, y) and a boom |
| `captions` | no | source ranges whose transcribed words (words.json) are captioned: `[[19.0, 21.5]]`. Use them for the streamer's best lines; they hide while the narrator talks |
| `title` | no | the video title (a meme, one emoji at most) |
| `summary` | no | one sentence, what really happens |

## The bundled sounds

`ding` (a bell, used for the arrows), `boom` (deep impact, the vine boom kind), `whoosh`, `scratch` (record scratch), `pop`, `buzzer` (wrong
answer), `boing`, `glitch`, `sad-trombone`, `airhorn`, `dun-dun` (dramatic). All synthesized by `scripts/make_sfx.py` (CC0).

## Your own memes

`--memes DIR`: every video file (mp4, mov, webm, mkv, gif) is a video meme and every audio file (wav, mp3, ogg, m4a, flac) a sound; the id is
the file name in lower case with dashes (`Rock Eyebrow.mp4` is `rock-eyebrow`). An optional `DIR/memes.json` gives descriptions:
`{"rock-eyebrow": "The Rock raises an eyebrow (suspicious)"}`. Short clips work best (2 to 4 s); an inserted meme plays 3.2 s at most.

## Example

[../examples/edit-example.json](../examples/edit-example.json) is a complete edit for a 42 s stream clip with a facecam.
