"""Stroke counter, break reminders and the pressure hint: the logic, and how a Session uses it."""
import datetime, json, os, tempfile
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
from swipepen import lexicon
from swipepen.area import DEFAULTS, PenRouter, Area, config_path, load_config, save_config
from swipepen.engine import Decoder
from swipepen.inject import DryRunInjector
from swipepen.panels import BreakPanel
from swipepen.session import Session
from swipepen.wellbeing import (REST_GAP, SETTLE, SNOOZE_MINUTES, THINK_GAP, PressureMonitor, Wellbeing)

def check(label, got, want=True):
    """check(label, got, want) compares; check(label, condition, detail) takes a True/False and shows the detail."""
    if isinstance(got, bool) and not isinstance(want, bool):
        ok, shown = got, f"  detail: {want!r}"
    else:
        ok, shown = got == want, f"  got {got!r} want {want!r}"
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else shown))
    assert ok

class Clock:
    def __init__(self, t=1000.0): self.t = t
    def __call__(self): return self.t
    def advance(self, s): self.t += s

# ---- the stroke counter ---------------------------------------------------------------------------
clk = Clock()
day = [datetime.date(2026, 10, 6)]
w = Wellbeing(clock=clk, today=lambda: day[0])
check("starts at zero", (w.session_strokes, w.today_strokes, w.active_s), (0, 0, 0.0))
for _ in range(5):
    clk.advance(2); w.stroke()
check("each stroke is counted, for the session and for today", (w.session_strokes, w.today_strokes), (5, 5))
check("a 2 second gap counts as 2 seconds of work (the first stroke only starts the clock)", w.active_s, 8.0)
check("the summary mentions today's strokes and the work time", "Strokes today: 5" in w.summary() and "writing 0 min" in w.summary(), w.summary())
day[0] = datetime.date(2026, 10, 7)
w.stroke()
check("a new day starts a new count", (w.today_strokes, w.yesterday_strokes), (1, 5))
check("the summary shows yesterday too", "yesterday: 5" in w.summary())
w.clear_today()
check("clear_today resets today only", (w.today_strokes, w.yesterday_strokes, w.session_strokes), (0, 5, 0))

# ---- work time: thinking pauses count only a little, a real rest resets ---------------------------------------------
clk = Clock(); w = Wellbeing(clock=clk)
w.stroke(); clk.advance(THINK_GAP * 3); w.stroke()
check("a long pause counts as at most THINK_GAP seconds of work", w.active_s, THINK_GAP)
clk.advance(REST_GAP - 1); w.stroke()
check("a pause just under REST_GAP is not a rest", w.rests == 0 and w.active_s == 2 * THINK_GAP, (w.rests, w.active_s))
clk.advance(REST_GAP); w.stroke()
check("a pause of REST_GAP is a real rest: the work timer starts over", (w.active_s, w.rests), (0.0, 1))
clk.advance(5); w.stroke()
check("...and counts again from there", w.active_s, 5.0)
clk.advance(REST_GAP + 10); w.idle_check(clk())
check("resting without touching the pen again also resets (idle_check)", (w.active_s, w.rests), (0.0, 2))
w.idle_check(clk() + 9999)
check("idle_check with nothing to reset does nothing", w.rests, 2)

# ---- due / ready / snooze / skip / take a break ------------------------------------------------------------------------
def worked(minutes, w, clk, every=10.0):
    n = int(minutes * 60 / every)
    for _ in range(n):
        clk.advance(every); w.stroke()
clk = Clock(); w = Wellbeing(clock=clk); w.set_break_minutes(30)
w.stroke(); worked(29, w, clk)
check("not due before the time is up", w.due(), False)
worked(1.1, w, clk)
check("due once 30 minutes of work are done", w.due() and w.work_minutes() >= 30)
check("...but not ready right away: the pen must be still for SETTLE seconds", w.ready(clk()), False)
check("...ready after SETTLE seconds", w.ready(clk() + SETTLE + 0.01), True)
w.snooze()
check("snooze: not due now", w.due(), False)
worked(SNOOZE_MINUTES - 0.5, w, clk)
check("snooze: still not due just before the snooze is over", w.due(), False)
worked(1, w, clk)
check("snooze: due again after SNOOZE_MINUTES more work", w.due(), True)
w.skip()
worked(29, w, clk)
check("skip: a full interval of work before the next one", w.due(), False)
worked(2, w, clk)
check("skip: ...then due again", w.due(), True)
w.take_break()
check("taking a break resets the timer and counts a rest", (w.active_s, w.due(), w.rests), (0.0, False, 1))
w.set_break_minutes(0)
worked(120, w, clk)
check("0 minutes = never due", w.due(), False)
check("turning reminders back on restores the last interval", w.toggle_minutes, 30)
w.set_break_minutes(45); w.set_break_minutes(0)
check("...the last one chosen", w.toggle_minutes, 45)

# ---- saving ---------------------------------------------------------------------------------------------------------------------
path = os.path.join(tempfile.mkdtemp(), "sub", "usage.json")
clk = Clock(); w = Wellbeing(clock=clk, today=lambda: datetime.date(2026, 10, 6), path=path)
for _ in range(3):
    clk.advance(1); w.stroke()
check("nothing is written for every stroke", os.path.exists(path), False)
w.save()
data = json.load(open(path))
check("the file holds daily counts only", data, {"days": {"2026-10-06": 3}})
w2 = Wellbeing(clock=clk, today=lambda: datetime.date(2026, 10, 6), path=path)
check("they are read back", w2.today_strokes, 3)
for _ in range(25):
    clk.advance(1); w2.stroke()
check("the count is also saved every 25 strokes", json.load(open(path))["days"]["2026-10-06"] >= 25)
open(path, "w").write("not json{{")
check("a damaged file is ignored, not fatal", Wellbeing(path=path).today_strokes, 0)
open(path, "w").write(json.dumps({"days": {"2026-10-01": 4, "bad": "x", "2026-10-02": -3}}))
check("odd entries are dropped", Wellbeing(path=path).days, {"2026-10-01": 4})
many = Wellbeing(path=path, today=lambda: datetime.date(2026, 10, 6))
many.days = {f"2026-{m:02d}-{d:02d}": 1 for m in (1, 2, 3, 4) for d in range(1, 29)}
many.save()
check("only the last 60 days are kept", len(json.load(open(path))["days"]), 60)
check("no path = nothing on disk", Wellbeing().save(), None)

# ---- pressure monitor ---------------------------------------------------------------------------------------------------------------
clk = Clock(); pm = PressureMonitor(clock=clk); pm.limit = 0.6
def stroke_at(p):
    pm.feed(p); return pm.end_stroke()
check("light strokes never trigger the hint", [stroke_at(0.2) for _ in range(10)], [False] * 10)
check("3 hard strokes are not enough", [stroke_at(0.9) for _ in range(3)], [False] * 3)
check("the 4th hard stroke in a row triggers the hint", stroke_at(0.9), True)
check("...and then it stays quiet (cooldown), however hard", [stroke_at(0.95) for _ in range(10)], [False] * 10)
clk.advance(PressureMonitor.COOLDOWN + 1)
check("after the cooldown, still pressing hard: the next hard stroke brings the hint back", [stroke_at(0.9) for _ in range(4)], [True, False, False, False])
clk.advance(1000)
stroke_at(0.9); stroke_at(0.9); stroke_at(0.9); stroke_at(0.1)
check("one light stroke breaks the streak", stroke_at(0.9), False)
pm.feed(0.4); pm.feed(0.95); pm.feed(0.3)
check("the peak of the stroke counts, not the last sample", pm.peak, 0.95)
check("level is the latest sample", pm.level, 0.3)
pm.abandon()
check("abandon forgets the stroke without counting it", (pm.level, pm.peak), (0.0, 0.0))
pm.enabled = False
check("switched off: never a hint", [stroke_at(0.99) for _ in range(10)], [False] * 10)
pm.enabled = True
check("pens without pressure never trigger it", [pm.end_stroke() for _ in range(10)], [False] * 10)
pm.feed(5); pm.feed(-2)
check("pressure is clamped to 0..1", (pm.peak, pm.level), (1.0, 0.0))

# ---- inside a Session ------------------------------------------------------------------------------------------------------------------------
dec = Decoder(lexicon.load_lexicon("en", force_fallback=True, verbose=False))
def fresh():
    global inj, s, clk
    inj = DryRunInjector(); clk = Clock()
    s = Session(dec, inj); s.clock = clk
    s.well.set_break_minutes(30)
def tap(x, y):
    s.pen_down(x, y); s.pen_move(x + 0.02, y); s.pen_up()
def work(minutes, every=10.0):
    for _ in range(int(minutes * 60 / every)):
        clk.advance(every); tap(5.0, 1.5)
fresh()
tap(5.0, 1.5); tap(1.0, 1.5)
check("taps are counted as strokes", (s.well.session_strokes, s.well.today_strokes), (2, 2))
s.pen_down(2.0, 1.5); s.pen_move(3.0, 1.5)
check("a stroke still going on is not counted yet", s.well.session_strokes, 2)
s.cancel_stroke()
check("a cancelled stroke is not counted", s.well.session_strokes, 2)
s.pen_down(2.0, 1.5); s.pen_move(3.0, 1.5); s.pen_move(4.0, 1.5); s.pen_up()
check("a swipe is one stroke", s.well.session_strokes, 3)

fresh(); work(31)
check("after 31 minutes of writing, the break is due", s.well.due())
s.tick()
check("...but the panel waits until the pen has been still", s.panel is None)
clk.advance(SETTLE + 0.1); s.tick()
check("then the break panel opens", isinstance(s.panel, BreakPanel) and s.well.reminders == 1)
texts = [b.text for b in s.panel.layout()]
check("it offers rest, snooze and skip", "Take a break now" in texts and any(t.startswith("Remind me in") for t in texts) and any(t.startswith("Skip this one") for t in texts), texts)
check("its title says how long you have been writing", any("min of writing" in b.text and "strokes today" in b.text for b in s.panel.layout()))
s.tick(); s.tick()
check("it does not open twice", s.well.reminders == 1)

def tap_box(text_start):
    b = next(b for b in s.panel.layout() if b.text.startswith(text_start))
    tap((b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2)
tap_box("Remind me in")
check("tapping 'remind me' closes it and snoozes", s.panel is None and not s.well.due())
clk.advance(SETTLE + 1); s.tick()
check("no panel while snoozed", s.panel is None)
work(SNOOZE_MINUTES + 1); clk.advance(SETTLE + 0.1); s.tick()
check("it comes back after the snooze", isinstance(s.panel, BreakPanel) and s.well.reminders == 2)
typed_before = inj.buffer
tap_box("Take a break now")
check("tapping 'take a break' closes it, resets the timer and says so", s.panel is None and s.well.active_s == 0 and s.message == "rest well")
check("nothing was typed by tapping the panel", inj.buffer == typed_before)

fresh(); work(31); clk.advance(SETTLE + 0.1); s.tick()
tap_box("Skip this one")
check("'skip' waits a whole interval", s.panel is None and not s.well.due())
work(29); check("...still quiet after 29 minutes of work", not s.well.due())
work(2); check("...due after 31", s.well.due())

fresh(); work(31); clk.advance(SETTLE + 0.1); s.tick()
s.close_panel()
check("closing the panel without choosing snoozes it a few minutes", s.panel is None and not s.well.due())
work(6); clk.advance(SETTLE + 0.1); s.tick()
check("...and it asks again", isinstance(s.panel, BreakPanel))

fresh(); work(31); clk.advance(SETTLE + 0.1); s.tick()
clk.advance(REST_GAP + 1); s.tick()
check("if you walk away and rest, the panel closes by itself", s.panel is None and s.well.active_s == 0)
clk.advance(5); tap(5.0, 1.5); s.tick(); clk.advance(5); s.tick()
check("...and does not come back", s.panel is None)

fresh(); work(31)
s.pen_down(5.0, 1.5)
clk.advance(SETTLE + 5); s.tick()
check("never while the pen is down", s.panel is None)
s.pen_up(); clk.advance(SETTLE + 0.1); s.tick()
check("...but right after it comes up and rests", isinstance(s.panel, BreakPanel))

fresh(); work(31)
s.open_tools(); clk.advance(SETTLE + 1); s.tick()
check("another panel is never pushed aside", type(s.panel).__name__ == "ToolsPanel")
s.close_panel(); s.tick()
check("...the reminder comes once it is closed", isinstance(s.panel, BreakPanel))

fresh(); s.well.set_break_minutes(0); work(120); clk.advance(SETTLE + 1); s.tick()
check("reminders off: no panel", s.panel is None)
fresh(); s.set_setting("break_minutes", 15); work(16); clk.advance(SETTLE + 0.1); s.tick()
check("set_setting('break_minutes') changes the interval", isinstance(s.panel, BreakPanel))
seen = []
fresh(); s.on_setting = lambda n, v: seen.append((n, v)); s.set_setting("break_minutes", 20)
check("the window is told about the change (it saves it)", seen, [("break_minutes", 20)])

# ---- the tools panel ---------------------------------------------------------------------------------------------------------------------------
fresh(); s.open_tools()
def ttexts(): return [b.text for b in s.panel.layout()]
s.panel.next()
check("tools: break reminders row shows the interval", "Break reminders: every 30 min" in ttexts(), ttexts())
check("tools: stroke summary row", any(t.startswith("Strokes today:") for t in ttexts()), ttexts())
check("tools: pressure hint row", "Lighter-touch hint: ON" in ttexts(), ttexts())
tap_box("Break reminders")
check("tapping the row turns reminders off", s.well.break_minutes == 0)
s.panel.next() if s.panel.page == 0 else None
check("...and the row says so", "Break reminders: off" in ttexts(), ttexts())
tap_box("Break reminders")
check("...tapping again restores the interval", s.well.break_minutes == 30)
tap_box("Lighter-touch hint")
check("tapping the pressure row switches it off", s.pressure.enabled is False)

# ---- pressure through the session -----------------------------------------------------------------------------------------------------------------
fresh(); s.pressure.limit = 0.6
def hard_tap():
    s.set_pressure(0.9); tap(5.0, 1.5)
for _ in range(3): hard_tap()
check("3 hard taps: no hint", s.hint_text, "")
hard_tap()
check("the 4th shows the hint", s.hint_text == "lighter touch is enough" and s.hint_until > clk(), (s.hint_text, s.hint_until))
check("...for a couple of seconds", 1.0 <= s.hint_until - clk() <= 5.0)
fresh()
for _ in range(10): s.set_pressure(0.2); tap(5.0, 1.5)
check("light taps: never", s.hint_text, "")
fresh(); s.set_setting("pressure_hint", False)
for _ in range(10): hard_tap()
check("switched off in settings: never", s.hint_text, "")
fresh(); s.set_setting("pressure_limit", 0.9)
for _ in range(10): s.set_pressure(0.8); tap(5.0, 1.5)
check("a higher limit setting is respected", s.hint_text, "")
fresh(); s.pen_down(5.0, 1.5); s.set_pressure(0.7); s.pen_move(5.1, 1.5)
check("the live pressure is available to the window", abs(s.pressure.level - 0.7) < 1e-9)
s.pen_up()
check("...and is zero after the stroke", s.pressure.level, 0.0)

# ---- the router passes pressure on ----------------------------------------------------------------------------------------------------------------------
class Spy(Session):
    pass
fresh(); area = Area(1.6, 1.0, 0.5, 0.5, key_aspect=1.0); router = PenRouter(s, area)
router.handle(("hover", 0.5, 0.5)); router.handle(("down", 0.5, 0.5, 0.42)); router.handle(("move", 0.55, 0.5, 0.81))
check("down / move events with a 4th number feed the pressure monitor", abs(s.pressure.peak - 0.81) < 1e-9, s.pressure.peak)
router.handle(("up",))
fresh(); router = PenRouter(s, area)
router.handle(("down", 0.5, 0.5)); router.handle(("move", 0.55, 0.5)); router.handle(("up",))
check("pens that report no pressure work as before", (s.pressure.peak, s.well.session_strokes), (0.0, 1))
class Bare:                                                          # a stub session without pressure support
    def __init__(self): self.log = []; self.hover_pos = None
    def pen_down(self, x, y): self.log.append("down")
    def pen_move(self, x, y): self.log.append("move")
    def pen_up(self): self.log.append("up")
    def hover(self, x, y): pass
bare = Bare(); r = PenRouter(bare, area)
r.handle(("down", 0.5, 0.5, 0.5)); r.handle(("move", 0.5, 0.5, 0.5)); r.handle(("up",))
check("a session without set_pressure is fine", bare.log, ["down", "move", "up"])

# ---- settings: defaults, clamping, saving ------------------------------------------------------------------------------------------------------------------
check("defaults: trail and highlights on, reminders every 30 minutes, pressure hint on at 0.6",
      (DEFAULTS["show_trail"], DEFAULTS["highlight_keys"], DEFAULTS["break_minutes"], DEFAULTS["pressure_hint"], DEFAULTS["pressure_limit"]),
      (True, True, 30, True, 0.6))
cfg = load_config()
check("an old config file without the new keys gets the defaults",
      (cfg["show_trail"], cfg["highlight_keys"], cfg["break_minutes"], cfg["pressure_hint"], cfg["pressure_limit"]), (True, True, 30, True, 0.6))
os.makedirs(os.path.dirname(config_path()), exist_ok=True)
json.dump({"size": 0.4, "break_minutes": 500, "pressure_limit": 0.01, "show_trail": False}, open(config_path(), "w"))
cfg = load_config()
check("break_minutes is clamped to 0..120", cfg["break_minutes"], 120)
check("pressure_limit is clamped to 0.2..1", cfg["pressure_limit"], 0.2)
check("a switched-off trail is remembered", cfg["show_trail"], False)
json.dump({"break_minutes": -5, "pressure_limit": 7}, open(config_path(), "w"))
cfg = load_config()
check("...both ends", (cfg["break_minutes"], cfg["pressure_limit"]), (0, 1.0))
save_config(cfg)
check("they survive a save", json.load(open(config_path()))["break_minutes"], 0)

print("\nAll wellbeing tests passed.")
