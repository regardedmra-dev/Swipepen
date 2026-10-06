"""Looking after your hands: a stroke counter, break reminders and a "lighter touch" hint.

Swipepen exists because typing hurts, so it keeps an eye on how much work the pen hand does.
Everything here is local: the only thing ever written is a small file of daily stroke counts
(~/.config/swipepen/usage.json). No clock times, no text.

Break reminders
    The work timer counts the time between finished strokes. A pause between strokes counts only up to
    THINK_GAP seconds (you were thinking, the hand was still on the job). A pause of REST_GAP seconds or
    more is a real rest and the timer starts over. When the timer reaches the number of minutes you chose,
    a small panel offers to rest, snooze or skip. It only appears after the pen has been still for SETTLE
    seconds, never in the middle of a word, and it goes away by itself if you walk off and rest.

Pressure hint
    Pressing hard strains the finger joints and a swipe does not need it. The pen cursor changes colour
    with pressure (see trailfx.pressure_heat); after STREAK hard strokes in a row a short hint appears
    (at most once every COOLDOWN seconds).
"""
from __future__ import annotations

import datetime
import json
import os
import time

REST_GAP = 180.0          # seconds without a stroke that count as a real rest
THINK_GAP = 20.0          # a pause counts as work only up to this long
SETTLE = 1.5              # wait this long after the last stroke before showing the reminder
SNOOZE_MINUTES = 10
SAVE_EVERY = 25           # strokes between saves of the daily count (it is also saved when the window closes)
KEEP_DAYS = 60            # how many days of counts are kept


def usage_path() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "swipepen", "usage.json")


class Wellbeing:
    def __init__(self, clock=time.monotonic, today=None, path: str | None = None):
        self.clock = clock
        self._today = today or datetime.date.today
        self.path = path                       # None = keep nothing on disk (the window turns it on)
        self.break_minutes = 30                # 0 = no reminders
        self._last_on = 30                     # what "turn reminders back on" restores
        self.session_strokes = 0
        self.days: dict[str, int] = {}         # "2026-10-06": strokes
        self.active_s = 0.0                    # seconds of work since the last rest
        self.last_t: float | None = None       # when the last stroke ended
        self._next_at: float | None = None     # work seconds at which the reminder is due (None = break_minutes)
        self._unsaved = 0
        self.reminders = 0                     # reminders shown this session
        self.rests = 0                         # real rests this session (a pause of REST_GAP, or "taking a break")
        if path:
            self.load()

    # ---- settings -----------------------------------------------------------------------------------------
    def set_break_minutes(self, minutes: int) -> None:
        self.break_minutes = max(0, int(minutes))
        if self.break_minutes:
            self._last_on = self.break_minutes
        self._next_at = None

    @property
    def toggle_minutes(self) -> int:
        """What a plain on/off switch should switch to when turning reminders on."""
        return self._last_on

    # ---- counting ---------------------------------------------------------------------------------------------
    def today_key(self) -> str:
        return self._today().isoformat()

    @property
    def today_strokes(self) -> int:
        return self.days.get(self.today_key(), 0)

    @property
    def yesterday_strokes(self) -> int:
        return self.days.get((self._today() - datetime.timedelta(days=1)).isoformat(), 0)

    def stroke(self) -> None:
        """A stroke (tap, swipe or gesture) has just ended."""
        t = self.clock()
        if self.last_t is not None:
            gap = t - self.last_t
            if gap >= REST_GAP:
                self._rested()
            else:
                self.active_s += min(gap, THINK_GAP)
        self.last_t = t
        self.session_strokes += 1
        key = self.today_key()
        self.days[key] = self.days.get(key, 0) + 1
        self._unsaved += 1
        if self._unsaved >= SAVE_EVERY:
            self.save()

    def _rested(self) -> None:
        if self.active_s > 0:
            self.rests += 1
        self.active_s = 0.0
        self._next_at = None

    def idle_check(self, now: float) -> None:
        """Call often. Resting for REST_GAP seconds restarts the work timer even if no stroke follows."""
        if self.last_t is not None and self.active_s > 0 and now - self.last_t >= REST_GAP:
            self._rested()

    # ---- reminders ----------------------------------------------------------------------------------------------
    def _threshold(self) -> float:
        return self._next_at if self._next_at is not None else self.break_minutes * 60.0

    def due(self) -> bool:
        return self.break_minutes > 0 and self.active_s >= self._threshold()

    def ready(self, now: float) -> bool:
        """Due, and the pen has been still long enough that a panel will not land in the middle of a word."""
        return self.due() and self.last_t is not None and now - self.last_t >= SETTLE

    def shown(self) -> None:
        self.reminders += 1

    def snooze(self, minutes: int = SNOOZE_MINUTES) -> None:
        self._next_at = self.active_s + minutes * 60.0

    def skip(self) -> None:
        """Not now: ask again after a full interval of work."""
        self._next_at = self.active_s + max(1, self.break_minutes) * 60.0

    def take_break(self) -> None:
        self.active_s = 0.0
        self._next_at = None
        self.rests += 1
        self.last_t = self.clock()

    # ---- readout --------------------------------------------------------------------------------------------------
    def work_minutes(self) -> int:
        return int(self.active_s // 60)

    def summary(self) -> str:
        parts = [f"Strokes today: {self.today_strokes}"]
        if self.yesterday_strokes:
            parts.append(f"yesterday: {self.yesterday_strokes}")
        parts.append(f"writing {self.work_minutes()} min since a rest")
        return "   ".join(parts)

    # ---- saving ---------------------------------------------------------------------------------------------------------
    def load(self) -> None:
        if not self.path:
            return
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
            days = data.get("days", {})
            self.days = {str(k): int(v) for k, v in days.items() if isinstance(v, int) and v >= 0}
        except (OSError, ValueError, AttributeError, TypeError):
            self.days = {}

    def save(self) -> None:
        self._unsaved = 0
        if not self.path:
            return
        keep = sorted(self.days)[-KEEP_DAYS:]
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as fh:
                json.dump({"days": {k: self.days[k] for k in keep}}, fh, indent=1)
        except OSError:
            pass

    def clear_today(self) -> None:
        self.days.pop(self.today_key(), None)
        self.session_strokes = 0
        self.save()


class PressureMonitor:
    """Watches how hard each stroke was pressed. Pressure is 0..1 (a fraction of what the pen can report)."""
    STREAK = 4              # this many hard strokes in a row ...
    COOLDOWN = 90.0         # ... shows the hint, and then not again for this many seconds

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.enabled = True
        self.limit = 0.6            # at or above this a stroke counts as "hard"
        self.level = 0.0            # pressure right now (for colouring the pen cursor)
        self.peak = 0.0             # hardest point of the stroke in progress
        self._streak = 0
        self._hint_t = -1e9

    def feed(self, p: float) -> None:
        p = min(1.0, max(0.0, float(p)))
        self.level = p
        if p > self.peak:
            self.peak = p

    def abandon(self) -> None:
        """The stroke was cancelled: forget it without counting it."""
        self.level = self.peak = 0.0

    def end_stroke(self) -> bool:
        """The pen came up. True when it is time to show the hint."""
        hard = self.peak >= self.limit > 0
        self.level = self.peak = 0.0
        if not self.enabled:
            self._streak = 0
            return False
        self._streak = self._streak + 1 if hard else 0
        now = self.clock()
        if self._streak >= self.STREAK and now - self._hint_t >= self.COOLDOWN:
            self._streak = 0
            self._hint_t = now
            return True
        return False
