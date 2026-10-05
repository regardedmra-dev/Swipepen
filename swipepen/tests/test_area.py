"""Tablet-area mapping and pen routing, headless."""
import random
from swipepen.area import Area, PenRouter, to_units
from swipepen.engine import Decoder
from swipepen.inject import DryRunInjector
from swipepen.lexicon import load_lexicon
from swipepen.session import Session
from swipepen.simulate import generate_swipe

def check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else "  " + str(detail)))
    assert ok

# --- geometry ---------------------------------------------------------------
a = Area(aspect=1.6, size=0.5, cx=0.5, cy=0.5)
u0, v0, u1, v1 = a.rect()
check("50% area is 50% wide", abs((u1 - u0) - 0.5) < 1e-9)
check("height keeps the 2:1 keyboard shape (0.5*1.6/2 = 0.4)", abs((v1 - v0) - 0.4) < 1e-9, (v1 - v0))
check("area is centred", abs((u0 + u1) / 2 - 0.5) < 1e-9 and abs((v0 + v1) / 2 - 0.5) < 1e-9)
un, vn = a.map(0.5, 0.5)
check("tablet centre maps to keyboard centre", abs(un - 0.5) < 1e-9 and abs(vn - 0.5) < 1e-9)
a.set_center(0.0, 0.0)
r = a.rect()
check("area cannot leave the tablet (top-left)", abs(r[0]) < 1e-9 and abs(r[1]) < 1e-9, r)
a.set_center(2.0, 2.0)
r = a.rect()
check("area cannot leave the tablet (bottom-right)", abs(r[2] - 1) < 1e-9 and abs(r[3] - 1) < 1e-9, r)
a.set_size(5.0)
check("size is capped at 100%", a.size == 1.0)
a.set_size(0.01)
check("size has a minimum of 5%", abs(a.size - 0.05) < 1e-9, a.size)
tall = Area(aspect=0.5, size=1.0)
check("tall tablets never get an area taller than the tablet", tall.h <= 1.0)

# --- routing: typing through the area ------------------------------------------
lex = load_lexicon("en", force_fallback=True, verbose=False)
dec = Decoder(lex)
inj = DryRunInjector()
s = Session(dec, inj)
area = Area(aspect=1.6, size=0.45, cx=0.3, cy=0.7)     # small, bottom-left of the tablet
router = PenRouter(s, area, follow=False)
rng = random.Random(9)

def to_tablet(x, y):
    """key units -> tablet (u, v), the inverse of the router's mapping"""
    un, vn = x / 10.0, (y + 1.0) / 5.0
    u0, v0, _, _ = area.rect()
    return u0 + un * area.w, v0 + vn * area.h

def stroke_on_tablet(pts):
    tp = [to_tablet(x, y) for x, y in pts]
    router.handle(("hover", *tp[0]))
    router.handle(("down", *tp[0]))
    for p in tp[1:]:
        router.handle(("move", *p))
    router.handle(("up",))
    router.handle(("leave",))

for w in ("hello", "world"):
    stroke_on_tablet(generate_swipe(w, rng, sigma=0.15, offset=0.1))
check("swipes inside a small, off-centre area type correctly", inj.buffer == "hello world ", inj.buffer)

before = inj.buffer
router.handle(("down", 0.95, 0.05))            # touch far outside the area
for u, v in ((0.9, 0.1), (0.5, 0.5), (0.3, 0.7)):
    router.handle(("move", u, v))
router.handle(("up",))
check("a touch that starts outside the area is ignored", inj.buffer == before, inj.buffer)

# a stroke that starts inside and drifts outside is clamped, not dropped
pts = generate_swipe("this", rng, sigma=0.1, offset=0.05)
tp = [to_tablet(x, y) for x, y in pts]
router.handle(("down", *tp[0]))
for p in tp[1:]:
    router.handle(("move", *p))
router.handle(("move", 0.0, 0.0))              # wander off the corner at the end
router.handle(("up",))
check("a stroke that drifts outside still ends cleanly (no crash, no stuck pen)", s.pen_down_now is False)
print("   typed so far:", repr(inj.buffer))

router.handle(("hover", 0.99, 0.01))
check("hovering outside the area hides the on-keyboard pointer", s.hover_pos is None)
check("minimap still knows where the pen is", router.pen_uv == (0.99, 0.01))

# --- follow mode ---------------------------------------------------------------------
f_area = Area(aspect=1.6, size=0.3, cx=0.5, cy=0.5)          # 0.3 wide, 0.24 tall
moved = []
fs = Session(dec, DryRunInjector())
fr = PenRouter(fs, f_area, follow=True, on_moved=lambda: moved.append(1))

fr.handle(("hover", 0.5, 0.5))
check("first hover inside the area does not move it", not moved and abs(f_area.cx - 0.5) < 1e-9)

fr.handle(("hover", 0.72, 0.5))                              # past the right edge (0.65)
u0, v0, u1, v1 = f_area.rect()
check("pushing past the right edge drags the area along", abs(u1 - 0.72) < 1e-9 and moved, f_area.rect())
check("pen sits at the keyboard's right edge after the push", fs.hover_pos is not None and abs(fs.hover_pos[0] - 10.0) < 1e-6, fs.hover_pos)

fr.handle(("hover", 0.72, 0.9))                              # past the bottom edge
check("pushing past the bottom edge drags the area down", abs(f_area.rect()[3] - 0.9) < 1e-9, f_area.rect())

c_before = (f_area.cx, f_area.cy)
fr.handle(("down", 0.80, 0.9))                               # touching: outside the area on the right
fr.handle(("move", 0.95, 0.5))
fr.handle(("up",))
check("the area does not move during a stroke / touch", (f_area.cx, f_area.cy) == c_before)

fr.handle(("leave",))
fr.handle(("hover", 0.15, 0.15))
check("after lifting the pen away and back, the area jumps to centre on the pen",
      abs(f_area.cx - 0.15) < 1e-9 or f_area.rect()[0] == 0.0, f_area.rect())
un, vn = f_area.map(0.15, 0.15)
check("... and the pen is inside it", 0 <= un <= 1 and 0 <= vn <= 1, (un, vn))

# swiping still works after the area has been dragged around
fs2 = DryRunInjector(); sess2 = Session(dec, fs2)
a2 = Area(aspect=1.6, size=0.3, cx=0.5, cy=0.5); r2 = PenRouter(sess2, a2, follow=True)
r2.handle(("hover", 0.5, 0.5)); r2.handle(("hover", 0.9, 0.2)); r2.handle(("hover", 0.2, 0.8))
def to_tab2(x, y):
    u0, v0, _, _ = a2.rect()
    return u0 + (x / 10) * a2.w, v0 + ((y + 1) / 5) * a2.h
pts2 = [to_tab2(x, y) for x, y in generate_swipe("write", rng, sigma=0.12, offset=0.05)]
r2.handle(("hover", *pts2[0])); r2.handle(("down", *pts2[0]))
for p in pts2[1:]: r2.handle(("move", *p))
r2.handle(("up",))
check("typing works after the area followed the pen to a new place", fs2.buffer == "write ", fs2.buffer)

# follow off: the old behaviour (area stays put)
a3 = Area(aspect=1.6, size=0.3, cx=0.5, cy=0.5); r3 = PenRouter(Session(dec, DryRunInjector()), a3, follow=False)
r3.handle(("hover", 0.5, 0.5)); r3.handle(("hover", 0.9, 0.9))
check("with follow off the area stays where it is", (a3.cx, a3.cy) == (0.5, 0.5))
print("\nAll area tests passed.")

# --- very small keyboards still decode (accuracy depends on the hand, not the code) ---------
tiny = Area(aspect=1.6, size=0.05, cx=0.5, cy=0.5)
check("a 5% keyboard is allowed", abs(tiny.w - 0.05) < 1e-9, tiny.w)
check("... and still has the 2:1 shape (0.05*1.6/2 = 0.04)", abs(tiny.h - 0.04) < 1e-9, tiny.h)
t_inj = DryRunInjector(); t_sess = Session(dec, t_inj); t_router = PenRouter(t_sess, tiny, follow=True)
t_router.handle(("hover", 0.5, 0.5))
def to_tab_tiny(x, y):
    u0, v0, _, _ = tiny.rect()
    return u0 + (x / 10) * tiny.w, v0 + ((y + 1) / 5) * tiny.h
pts = [to_tab_tiny(x, y) for x, y in generate_swipe("hello", random.Random(21), sigma=0.12, offset=0.05)]
t_router.handle(("hover", *pts[0])); t_router.handle(("down", *pts[0]))
for p in pts[1:]: t_router.handle(("move", *p))
t_router.handle(("up",))
check("a swipe on a 5% keyboard types the word (when the hand is steady)", t_inj.buffer == "hello ", t_inj.buffer)
print("\nTiny-keyboard test passed.")

# --- tall keys (key shape 1.5 like Gboard) ----------------------------------------------------
ka_area = Area(aspect=1.6, size=0.5, cx=0.5, cy=0.5, key_aspect=1.5)
check("tall keys: 50% wide area is 0.5*1.6*5*1.5/10 = 0.6 of the tablet tall", abs(ka_area.h - 0.6) < 1e-9, ka_area.h)
ka_area.set_size(1.0)
check("tall keys: at 100% the area is shrunk to fit the tablet and keeps its shape",
      abs(ka_area.h - 1.0) < 1e-9 and abs(ka_area.w - 1 / 1.2) < 1e-9, (ka_area.w, ka_area.h))
ka_area.set_size(0.2)
dec15 = Decoder(lex, ys=1.5)
k_inj = DryRunInjector(); k_sess = Session(dec15, k_inj); k_router = PenRouter(k_sess, ka_area, follow=True)
def to_tab_ka(x, y):
    u0, v0, _, _ = ka_area.rect()
    return u0 + (x / 10) * ka_area.w, v0 + ((y + 1) / 5) * ka_area.h
for w in ("hello", "world", "write"):
    kp = [to_tab_ka(x, y) for x, y in generate_swipe(w, rng, sigma=0.12, offset=0.05, ka=1.5)]
    k_router.handle(("hover", *kp[0])); k_router.handle(("down", *kp[0]))
    for p in kp[1:]: k_router.handle(("move", *p))
    k_router.handle(("up",)); k_router.handle(("hover", 0.5, 0.5))
check("swiping on a tall-key keyboard types the words", k_inj.buffer == "hello world write ", k_inj.buffer)

# ---- a config saved by 0.5.1 (Shift+F10) moves to the new Docs menu key once ---------------------------------------
import json as _json, os, tempfile
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
from swipepen.area import config_path as _cp, load_config as _lc, save_config as _sc
os.makedirs(os.path.dirname(_cp()), exist_ok=True)
with open(_cp(), "w") as fh:
    _json.dump({"size": 0.4, "docs_menu_key": "shift+f10"}, fh)
c = _lc()
check("old config: Shift+F10 is replaced by the new default, other settings stay", (c["docs_menu_key"], c["size"]) == ("ctrl+shift+\\", 0.4), c)
c["docs_menu_key"] = "shift+f10"; _sc(c)
check("a key chosen afterwards is kept", _lc()["docs_menu_key"] == "shift+f10")
print("\nTall-key tests passed.")
