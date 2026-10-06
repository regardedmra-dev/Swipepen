"""Swipe trail and key highlights (trailfx.py): pure logic, no Tk."""
import os, tempfile
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
from swipepen.engine import CANVAS_W, FUNCTION_KEYS, KEY_CENTER, SYM_CENTER
from swipepen.trailfx import (CHUNKS, GHOST_SECONDS, MAX_VISITED, MIN_HEAT, TrailTracker, key_rect, lerp_hex,
                              pressure_heat)

def check(label, got, want=True):
    ok = got == want
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else f"  got {got!r} want {want!r}"))
    assert ok

# ---- colours ------------------------------------------------------------------------------------------
check("lerp_hex: ends", (lerp_hex("#000000", "#ffffff", 0), lerp_hex("#000000", "#ffffff", 1)), ("#000000", "#ffffff"))
check("lerp_hex: middle", lerp_hex("#000000", "#ffffff", 0.5), "#808080")
check("lerp_hex: t is clamped", (lerp_hex("#102030", "#ffffff", -3), lerp_hex("#102030", "#ffffff", 9)), ("#102030", "#ffffff"))
check("pressure_heat scales to the limit", (pressure_heat(0.3, 0.6), pressure_heat(0.6, 0.6), pressure_heat(0.9, 0.6), pressure_heat(0, 0.6)),
      (0.5, 1.0, 1.0, 0.0))
check("pressure_heat with a zero limit is 'hard'", pressure_heat(0.1, 0), 1.0)

# ---- key rectangles ---------------------------------------------------------------------------------------
cx, cy = KEY_CENTER["h"]
check("a letter's rectangle surrounds its centre", key_rect("letter", "h"), (cx - 0.47, cy - 0.47, cx + 0.47, cy + 0.47))
sx, sy = SYM_CENTER["sym1"]["5"]
check("a symbol's rectangle uses the symbol layer", key_rect("sym", "5", "sym1"), (sx - 0.47, sy - 0.47, sx + 0.47, sy + 0.47))
x0, x1, y0, y1 = FUNCTION_KEYS["space"]
check("a function key's rectangle", key_rect("key", "space"), (x0 + 0.03, y0 + 0.03, x1 - 0.03, y1 - 0.03))
check("'page' is the shift key's place on the symbol layers", key_rect("key", "page", "sym1"), key_rect("key", "shift"))
check("the suggestion strip has no highlight rectangle", key_rect("cand", 2), None)
every = [key_rect("letter", ch) for ch in KEY_CENTER] + [key_rect("key", n) for n in FUNCTION_KEYS]
check("every rectangle is well-formed and inside the keyboard",
      all(r[0] < r[2] and r[1] < r[3] and r[0] >= 0 and r[2] <= CANVAS_W and r[1] >= 0 and r[3] <= 4.0 for r in every))

# ---- following a stroke ---------------------------------------------------------------------------------------
t = TrailTracker()
check("nothing drawn before any stroke", t.segments(0.0), [])
check("a single point (a tap) draws nothing", (t.update([(5.5, 1.5)], 0.0), t.segments(0.0)), (None, []))
stroke = [(1.0, 1.5), (2.0, 1.5), (3.0, 1.5), (4.0, 1.5)]               # a, s, d, f
t.update(stroke[:2], 1.0)
t.update(stroke, 1.1)
check("the tracker copies the points and stamps them", (t.pts, t.stamps), (stroke, [1.0, 1.0, 1.1, 1.1]))
check("keys passed over are remembered in order", t.visited, [("letter", "a"), ("letter", "s"), ("letter", "d"), ("letter", "f")])
t.update(stroke + [(3.0, 1.5)], 1.2)
check("passing a key again does not list it twice", len(t.visited), 4)

segs = t.segments(1.2)
check("the trail is drawn as a few pieces", 1 <= len(segs) <= CHUNKS)
check("every piece has at least two points", all(len(p) >= 2 for p, h, w in segs))
check("pieces share their end points (no gaps)", all(segs[i][0][-1] == segs[i + 1][0][0] for i in range(len(segs) - 1)))
check("together the pieces cover the whole path", segs[0][0][0] == t.pts[0] and segs[-1][0][-1] == t.pts[-1])
heats = [h for p, h, w in segs]
check("older pieces are dimmer, the newest is full strength", heats == sorted(heats) and heats[-1] == 1.0 and heats[0] >= MIN_HEAT - 1e-9)
widths = [w for p, h, w in segs]
check("older pieces are thinner", widths == sorted(widths) and widths[-1] == 1.0 and widths[0] < 1.0)

long = [(0.5 + i * 0.01, 1.5) for i in range(300)]
t2 = TrailTracker(); t2.update(long, 0.0)
check("a 300-point stroke is still only CHUNKS pieces (cheap to redraw)", len(t2.segments(0.0)), CHUNKS)
check("...and covers all points", sum(len(p) - 1 for p, h, w in t2.segments(0.0)), 299)
two = TrailTracker(); two.update([(1, 1), (2, 1)], 0.0)
check("a two-point stroke is one piece", len(two.segments(0.0)), 1)

# ---- pen up: the ghost fades, then goes ---------------------------------------------------------------------------
t.update([], 2.0)
ghost = t.segments(2.0)
check("right after pen-up the stroke is still shown (the ghost) at full strength", len(ghost) > 0 and ghost[-1][1] == 1.0)
half = t.segments(2.0 + GHOST_SECONDS / 2)
check("the ghost fades with time", half[-1][1] < ghost[-1][1] and abs(half[-1][1] - 0.5) < 1e-9)
check("the ghost is gone after GHOST_SECONDS", t.segments(2.0 + GHOST_SECONDS + 0.01), [])
check("...and stays gone", t.segments(2.0), [])
check("visited keys are forgotten at pen-up", t.visited, [])

# a tap never leaves a ghost
t3 = TrailTracker(); t3.update([(5.5, 1.5)], 0.0); t3.update([], 0.1)
check("a tap leaves no ghost", t3.segments(0.1), [])

# ---- a new stroke starts clean, even without an empty frame in between ----------------------------------------------
t4 = TrailTracker()
t4.update([(1.0, 1.5), (2.0, 1.5), (3.0, 1.5)], 0.0)
t4.update([(7.0, 1.5), (8.0, 1.5)], 0.02)                                   # different start, shorter: new stroke
check("a new stroke replaces the old points", t4.pts, [(7.0, 1.5), (8.0, 1.5)])
check("...and its keys", t4.visited, [("letter", "j"), ("letter", "k")])
check("...the old one becomes the ghost only while no new stroke is on", len(t4.segments(0.03)) == 1 and t4.segments(0.03)[0][0][0] == (7.0, 1.5))

# ---- highlights ---------------------------------------------------------------------------------------------------------
t5 = TrailTracker()
t5.update([(1.0, 1.5), (2.0, 1.5), (3.0, 1.5)], 0.0)                        # a s d, pen on d
hl = t5.highlights((3.0, 1.5))
check("highlights: visited keys and the current one", [(r, k, v) for _, r, k, v in hl], [("visited", "letter", "a"), ("visited", "letter", "s"), ("current", "letter", "d")])
check("the current key is listed last, so it is drawn on top", hl[-1][1] == "current")
check("no visited keys when asked not to show them", [r for _, r, k, v in t5.highlights((3.0, 1.5), show_visited=False)], ["current"])
check("hovering (no stroke) lights only the key under the pen", [(r, v) for _, r, k, v in TrailTracker().highlights((6.0, 1.5))], [("current", "h")])
check("hovering over a function key lights it", [(r, k, v) for _, r, k, v in TrailTracker().highlights((5.0, 3.5))], [("current", "key", "space")])
check("pen over the suggestion strip lights nothing", TrailTracker().highlights((5.0, -0.5)), [])
check("pen out of range lights nothing", TrailTracker().highlights(None), [])
tf = TrailTracker(); tf.update([(1.0, 1.5), (9.0, 2.5), (5.0, 3.5)], 0.0)    # passes over a, backspace, space
check("only letters count as swiped-over keys (not backspace / space)", tf.visited, [("letter", "a")])
check("symbol layer keys are tracked on their own layer",
      (lambda tt: (tt.update([(0.5, 0.5), (1.5, 0.5)], 0.0, "sym1"), tt.visited)[1])(TrailTracker()), [("sym", "1"), ("sym", "2")])
ts = TrailTracker(); ts.update([(1.0, 1.5), (2.0, 1.5)], 0.0, "letters"); ts.update([(1.0, 1.5), (2.0, 1.5)], 0.1, "sym1")
check("switching layer forgets the keys passed over", ts.visited, [])
off = TrailTracker(track_keys=False); off.update([(1.0, 1.5), (2.0, 1.5), (3.0, 1.5)], 0.0)
check("with highlighting off no keys are tracked (the trail still is)", (off.visited, len(off.segments(0.0)) > 0), ([], True))
wild = TrailTracker(); wild.update([(x % 10 + 0.5, (x // 10) % 3 + 0.5) for x in range(0, 400, 1)], 0.0)
check("the list of visited keys is bounded", len(wild.visited) <= MAX_VISITED)
wild.clear()
check("clear() forgets everything, ghost included", (wild.pts, wild.visited, wild.ghost, wild.segments(0.0)), ([], [], None, []))

print("\nAll trail / highlight tests passed.")
