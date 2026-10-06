"""Exercise pen.py and inject.py against a fake `evdev` module (no hardware needed)."""
import sys, types, itertools

# ---- fake evdev --------------------------------------------------------------
codes = types.SimpleNamespace(EV_SYN=0, EV_KEY=1, EV_REL=2, REL_WHEEL=8, REL_WHEEL_HI_RES=11, EV_ABS=3, SYN_REPORT=0, ABS_X=0, ABS_Y=1,
                              BTN_TOOL_PEN=0x140, BTN_TOUCH=0x14a, BTN_STYLUS=0x14b, BTN_STYLUS2=0x14c)
_n = itertools.count(1000)
for name in ["KEY_" + c.upper() for c in "abcdefghijklmnopqrstuvwxyz"] + [
        "KEY_SPACE", "KEY_COMMA", "KEY_DOT", "KEY_APOSTROPHE", "KEY_MINUS",
        "KEY_BACKSPACE", "KEY_ENTER", "KEY_LEFTSHIFT", "KEY_LEFTCTRL", "KEY_LEFT", "KEY_RIGHT", "KEY_UP", "KEY_DOWN", "KEY_F7", "KEY_F10", "KEY_TAB", "KEY_ESC",
        "KEY_LEFTALT", "KEY_DELETE", "KEY_HOME", "KEY_END", "KEY_EQUAL", "KEY_LEFTBRACE", "KEY_RIGHTBRACE",
        "KEY_BACKSLASH", "KEY_SEMICOLON", "KEY_SLASH", "KEY_GRAVE"] + ["KEY_%d" % i for i in range(10)]:
    setattr(codes, name, next(_n))

class Ev:
    def __init__(self, type, code, value): self.type, self.code, self.value = type, code, value

class UInput:
    last = None
    def __init__(self, caps, name=""): self.log = []; UInput.last = self
    def write(self, t, c, v): self.log.append((c, v))
    def syn(self): pass
    def close(self): pass

class AbsInfo:
    def __init__(self, mn, mx): self.min, self.max = mn, mx

class InputDevice:
    name, path = "Wacom Bamboo Pen Pen", "/dev/input/event7"
    script = []
    def __init__(self, path=None): pass
    def capabilities(self, **kw):
        return {codes.EV_ABS: [(codes.ABS_X, None), (codes.ABS_Y, None)],
                codes.EV_KEY: [codes.BTN_TOOL_PEN, codes.BTN_TOUCH, codes.BTN_STYLUS, codes.BTN_STYLUS2]}
    def absinfo(self, code): return AbsInfo(0, 1000) if code == codes.ABS_X else AbsInfo(0, 500)
    def grab(self): self.grabbed = True
    def ungrab(self): self.grabbed = False
    def read_loop(self): return iter(InputDevice.script)

fake = types.ModuleType("evdev")
fake.UInput, fake.InputDevice, fake.list_devices, fake.ecodes = UInput, InputDevice, (lambda: ["/dev/input/event7"]), codes
sys.modules["evdev"] = fake
sys.modules["evdev.ecodes"] = codes
fake.__dict__["ecodes"] = codes

from swipepen.inject import UInputInjector
from swipepen.pen import PenReader

def check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else "  " + str(detail)))
    assert ok

# ---- injector ------------------------------------------------------------------
import swipepen.inject as inj_mod
inj_mod.time.sleep = lambda *_: None
inj = UInputInjector("us")
inj.type_text("Hi, a")
log = UInput.last.log
presses = [c for c, v in log if v == 1]
expect = [codes.KEY_LEFTSHIFT, codes.KEY_H, codes.KEY_I, codes.KEY_COMMA, codes.KEY_SPACE, codes.KEY_A]
check("type_text presses shift+h, i, comma, space, a in order", presses == expect, presses)
check("every key press is released", sorted(c for c, v in log if v == 1) == sorted(c for c, v in log if v == 0))
inj.backspace(2); inj.enter()
check("backspace x2 then enter", [c for c, v in UInput.last.log if v == 1][-3:] ==
      [codes.KEY_BACKSPACE, codes.KEY_BACKSPACE, codes.KEY_ENTER])
check("es layout moves apostrophe to KEY_MINUS",
      UInputInjector("es").keymap["'"] == codes.KEY_MINUS and inj.keymap["'"] == codes.KEY_APOSTROPHE)

inj.ui.log.clear()
inj.move_cursor(-2); inj.move_cursor(1)
check("move_cursor presses Left x2 then Right",
      [c for c, v in inj.ui.log if v == 1] == [codes.KEY_LEFT, codes.KEY_LEFT, codes.KEY_RIGHT])
inj.ui.log.clear()
inj.select_word_left()
check("select_word_left is Ctrl+Shift+Left (modifiers held around the arrow)",
      inj.ui.log == [(codes.KEY_LEFTCTRL, 1), (codes.KEY_LEFTSHIFT, 1), (codes.KEY_LEFT, 1),
                          (codes.KEY_LEFT, 0), (codes.KEY_LEFTSHIFT, 0), (codes.KEY_LEFTCTRL, 0)],
      inj.ui.log)
inj.ui.log.clear()
inj.collapse_selection()
check("collapse_selection is Right arrow", [c for c, v in inj.ui.log if v == 1] == [codes.KEY_RIGHT])

# ---- symbols, key combos, mouse wheel ----------------------------------------------------------
inj3 = UInputInjector("us")
inj3.type_text("a1!?-")
log3 = inj3.ui.log
check("US symbols use key codes: a 1 shift+1 shift+/ -",
      [c for c, v in log3 if v == 1] == [codes.KEY_A, codes.KEY_1, codes.KEY_LEFTSHIFT, codes.KEY_1,
                                         codes.KEY_LEFTSHIFT, codes.KEY_SLASH, codes.KEY_MINUS], log3)
inj3.ui.log.clear()
inj3.press("ctrl+z"); inj3.press("f7"); inj3.press("ctrl+'"); inj3.press("shift+tab")
check("press() sends combos",
      [c for c, v in inj3.ui.log if v == 1] == [codes.KEY_LEFTCTRL, codes.KEY_Z, codes.KEY_F7, codes.KEY_LEFTCTRL,
                                                codes.KEY_APOSTROPHE, codes.KEY_LEFTSHIFT, codes.KEY_TAB], inj3.ui.log)
class FakeClip2:
    kind = "fake"
    def __init__(self): self.value = "keep"; self.history = []
    def get(self): return self.value
    def set(self, t): self.value = t; self.history.append(t)
    def clear(self): self.value = None
inj4 = UInputInjector("latam"); inj4.clip = FakeClip2()
inj4.type_text("¿")
check("other layouts / unknown characters are pasted (Ctrl+V) and the clipboard is restored",
      (inj4.clip.history[0], inj4.clip.value, codes.KEY_V in [c for c, v in inj4.ui.log if v == 1]), ("¿", "keep", True))
inj5 = UInputInjector("us")
inj5.scroll(0.25)
inj5.scroll(1.0)
wheel = inj5.wheel
hires = [v for c, v in wheel.log if c == codes.REL_WHEEL_HI_RES]
notch = [v for c, v in wheel.log if c == codes.REL_WHEEL]
check("scroll(+) turns the wheel toward 'down': high-resolution events", hires == [-30, -120], hires)
check("... and whole notches are reported too", notch == [-1, -1][:len(notch)] and len(notch) == 1, notch)

# ---- reading the document through the clipboard (fake clipboard tool) ------------------------
import swipepen.inject as im
class FakeClip:
    kind = "fake"
    def __init__(self): self.value = "my old clipboard"; self.sets = []
    def get(self): return self.value
    def set(self, t): self.value = t; self.sets.append(t)
    def clear(self): self.value = None
clip = FakeClip()
inj.clip = clip
doc = "teh paragraph"
real_tap = inj._tap
def fake_tap(code, mods=()):
    real_tap(code, mods)
    if code == codes.KEY_C and codes.KEY_LEFTCTRL in mods and not clip.nocopy:
        clip.value = doc        # the app copies the selection
clip.nocopy = False
inj._tap = fake_tap
inj.ui.log.clear()
text = inj.grab_paragraph_before()
presses = [c for c, v in inj.ui.log if v == 1]
check("grab_paragraph_before returns the document text", text == "teh paragraph", text)
check("it pressed Ctrl+Shift+Up, Ctrl+C, then Right to drop the selection",
      presses == [codes.KEY_LEFTCTRL, codes.KEY_LEFTSHIFT, codes.KEY_UP, codes.KEY_LEFTCTRL, codes.KEY_C, codes.KEY_RIGHT], presses)
check("the old clipboard was put back", clip.value == "my old clipboard", clip.value)
clip.nocopy = True
inj.ui.log.clear()
check("nothing selected -> empty text", inj.grab_word_before() == "")
check("... and no stray Right arrow was pressed", codes.KEY_RIGHT not in [c for c, v in inj.ui.log if v == 1])
inj.clip.kind = None
try:
    inj.grab_word_before(); check("no clipboard tool -> readable error", False)
except RuntimeError as e:
    check("no clipboard tool -> readable error", "wl-clipboard" in str(e))

# ---- pen reader ------------------------------------------------------------------
E = Ev
SYN = E(codes.EV_SYN, codes.SYN_REPORT, 0)
def pos(x, y): return [E(codes.EV_ABS, codes.ABS_X, x), E(codes.EV_ABS, codes.ABS_Y, y)]

InputDevice.script = (
    [E(codes.EV_KEY, codes.BTN_TOOL_PEN, 1)] + pos(100, 100) + [SYN] +          # enters range: hover
    pos(500, 250) + [SYN] +                                                       # hover
    [E(codes.EV_KEY, codes.BTN_TOUCH, 1)] + [SYN] +                               # pen down
    pos(600, 250) + [SYN] + pos(700, 300) + [SYN] +                               # drag
    [E(codes.EV_KEY, codes.BTN_TOUCH, 0)] + [SYN] +                               # pen up
    [E(codes.EV_KEY, codes.BTN_STYLUS2, 1)] + [SYN] +                             # side button
    [E(codes.EV_KEY, codes.BTN_TOOL_PEN, 0)] + [SYN]                              # leaves range
)
r = PenReader()
check("auto-picks stylus2 toggle when the pen has it", r.toggle_code == codes.BTN_STYLUS2)
r.set_active(True)
r.run()
evs = []
while not r.events.empty():
    evs.append(r.events.get())
kinds = [e[0] for e in evs]
print("   events:", kinds)
check("sequence hover,hover,down,move,move,up,toggle,leave",
      kinds == ["hover", "hover", "down", "move", "move", "up", "toggle", "leave"], kinds)
check("coordinates normalised to 0..1", abs(evs[1][1] - 0.5) < 1e-9 and abs(evs[1][2] - 0.5) < 1e-9, evs[1])

# inactive: only the toggle button gets through
r2 = PenReader(); r2.set_active(False)
r2.run()
kinds2 = []
while not r2.events.empty():
    kinds2.append(r2.events.get()[0])
check("while paused only the toggle button is reported", kinds2 == ["toggle"], kinds2)
InputDevice.script = [E(codes.EV_KEY, codes.BTN_STYLUS, 1), SYN, E(codes.EV_KEY, codes.BTN_STYLUS, 0), SYN]
r3 = PenReader(); r3.set_active(True); r3.run()
check("the other side button (not the toggle) reports 'tidy'", r3.events.get() == ("tidy",) and r3.events.empty())
print("\nAll evdev-stub tests passed.")

# ---- rotation / left-handed mode ---------------------------------------------------
InputDevice.script = (
    [E(codes.EV_KEY, codes.BTN_TOOL_PEN, 1)] + pos(100, 100) + [SYN]
)
def first_hover(rotate):
    rr = PenReader(rotate=rotate); rr.set_active(True); rr.run()
    return rr, rr.events.get()

r0, e0 = first_hover(0)
r180, e180 = first_hover(180)
r90, e90 = first_hover(90)
check("rotate 0: (100,100) of 1000x500 -> (0.1, 0.2)", abs(e0[1] - 0.1) < 1e-9 and abs(e0[2] - 0.2) < 1e-9, e0)
check("left-handed (180): the same touch lands on the opposite corner", abs(e180[1] - 0.9) < 1e-9 and abs(e180[2] - 0.8) < 1e-9, e180)
check("rotate 90 swaps the tablet aspect", abs(r90.aspect - 1 / r0.aspect) < 1e-9, (r0.aspect, r90.aspect))
r0.set_rotate(180)
check("rotation can be changed while running", r0.rotate == 180 and abs(r0.aspect - 2.0) < 1e-9)
print("\nAll rotation tests passed.")

# ---- pen pressure (optional) ------------------------------------------------------------------------
rn = PenReader()
check("a pen without ABS_PRESSURE reports no pressure (events keep their old shape)", rn.pmax == 0)
codes.ABS_PRESSURE = 24
_caps, _abs = InputDevice.capabilities, InputDevice.absinfo
InputDevice.capabilities = lambda self, **kw: {codes.EV_ABS: [(codes.ABS_X, None), (codes.ABS_Y, None), (codes.ABS_PRESSURE, None)],
                                               codes.EV_KEY: [codes.BTN_TOOL_PEN, codes.BTN_TOUCH, codes.BTN_STYLUS, codes.BTN_STYLUS2]}
InputDevice.absinfo = lambda self, code: AbsInfo(0, 1000) if code == codes.ABS_X else AbsInfo(0, 500) if code == codes.ABS_Y else AbsInfo(0, 1023)
def press(v): return [E(codes.EV_ABS, codes.ABS_PRESSURE, v)]
InputDevice.script = (
    [E(codes.EV_KEY, codes.BTN_TOOL_PEN, 1)] + pos(100, 100) + [SYN] +                       # hover
    press(200) + [E(codes.EV_KEY, codes.BTN_TOUCH, 1)] + [SYN] +                              # down, pressure 200
    press(1023) + pos(600, 250) + [SYN] +                                                     # move, full pressure
    press(0) + [E(codes.EV_KEY, codes.BTN_TOUCH, 0)] + [SYN] +                               # up
    [E(codes.EV_KEY, codes.BTN_TOOL_PEN, 0)] + [SYN]
)
rp = PenReader()
check("a pen with ABS_PRESSURE: the range is read", rp.pmax == 1023, rp.pmax)
rp.set_active(True); rp.run()
evp = []
while not rp.events.empty():
    evp.append(rp.events.get())
check("hover carries no pressure, down and move carry it as a 4th number",
      [len(e) for e in evp] == [3, 4, 4, 1, 1] and [e[0] for e in evp] == ["hover", "down", "move", "up", "leave"], evp)
check("pressure is normalised to 0..1", abs(evp[1][3] - 200 / 1023) < 1e-3 and evp[2][3] == 1.0, evp)
InputDevice.capabilities, InputDevice.absinfo = _caps, _abs
print("\nAll pressure tests passed.")
