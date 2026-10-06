"""What the keyboard window shows while you swipe: a trail that fades with age, and the keys under the pen.

The tablet is not a screen, so this is how you see what the pen is doing. This module only works out
*what* to draw (points, colours, rectangles in key units); it never touches Tk, so it can be tested.

- The trail: the whole path of the stroke stays on screen while the pen is down, but the older part is
  dimmer and thinner than the part near the pen. When you lift the pen the finished path lingers for a
  moment (the "ghost") and fades out, so you can still see what you just swiped while the word appears.
- Key highlights: the key under the pen is lit, and so are the letters the stroke has passed over (those
  are the ones the decoder is looking at). Taps on the strip are not highlighted.
"""
from __future__ import annotations

from .engine import CANVAS_W, FUNCTION_KEYS, KEY_CENTER, STRIP_CELLS, SYM_CENTER, classify

GHOST_SECONDS = 0.45     # a finished stroke fades out over this long
CHUNKS = 10              # the trail is drawn as at most this many pieces (few canvas items = smooth redraw)
MIN_HEAT = 0.30          # the oldest part of a stroke is this bright (1.0 = brightest)
MAX_VISITED = 40         # remember at most this many keys passed over in one stroke


def lerp_hex(a: str, b: str, t: float) -> str:
    """Colour between two '#rrggbb' colours: t=0 gives a, t=1 gives b."""
    t = min(1.0, max(0.0, t))
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(ca, cb))


def pressure_heat(p: float, limit: float) -> float:
    """0 = light touch, 1 = at or above the 'pressing hard' level."""
    if limit <= 0:
        return 1.0
    return min(1.0, max(0.0, p / limit))


def key_rect(kind: str, val, layer: str = "letters"):
    """The rectangle (x0, y0, x1, y1) in key units of what classify() reported, or None for the strip."""
    if kind == "letter":
        cx, cy = KEY_CENTER[val]
        return (cx - 0.47, cy - 0.47, cx + 0.47, cy + 0.47)
    if kind == "sym":
        cx, cy = SYM_CENTER[layer][val]
        return (cx - 0.47, cy - 0.47, cx + 0.47, cy + 0.47)
    if kind == "key":
        name = "shift" if val == "page" else val
        x0, x1, y0, y1 = FUNCTION_KEYS[name]
        return (x0 + 0.03, y0 + 0.03, x1 - 0.03, y1 - 0.03)
    return None


class TrailTracker:
    """Follows `Session.trail` from frame to frame. The session's trail is the decoder's input and is left
    alone; this keeps its own copy with a timestamp for each point."""

    def __init__(self, track_keys: bool = True):
        self.track_keys = track_keys
        self.pts: list[tuple[float, float]] = []
        self.stamps: list[float] = []
        self.visited: list[tuple[str, str]] = []      # ("letter", "h") ... in the order the stroke reached them
        self.ghost = None                             # (points, time the pen came up) of the last stroke
        self._layer = None

    # ---- feeding it -------------------------------------------------------------------------------
    def update(self, trail, now: float, layer: str = "letters") -> None:
        n, m = len(trail), len(self.pts)
        new_stroke = n < m or (n > 0 and m > 0 and tuple(trail[0]) != self.pts[0])
        if (n == 0 or new_stroke) and m >= 2:
            self.ghost = (list(self.pts), now)
        if n == 0 or new_stroke:
            self.pts, self.stamps, self.visited = [], [], []
            m = 0
        if layer != self._layer:
            self._layer = layer
            self.visited = []
        for p in trail[m:]:
            p = (p[0], p[1])
            self.pts.append(p)
            self.stamps.append(now)
            if self.track_keys:
                self._visit(p, layer)

    def _visit(self, p, layer):
        kind, val = classify(p[0], p[1], layer)
        if kind not in ("letter", "sym"):
            return
        key = (kind, val)
        if key in self.visited:
            return
        self.visited.append(key)
        if len(self.visited) > MAX_VISITED:
            del self.visited[0]

    def clear(self) -> None:
        self.pts, self.stamps, self.visited, self.ghost = [], [], [], None

    # ---- what to draw ---------------------------------------------------------------------------------
    def segments(self, now: float):
        """The trail as [(points, heat, width_scale)], oldest piece first. heat is 0..1 (1 = brightest);
        the window blends it between the background and the trail colour."""
        if len(self.pts) >= 2:
            return _pieces(self.pts, 1.0)
        if self.ghost:
            pts, t_up = self.ghost
            age = now - t_up
            if age >= GHOST_SECONDS:
                self.ghost = None
            else:
                return _pieces(pts, 1.0 - age / GHOST_SECONDS)
        return []

    def highlights(self, pos, layer: str = "letters", show_visited: bool = True):
        """[(rect, role, kind, val)] with role "visited" (the stroke passed over it) or "current" (the pen is
        on it); kind and val say which key it is (as classify() does), so the window can redraw its label.
        `pos` is where the pen is, in key units, or None."""
        out = []
        under = classify(pos[0], pos[1], layer) if pos else None
        if show_visited and self.pts:
            for kind, val in self.visited:
                if under and (kind, val) == under:
                    continue
                rect = key_rect(kind, val, layer)
                if rect:
                    out.append((rect, "visited", kind, val))
        if under:
            rect = key_rect(under[0], under[1], layer)
            if rect:
                out.append((rect, "current", under[0], under[1]))
        return out


def _pieces(pts, fade: float):
    n = len(pts)
    k = min(CHUNKS, n - 1)
    out = []
    for i in range(k):
        a, b = i * (n - 1) // k, (i + 1) * (n - 1) // k + 1      # neighbouring pieces share a point: no gaps
        age = (i + 1) / k                                        # 1 = the piece nearest the pen
        out.append((pts[a:b], (MIN_HEAT + (1.0 - MIN_HEAT) * age) * fade, 0.45 + 0.55 * age))
    return out
