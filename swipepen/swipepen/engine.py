"""Swipe-typing engine: keyboard geometry + SHARK2-style template decoder.

Pure standard library. All coordinates are in "key units": one letter key is
1.0 wide and 1.0 tall. The whole tablet maps onto a canvas that is 10 units
wide and 5 units tall, spanning y = -1 .. 4:

    y in [-1, 0)  suggestion strip (4 cells)
    y in [ 0, 3)  three letter rows (QWERTY, Gboard-style staggering)
    y in [ 3, 4)  bottom row (comma, space, period, enter)

Decoding idea (after Kristensson & Zhai's SHARK2): every dictionary word is a
"template" path through the centres of its letters. A swipe is resampled to a
fixed number of points and compared with the templates of words whose first
and last letters are near where the swipe started and ended. The final score
combines path distance, how closely the swipe passes over every letter, and a
word-frequency prior.
"""
from __future__ import annotations

import math
from collections import defaultdict

# --------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------
CANVAS_W = 10.0
CANVAS_Y0 = -1.0
CANVAS_H = 5.0

# (letters, x of first key centre, y of row centre)
ROWS = (
    ("qwertyuiop", 0.5, 0.5),
    ("asdfghjkl", 1.0, 1.5),
    ("zxcvbnm", 2.0, 2.5),
)

KEY_CENTER: dict[str, tuple[float, float]] = {}
for _letters, _x0, _y in ROWS:
    for _i, _ch in enumerate(_letters):
        KEY_CENTER[_ch] = (_x0 + _i, _y)

# name: (x0, x1, y0, y1)
FUNCTION_KEYS = {
    "shift": (0.0, 1.5, 2.0, 3.0),          # in the symbol layers this key flips between the two symbol pages
    "backspace": (8.5, 10.0, 2.0, 3.0),
    "sym": (0.0, 1.2, 3.0, 4.0),            # ?123  <->  ABC
    "comma": (1.2, 2.1, 3.0, 4.0),
    "apostrophe": (2.1, 3.0, 3.0, 4.0),
    "space": (3.0, 7.5, 3.0, 4.0),
    "period": (7.5, 8.5, 3.0, 4.0),
    "enter": (8.5, 10.0, 3.0, 4.0),
}
FUNCTION_LABELS = {
    "shift": "shift", "backspace": "bksp", "sym": "?123", "comma": ",", "apostrophe": "'",
    "space": "space", "period": ".", "enter": "enter",
}

# The number / symbol layers (tap only; swiping works on the letter layer).
SYM_ROWS = {
    "sym1": (
        ("1234567890", 0.5, 0.5),
        ("@#$%&-+()/", 0.5, 1.5),
        ("*\"':;!?", 2.0, 2.5),
    ),
    "sym2": (
        ("[]{}<>^~|\\`", 0.5, 0.5),
        ("=_¿¡€£°©×÷", 0.5, 1.5),
        ("…•·±§¶¬", 2.0, 2.5),
    ),
}
SYM_CENTER: dict[str, dict[str, tuple[float, float]]] = {}
for _layer, _rows in SYM_ROWS.items():
    SYM_CENTER[_layer] = {}
    for _letters, _x0, _y in _rows:
        for _i, _ch in enumerate(_letters):
            SYM_CENTER[_layer][_ch] = (_x0 + _i, _y)
LAYERS = ("letters", "sym1", "sym2")


def function_label(name: str, layer: str = "letters") -> str:
    """What a function key says on the given layer."""
    if layer != "letters":
        if name == "sym":
            return "ABC"
        if name == "shift":
            return "=\\<" if layer == "sym1" else "?123"
    return FUNCTION_LABELS[name]
STRIP_CELLS = 4


def dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def nearest_letter(x: float, y: float) -> str:
    return min(KEY_CENTER, key=lambda c: (KEY_CENTER[c][0] - x) ** 2 + (KEY_CENTER[c][1] - y) ** 2)


def classify(x: float, y: float, layer: str = "letters"):
    """What is under this point? Returns ('cand', i), ('key', name), ('letter', ch) or ('sym', ch)."""
    if y < 0:
        i = int(max(0.0, x) // (CANVAS_W / STRIP_CELLS))
        return ("cand", min(STRIP_CELLS - 1, i))
    y = min(y, 3.999)
    for name, (x0, x1, y0, y1) in FUNCTION_KEYS.items():
        if x0 <= x < x1 and y0 <= y < y1:
            if name == "shift" and layer != "letters":
                return ("key", "page")
            return ("key", name)
    if layer == "letters":
        return ("letter", nearest_letter(x, y))
    centers = SYM_CENTER[layer]
    return ("sym", min(centers, key=lambda c: (centers[c][0] - x) ** 2 + (centers[c][1] - y) ** 2))


def path_length(pts) -> float:
    return sum(dist(pts[i - 1], pts[i]) for i in range(1, len(pts)))


def resample(pts, n: int):
    """Resample a polyline to n points equally spaced by arc length."""
    if len(pts) == 1:
        return [pts[0]] * n
    cum = [0.0]
    for i in range(1, len(pts)):
        cum.append(cum[-1] + dist(pts[i - 1], pts[i]))
    total = cum[-1]
    if total == 0:
        return [pts[0]] * n
    out = []
    j = 0
    for k in range(n):
        target = total * k / (n - 1)
        while j < len(cum) - 2 and cum[j + 1] < target:
            j += 1
        seg = cum[j + 1] - cum[j]
        t = 0.0 if seg == 0 else (target - cum[j]) / seg
        out.append((pts[j][0] + (pts[j + 1][0] - pts[j][0]) * t,
                    pts[j][1] + (pts[j + 1][1] - pts[j][1]) * t))
    return out


def word_path(letters: str, centers=None):
    """Polyline through the key centres of a word (repeated letters collapse)."""
    centers = centers or KEY_CENTER
    pts, prev = [], None
    for ch in letters:
        if ch != prev:
            pts.append(centers[ch])
            prev = ch
    return pts


def clean_trace(pts, min_step: float = 0.02):
    out = [pts[0]]
    for p in pts[1:]:
        if dist(p, out[-1]) >= min_step:
            out.append(p)
    return out


# --------------------------------------------------------------------------
# Decoder
# --------------------------------------------------------------------------
class _Entry:
    __slots__ = ("surface", "key", "logp", "distinct", "tmpl", "tlen", "user", "geom")

    def __init__(self, surface: str, key: str, logp: float, user: bool = False):
        self.user = user
        self.surface = surface
        self.key = key
        self.logp = logp
        self.distinct = tuple(dict.fromkeys(key))
        self.tmpl = None
        self.tlen = 0.0
        self.geom = None         # (path points, cumulative lengths, letters per point) for partial matching


class Decoder:
    """Turn a swipe trace (list of (x, y) in key units) into ranked words."""

    def __init__(self, words, n_points: int = 32, prior_weight: float = 0.18,
                 coverage_weight: float = 0.5, end_weight: float = 0.5,
                 endpoint_radius: float = 1.7, shortlist: int = 80, ys: float = 1.0,
                 partial_penalty: float = 0.14, partial: bool = True, partial_base: float = 0.16):
        """words: iterable of (surface, letters_key, log10_probability).

        ys: how much taller a key is than it is wide on the tablet. Distances are
        measured in physical units (so a 1 mm slip counts the same sideways and up/down).
        """
        self.ys = ys
        self.kc = {c: (x, y * ys) for c, (x, y) in KEY_CENTER.items()}
        self.n = n_points
        self.prior_weight = prior_weight
        self.coverage_weight = coverage_weight
        self.end_weight = end_weight
        self.endpoint_radius = endpoint_radius
        self.shortlist = shortlist
        self.partial = partial                  # a swipe may stop before the end of the word
        self.partial_penalty = partial_penalty  # cost per letter you did not swipe
        self.partial_base = partial_base        # ...plus this for stopping early at all (a finished word wins a tie)
        self.loc_max = 2.2                      # shape distance above which a word is not considered
        self.looseness = None
        self._by_first = None
        self.by_pair: dict[tuple[str, str], list[_Entry]] = defaultdict(list)
        words = list(words)
        # "dont" is a typo for "don't": never offer it, and make sure "don't" exists even if the
        # word list lacks it. Real words like "hell" or "well" are not touched.
        from .tidy import MISSING_APOSTROPHE
        have = {sf.lower() for sf, _, _ in words if "'" in sf}
        bare_lp = {sf: lp for sf, k, lp in words if sf == k and sf in MISSING_APOSTROPHE}
        for bare, apos in MISSING_APOSTROPHE.items():
            if apos.lower() not in have:
                words.append((apos.lower(), bare, max(-4.5, bare_lp.get(bare, -4.0))))
        typo_forms = set(MISSING_APOSTROPHE)
        self.freq: dict[str, float] = {}          # lowercase word -> log10 frequency
        self.user_freq: dict[str, float] = {}
        for surface, key, logp in words:
            if "'" not in surface and surface == key and key in typo_forms:
                continue
            low = surface.lower()
            self.freq[low] = max(logp, self.freq.get(low, -99.0))
            if len(set(key)) < 2:
                continue  # single-letter paths are handled as taps
            self.by_pair[(key[0], key[-1])].append(_Entry(surface, key, logp))

    def logp(self, word: str):
        """log10 frequency of a lowercase word (your own words count too), or None if unknown."""
        a, b = self.freq.get(word), self.user_freq.get(word)
        return b if a is None else a if b is None else max(a, b)

    def set_user_words(self, entries):
        """Replace your personal words (entries: (surface, key, logp)). Takes effect immediately."""
        for lst in self.by_pair.values():
            lst[:] = [e for e in lst if not e.user]
        self.user_freq = {}
        self._by_first = None
        for surface, key, logp in entries:
            self.user_freq[surface.lower()] = max(logp, self.user_freq.get(surface.lower(), -99.0))
            if len(set(key)) >= 2:
                self.by_pair[(key[0], key[-1])].append(_Entry(surface, key, logp, user=True))

    def set_ys(self, ys: float):
        """Change the key shape at runtime (templates are rebuilt lazily)."""
        if abs(ys - self.ys) < 1e-9:
            return
        self.ys = ys
        self.kc = {c: (x, y * ys) for c, (x, y) in KEY_CENTER.items()}
        for lst in self.by_pair.values():
            for e in lst:
                e.tmpl = None
                e.geom = None

    def _template(self, e: _Entry):
        if e.tmpl is None:
            path = word_path(e.key, self.kc)
            e.tlen = path_length(path)
            e.tmpl = resample(path, self.n)
        return e.tmpl

    def set_looseness(self, v: float):
        """0 = strict (swipe every letter, close to the keys) ... 1 = loose (sloppy paths and unfinished
        words are understood; the word list does more of the work). Takes effect immediately."""
        v = min(1.0, max(0.0, float(v)))
        self.looseness = v
        self.endpoint_radius = 1.7 + 0.8 * v
        self.loc_max = 2.2 + 0.8 * v
        self.coverage_weight = 0.5 - 0.3 * v
        self.partial_penalty = 0.16 - 0.08 * v
        self.partial_base = 0.18 - 0.08 * v
        self.prior_weight = 0.18 + 0.08 * v

    def _geom(self, e: _Entry):
        if e.geom is None:
            pts, cums, letters, prev = [], [], [], None
            total = 0.0
            for ch in e.key:
                if ch == prev:
                    continue
                prev = ch
                p = self.kc[ch]
                if pts:
                    total += dist(pts[-1], p)
                pts.append(p)
                cums.append(total)
                letters.append(ch)
            e.geom = (pts, cums, "".join(letters))
        return e.geom

    def _entries_by_first(self):
        if self._by_first is None:
            idx: dict[str, list] = defaultdict(list)
            for (f, _l), lst in self.by_pair.items():
                idx[f].extend(lst)
            self._by_first = idx
        return self._by_first

    def _partial_candidates(self, g, glen, firsts, r):
        """Words whose beginning looks like the stroke: (cost, entry, letters swiped) for the best few."""
        import bisect
        near = []
        idx = self._entries_by_first()
        gx, gy = g[-1]
        for f in firsts:
            for e in idx.get(f, ()):
                pts, cums, _letters = self._geom(e)
                npts = len(pts)
                if npts < 3:
                    continue
                m = bisect.bisect_left(cums, glen, 2, npts - 1)        # vertices swiped, 2 .. npts-1
                best = None
                for mm in (m - 1, m):
                    if 2 <= mm <= npts - 1:
                        c = cums[mm - 1]
                        if c > 0 and 0.55 <= glen / c <= 1.6:
                            d = math.hypot(gx - pts[mm - 1][0], gy - pts[mm - 1][1])
                            if d <= r and (best is None or d < best[0]):
                                best = (d, mm)
                if best:
                    near.append((best[0] - self.prior_weight * e.logp + self.partial_base
                                 + self.partial_penalty * (npts - best[1]),
                                 e, best[1], best[0]))
        near.sort(key=lambda t: t[0])
        out = []
        for _, e, m, endd in near[: self.shortlist * 3]:
            pts, cums, letters = self._geom(e)
            t = resample(pts[:m], self.n)
            total = 0.0
            for (ax, ay), (tx, ty) in zip(g, t):
                total += math.hypot(ax - tx, ay - ty)
            loc = total / self.n
            if loc > self.loc_max:
                continue
            ends = (dist(g[0], t[0]) + endd) / 2
            cost = (loc + self.end_weight * ends - self.prior_weight * e.logp + self.partial_base
                    + self.partial_penalty * (len(pts) - m))
            out.append((cost, e, tuple(dict.fromkeys(letters[:m]))))
        return out

    def decode(self, trace, k: int = 5):
        """Return up to k (surface, cost) pairs, best first. Lower cost = better."""
        if len(trace) < 2:
            return []
        pts = clean_trace(trace)
        if len(pts) < 2:
            return []
        if self.ys != 1.0:
            pts = [(x, y * self.ys) for x, y in pts]
        glen = path_length(pts)
        if glen <= 0:
            return []
        g = resample(pts, self.n)
        dense = resample(pts, self.n * 4)
        r = self.endpoint_radius

        firsts = [c for c, p in self.kc.items() if dist(p, g[0]) <= r]
        lasts = [c for c, p in self.kc.items() if dist(p, g[-1]) <= r]

        scored = []
        for f in firsts:
            for l in lasts:
                for e in self.by_pair.get((f, l), ()):
                    t = self._template(e)
                    ratio = glen / e.tlen if e.tlen else 99.0
                    if ratio < 0.45 or ratio > 2.5:
                        continue
                    total = 0.0
                    for (gx, gy), (tx, ty) in zip(g, t):
                        total += math.hypot(gx - tx, gy - ty)
                    loc = total / self.n
                    if loc > self.loc_max:
                        continue
                    ends = (dist(g[0], t[0]) + dist(g[-1], t[-1])) / 2
                    cost = loc + self.end_weight * ends - self.prior_weight * e.logp
                    scored.append((cost, e, e.distinct))

        if self.partial and glen >= 1.2:
            scored.extend(self._partial_candidates(g, glen, firsts, r))

        if not scored:
            return []
        scored.sort(key=lambda s: s[0])
        short = scored[: self.shortlist]

        # Second stage: coverage - does the swipe actually pass over every letter?
        final = []
        for cost, e, distinct in short:
            cov = 0.0
            for c in distinct:
                cx, cy = self.kc[c]
                dmin = min(math.hypot(px - cx, py - cy) for px, py in dense)
                cov += max(0.0, dmin - 0.4)
            cov /= len(distinct)
            final.append((cost + self.coverage_weight * cov, e))
        final.sort(key=lambda s: s[0])

        out, seen = [], set()
        for cost, e in final:
            if e.surface in seen:
                continue
            seen.add(e.surface)
            out.append((e.surface, cost))
            if len(out) == k:
                break
        return out
