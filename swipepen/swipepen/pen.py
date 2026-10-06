"""Read a Wacom pen straight from evdev.

While "active" the pen is grabbed exclusively, so the desktop cursor does not
move and clicks do not reach other apps; the pen then acts purely as a swipe
keyboard. When paused, the pen is released and behaves like a normal tablet.

Events are put on `reader.events` as tuples with u, v normalised to 0..1:
    ('hover', u, v)  ('down', u, v)  ('move', u, v)  ('up',)  ('leave',)  ('toggle',)  ('tidy',)
'down' and 'move' carry a fourth number, the pen pressure 0..1, when the pen reports pressure.
"""
from __future__ import annotations

import queue
import threading


def _abs_codes(caps, e):
    return [c if isinstance(c, int) else c[0] for c in caps.get(e.EV_ABS, [])]


def list_pen_candidates():
    import evdev
    from evdev import ecodes as e

    found = []
    for path in evdev.list_devices():
        try:
            d = evdev.InputDevice(path)
        except PermissionError:
            continue
        caps = d.capabilities()
        keys = caps.get(e.EV_KEY, [])
        codes = _abs_codes(caps, e)
        if e.ABS_X in codes and e.ABS_Y in codes and e.BTN_TOOL_PEN in keys:
            found.append(d)
    return found


def find_pen(path: str | None = None):
    import evdev

    if path:
        return evdev.InputDevice(path)
    cands = list_pen_candidates()
    # Wacom exposes separate Pen / Pad / Finger devices; we want the pen.
    good = [d for d in cands
            if not any(w in d.name.lower() for w in ("pad", "finger", "touch"))]
    pick = good or cands
    if not pick:
        raise SystemExit(
            "No pen tablet found. Run `swipepen doctor` to see why "
            "(tablet not plugged in, or not allowed to read it).")
    wacom = [d for d in pick if "wacom" in d.name.lower()]
    return (wacom or pick)[0]


def rotate_uv(u, v, rotate):
    if rotate == 90:
        return 1 - v, u
    if rotate == 180:
        return 1 - u, 1 - v
    if rotate == 270:
        return v, 1 - u
    return u, v


class PenReader(threading.Thread):
    def __init__(self, device_path=None, rotate: int = 0, toggle_button: str = "auto"):
        super().__init__(daemon=True)
        from evdev import ecodes as e

        self.e = e
        self.dev = find_pen(device_path)
        self.rotate = rotate
        self.events: "queue.Queue[tuple]" = queue.Queue()
        self.active = False

        ax = self.dev.absinfo(e.ABS_X)
        ay = self.dev.absinfo(e.ABS_Y)
        self.xmin, self.xmax = ax.min, ax.max
        self.ymin, self.ymax = ay.min, ay.max

        # physical shape of the tablet surface (width / height), after rotation
        rx, ry = getattr(ax, "resolution", 0) or 0, getattr(ay, "resolution", 0) or 0
        if rx and ry:
            pw, ph = (self.xmax - self.xmin) / rx, (self.ymax - self.ymin) / ry
        else:
            pw, ph = self.xmax - self.xmin, self.ymax - self.ymin
        self._base_aspect = pw / ph if ph else 1.6
        self.set_rotate(rotate)

        self.p_code, self.pmax = getattr(e, "ABS_PRESSURE", None), 0     # pressure is optional
        if self.p_code is not None and self.p_code in _abs_codes(self.dev.capabilities(), e):
            try:
                self.pmax = max(0, int(self.dev.absinfo(self.p_code).max))
            except (OSError, AttributeError, TypeError, ValueError):
                self.pmax = 0

        keys = self.dev.capabilities().get(e.EV_KEY, [])
        if toggle_button == "auto":
            toggle_button = "stylus2" if e.BTN_STYLUS2 in keys else "stylus"
        self.toggle_code = e.BTN_STYLUS2 if toggle_button == "stylus2" else e.BTN_STYLUS
        self.toggle_name = toggle_button
        print(f"[swipepen] pen device: {self.dev.name} ({self.dev.path}); "
              f"toggle with the '{toggle_button}' side button")

    def set_rotate(self, rotate: int):
        """Turn the tablet 0/90/180/270 degrees (180 = left-handed). Takes effect immediately."""
        self.rotate = rotate
        self.aspect = 1 / self._base_aspect if rotate in (90, 270) else self._base_aspect

    def set_active(self, on: bool):
        if on == self.active:
            return
        try:
            if on:
                self.dev.grab()
            else:
                self.dev.ungrab()
            self.active = on
        except OSError as err:
            print(f"[swipepen] could not {'grab' if on else 'release'} the pen: {err}")

    def run(self):
        e = self.e
        x = y = None
        pressure = 0.0
        touching = in_range = False
        touch_changed = moved = range_changed = False
        was_touching = False
        for ev in self.dev.read_loop():
            if ev.type == e.EV_ABS:
                if ev.code == e.ABS_X:
                    x, moved = ev.value, True
                elif ev.code == e.ABS_Y:
                    y, moved = ev.value, True
                elif self.pmax and ev.code == self.p_code:
                    pressure = min(1.0, max(0.0, ev.value / self.pmax))
            elif ev.type == e.EV_KEY:
                if ev.code == e.BTN_TOUCH:
                    touching, touch_changed = bool(ev.value), True
                elif ev.code == e.BTN_TOOL_PEN:
                    in_range, range_changed = bool(ev.value), True
                elif ev.code == self.toggle_code and ev.value == 1:
                    self.events.put(("toggle",))
                elif ev.code == e.BTN_STYLUS and ev.value == 1:     # the other side button: tidy up the text
                    self.events.put(("tidy",))
            elif ev.type == e.EV_SYN and ev.code == e.SYN_REPORT:
                if self.active and x is not None and y is not None:
                    u = (x - self.xmin) / max(1, self.xmax - self.xmin)
                    v = (y - self.ymin) / max(1, self.ymax - self.ymin)
                    u, v = rotate_uv(min(1, max(0, u)), min(1, max(0, v)), self.rotate)
                    extra = (round(pressure, 3),) if self.pmax else ()
                    if touch_changed and touching and not was_touching:
                        self.events.put(("down", u, v) + extra)
                    elif touch_changed and not touching and was_touching:
                        self.events.put(("up",))
                    elif touching and moved:
                        self.events.put(("move", u, v) + extra)
                    elif in_range and moved:
                        self.events.put(("hover", u, v))
                    if range_changed and not in_range:
                        if was_touching:
                            self.events.put(("up",))
                        self.events.put(("leave",))
                was_touching = touching if self.active else False
                if not touching:
                    pressure = 0.0
                touch_changed = moved = range_changed = False
