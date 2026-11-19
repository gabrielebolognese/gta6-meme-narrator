"""Reads narrator lines with Kokoro (a free, local text to speech model) and writes one WAV per line.
narrator.py runs it under the interpreter that has kokoro installed (--python):  python tts_kokoro.py job.json
job.json: {"voice": "am_michael", "speed": 1.1, "lang": "a", "lines": [{"id": "n1", "text": "...", "wav": "path/n1.wav"}, ...]}
Install once (Python 3.10 to 3.12):  python -m pip install kokoro soundfile"""
import json
import sys

import numpy as np
import soundfile as sf

SR = 24000


def mono(a):
    a = a.detach().cpu().numpy() if hasattr(a, "detach") else np.asarray(a)
    return a.reshape(-1).astype(np.float32)


def trim(x, db=-40.0, keep=0.06):
    """Cut the silence before and after the speech, keeping a little air."""
    if not len(x):
        return x
    thr = np.max(np.abs(x)) * 10 ** (db / 20)
    idx = np.where(np.abs(x) > thr)[0]
    if not len(idx):
        return x
    k = int(SR * keep)
    return x[max(0, idx[0] - k):min(len(x), idx[-1] + k)]


def main():
    job = json.load(open(sys.argv[1], encoding="utf-8"))
    from kokoro import KPipeline
    pipe = KPipeline(lang_code=job.get("lang", "a"))
    done = []
    for ln in job["lines"]:
        chunks = [mono(audio) for _, _, audio in pipe(ln["text"], voice=job.get("voice", "am_michael"), speed=float(job.get("speed", 1.1)))]
        if not chunks:
            continue
        x = trim(np.concatenate(chunks))
        sf.write(ln["wav"], x, SR)
        done.append(ln["id"])
    print(json.dumps({"ok": True, "lines": done}))


if __name__ == "__main__":
    main()
