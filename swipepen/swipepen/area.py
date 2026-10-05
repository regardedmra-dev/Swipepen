"""Which part of the tablet is the keyboard, plus saved settings.

The keyboard does not have to use the whole tablet. A smaller area means less
hand movement. The area keeps the keyboard's natural 2:1 shape in physical
units (so keys are about as wide as they are tall on the tablet surface).

Tablet coordinates (u, v) are 0..1 across the tablet. Keyboard coordinates are
the key units from engine.py.
"""
from __future__ import annotations

import json
import os

from .engine import CANVAS_H, CANVAS_W, CANVAS_Y0

DEFAULTS = {"size": 0.5, "cx": 0.5, "cy": 0.5, "topmost": True, "scale": 60, "rotate": 0,
            "follow": True, "key_aspect": 1.5, "edge_speed": 1.0, "autofix": True,
            "typewriter": False, "chars_per_line": 80, "notches_per_line": 0.25,
            "languagetool_url": "", "online_lookup": True,
            "predict": True, "learn_typing": True, "looseness": 0.5,
            "docs_menu_key": "ctrl+shift+\\", "docs_menu_v": 2, "docs_delay": 0.25, "docs_auto": True}
SIZE_MIN, SIZE_MAX = 0.05, 1.0


def config_path() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "swipepen", "config.json")


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    try:
        with open(config_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        if data.get("docs_menu_v") != 2:         # 0.5.1 saved Shift+F10, which Firefox keeps for its own menu
            data.pop("docs_menu_key", None)
        for k, default in DEFAULTS.items():
            if k in data and isinstance(data[k], type(default)) or (
                    k in data and isinstance(default, float) and isinstance(data[k], int)):
                cfg[k] = data[k]
    except (OSError, ValueError):
        pass
    cfg["size"] = min(SIZE_MAX, max(SIZE_MIN, float(cfg["size"])))
    cfg["scale"] = min(200, max(8, int(cfg["scale"])))
    if cfg["rotate"] not in (0, 90, 180, 270):
        cfg["rotate"] = 0
    cfg["key_aspect"] = min(2.0, max(1.0, float(cfg["key_aspect"])))
    cfg["edge_speed"] = min(3.0, max(0.3, float(cfg["edge_speed"])))
    cfg["docs_delay"] = min(1.0, max(0.05, float(cfg["docs_delay"])))
    if cfg["docs_menu_key"] not in ("shift+f10", "ctrl+shift+x", "ctrl+shift+\\"):
        cfg["docs_menu_key"] = DEFAULTS["docs_menu_key"]
    cfg["looseness"] = min(1.0, max(0.0, float(cfg["looseness"])))
    cfg["chars_per_line"] = min(200, max(20, int(cfg["chars_per_line"])))
    cfg["notches_per_line"] = min(1.0, max(0.05, float(cfg["notches_per_line"])))
    return cfg


def save_config(cfg: dict):
    try:
        os.makedirs(os.path.dirname(config_path()), exist_ok=True)
        with open(config_path(), "w", encoding="utf-8") as fh:
            json.dump({k: cfg[k] for k in DEFAULTS if k in cfg}, fh, indent=2)
    except OSError:
        pass


def to_units(un: float, vn: float):
    """Normalised keyboard position (0..1) -> key units."""
    return un * CANVAS_W, CANVAS_Y0 + vn * CANVAS_H


class Area:
    def __init__(self, aspect: float = 1.6, size: float = 0.5, cx: float = 0.5, cy: float = 0.5,
                 key_aspect: float = 1.0):
        self.aspect = aspect          # tablet width / height (physical)
        self.key_aspect = key_aspect  # key height / key width: 1.0 square, 1.5 like Gboard
        self.size = min(SIZE_MAX, max(SIZE_MIN, size))
        self.cx, self.cy = cx, cy
        self._clamp()

    @property
    def _ratio(self) -> float:
        """Keyboard height / width as fractions of the tablet (keys are key_aspect times taller than wide)."""
        return self.aspect * CANVAS_H * self.key_aspect / CANVAS_W

    @property
    def w(self) -> float:
        return min(self.size, 1.0 / self._ratio)

    @property
    def h(self) -> float:
        return min(1.0, self.w * self._ratio)

    def _clamp(self):
        self.cx = min(max(self.cx, self.w / 2), 1 - self.w / 2)
        self.cy = min(max(self.cy, self.h / 2), 1 - self.h / 2)

    def set_size(self, size: float):
        self.size = min(SIZE_MAX, max(SIZE_MIN, size))
        self._clamp()

    def set_center(self, cx: float, cy: float):
        self.cx, self.cy = cx, cy
        self._clamp()

    def rect(self):
        """(u0, v0, u1, v1) of the keyboard on the tablet."""
        return (self.cx - self.w / 2, self.cy - self.h / 2,
                self.cx + self.w / 2, self.cy + self.h / 2)

    def map(self, u: float, v: float):
        """Tablet (u, v) -> normalised keyboard (un, vn). May be outside 0..1."""
        u0, v0, _, _ = self.rect()
        return (u - u0) / self.w, (v - v0) / self.h


class PenRouter:
    """Feeds pen events from the tablet into the Session, honouring the area.

    - touches that start outside the keyboard area are ignored (resting your hand
      or the pen near the edge does nothing)
    - once a stroke has started inside, drifting outside is clamped to the edge

    Follow mode (so you are not stuck in one spot on the tablet):
    - while the pen hovers (not touching) and moves past an edge of the keyboard
      area, the area is pushed along with it, like dragging a window by its edge
    - when you lift the pen away from the tablet and put it down somewhere else,
      the area jumps to be centred on the pen
    - while the pen is touching (a stroke), the area never moves
    Only the pen device is read here; the mouse is a different device and is never involved.
    """

    def __init__(self, session, area: Area, follow: bool = True, on_moved=None):
        self.s = session
        self.area = area
        self.follow = follow
        self.on_moved = on_moved   # called when follow mode moves the area
        self.pen_uv = None         # last pen position on the tablet, for the minimap
        self._ok = False
        self._fresh = True         # pen has just come into range

    def reset(self):
        self._ok = False
        self.pen_uv = None
        self._fresh = True

    def _follow(self, u, v, un, vn):
        a = self.area
        if self._fresh:
            a.set_center(u, v)                      # pen appeared somewhere new: centre on it
        else:
            a.set_center(a.cx + min(0.0, un) * a.w + max(0.0, un - 1.0) * a.w,
                         a.cy + min(0.0, vn) * a.h + max(0.0, vn - 1.0) * a.h)
        if self.on_moved:
            self.on_moved()
        return a.map(u, v)

    def handle(self, ev):
        kind = ev[0]
        if kind == "leave":
            self.pen_uv = None
            self.s.hover_pos = None
            self._fresh = True
            return
        if kind == "up":
            if self._ok:
                self.s.pen_up()
            self._ok = False
            return
        u, v = ev[1], ev[2]
        self.pen_uv = (u, v)
        un, vn = self.area.map(u, v)
        inside = 0.0 <= un <= 1.0 and 0.0 <= vn <= 1.0
        if kind == "hover" and self.follow and not inside:
            un, vn = self._follow(u, v, un, vn)
            inside = 0.0 <= un <= 1.0 and 0.0 <= vn <= 1.0
        self._fresh = False
        cx, cy = to_units(min(1.0, max(0.0, un)), min(1.0, max(0.0, vn)))
        if kind == "hover":
            if inside:
                self.s.hover(cx, cy)
            else:
                self.s.hover_pos = None
        elif kind == "down":
            self._ok = inside
            if inside:
                self.s.pen_down(cx, cy)
            else:
                self.s.hover_pos = None
        elif kind == "move":
            if self._ok:
                self.s.pen_move(cx, cy)
