"""The skill's self-test: no footage and no voice model needed. It makes a synthetic 32 s clip with ffmpeg (a moving test pattern and a
tone), writes an edit for it, and runs frames, check and render (--voice none). Takes about a minute.
    python tests/selftest.py [--keep]"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NARRATOR = os.path.join(SKILL, "scripts", "narrator.py")


def run(*args):
    res = subprocess.run([sys.executable, NARRATOR, *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        raise SystemExit(f"FAIL: narrator.py {args[0]}:\n{res.stdout}\n{res.stderr}")
    return res.stdout


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height", "-of", "json", path],
                         capture_output=True, text=True).stdout
    return json.loads(out)


def main():
    tmp = tempfile.mkdtemp(prefix="narrator-test-")
    clip = os.path.join(tmp, "clip.mp4")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=1920x1080:r=30:d=32", "-f", "lavfi",
                    "-i", "sine=f=330:d=32", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", clip], check=True)
    work, out = os.path.join(tmp, "work"), os.path.join(tmp, "out")
    run("frames", clip, work)
    assert os.path.isfile(os.path.join(work, "sheet-1.jpg")), "no frame sheet"
    edit = {
        "layout": {"facecam": None, "focus_x": 50},
        "wrong_name": "Taylor Swift",
        "start_s": 1.0, "end_s": 30.0, "hook_from_s": 14.0, "hook_to_s": 17.0,
        "hook_text": "THE SQUARES ARE PLOTTING", "hook_line": "When Taylor Swift was playing GTA 6 for science",
        "narration": [{"at_s": 2.0, "text": "This colorful gentleman is just stretching before work."},
                      {"at_s": 7.0, "text": "Nobody told him the meeting was cancelled."},
                      {"at_s": 12.0, "text": "And now the squares have unionized."},
                      {"at_s": 19.0, "text": "Ten years of waiting for this exact moment."},
                      {"at_s": 25.0, "text": "Honestly, a flawless performance."}],
        "pointers": [{"from_s": 14.0, "to_s": 17.5, "label": "THE BOSS", "track": [[14.2, 40, 50], [15.2, 45, 52], [16.2, 50, 55], [17.2, 52, 55]]}],
        "memes": [],
        "sfx": [{"at_s": 15.0, "sfx": "boom"}, {"at_s": 20.0, "sfx": "buzzer"}, {"at_s": 26.0, "sfx": "airhorn"}],
        "freezes": [{"at_s": 22.0, "seconds": 1.0, "x": 50, "y": 50}],
        "captions": [], "title": "The test pattern had a rough day", "summary": "A synthetic test clip.",
    }
    ep = os.path.join(tmp, "edit.json")
    json.dump(edit, open(ep, "w", encoding="utf-8"), indent=1)
    text = run("check", clip, ep, "--work", work)
    assert "the short:" in text and os.path.isfile(os.path.join(work, "layout.jpg")), "check gave no timeline or preview"
    bad = dict(edit, hook_line="A line without the wrong name")
    bp = os.path.join(tmp, "bad.json")
    json.dump(bad, open(bp, "w", encoding="utf-8"))
    res = subprocess.run([sys.executable, NARRATOR, "check", clip, bp], capture_output=True, text=True)
    assert res.returncode == 1 and "wrong_name" in res.stdout, "check accepted a hook line without the wrong name"
    run("render", clip, ep, out, "--voice", "none")
    p = probe(os.path.join(out, "short.mp4"))
    v = [s for s in p["streams"] if s["codec_type"] == "video"][0]
    dur = float(p["format"]["duration"])
    assert (v["width"], v["height"]) == (1080, 1920), f"size {v['width']}x{v['height']}"
    assert dur >= 30.0, f"the short is {dur:.1f} s, under --min-seconds 30"
    assert any(s["codec_type"] == "audio" for s in p["streams"]), "no sound"
    assert os.path.isfile(os.path.join(out, "keys.jpg")), "no keys.jpg"
    plan = json.load(open(os.path.join(out, "plan.json"), encoding="utf-8"))
    kinds = [s["kind"] for s in plan["segments"]]
    assert kinds[:2] == ["hook", "rewind"] and "freeze" in kinds, f"segments {kinds}"
    assert any(s.get("auto") == "arrow" for s in plan["sfx"]), "no ding for the arrow"
    print(f"selftest OK: {dur:.1f} s short, segments {kinds}, {len(plan['sfx'])} sounds ({tmp if '--keep' in sys.argv else 'cleaned up'})")
    if "--keep" not in sys.argv:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
