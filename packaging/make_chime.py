"""Makes bchat/assets/sounds/soft.wav and bee.wav: BChat's own pop-up sounds (0.5.0).
bee.wav: a short soft bee passing by (about 0.5 s): a 200-260 Hz buzz with a few harmonics only (no harsh top),
a gentle rise and fall in pitch and loudness, a little wing flutter, same quiet peak.
soft.wav: Drawn here from sine waves, so no licence
question. Two soft bell notes a fifth apart (E6 then B6), quick start, gentle fade, about 0.45 s, quiet (peak -14 dBFS),
mono 44.1 kHz 16-bit. Run: python packaging/make_chime.py"""
import math
import struct
import wave
from pathlib import Path

RATE = 44100
PEAK = 10 ** (-14 / 20)


def bell(freq: float, start: float, length: float, n: int) -> list[float]:
    out = [0.0] * n
    s0 = int(start * RATE)
    for i in range(int(length * RATE)):
        t = i / RATE
        attack = min(1.0, t / 0.006)                       # 6 ms: no click
        decay = math.exp(-t * 7.5)
        v = (math.sin(2 * math.pi * freq * t) + 0.25 * math.sin(2 * math.pi * freq * 2 * t) * math.exp(-t * 14)) * attack * decay
        if s0 + i < n:
            out[s0 + i] += v
    return out


def main() -> Path:
    total = 0.48
    n = int(total * RATE)
    a = bell(1318.5, 0.0, total, n)
    b = bell(1975.5, 0.09, total - 0.09, n)
    mix = [x * 0.6 + y * 0.45 for x, y in zip(a, b)]
    fade = int(0.04 * RATE)
    for i in range(fade):                                  # end at silence
        mix[n - 1 - i] *= i / fade
    top = max(abs(x) for x in mix)
    data = b"".join(struct.pack("<h", int(x / top * PEAK * 32767)) for x in mix)
    dst = Path(__file__).resolve().parents[1] / "bchat" / "assets" / "sounds" / "soft.wav"
    dst.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(dst), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(data)
    print("saved", dst, dst.stat().st_size)
    return dst


def bee() -> Path:
    total = 0.55
    n = int(total * RATE)
    out = []
    phase = 0.0
    for i in range(n):
        t = i / RATE
        x = t / total
        freq = 205 + 55 * math.sin(math.pi * x) - 15 * x          # comes closer (higher), then drifts away
        phase += 2 * math.pi * freq / RATE
        tone = sum(math.sin(k * phase) / k ** 1.6 for k in range(1, 9))   # soft saw: harmonics fall away fast
        flutter = 1 + 0.18 * math.sin(2 * math.pi * 28 * t)                 # wing beats
        env = math.sin(math.pi * x) ** 1.4                                  # fades in and out, no click
        out.append(tone * flutter * env)
    top = max(abs(v) for v in out)
    data = b"".join(struct.pack("<h", int(v / top * PEAK * 32767)) for v in out)
    dst = Path(__file__).resolve().parents[1] / "bchat" / "assets" / "sounds" / "bee.wav"
    with wave.open(str(dst), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(data)
    print("saved", dst, dst.stat().st_size)
    return dst


if __name__ == "__main__":
    main()
    bee()
