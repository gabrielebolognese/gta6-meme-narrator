"""Optional: the words said in the clip with their times (faster-whisper, local), so Claude knows what the streamer says and the short can
caption it.  python words.py CLIP WORK [--model small] [--language en]
Writes WORK/words.json ({"words": [{"i", "w", "start", "end"}]}) and WORK/words.txt (`start-end | (number)word ...`, one line per stretch).
Install once:  python -m pip install faster-whisper"""
import argparse
import json
import os
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clip")
    ap.add_argument("work")
    ap.add_argument("--model", default="small")
    ap.add_argument("--language", default=None)
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", newline="\n")
    from faster_whisper import WhisperModel
    os.makedirs(a.work, exist_ok=True)
    model = WhisperModel(a.model, device="cpu", compute_type="int8")
    segs, info = model.transcribe(a.clip, word_timestamps=True, language=a.language, vad_filter=False)
    words = []
    for s in segs:
        for w in s.words or []:
            text = w.word.strip()
            if text:
                words.append({"i": len(words), "w": text, "start": round(w.start, 3), "end": round(w.end, 3)})
    with open(os.path.join(a.work, "words.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump({"language": info.language, "words": words}, f, ensure_ascii=False, indent=1)
    lines, cur = [], []
    for w in words:
        if cur and (w["start"] - cur[-1]["end"] > 0.6 or len(cur) >= 14):
            lines.append(cur)
            cur = []
        cur.append(w)
    if cur:
        lines.append(cur)
    with open(os.path.join(a.work, "words.txt"), "w", encoding="utf-8", newline="\n") as f:
        for g in lines:
            f.write(f"{g[0]['start']:.1f}-{g[-1]['end']:.1f} | " + " ".join(f"({w['i']}){w['w']}" for w in g) + "\n")
        if not lines:
            f.write("(no speech was heard)\n")
    print(f"{len(words)} words in {os.path.join(a.work, 'words.txt')}")


if __name__ == "__main__":
    main()
