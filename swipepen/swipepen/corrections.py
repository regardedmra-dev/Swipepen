"""Learning from your corrections.

When a swipe comes out as the wrong word and you fix it, that is the most useful thing swipepen can learn from:
    * you tapped another candidate in the strip  (wanted = that candidate, wrong = what was typed first)
    * you erased the word and swiped it again    (wanted = what the second swipe ended up as)
Each fix is counted, and the next time the same two words compete the one you meant gets a small push. The swipe
still decides: the push is capped, so it can reorder close calls but never overrule a clear swipe. Counts stay on
this computer (~/.config/swipepen/corrections.json). Settings can switch learning off or wipe it.

    m = CorrectionModel(path=None)
    m.learn("form", "from")                 # you wanted "form", it typed "from"
    m.adjust(["from", "form"])              # -> {"form": 0.12, "from": -0.05}   (cost change: negative = better)
"""
from __future__ import annotations

import json
import math
import os
import tempfile
from collections import Counter

PAIR_STEP = 0.12      # cost change per doubling of "you meant A, not B" (when both are on offer)
WORD_STEP = 0.04      # ...and per doubling of "A is usually what I meant" / "B is usually wrong"
CAP = 0.45            # a word's total change never exceeds this (a swipe gap of that size is not a close call)
MAX_PAIRS = 4000
SAVE_EVERY = 5


def _config_file() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "swipepen", "corrections.json")


def _lg(n: int, top: int = 4) -> float:
    return min(float(top), math.log2(1 + n))


class CorrectionModel:
    def __init__(self, path: str | None = "auto"):
        self.path = _config_file() if path == "auto" else path
        self.pair: Counter = Counter()      # (wanted, wrong) -> times
        self.wanted: Counter = Counter()
        self.wrong: Counter = Counter()
        self._dirty = 0
        self.load()

    # ---- storage ---------------------------------------------------------------------------------
    def load(self):
        if not self.path:
            return
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
            for key, n in data.get("pair", {}).items():
                a, _, b = key.partition("\t")
                if a and b and isinstance(n, int):
                    self.pair[(a, b)] = n
            for table, name in ((self.wanted, "wanted"), (self.wrong, "wrong")):
                for w, n in data.get(name, {}).items():
                    if isinstance(n, int):
                        table[w] = n
        except (OSError, ValueError, AttributeError):
            pass

    def save(self):
        if not self.path or not self._dirty:
            return
        if len(self.pair) > MAX_PAIRS:
            keep = {k for k, _ in self.pair.most_common(MAX_PAIRS * 3 // 4)}
            self.pair = Counter({k: v for k, v in self.pair.items() if k in keep})
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.path), suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"v": 1, "pair": {f"{a}\t{b}": n for (a, b), n in self.pair.items()},
                           "wanted": dict(self.wanted), "wrong": dict(self.wrong)}, fh, ensure_ascii=False)
            os.replace(tmp, self.path)
            self._dirty = 0
        except OSError:
            pass

    def forget(self):
        self.pair.clear()
        self.wanted.clear()
        self.wrong.clear()
        self._dirty = 0
        if self.path:
            try:
                os.remove(self.path)
            except OSError:
                pass

    # ---- learning ----------------------------------------------------------------------------------
    def learn(self, wanted: str, wrong: str):
        wanted, wrong = wanted.lower(), wrong.lower()
        if not wanted or not wrong or wanted == wrong:
            return
        self.pair[(wanted, wrong)] += 1
        self.wanted[wanted] += 1
        self.wrong[wrong] += 1
        self._dirty += 1
        if self._dirty >= SAVE_EVERY:
            self.save()

    def __len__(self):
        return len(self.pair)

    # ---- using it ------------------------------------------------------------------------------------
    def adjust(self, words) -> dict:
        """Cost change for each of `words` (lowercase, the candidates on offer). Negative = more likely."""
        if not self.pair:
            return {}
        words = [w.lower() for w in words]
        out = {}
        for w in words:
            d = -WORD_STEP * _lg(self.wanted.get(w, 0)) + WORD_STEP * _lg(self.wrong.get(w, 0))
            for o in words:
                if o != w:
                    d -= PAIR_STEP * _lg(self.pair.get((w, o), 0))
                    d += PAIR_STEP * _lg(self.pair.get((o, w), 0))
            if d:
                out[w] = max(-CAP, min(CAP, d))
        return out
