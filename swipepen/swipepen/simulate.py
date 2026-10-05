"""Synthetic swipe generator + accuracy benchmark for the decoder.

    python -m swipepen.simulate

Synthetic noise is only a rough stand-in for a real hand and a real tablet, so
treat the numbers as a sanity check, not a promise. Use `--record` in the real
tool to collect your own swipes for tuning.
"""
from __future__ import annotations

import argparse
import math
import os
import random
import time

from .engine import KEY_CENTER, Decoder, resample, word_path, path_length
from .lexicon import HERE, load_lexicon


def generate_swipe(word: str, rng: random.Random, sigma: float = 0.3, offset: float = 0.2,
                   jitter: float = 0.04, samples: int = 90, ka: float = 1.0):
    """A noisy, corner-rounded swipe over `word` (letters only), in key units.

    ka = key height / key width. Hand noise is the same sideways and up/down on the
    tablet, so with tall keys the noise is smaller in key units vertically.
    """
    key = word.replace("'", "")
    wp = word_path(key)
    ox, oy = rng.gauss(0, offset), rng.gauss(0, offset) / ka
    wp = [(x + rng.gauss(0, sigma) + ox, y + rng.gauss(0, sigma) / ka + oy) for x, y in wp]
    if len(wp) == 1:
        wp = [wp[0], (wp[0][0] + 0.01, wp[0][1])]
    dense = resample(wp, 400)

    # round the corners with a moving average (about 0.35 key units each side)
    total = max(path_length(dense), 1e-6)
    radius = max(1, min(60, int(0.35 / (total / 400))))
    smooth = []
    for i in range(len(dense)):
        lo, hi = max(0, i - radius), min(len(dense) - 1, i + radius)
        r = min(i - lo, hi - i)  # shrink the window at the ends so endpoints stay put
        lo, hi = i - r, i + r
        n = hi - lo + 1
        smooth.append((sum(p[0] for p in dense[lo:hi + 1]) / n,
                       sum(p[1] for p in dense[lo:hi + 1]) / n))

    # uneven hand speed: pick monotone sample positions along the curve
    speeds = [rng.lognormvariate(0, 0.5) for _ in range(samples)]
    cum, acc = [], 0.0
    for s in speeds:
        acc += s
        cum.append(acc)
    out = []
    for c in cum:
        idx = min(len(smooth) - 1, int((c - cum[0]) / (cum[-1] - cum[0] + 1e-9) * (len(smooth) - 1)))
        x, y = smooth[idx]
        out.append((x + rng.gauss(0, jitter), y + rng.gauss(0, jitter) / ka))
    return out


def benchmark(decoder: Decoder, targets, sigma: float, rng: random.Random, reps: int = 1, ka: float = 1.0):
    hits = {1: 0, 3: 0, 5: 0}
    n = 0
    t_total = 0.0
    for w in targets:
        for _ in range(reps):
            swipe = generate_swipe(w, rng, sigma=sigma, offset=sigma * 0.7, ka=ka)
            t0 = time.perf_counter()
            res = [s for s, _ in decoder.decode(swipe, k=5)]
            t_total += time.perf_counter() - t0
            n += 1
            for k in hits:
                if w in res[:k]:
                    hits[k] += 1
    return {k: v / n for k, v in hits.items()}, t_total / n * 1000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", type=int, default=300)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--lang", default="en")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    lex = load_lexicon(args.lang, force_fallback=(args.lang == "en" and not _has_wordfreq()))
    common = []
    with open(os.path.join(HERE, "data", "common_en.txt"), encoding="utf-8") as fh:
        for line in fh:
            w = line.strip()
            if len(set(w)) >= 2 and len(w) >= 3 and w not in common:
                common.append(w)
    targets = rng.sample(common, min(args.targets, len(common)))

    print(f"{len(targets)} common target words, {len(lex)} words in the dictionary\n")
    print(f"{'noise (key units)':<20}{'prior':<10}{'top-1':>8}{'top-3':>8}{'top-5':>8}{'ms/swipe':>10}")
    for sigma in (0.15, 0.30, 0.45):
        for label, weight in (("none", 0.0), ("on", 0.18)):
            dec = Decoder(lex, prior_weight=weight)
            acc, ms = benchmark(dec, targets, sigma, random.Random(args.seed))
            print(f"{sigma:<20}{label:<10}{acc[1]:>8.1%}{acc[3]:>8.1%}{acc[5]:>8.1%}{ms:>10.1f}")


def _has_wordfreq():
    try:
        import wordfreq  # noqa: F401
        return True
    except ImportError:
        return False


if __name__ == "__main__":
    main()
