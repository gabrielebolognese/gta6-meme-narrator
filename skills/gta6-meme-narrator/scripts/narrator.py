#!/usr/bin/env python3
"""gta6-meme-narrator: turns a gameplay or stream clip into a narrated meme short (1080x1920): a cold open on the peak, a rewind, the whole
clip with a deadpan narrator who gets everything wrong on purpose, arrows that follow people and cars, freeze frames, memes and sound effects.
Claude watches the frames and writes the edit (edit.json); this script checks it and renders it.

    python narrator.py frames CLIP WORK [--memes DIR]          sheets of the clip's frames for Claude to watch (one a second, a percent grid,
                                                               the time), info.json, catalog.txt (the sounds and memes Claude may use)
    python narrator.py check  CLIP EDIT [--work WORK] [--memes DIR] [--min-seconds 30] [--max-seconds 59]
                                                               validates edit.json and prints the timeline; WORK/layout.jpg shows one frame in
                                                               the vertical layout with the arrows' first points (red dots)
    python narrator.py render CLIP EDIT OUT [--memes DIR] [--python PY] [--voice am_michael] [--speed 1.1] [--words WORK/words.json]
                                                               OUT/short.mp4, OUT/keys.jpg (its key moments, to check), OUT/plan.json

Needs ffmpeg (with libass) on PATH, Python 3.10+ with Pillow, and for the voice an interpreter with kokoro (--python, see tts_kokoro.py).
The edit format is in ../references/edit-format.md.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
FONTS = os.path.join(SKILL, "fonts")
SFX_DIR = os.path.join(SKILL, "sfx")
W, H, FPS = 1080, 1920, 30
DEF = {"duck_voice": 0.2, "duck_corner": 0.55, "voice_gain": 1.6, "meme_gain": 0.9, "sfx_gain": 0.8, "auto_gain": 0.7, "rewind_speed": 4.0,
       "corner_w": 520, "insert_max_s": 3.2, "freeze_zoom": 1.25, "max_auto_memes": 2, "lufs": -14, "true_peak": -1.5, "crf": 18,
       "narr_font": "Anton", "narr_size": 104, "cap_font": "Archivo Black", "cap_size": 78, "hook_font": "Anton", "hook_size": 112,
       "label_font": "Anton", "label_size": 68, "outline": 8, "cam_share": 0.42, "game_width": 62}
DOWN = "m 33 0 l 77 0 l 77 120 l 110 120 l 55 200 l 0 120 l 33 120"     # tip at (55, 200): \an2 puts the tip on \pos
UP = "m 55 0 l 110 80 l 77 80 l 77 200 l 33 200 l 33 80 l 0 80"         # tip at (55, 0): \an8 puts the tip on \pos
REWIND_ICON = "m 70 0 l 70 90 l 0 45 m 140 0 l 140 90 l 70 45"
VIDEO_EXT = (".mp4", ".mov", ".webm", ".mkv", ".gif")
AUDIO_EXT = (".wav", ".mp3", ".ogg", ".m4a", ".flac")


# ---------------------------------------------------------------- helpers

def run(cmd: list, timeout: int = 3600, check: bool = True, cwd: str | None = None) -> subprocess.CompletedProcess:
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL, timeout=timeout, cwd=cwd)
    if check and res.returncode != 0:
        raise SystemExit(f"{os.path.basename(cmd[0])} failed ({res.returncode}): {(res.stderr or res.stdout)[-800:]}")
    return res


def probe(path: str) -> dict:
    res = run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height", "-of", "json", path], timeout=120)
    d = json.loads(res.stdout or "{}")
    out = {"duration": float((d.get("format") or {}).get("duration") or 0), "width": 0, "height": 0, "audio": False}
    for s in d.get("streams") or []:
        if s.get("codec_type") == "video" and not out["width"]:
            out["width"], out["height"] = int(s.get("width") or 0), int(s.get("height") or 0)
        if s.get("codec_type") == "audio":
            out["audio"] = True
    return out


def say(msg: str) -> None:
    print(msg, flush=True)


def clean(text) -> str:
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    return t.replace(chr(0x2014), ", ").replace(chr(0x2013), "-").replace(" ,", ",")


def fnum(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def write_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def need_tools() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise SystemExit(f"{tool} is not on PATH: install ffmpeg (https://ffmpeg.org/download.html, or winget install ffmpeg / brew install ffmpeg)")
    res = run(["ffmpeg", "-hide_banner", "-filters"], check=False)
    if " subtitles " not in (res.stdout or ""):
        raise SystemExit("this ffmpeg has no libass (the subtitles filter): install a full build of ffmpeg")


# ---------------------------------------------------------------- the library: bundled sounds and the user's memes

def catalog(memes_dir: str | None) -> list:
    cat = []
    meta = json.load(open(os.path.join(SFX_DIR, "sfx.json"), encoding="utf-8"))["sounds"]
    for m in meta:
        cat.append({"id": m["id"], "kind": "sfx", "file": os.path.join(SFX_DIR, m["file"]), "dur": float(m["seconds"]), "desc": m["desc"],
                    "tags": m["tags"], "bundled": True})
    if memes_dir:
        if not os.path.isdir(memes_dir):
            raise SystemExit(f"the memes folder {memes_dir} does not exist")
        desc = {}
        if os.path.isfile(os.path.join(memes_dir, "memes.json")):
            desc = json.load(open(os.path.join(memes_dir, "memes.json"), encoding="utf-8"))
        for f in sorted(glob.glob(os.path.join(memes_dir, "**", "*"), recursive=True)):
            ext = os.path.splitext(f)[1].lower()
            if ext not in VIDEO_EXT + AUDIO_EXT:
                continue
            mid = re.sub(r"[^a-z0-9]+", "-", os.path.splitext(os.path.basename(f))[0].lower()).strip("-")
            if any(c["id"] == mid for c in cat):
                mid += "-2"
            p = probe(f)
            kind = "video" if ext in VIDEO_EXT and p["width"] else "sfx"
            d = desc.get(mid) or desc.get(os.path.basename(f)) or os.path.splitext(os.path.basename(f))[0].replace("-", " ").replace("_", " ")
            cat.append({"id": mid, "kind": kind, "file": f, "dur": round(p["duration"], 2), "desc": str(d), "tags": [], "audio": p["audio"]})
    return cat


def find(cat: list, sid: str) -> dict | None:
    return next((c for c in cat if c["id"] == sid), None)


def catalog_text(cat: list) -> str:
    vids = [m for m in cat if m["kind"] == "video"]
    sfx = [m for m in cat if m["kind"] == "sfx"]
    out = ["Sound effects (id | what | seconds):"] + [f"- {m['id']} | {m['desc']} | {m['dur']:.1f}" for m in sfx]
    out += ["", "Video memes (id | what | seconds):"] + ([f"- {m['id']} | {m['desc']} | {m['dur']:.1f}" for m in vids] or ["- (none: give --memes DIR with your meme clips)"])
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- the vertical layout

def make_frame(info: dict, layout: dict) -> dict:
    """Where the facecam and the game go in the 1080x1920 short. layout: {"facecam": [x0, y0, x1, y1] in percent of the frame or null,
    "focus_x": percent across where the action is (default 50), "game_width": percent of the frame's width shown without a facecam (62)}."""
    sw, sh = int(info["width"]), int(info["height"])
    fr = {"src": {"w": sw, "h": sh}, "out": {"w": W, "h": H}}
    layout = layout or {}
    if sh > sw * 1.2:
        return {**fr, "layout": "vertical", "seam_y": None}
    fx = min(max(float(layout.get("focus_x", 50)), 0), 100) / 100 * sw
    cam = layout.get("facecam")
    if cam:
        x0, y0, x1, y1 = [min(max(float(v), 0), 100) for v in cam]
        bx, by, bw, bh = x0 / 100 * sw, y0 / 100 * sh, (x1 - x0) / 100 * sw, (y1 - y0) / 100 * sh
        if bw < 20 or bh < 20:
            raise SystemExit("layout.facecam is too small: give [left, top, right, bottom] in percent of the frame")
        CH = int(H * DEF["cam_share"])
        GH = H - CH
        target = W / CH
        # fill the facecam area by trimming the box inward (never showing what is outside it); a box far from the area's shape is shown
        # whole over a blurred copy instead
        nw, nh = (bh * target, bh) if bw / bh > target else (bw, bw / target)
        if nw * nh >= 0.6 * bw * bh:
            box = [int(bx + (bw - nw) / 2), int(by + (bh - nh) / 2), int(nw), int(nh)]
            fit = "cover"
        else:
            box, fit = [int(bx), int(by), int(bw), int(bh)], "contain"
        gh = sh
        gw = gh * W / GH
        if gw > sw:
            gw, gh = sw, sw * GH / W
        game = [int(min(max(fx - gw / 2, 0), sw - gw)), int((sh - gh) / 2), int(gw), int(gh)]
        return {**fr, "layout": "split", "seam_y": CH, "cam": {"box": box, "fit": fit, "region": [W, CH]}, "game": {"box": game, "region": [W, GH]}}
    share = min(max(float(layout.get("game_width", DEF["game_width"])), 30), 100) / 100
    gw = sw * share
    SB = int(round(W * sh / gw))
    if SB > H:
        SB = H
        gw = sh * W / H
    box = [int(min(max(fx - gw / 2, 0), sw - gw)), 0, int(gw), sh]
    return {**fr, "layout": "single", "seam_y": None, "single": {"box": box, "region": [W, SB], "y": (H - SB) // 2}}


def to_out(fr: dict, x: float, y: float) -> tuple[float, float] | None:
    """A point of the source frame in percent, in the short's pixels (None when the short does not show it)."""
    sw, sh = float(fr["src"]["w"]), float(fr["src"]["h"])
    px, py = x / 100 * sw, y / 100 * sh
    if fr["layout"] == "vertical":
        s = max(W / sw, H / sh)
        ox, oy = px * s - (sw * s - W) / 2, py * s - (sh * s - H) / 2
        return (ox, oy) if 0 <= ox <= W and 0 <= oy <= H else None
    if fr["layout"] == "split":
        cx, cy, cw, ch = fr["cam"]["box"]
        CH = float(fr["cam"]["region"][1])
        if cx <= px <= cx + cw and cy <= py <= cy + ch:
            if fr["cam"]["fit"] == "cover":
                return (px - cx) / cw * W, (py - cy) / ch * CH
            s = min(W / cw, CH / ch)
            return (W - cw * s) / 2 + (px - cx) * s, (CH - ch * s) / 2 + (py - cy) * s
        gx, gy, gw, gh = fr["game"]["box"]
        if gx <= px <= gx + gw and gy <= py <= gy + gh:
            return (px - gx) / gw * W, CH + (py - gy) / gh * float(fr["game"]["region"][1])
        return None
    sx, sy, sw2, sh2 = fr["single"]["box"]
    SB, Y = float(fr["single"]["region"][1]), float(fr["single"]["y"])
    if sx <= px <= sx + sw2 and sy <= py <= sy + sh2:
        return (px - sx) / sw2 * W, Y + (py - sy) / sh2 * SB
    return None


def cap_y(fr: dict) -> int:
    return int(fr["seam_y"]) if fr["layout"] == "split" else int(H * 0.70)


def layout_chain(i: int, k: int, fr: dict) -> str:
    """The vertical layout for input i, ending in [L<k>]."""
    if fr["layout"] == "vertical":
        return f"[{i}:v]fps={FPS},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1[L{k}]"
    if fr["layout"] == "split":
        cx, cy, cw, ch = fr["cam"]["box"]
        gx, gy, gw, gh = fr["game"]["box"]
        CH, GH = fr["cam"]["region"][1], fr["game"]["region"][1]
        if fr["cam"]["fit"] == "cover":
            cam = f"[c{k}]crop={cw}:{ch}:{cx}:{cy},scale={W}:{CH}:flags=lanczos,setsar=1[cam{k}]"
        else:
            cam = (f"[c{k}]crop={cw}:{ch}:{cx}:{cy},split=2[ca{k}][cb{k}];"
                   f"[ca{k}]scale={W}:{CH}:force_original_aspect_ratio=increase,crop={W}:{CH},gblur=sigma=28,eq=brightness=-0.12[cg{k}];"
                   f"[cb{k}]scale={W}:{CH}:force_original_aspect_ratio=decrease:flags=lanczos[cf{k}];[cg{k}][cf{k}]overlay=(W-w)/2:(H-h)/2,setsar=1[cam{k}]")
        return (f"[{i}:v]fps={FPS},split=2[c{k}][g{k}];{cam};[g{k}]crop={gw}:{gh}:{gx}:{gy},scale={W}:{GH}:flags=lanczos,setsar=1[game{k}];"
                f"[cam{k}][game{k}]vstack=inputs=2[L{k}]")
    sx, sy, sw, sh = fr["single"]["box"]
    SB, Y = fr["single"]["region"][1], fr["single"]["y"]
    return (f"[{i}:v]fps={FPS},split=2[sa{k}][sb{k}];[sa{k}]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},gblur=sigma=28,"
            f"eq=brightness=-0.12[bg{k}];[sb{k}]crop={sw}:{sh}:{sx}:{sy},scale={W}:{SB}:flags=lanczos[fg{k}];[bg{k}][fg{k}]overlay=0:{Y},setsar=1[L{k}]")


# ---------------------------------------------------------------- frames

def cmd_frames(a) -> int:
    need_tools()
    from PIL import Image, ImageDraw, ImageFont
    info = probe(a.clip)
    if not info["width"]:
        raise SystemExit(f"{a.clip} has no video stream")
    dur = info["duration"]
    os.makedirs(a.work, exist_ok=True)
    fdir = os.path.join(a.work, "frames")
    os.makedirs(fdir, exist_ok=True)
    for f in glob.glob(os.path.join(fdir, "*.png")) + glob.glob(os.path.join(a.work, "sheet-*.jpg")):
        os.remove(f)
    step = 1.0
    n = int((dur - 0.3) // step) + 1
    if n > 90:
        n, step = 90, round((dur - 0.3) / 89, 2)
    times = [round(0.25 + k * step, 2) for k in range(n) if 0.25 + k * step < dur - 0.05]
    TW = 760
    for k, t in enumerate(times):
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-nostdin", "-ss", f"{t:.3f}", "-i", a.clip, "-frames:v", "1",
             "-vf", f"scale={TW}:-2", os.path.join(fdir, f"f{k:03d}.png")], timeout=120)
    try:
        big = ImageFont.truetype(os.path.join(FONTS, "Anton-Regular.ttf"), 34)
        small = ImageFont.truetype(os.path.join(FONTS, "Anton-Regular.ttf"), 17)
    except OSError:
        big = small = ImageFont.load_default()
    tiles = []
    for k, t in enumerate(times):
        p = os.path.join(fdir, f"f{k:03d}.png")
        if not os.path.isfile(p):
            continue
        im = Image.open(p).convert("RGB")
        w, h = im.size
        d = ImageDraw.Draw(im, "RGBA")
        for j in range(1, 10):
            x, y = round(j * w / 10), round(j * h / 10)
            d.line([(x, 0), (x, h)], fill=(255, 255, 255, 85), width=1)
            d.line([(0, y), (w, y)], fill=(255, 255, 255, 85), width=1)
            d.text((x + 2, 2), str(j * 10), font=small, fill=(255, 255, 255, 230), stroke_width=2, stroke_fill=(0, 0, 0, 230))
            d.text((2, y + 1), str(j * 10), font=small, fill=(255, 255, 255, 230), stroke_width=2, stroke_fill=(0, 0, 0, 230))
        d.rectangle([w - 118, 0, w, 46], fill=(0, 0, 0, 200))
        d.text((w - 110, 2), f"{t:.1f} s", font=big, fill=(255, 255, 255, 255))
        tiles.append(im)
    sheets, per, cols, gap = [], 8, 2, 10
    vertical = info["height"] > info["width"] * 1.2
    if vertical:
        per, cols = 8, 4
    for s in range(0, len(tiles), per):
        group = tiles[s:s + per]
        tw, th = group[0].size
        rows = (len(group) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * tw + (cols + 1) * gap, rows * th + (rows + 1) * gap), (40, 40, 40))
        for i, im in enumerate(group):
            sheet.paste(im, (gap + (i % cols) * (tw + gap), gap + (i // cols) * (th + gap)))
        path = os.path.join(a.work, f"sheet-{s // per + 1}.jpg")
        sheet.save(path, quality=86)
        sheets.append(path)
    cat = catalog(a.memes)
    with open(os.path.join(a.work, "catalog.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write(catalog_text(cat))
    write_json(os.path.join(a.work, "info.json"), {"clip": os.path.abspath(a.clip), "duration": dur, "width": info["width"], "height": info["height"],
                                                   "audio": info["audio"], "frame_times": times, "sheets": sheets})
    say(f"{len(tiles)} frames of {dur:.1f} s on {len(sheets)} sheets:")
    for s in sheets:
        say(f"  {os.path.normpath(s)}")
    say(f"the sounds and memes you can use: {os.path.normpath(os.path.join(a.work, 'catalog.txt'))}")
    if not os.path.isfile(os.path.join(a.work, "words.json")):
        say("no words.json yet: run scripts/words.py for the words said in the clip (optional, needs faster-whisper)")
    return 0


# ---------------------------------------------------------------- the plan

def src_to_out(segs: list, t: float, late: bool = False) -> float | None:
    hit = None
    for s in segs:
        if s["kind"] == "main" and s["a"] - 1e-6 <= t <= s["b"] + 1e-6:
            hit = s["out"] + (t - s["a"])
            if not late:
                return round(hit, 3)
    return None if hit is None else round(hit, 3)


def out_to_src(segs: list, ot: float) -> tuple[dict, float] | None:
    for s in segs:
        if s["out"] - 1e-6 <= ot < s["out"] + s["dur"]:
            k = ot - s["out"]
            if s["kind"] in ("main", "hook"):
                return s, s["a"] + k
            if s["kind"] == "replay":
                return s, s["a"] + k * 0.5
            if s["kind"] == "freeze":
                return s, s["t"]
            return None
    return None


def arrow_starts(segs: list, p: dict) -> list:
    out = []
    for kind in ("hook", "main"):
        for s in segs:
            if s["kind"] != kind:
                continue
            a, b = max(p["from"], s["a"]), min(p["to"], s["b"])
            if b - a >= 0.3:
                out.append(round(s["out"] + a - s["a"], 3))
                break
    return out


def build_plan(ed: dict, info: dict, cat: list, words: list, mn: float, mx: float) -> tuple[dict | None, list, list]:
    errors, notes = [], []
    dur = float(info["duration"])
    fr = make_frame(info, ed.get("layout") or {})
    st, en = fnum(ed.get("start_s")), fnum(ed.get("end_s"))
    if st is None or en is None or not (0 <= st < en <= dur + 0.05):
        return None, [f"start_s and end_s must be inside the clip (0 to {dur:.1f} s) with start before end"], notes
    en = min(en, dur)
    hf, ht = fnum(ed.get("hook_from_s")), fnum(ed.get("hook_to_s"))
    if hf is None or ht is None or not (st - 0.05 <= hf < ht <= en + 0.05):
        errors.append("hook_from_s and hook_to_s must be inside the main window (start_s to end_s), from before to")
    elif not 2.0 <= ht - hf <= 5.0:
        errors.append(f"the cold open hook_from_s to hook_to_s is {ht - hf:.1f} s: make it 2.5 to 4.5 s of the peak")
    hook_text = clean(ed.get("hook_text")).upper()
    if not 2 <= len(hook_text.split()) <= 8 or len(hook_text) > 48:
        errors.append(f"hook_text must be 2 to 7 words and at most 48 characters (got {len(hook_text.split())} words, {len(hook_text)} characters)")
    hook_line = clean(ed.get("hook_line"))
    if not 3 <= len(hook_line.split()) <= 18:
        errors.append(f"hook_line must be 3 to 18 words (got {len(hook_line.split())})")
    wrong = clean(ed.get("wrong_name"))
    if wrong and wrong.lower() not in hook_line.lower():
        errors.append(f"wrong_name is \"{wrong}\": the hook_line must say it (\"When {wrong} was playing GTA 6\")")
    narr = []
    for v in ed.get("narration") or []:
        t, text = fnum((v or {}).get("at_s")), clean((v or {}).get("text"))
        if t is None or not text:
            continue
        n = len(text.split())
        if not 2 <= n <= 22:
            notes.append(f"narration line of {n} words left out: {text[:40]!r}")
            continue
        if not st - 0.6 <= t <= en - 0.5:
            notes.append(f"narration line at {t:.1f} s is outside the main window, left out")
            continue
        narr.append({"src_t": round(max(st, t), 3), "text": text})
    narr.sort(key=lambda v: v["src_t"])
    if len(narr) < 3:
        errors.append(f"narration has {len(narr)} usable lines inside the main window: write 6 to 12 lines of 4 to 16 words")
    pointers = []
    for p in ed.get("pointers") or []:
        a0, b0, label = fnum((p or {}).get("from_s")), fnum((p or {}).get("to_s")), clean((p or {}).get("label")).upper()
        keys = []
        for k in (p or {}).get("track") or []:
            try:
                t, x, y = float(k[0]), float(k[1]), float(k[2])
            except (TypeError, ValueError, IndexError):
                continue
            if 0 <= x <= 100 and 0 <= y <= 100 and to_out(fr, x, y):
                keys.append([round(t, 3), round(x, 2), round(y, 2)])
        if a0 is None or b0 is None or b0 <= a0 or not keys:
            notes.append(f"arrow {label!r} left out: no valid time span or no point inside the short's picture")
            continue
        if b0 - a0 < 0.8:
            b0 = a0 + 0.8
        pointers.append({"from": round(a0, 3), "to": round(min(b0, a0 + 6.0), 3), "label": " ".join(label.split()[:4])[:24], "keys": sorted(keys)})
    if (ed.get("pointers") or []) and not pointers:
        errors.append("every arrow was invalid: each needs from_s < to_s and a track of [time, x, y] (percent of the frame) inside the visible picture")
    memes = []
    for m in (ed.get("memes") or [])[:5]:
        mid, t = str((m or {}).get("meme") or ""), fnum((m or {}).get("at_s"))
        c = find(cat, mid)
        if not c or c["kind"] != "video" or t is None:
            errors.append(f"meme {mid!r} is not a video meme of the catalog (see catalog.txt)")
            continue
        memes.append({"src_t": t, "id": mid, "mode": "insert" if (m or {}).get("mode") == "insert" else "corner", "file": c["file"], "dur": c["dur"]})
    for m in [m for m in memes if m["mode"] == "insert"][2:]:
        m["mode"] = "corner"
    sfx = []
    for s in (ed.get("sfx") or [])[:14]:
        sid, t = str((s or {}).get("sfx") or ""), fnum((s or {}).get("at_s"))
        c = find(cat, sid)
        if not c or c["kind"] != "sfx" or t is None:
            errors.append(f"sound {sid!r} is not in the catalog (see catalog.txt)")
            continue
        sfx.append({"src_t": t, "id": sid, "file": c["file"], "dur": c["dur"]})
    freezes = []
    for f in (ed.get("freezes") or [])[:2]:
        t, s, x, y = (fnum((f or {}).get(k)) for k in ("at_s", "seconds", "x", "y"))
        if t is None or not st + 0.3 <= t <= en - 0.3:
            notes.append("a freeze outside the main window was left out")
            continue
        pos = to_out(fr, x, y) if x is not None and y is not None and 0 <= x <= 100 and 0 <= y <= 100 else None
        freezes.append({"src_t": round(t, 3), "dur": round(min(max(s or 1.0, 0.6), 1.6), 3), "zoom": [round(pos[0]), round(pos[1])] if pos else None})
    if errors:
        return None, errors, notes

    ins = [{"kind": "meme", "at": m["src_t"], "id": m["id"], "file": m["file"], "dur": round(min(m["dur"], DEF["insert_max_s"]), 3)}
           for m in memes if m["mode"] == "insert"]
    ins += [{"kind": "freeze", "at": f["src_t"], "dur": f["dur"], "zoom": f["zoom"]} for f in freezes]
    hook = round(ht - hf, 3)
    rew = round(max(0.6, hook / DEF["rewind_speed"]), 3)
    total = lambda: hook + rew + (en - st) + sum(i["dur"] for i in ins if st + 0.3 <= i["at"] <= en - 0.3)
    if total() < mn:
        need = mn + 0.3 - total()
        g = min(dur - en, need)
        en, need = en + g, need - g
        if need > 0:
            g = min(st, need)
            st, need = st - g, need - g
        if g > 0:
            notes.append(f"the main window was widened to {st:.1f} to {en:.1f} s to reach {mn:g} s")
        while total() < mn - 0.05:
            ins.append({"kind": "replay", "at": min(ht, en - 0.4), "a": hf, "b": ht, "dur": round(hook * 2, 3)})
            notes.append("a slow replay of the peak was added (the clip is too short for --min-seconds)")
            if sum(1 for i in ins if i["kind"] == "replay") >= 2:
                break
    if total() > mx:
        en = max(ht + 2.0, en - (total() - mx))
        notes.append(f"the main window was cut to end at {en:.1f} s to stay under {mx:g} s")
    ins = sorted([i for i in ins if st + 0.3 <= i["at"] <= en - 0.3], key=lambda i: (i["at"], i["kind"] != "replay"))
    segs = [{"kind": "hook", "a": round(hf, 3), "b": round(ht, 3), "dur": hook}, {"kind": "rewind", "a": round(hf, 3), "b": round(ht, 3), "dur": rew}]
    cur = st
    for i in ins:
        t = min(max(i["at"], cur), en)
        if t - cur >= 0.08:
            segs.append({"kind": "main", "a": round(cur, 3), "b": round(t, 3), "dur": round(t - cur, 3)})
        seg = {k: v for k, v in i.items() if k != "at"}
        if i["kind"] == "freeze":
            seg["t"] = round(t, 3)
        segs.append(seg)
        cur = t
    if en - cur >= 0.08:
        segs.append({"kind": "main", "a": round(cur, 3), "b": round(en, 3), "dur": round(en - cur, 3)})
    o = 0.0
    for s in segs:
        s["out"] = round(o, 3)
        o += s["dur"]
    total_s = round(o, 3)

    lines = [{"t": 0.12, "text": hook_line, "hook": True}]
    for v in narr:
        t = src_to_out(segs, v["src_t"], late=True)
        if t is None:
            notes.append(f"narration line at {v['src_t']:.1f} s is outside the final window, left out")
            continue
        lines.append({"t": t, "text": v["text"]})
    corners = []
    for m in memes:
        if m["mode"] == "corner":
            t = src_to_out(segs, m["src_t"])
            if t is not None and t < total_s - 0.8:
                corners.append({"t": t, "id": m["id"], "file": m["file"], "dur": round(min(m["dur"], 4.0, total_s - t), 3)})
    sounds = []
    for s in sfx:
        t = src_to_out(segs, s["src_t"])
        if t is not None and t < total_s - 0.2:
            sounds.append({"t": t, "id": s["id"], "file": s["file"], "dur": s["dur"], "gain": DEF["sfx_gain"]})
    ag = DEF["auto_gain"]
    ding, whoosh, boom, scratch = find(cat, "ding"), find(cat, "whoosh"), find(cat, "boom"), find(cat, "scratch")
    sounds.append({"t": segs[1]["out"], "id": "scratch", "file": scratch["file"], "dur": scratch["dur"], "gain": ag, "auto": "rewind"})
    for s in segs:
        if s["kind"] == "meme":
            sounds.append({"t": max(0.0, s["out"] - 0.3), "id": "whoosh", "file": whoosh["file"], "dur": whoosh["dur"], "gain": ag, "auto": "meme"})
        if s["kind"] == "freeze":
            sounds.append({"t": s["out"], "id": "boom", "file": boom["file"], "dur": boom["dur"], "gain": ag, "auto": "freeze"})
    for p in pointers:
        for t in arrow_starts(segs, p):
            sounds.append({"t": t, "id": "ding", "file": ding["file"], "dur": ding["dur"], "gain": ag, "auto": "arrow"})
    sounds.sort(key=lambda s: s["t"])
    caps = []
    ranges = [r for r in (ed.get("captions") or []) if isinstance(r, (list, tuple)) and len(r) == 2]
    for w in words:
        if not any(float(r[0]) - 0.05 <= w["start"] and w["end"] <= float(r[1]) + 0.05 for r in ranges):
            continue
        o1, o2 = src_to_out(segs, w["start"]), src_to_out(segs, w["end"])
        if o1 is not None and o2 is not None and 0 <= o2 - o1 < 3:
            caps.append({"w": w["w"], "start": o1, "end": o2})
    plan = {"total_s": total_s, "frame": fr, "window": [round(st, 3), round(en, 3)], "hook": [round(hf, 3), round(ht, 3)], "hook_text": hook_text,
            "hook_line": hook_line, "segments": segs, "narration": lines, "pointers": pointers, "corners": corners, "sfx": sounds, "captions": caps,
            "title": clean(ed.get("title")), "summary": clean(ed.get("summary")), "wrong_name": wrong or None}
    return plan, [], notes


def load(a) -> tuple[dict, dict, list, list]:
    info = probe(a.clip)
    if not info["width"]:
        raise SystemExit(f"{a.clip} has no video stream")
    try:
        ed = json.load(open(a.edit, encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"cannot read {a.edit}: {exc}")
    cat = catalog(a.memes)
    words = []
    wpath = getattr(a, "words", "") or (os.path.join(a.work, "words.json") if getattr(a, "work", "") else "")
    if wpath and os.path.isfile(wpath):
        words = json.load(open(wpath, encoding="utf-8")).get("words") or []
    return info, ed, cat, words


def summary_lines(plan: dict, notes: list) -> list:
    out = [f"the short: {plan['total_s']:.1f} s ({plan['frame']['layout']} layout), main window {plan['window'][0]:.1f} to {plan['window'][1]:.1f} s, "
           f"cold open {plan['hook'][0]:.1f} to {plan['hook'][1]:.1f} s"]
    for s in plan["segments"]:
        extra = f" {s['a']:.1f}-{s['b']:.1f} s of the clip" if "a" in s else (f" {s.get('id')}" if s["kind"] == "meme" else "")
        out.append(f"  {s['out']:5.1f} s  {s['kind']:<7}{extra} ({s['dur']:.1f} s)")
    out.append(f"{len(plan['narration'])} narrator lines, {len(plan['pointers'])} arrows, {len(plan['corners'])} corner memes, {len(plan['sfx'])} sounds, "
               f"{len(plan['captions'])} caption words")
    out += [f"note: {n}" for n in notes]
    return out


def cmd_check(a) -> int:
    need_tools()
    info, ed, cat, words = load(a)
    plan, errors, notes = build_plan(ed, info, cat, words, a.min_seconds, a.max_seconds)
    if errors:
        say("edit.json has problems:")
        for e in errors:
            say(f"  - {e}")
        return 1
    for line in summary_lines(plan, notes):
        say(line)
    if a.work:
        path = layout_preview(a.clip, plan, a.work)
        say(f"layout preview (the cold open's frame, then every point of every arrow as a red dot on its own frame): {os.path.normpath(path)}")
    return 0


def layout_preview(clip: str, plan: dict, work: str) -> str:
    """The vertical layout at the cold open, then one tile per arrow point (up to 15): its frame with a red dot where the tip goes."""
    from PIL import Image, ImageDraw, ImageFont
    os.makedirs(work, exist_ok=True)
    fr = plan["frame"]
    shots = [(plan["hook"][0] + 0.5, "cold open", None)]
    for p in plan["pointers"]:
        for t, x, y in p["keys"]:
            shots.append((t, p["label"], (x, y)))
    shots = shots[:16]
    try:
        font = ImageFont.truetype(os.path.join(FONTS, "Anton-Regular.ttf"), 26)
    except OSError:
        font = ImageFont.load_default()
    tiles = []
    for i, (t, label, pt) in enumerate(shots):
        tmp = os.path.join(work, f"layout-{i}.png")
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-nostdin", "-ss", f"{max(0.0, t):.3f}", "-i", clip,
             "-filter_complex", layout_chain(0, 0, fr) + ";[L0]format=rgb24[v]", "-map", "[v]", "-frames:v", "1", tmp])
        im = Image.open(tmp).convert("RGB")
        os.remove(tmp)
        d = ImageDraw.Draw(im)
        if pt:
            pos = to_out(fr, *pt)
            if pos:
                d.ellipse([pos[0] - 18, pos[1] - 18, pos[0] + 18, pos[1] + 18], fill=(255, 0, 0), outline=(255, 255, 255), width=4)
        im = im.resize((270, 480))
        d = ImageDraw.Draw(im)
        d.rectangle([0, 0, 270, 34], fill=(0, 0, 0))
        d.text((6, 2), f"{t:.1f} s {label}"[:24], font=font, fill=(255, 220, 0))
        tiles.append(im)
    cols = min(4, len(tiles))
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 270 + (cols + 1) * 6, rows * 480 + (rows + 1) * 6), (30, 30, 30))
    for i, im in enumerate(tiles):
        sheet.paste(im, (6 + (i % cols) * 276, 6 + (i // cols) * 486))
    path = os.path.join(work, "layout.jpg")
    sheet.save(path, quality=88)
    return path


# ---------------------------------------------------------------- render

def synth(lines: list, out: str, a) -> list:
    """Kokoro reads every line (one WAV each). --voice none: no audio, the lines show as text for as long as they would take to say."""
    if a.voice == "none":
        return [{**ln, "wav": None, "dur": round(max(1.2, len(ln["text"].split()) / 2.8), 3)} for ln in lines]
    vdir = os.path.join(out, "voice")
    shutil.rmtree(vdir, ignore_errors=True)
    os.makedirs(vdir)
    py = a.python or sys.executable
    job = {"voice": a.voice, "speed": a.speed, "lang": "a",
           "lines": [{"id": f"n{i + 1}", "text": re.sub(r"\bxQc\b", "X Q C", ln["text"]), "wav": os.path.join(vdir, f"n{i + 1}.wav")} for i, ln in enumerate(lines)]}
    write_json(os.path.join(vdir, "job.json"), job)
    res = run([py, os.path.join(HERE, "tts_kokoro.py"), os.path.join(vdir, "job.json")], timeout=1800, check=False)
    if res.returncode != 0:
        tail = (res.stderr or res.stdout)[-500:]
        hint = " (kokoro is missing: python -m pip install kokoro soundfile, or point --python at the interpreter that has it)" if "kokoro" in tail.lower() else ""
        raise SystemExit(f"the voice failed{hint}: {tail}")
    done = []
    for i, ln in enumerate(lines):
        wav = os.path.join(vdir, f"n{i + 1}.wav")
        if os.path.isfile(wav):
            done.append({**ln, "wav": wav, "dur": round(probe(wav)["duration"], 3)})
        else:
            say(f"warning: the line {ln['text'][:40]!r} has no audio, left out")
    return done


def place_lines(voiced: list, segs: list, total: float) -> list:
    memes = [(s["out"], s["out"] + s["dur"]) for s in segs if s["kind"] == "meme"]
    rew = [(s["out"], s["out"] + s["dur"]) for s in segs if s["kind"] == "rewind"]
    out, at = [], 0.0
    for v in sorted(voiced, key=lambda x: (not x.get("hook"), x["t"])):
        t = max(v["t"], at)
        blocked = memes + ([] if v.get("hook") else rew)
        moved = True
        while moved:
            moved = False
            for x, y in blocked:
                if t < y - 0.01 and t + v["dur"] > x + 0.01:
                    t, moved = y + 0.05, True
        if t + v["dur"] > total - 0.1:
            say(f"warning: the line {v['text'][:40]!r} does not fit before the end, left out")
            continue
        out.append({**v, "t": round(t, 3)})
        at = t + v["dur"] + 0.15
    return out


def ass_time(t: float) -> str:
    cs = int(round(max(0.0, t) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def ass_text(t: str) -> str:
    return re.sub(r"[{}\\]", "", t)


def wrap(text: str, width: int) -> str:
    lines, cur = [], ""
    for word in text.split():
        if cur and len(cur) + 1 + len(word) > width:
            lines.append(cur)
            cur = word
        else:
            cur = (cur + " " + word).strip()
    if cur:
        lines.append(cur)
    return "\\N".join(lines)


def word_groups(text: str, a: float, dur: float) -> list:
    words = text.split()
    weights = [len(w) + 2 for w in words]
    tot = float(sum(weights)) or 1.0
    t, timed = a, []
    for w, k in zip(words, weights):
        d = dur * k / tot
        timed.append((w, t, t + d))
        t += d
    groups, cur = [], []
    for item in timed:
        if cur and (len(cur) >= 3 or len(" ".join(x[0] for x in cur + [item])) > 16 or re.search(r"[.?!,]$", cur[-1][0])):
            groups.append(cur)
            cur = []
        cur.append(item)
    if cur:
        groups.append(cur)
    return [(" ".join(x[0] for x in g), g[0][1], g[-1][2]) for g in groups]


def zoom_xy(seg: dict) -> tuple[int, int]:
    Z = DEF["freeze_zoom"]
    zx, zy = seg.get("zoom") or [W / 2, H / 2]
    return int(min(max(zx * Z - W / 2, 0), W * Z - W)), int(min(max(zy * Z - H / 2, 0), H * Z - H))


def interp(keys: list, t: float) -> tuple[float, float]:
    if t <= keys[0][0]:
        return keys[0][1], keys[0][2]
    for (t0, x0, y0), (t1, x1, y1) in zip(keys, keys[1:]):
        if t0 <= t <= t1:
            k = (t - t0) / (t1 - t0) if t1 > t0 else 0
            k = k * k * (3 - 2 * k)
            return x0 + (x1 - x0) * k, y0 + (y1 - y0) * k
    return keys[-1][1], keys[-1][2]


def arrow_events(plan: dict, track: list) -> list:
    """Every arrow in 0.1 s steps (each ends where the next starts): the tip on the tracked point, bobbing, the label beside it; hidden in an
    inserted meme and the rewind; from below when the point is too high for the arrow and its label above it."""
    segs, fr, Z = plan["segments"], plan["frame"], DEF["freeze_zoom"]
    ev = []
    for p in plan["pointers"]:
        keys = p["keys"] if len(p["keys"]) > 1 else [[p["from"], p["keys"][0][1], p["keys"][0][2]], [p["to"], p["keys"][0][1], p["keys"][0][2]]]
        ys = [pos[1] for pos in (to_out(fr, k[1], k[2]) for k in keys) if pos]
        direction = "up" if ys and min(ys) < 400 and max(ys) <= H - 420 else "down"
        first, ot, step = True, 0.0, 0.1
        while ot < plan["total_s"]:
            hit = out_to_src(segs, ot)
            if hit is None or not p["from"] - 1e-6 <= hit[1] <= p["to"] + 1e-6:
                first = True
                ot = round(ot + step, 3)
                continue
            seg, ts = hit
            pos = to_out(fr, *interp(keys, ts))
            if pos is None:
                ot = round(ot + step, 3)
                continue
            px, py = pos
            if seg["kind"] == "freeze":
                X, Y = zoom_xy(seg)
                px, py = px * Z - X, py * Z - Y
            bob = 12 * math.sin(2 * math.pi * ot / 0.7)
            px = min(max(px, 70), W - 70)
            pop = "\\fscx20\\fscy20\\t(0,140,\\fscx100\\fscy100)" if first else ""
            a, b = ass_time(ot), ass_time(ot + step)
            half = max(60, len(p["label"]) * 17)
            if direction == "down":
                tip = py - 14 - abs(bob)
                ev.append(f"Dialogue: 6,{a},{b},Arrow,,0,0,0,,{{\\an2\\pos({px:.0f},{tip:.0f}){pop}\\p1}}{DOWN}{{\\p0}}")
                ev.append(f"Dialogue: 7,{a},{b},Label,,0,0,0,,{{\\an2\\pos({px:.0f},{tip - 212:.0f}){pop}}}{ass_text(p['label'])}")
                track.append((ot, (px - half, tip - 290, px + half, tip)))
            else:
                tip = py + 14 + abs(bob)
                ev.append(f"Dialogue: 6,{a},{b},Arrow,,0,0,0,,{{\\an8\\pos({px:.0f},{tip:.0f}){pop}\\p1}}{UP}{{\\p0}}")
                ev.append(f"Dialogue: 7,{a},{b},Label,,0,0,0,,{{\\an8\\pos({px:.0f},{tip + 212:.0f}){pop}}}{ass_text(p['label'])}")
                track.append((ot, (px - half, tip, px + half, tip + 290)))
            first = False
            ot = round(ot + step, 3)
    return ev


def build_ass(plan: dict, placed: list, track: list) -> str:
    fr, ol = plan["frame"], DEF["outline"]
    y_cap = cap_y(fr)
    style = lambda n, f, s, o, sh, al: f"Style: {n},{f},{s},&H00FFFFFF,&H000000FF,&H00000000,&H96000000,0,0,0,0,100,100,0,0,1,{o},{sh},{al},40,40,0,1"
    head = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 2", "ScaledBorderAndShadow: yes", "", "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            style("Cap", DEF["cap_font"], DEF["cap_size"], ol - 1, 3, 5), style("Narr", DEF["narr_font"], DEF["narr_size"], ol, 3, 5),
            style("Hook", DEF["hook_font"], DEF["hook_size"], ol, 3, 8), style("Label", DEF["label_font"], DEF["label_size"], ol - 2, 2, 2),
            style("Arrow", DEF["label_font"], 20, 6, 3, 7), "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    ev = [f"Dialogue: 5,{ass_time(0)},{ass_time(plan['segments'][0]['dur'])},Hook,,0,0,0,,{{\\pos({W // 2},300)\\fscx80\\fscy80\\t(0,120,\\fscx100\\fscy100)}}"
          + wrap(ass_text(plan["hook_text"]), 16)]
    spans = []
    for ln in placed:
        spans.append((ln["t"], ln["t"] + ln["dur"] + 0.1))
        groups = word_groups(ass_text(ln["text"]).upper(), ln["t"] + 0.03, max(0.3, ln["dur"] - 0.05))
        for n, (text, a, b) in enumerate(groups):
            b = groups[n + 1][1] if n + 1 < len(groups) else ln["t"] + ln["dur"] + 0.15
            ev.append(f"Dialogue: 4,{ass_time(a)},{ass_time(b)},Narr,,0,0,0,,{{\\pos({W // 2},{y_cap})\\fscx82\\fscy82\\t(0,90,\\fscx100\\fscy100)}}{text}")
    words = [w for w in plan["captions"] if not any(x - 0.05 < w["end"] and w["start"] < y for x, y in spans)]
    groups, cur = [], []
    for w in words:
        if cur and (len(cur) >= 3 or len(" ".join(x["w"] for x in cur + [w])) > 18 or w["start"] - cur[-1]["end"] > 0.45 or re.search(r"[.?!,]$", cur[-1]["w"])):
            groups.append(cur)
            cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    for n, g in enumerate(groups):
        a = g[0]["start"]
        nxt = groups[n + 1][0]["start"] if n + 1 < len(groups) else plan["total_s"]
        b = min(nxt, g[-1]["end"] + 0.5)
        later = [x for x, y in spans if x > a]
        if later:
            b = min(b, min(later))
        if b - a >= 0.2:
            ev.append(f"Dialogue: 3,{ass_time(a)},{ass_time(b)},Cap,,0,0,0,,{{\\pos({W // 2},{y_cap})\\fscx85\\fscy85\\t(0,80,\\fscx100\\fscy100)}}"
                      + ass_text(" ".join(x["w"] for x in g).upper()))
    for s in plan["segments"]:
        if s["kind"] == "rewind":
            a, b = ass_time(s["out"]), ass_time(s["out"] + s["dur"])
            ev.append(f"Dialogue: 8,{a},{b},Arrow,,0,0,0,,{{\\an9\\pos({W - 60},110)\\p1}}{REWIND_ICON}{{\\p0}}")
            ev.append(f"Dialogue: 8,{a},{b},Label,,0,0,0,,{{\\an9\\pos({W - 60},300)}}REWIND")
    ev += arrow_events(plan, track)
    return "\n".join(head + ev) + "\n"


def corner_sides(corners: list, track: list, fr: dict) -> None:
    cw = DEF["corner_w"]
    y0 = int(fr.get("seam_y") or H * 0.25) + 70
    rects = {"right": (W - cw - 52, y0, W - 36, y0 + int(cw * 0.6) + 16), "left": (36, y0, 52 + cw, y0 + int(cw * 0.6) + 16)}
    hit = lambda r, b: not (b[2] < r[0] or b[0] > r[2] or b[3] < r[1] or b[1] > r[3])
    for c in corners:
        boxes = [b for t, b in track if c["t"] - 0.1 <= t <= c["t"] + c["dur"] + 0.1]
        score = {side: sum(1 for b in boxes if hit(r, b)) for side, r in rects.items()}
        c["side"] = "left" if score["right"] > score["left"] else "right"


def seg_inputs(segs: list, clip: str) -> list:
    ins = []
    for s in segs:
        if s["kind"] in ("hook", "main", "rewind", "replay"):
            ins += ["-ss", f"{s['a']:.3f}", "-t", f"{s['b'] - s['a'] + 0.4:.3f}", "-i", clip]
        elif s["kind"] == "freeze":
            ins += ["-ss", f"{s['t']:.3f}", "-t", "0.5", "-i", clip]
        else:
            ins += ["-i", s["file"]]
    return ins


def video_graph(plan: dict, n_seg: int, corners: list) -> str:
    fr, Z = plan["frame"], DEF["freeze_zoom"]
    parts, labels = [], []
    for k, s in enumerate(plan["segments"]):
        d = s["dur"]
        fix = f"fps={FPS},format=yuv420p,setsar=1,tpad=stop_mode=clone:stop_duration=0.6,trim=0:{d:.3f},setpts=PTS-STARTPTS[v{k}]"
        if s["kind"] == "meme":
            parts.append(f"[{k}:v]trim=0:{d:.3f},setpts=PTS-STARTPTS,fps={FPS},split=2[mb{k}][mf{k}];"
                         f"[mb{k}]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},gblur=sigma=30,eq=brightness=-0.15[mg{k}];"
                         f"[mf{k}]scale={W}:{H}:force_original_aspect_ratio=decrease[mm{k}];[mg{k}][mm{k}]overlay=(W-w)/2:(H-h)/2,{fix}")
        else:
            parts.append(layout_chain(k, k, fr))
            span = s["b"] - s["a"] if "b" in s else 0
            if s["kind"] in ("hook", "main"):
                parts.append(f"[L{k}]trim=0:{d:.3f},setpts=PTS-STARTPTS,{fix}")
            elif s["kind"] == "rewind":
                parts.append(f"[L{k}]trim=0:{span:.3f},setpts=PTS-STARTPTS,reverse,setpts=PTS/{DEF['rewind_speed']:.3f},hue=s=0.45,noise=alls=16:allf=t+u,{fix}")
            elif s["kind"] == "replay":
                parts.append(f"[L{k}]trim=0:{span:.3f},setpts=(PTS-STARTPTS)*2,{fix}")
            elif s["kind"] == "freeze":
                X, Y = zoom_xy(s)
                parts.append(f"[L{k}]trim=end_frame=1,setpts=PTS-STARTPTS,scale={round(W * Z)}:{round(H * Z)}:flags=lanczos,crop={W}:{H}:{X}:{Y},"
                             f"tpad=stop_mode=clone:stop_duration={d + 0.2:.3f},{fix}")
        labels.append(f"[v{k}]")
    parts.append(f"{''.join(labels)}concat=n={len(labels)}:v=1:a=0[cat]")
    cur, cw = "cat", DEF["corner_w"]
    y = int(fr.get("seam_y") or H * 0.25) + 70
    for j, c in enumerate(corners):
        t, dd = c["t"], c["dur"]
        x = 36 if c.get("side") == "left" else W - cw - 16 - 36
        parts.append(f"[{n_seg + j}:v]trim=0:{dd:.3f},setpts=PTS-STARTPTS,fps={FPS},scale={cw}:-2,pad=iw+16:ih+16:8:8:white,setsar=1,"
                     f"tpad=start_duration={t:.3f}:start_mode=add:color=black[cm{j}]")
        parts.append(f"[{cur}][cm{j}]overlay={x}:{y}:enable='between(t,{t:.3f},{t + dd:.3f})':eof_action=pass[o{j}]")
        cur = f"o{j}"
    parts.append(f"[{cur}]subtitles=filename=short.ass:fontsdir=fonts,format=yuv420p[v]")
    return ";".join(parts)


def level(i: int, target: float = -18.0) -> str:
    return f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo,loudnorm=I={target}:TP=-2:LRA=9,aresample=48000"


def has_audio(path: str) -> bool:
    try:
        return bool(probe(path)["audio"])
    except SystemExit:
        return False


def atempo_chain(speed: float) -> str:
    parts, s = [], speed
    while s > 2.0:
        parts.append("atempo=2")
        s /= 2.0
    parts.append(f"atempo={s:.4f}")
    return ",".join(parts)


def build_mix(plan: dict, placed: list, corners: list, clip: str, clip_audio: bool, out: str, clip_volume: float = 1.0) -> str:
    """Two tracks in the short's time: the clip's own sound (normalized, then --clip-volume, turned down under the narrator and the corner
    memes) and the inserted memes' sound; then the corner memes, the sounds and the narrator on top."""
    segs, total = plan["segments"], plan["total_s"]
    ins = seg_inputs(segs, clip)
    clip_audio = clip_audio and clip_volume > 0
    parts, pieces, mpieces = [], [], []
    for k, s in enumerate(segs):
        d = s["dur"]
        pad = lambda lab: f"apad=whole_dur={d:.3f},atrim=0:{d:.3f},asetpts=PTS-STARTPTS[{lab}{k}]"
        base = f"[{k}:a]aresample=48000,aformat=channel_layouts=stereo"
        silent = lambda lab: f"anullsrc=r=48000:cl=stereo,atrim=0:{d:.3f},asetpts=PTS-STARTPTS[{lab}{k}]"
        if s["kind"] in ("hook", "main") and clip_audio:
            parts.append(f"{base},atrim=0:{d:.3f},asetpts=PTS-STARTPTS,{pad('p')}")
        elif s["kind"] == "rewind" and clip_audio:
            parts.append(f"{base},atrim=0:{s['b'] - s['a']:.3f},asetpts=PTS-STARTPTS,areverse,{atempo_chain(DEF['rewind_speed'])},{pad('p')}")
        elif s["kind"] == "replay" and clip_audio:
            parts.append(f"{base},atrim=0:{s['b'] - s['a']:.3f},asetpts=PTS-STARTPTS,asetrate=24000,aresample=48000,{pad('p')}")
        else:
            parts.append(silent("p"))
        if s["kind"] == "meme" and has_audio(s["file"]):
            parts.append(f"{level(k)},atrim=0:{d:.3f},asetpts=PTS-STARTPTS,afade=t=out:st={max(0.0, d - 0.2):.3f}:d=0.2,volume={DEF['meme_gain']},{pad('q')}")
        else:
            parts.append(silent("q"))
        pieces.append(f"[p{k}]")
        mpieces.append(f"[q{k}]")
    spans = [(ln["t"], ln["t"] + ln["dur"], DEF["duck_voice"]) for ln in placed if ln.get("wav")] + [(c["t"], c["t"] + c["dur"], DEF["duck_corner"]) for c in corners]
    duck = "*".join(f"if(between(t,{x:.3f},{y:.3f}),{f},1)" for x, y, f in spans) or "1"
    norm = ",loudnorm=I=-18:TP=-2:LRA=9,aresample=48000" if clip_audio else ""
    parts.append(f"{''.join(pieces)}concat=n={len(pieces)}:v=0:a=1{norm},volume={min(max(clip_volume, 0.0), 1.0):.3f},volume='{duck}':eval=frame[st]")
    parts.append(f"{''.join(mpieces)}concat=n={len(mpieces)}:v=0:a=1[mt]")
    labels, k = ["[st]", "[mt]"], len(segs)
    for j, c in enumerate(corners):
        ins += ["-i", c["file"]]
        if has_audio(c["file"]):
            ms = int(c["t"] * 1000)
            parts.append(f"{level(k)},atrim=0:{c['dur']:.3f},asetpts=PTS-STARTPTS,afade=t=out:st={max(0.0, c['dur'] - 0.2):.3f}:d=0.2,"
                         f"adelay={ms}|{ms},volume={DEF['meme_gain'] * 0.8:.3f}[c{j}]")
            labels.append(f"[c{j}]")
        k += 1
    for j, s in enumerate(plan["sfx"]):
        ins += ["-i", s["file"]]
        ms = int(s["t"] * 1000)
        parts.append(f"[{k}:a]aresample=48000,aformat=channel_layouts=stereo,adelay={ms}|{ms},volume={s.get('gain', 0.8)}[x{j}]")
        labels.append(f"[x{j}]")
        k += 1
    for j, ln in enumerate([ln for ln in placed if ln.get("wav")]):
        ins += ["-i", ln["wav"]]
        ms = int(ln["t"] * 1000)
        parts.append(f"{level(k, -16.0)},adelay={ms}|{ms},volume={DEF['voice_gain']}[n{j}]")
        labels.append(f"[n{j}]")
        k += 1
    graph = ";".join(parts) + f";{''.join(labels)}amix=inputs={len(labels)}:duration=first:normalize=0,alimiter=limit=0.95,atrim=0:{total:.3f}[mix]"
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-nostdin", *ins, "-filter_complex", graph, "-map", "[mix]",
         "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", os.path.join(out, "mix.wav")])
    return os.path.join(out, "mix.wav")


def loud_measure(path: str) -> dict:
    res = run(["ffmpeg", "-hide_banner", "-nostdin", "-i", path, "-vn", "-af", f"loudnorm=I={DEF['lufs']}:TP={DEF['true_peak']}:LRA=11:print_format=json",
               "-f", "null", "-"], check=False)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", res.stderr or "", re.S)
    return json.loads(m.group(0)) if m else {}


def integrated(path: str) -> float | None:
    res = run(["ffmpeg", "-hide_banner", "-nostdin", "-i", path, "-vn", "-af", "ebur128", "-f", "null", "-"], check=False)
    m = re.findall(r"I:\s+(-?\d+(?:\.\d+)?) LUFS", res.stderr or "")
    return float(m[-1]) if m else None


def key_sheet(plan: dict, placed: list, final: str, out: str) -> str:
    """Frames of the key moments (each segment, the first lines, every arrow, the corner memes) on one image, to check the edit."""
    from PIL import Image, ImageDraw, ImageFont
    segs, times = plan["segments"], []
    for s in segs:
        times.append((s["out"] + min(0.6, s["dur"] / 2), s["kind"]))
    for ln in placed[:4]:
        times.append((ln["t"] + ln["dur"] / 2, "line"))
    for p in plan["pointers"]:
        for t in arrow_starts(segs, p)[-1:]:
            times.append((t + 0.5, "arrow " + p["label"]))
    for c in plan["corners"][:2]:
        times.append((c["t"] + 0.6, "corner meme"))
    times = sorted({round(t, 2): k for t, k in times if t < plan["total_s"] - 0.05}.items())[:20]
    try:
        font = ImageFont.truetype(os.path.join(FONTS, "Anton-Regular.ttf"), 22)
    except OSError:
        font = ImageFont.load_default()
    tiles, kdir = [], os.path.join(out, "keys")
    os.makedirs(kdir, exist_ok=True)
    for i, (t, k) in enumerate(times):
        f = os.path.join(kdir, f"k{i:02d}.png")
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{t:.2f}", "-i", final, "-frames:v", "1", "-vf", "scale=270:-2", f])
        im = Image.open(f).convert("RGB")
        d = ImageDraw.Draw(im)
        d.rectangle([0, 0, 270, 30], fill=(0, 0, 0))
        d.text((5, 2), f"{t:.1f} s {k}"[:28], font=font, fill=(255, 220, 0))
        tiles.append(im)
    shutil.rmtree(kdir, ignore_errors=True)
    cols = 5
    rows = (len(tiles) + cols - 1) // cols
    w, h = tiles[0].size
    sheet = Image.new("RGB", (cols * w + (cols + 1) * 6, rows * h + (rows + 1) * 6), (30, 30, 30))
    for i, im in enumerate(tiles):
        sheet.paste(im, (6 + (i % cols) * (w + 6), 6 + (i // cols) * (h + 6)))
    path = os.path.join(out, "keys.jpg")
    sheet.save(path, quality=88)
    return path


def cmd_render(a) -> int:
    need_tools()
    a.work = ""
    info, ed, cat, words = load(a)
    plan, errors, notes = build_plan(ed, info, cat, words, a.min_seconds, a.max_seconds)
    if errors:
        say("edit.json has problems (run check first):")
        for e in errors:
            say(f"  - {e}")
        return 1
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    fdir = os.path.join(out, "fonts")
    shutil.copytree(FONTS, fdir, dirs_exist_ok=True)
    clip = os.path.abspath(a.clip)
    for line in summary_lines(plan, notes):
        say(line)
    t0 = time.time()
    say("the voice (Kokoro)...")
    placed = place_lines(synth(plan["narration"], out, a), plan["segments"], plan["total_s"])
    corners = [dict(c) for c in plan["corners"]]
    track = []
    with open(os.path.join(out, "short.ass"), "w", encoding="utf-8", newline="\n") as f:
        f.write(build_ass(plan, placed, track))
    corner_sides(corners, track, plan["frame"])
    say("the sound mix...")
    mix = build_mix(plan, placed, corners, clip, info["audio"], out, a.clip_volume)
    say("the video...")
    ins = seg_inputs(plan["segments"], clip)
    for c in corners:
        ins += ["-i", c["file"]]
    graph = video_graph(plan, len(plan["segments"]), corners)
    lm = loud_measure(mix)
    an = (f"loudnorm=I={DEF['lufs']}:TP={DEF['true_peak']}:LRA=11:measured_I={lm['input_i']}:measured_TP={lm['input_tp']}:measured_LRA={lm['input_lra']}:"
          f"measured_thresh={lm['input_thresh']}:offset={lm['target_offset']}:linear=true") if lm else f"loudnorm=I={DEF['lufs']}:TP={DEF['true_peak']}:LRA=11"
    mi = len(plan["segments"]) + len(corners)
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-nostdin", *ins, "-i", mix, "-filter_complex", graph + f";[{mi}:a]{an},aresample=48000[a]",
         "-map", "[v]", "-map", "[a]", "-t", f"{plan['total_s']:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", str(DEF["crf"]), "-pix_fmt", "yuv420p",
         "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", "short.mp4"], cwd=out)
    final = os.path.join(out, "short.mp4")
    p = probe(final)
    lufs = integrated(final)
    keys = key_sheet(plan, placed, final, out)
    plan["placed"] = [{k: x[k] for k in ("t", "text", "dur")} for x in placed]
    plan["corners"] = corners
    write_json(os.path.join(out, "plan.json"), plan)
    say(f"done in {time.time() - t0:.0f} s: {final} ({p['duration']:.1f} s, {p['width']}x{p['height']}, {lufs} LUFS)")
    say(f"look at the key moments before you call it finished: {keys}")
    if plan["title"]:
        say(f"title: {plan['title']}")
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", newline="\n")
    ap = argparse.ArgumentParser(description="Narrated meme shorts from gameplay or stream clips.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("frames", help="sheets of the clip's frames for Claude to watch")
    f.add_argument("clip")
    f.add_argument("work")
    f.add_argument("--memes", default="")
    for name in ("check", "render"):
        sp = sub.add_parser(name)
        sp.add_argument("clip")
        sp.add_argument("edit")
        if name == "render":
            sp.add_argument("out")
            sp.add_argument("--python", default="", help="the interpreter that has kokoro (default: this one)")
            sp.add_argument("--voice", default="am_michael", help="a Kokoro voice (am_michael, am_adam, af_bella, ...) or none for text only")
            sp.add_argument("--speed", type=float, default=1.1)
            sp.add_argument("--words", default="", help="words.json from words.py, for the captions")
            sp.add_argument("--clip-volume", type=float, default=1.0, help="the clip's own sound, 0 (muted, e.g. copyrighted music) to 1")
        else:
            sp.add_argument("--work", default="")
        sp.add_argument("--memes", default="")
        sp.add_argument("--min-seconds", type=float, default=30.0)
        sp.add_argument("--max-seconds", type=float, default=59.0)
    a = ap.parse_args()
    a.memes = a.memes or None
    return {"frames": cmd_frames, "check": cmd_check, "render": cmd_render}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
