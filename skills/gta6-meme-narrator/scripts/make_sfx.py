"""Synthesizes the bundled sound effects (sfx/*.wav and sfx/sfx.json). Every sound is made from sine, square and saw waves and noise in this
file, so they are free to use and share (CC0). Run it again to rebuild them:  python make_sfx.py
Needs numpy."""
import json
import os
import wave

import numpy as np

SR = 48000
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sfx")
rng = np.random.default_rng(7)


def t_of(sec):
    return np.arange(int(SR * sec)) / SR


def env(n, attack=0.005, release=0.05):
    e = np.ones(n)
    a, r = max(1, int(SR * attack)), max(1, int(SR * release))
    e[:a] = np.linspace(0, 1, a)
    e[-r:] *= np.linspace(1, 0, r)
    return e


def lowpass(x, cutoff):
    """One-pole low-pass; cutoff may be an array (a sweep)."""
    cutoff = np.broadcast_to(np.asarray(cutoff, dtype=float), x.shape)
    a = np.exp(-2 * np.pi * cutoff / SR)
    y, prev = np.empty_like(x), 0.0
    for i in range(len(x)):
        prev = (1 - a[i]) * x[i] + a[i] * prev
        y[i] = prev
    return y


def saw(phase):
    return 2 * (phase % 1.0) - 1


def square(phase):
    return np.sign(np.sin(2 * np.pi * phase))


def phase_of(freq):
    return np.cumsum(np.broadcast_to(freq, freq.shape if np.ndim(freq) else (1,))) / SR


def ding():
    t = t_of(1.2)
    f = 1318.5
    x = sum(a * np.sin(2 * np.pi * f * r * t) * np.exp(-t * d) for r, a, d in ((1, 1.0, 3.5), (2.0, 0.45, 5), (2.76, 0.3, 7), (5.4, 0.12, 11)))
    return x * env(len(t), 0.002, 0.1)


def boom():
    t = t_of(1.6)
    f = 45 + 95 * np.exp(-t * 28)
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 2.2)
    x = np.tanh(2.8 * x)
    click = rng.standard_normal(len(t)) * np.exp(-t * 180) * 0.6
    tail = lowpass(rng.standard_normal(len(t)), 180) * np.exp(-t * 3) * 1.5
    return (x + click + tail) * env(len(t), 0.001, 0.2)


def whoosh():
    t = t_of(1.0)
    sweep = 300 + 5200 * np.sin(np.pi * t / t[-1]) ** 2
    x = lowpass(rng.standard_normal(len(t)), sweep)
    x -= lowpass(x, 150)
    return x * np.sin(np.pi * t / t[-1]) ** 1.5


def scratch():
    t = t_of(0.65)
    speed = np.abs(np.sin(2 * np.pi * 3.2 * t)) * 1.6 + 0.1
    x = saw(np.cumsum(180 * speed) / SR) * 0.5 + rng.standard_normal(len(t)) * 0.5
    x = lowpass(x, 600 + 3500 * speed)
    return x * env(len(t), 0.003, 0.08)


def pop():
    t = t_of(0.16)
    f = 220 + 700 * np.exp(-t * 60)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 35)


def buzzer():
    t = t_of(0.75)
    x = 0.5 * square(150 * t) + 0.5 * square(156 * t)
    return lowpass(x, 2500) * env(len(t), 0.005, 0.06)


def boing():
    t = t_of(0.9)
    f = 210 * (1 + 0.35 * np.sin(2 * np.pi * 11 * t) * np.exp(-t * 3)) * (1 + 0.6 * np.exp(-t * 8))
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 4) * env(len(t), 0.002, 0.05)


def glitch():
    out = []
    for _ in range(18):
        n = int(SR * rng.uniform(0.018, 0.045))
        tt = np.arange(n) / SR
        kind = rng.integers(3)
        if kind == 0:
            seg = square(rng.uniform(200, 2400) * tt)
        elif kind == 1:
            seg = rng.standard_normal(n)
        else:
            seg = np.zeros(n)
        out.append(seg)
    x = np.concatenate(out)
    x = np.round(x * 6) / 6
    hold = 8
    x = np.repeat(x[::hold], hold)[:len(x)]
    return x * env(len(x), 0.001, 0.03) * 0.8


def sad_trombone():
    notes = [(293.7, 0.42), (277.2, 0.42), (261.6, 0.42), (246.9, 1.1)]
    out = []
    for i, (f, d) in enumerate(notes):
        t = t_of(d)
        vib = 1 + (0.012 * np.sin(2 * np.pi * 5.5 * t) if i == 3 else 0)
        x = saw(np.cumsum(f * vib) / SR)
        x = lowpass(x, 1400) * env(len(t), 0.03, 0.08)
        out.append(x)
    return np.concatenate(out)


def airhorn():
    out = []
    for d, gap in ((0.22, 0.08), (0.22, 0.08), (0.75, 0.0)):
        t = t_of(d)
        x = sum(saw(f * t * (1 + 0.004 * np.sin(2 * np.pi * 7 * t))) for f in (466, 470, 698))
        x = np.tanh(1.8 * lowpass(x, 4000)) * env(len(t), 0.01, 0.05)
        out += [x, np.zeros(int(SR * gap))]
    return np.concatenate(out)


def dun_dun():
    out = []
    for f, d in ((98, 0.45), (92.5, 0.45), (87.3, 1.3)):
        t = t_of(d)
        x = sum(saw(ff * t) for ff in (f, f * 1.5, f * 2)) / 3
        x = lowpass(np.tanh(1.5 * x), 900) * np.exp(-t * (1.2 if d > 1 else 2.5)) * env(len(t), 0.01, 0.1)
        out.append(x)
    return np.concatenate(out)


SOUNDS = [
    ("ding", ding, ["ding", "point", "correct", "reveal"], "a bright bell ding (the arrows use it)"),
    ("boom", boom, ["boom", "impact", "punchline", "reaction"], "a deep cinematic boom, the vine boom kind"),
    ("whoosh", whoosh, ["whoosh", "transition", "swipe"], "a whoosh"),
    ("scratch", scratch, ["record scratch", "stop", "wait", "twist", "rewind"], "a record scratch"),
    ("pop", pop, ["pop", "appear", "small"], "a short pop"),
    ("buzzer", buzzer, ["wrong", "fail", "buzzer"], "a wrong-answer buzzer"),
    ("boing", boing, ["boing", "bounce", "silly", "jump"], "a cartoon boing"),
    ("glitch", glitch, ["glitch", "error", "bug", "broken"], "a digital glitch"),
    ("sad-trombone", sad_trombone, ["fail", "sad", "wah wah"], "the sad trombone"),
    ("airhorn", airhorn, ["hype", "win", "airhorn"], "an air horn, three blasts"),
    ("dun-dun", dun_dun, ["dramatic", "reveal", "suspense"], "dun dun duuun"),
]


def write_wav(path, x):
    x = x / (np.max(np.abs(x)) or 1) * 0.89
    pcm = (x * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def main():
    os.makedirs(OUT, exist_ok=True)
    cat = []
    for sid, fn, tags, desc in SOUNDS:
        x = fn()
        write_wav(os.path.join(OUT, sid + ".wav"), x)
        cat.append({"id": sid, "tags": tags, "desc": desc, "seconds": round(len(x) / SR, 2), "file": sid + ".wav"})
    with open(os.path.join(OUT, "sfx.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump({"license": "CC0 (synthesized by scripts/make_sfx.py)", "sounds": cat}, f, indent=1)
    print(f"{len(cat)} sounds in {os.path.normpath(OUT)}")


if __name__ == "__main__":
    main()
