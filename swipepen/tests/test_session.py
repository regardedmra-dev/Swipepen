"""Headless end-to-end test: simulated pen strokes -> Session -> DryRunInjector."""
import random
from swipepen.engine import Decoder, KEY_CENTER, FUNCTION_KEYS, STRIP_CELLS, CANVAS_W
from swipepen.inject import DryRunInjector
from swipepen.lexicon import load_lexicon
from swipepen.session import Session
from swipepen.simulate import generate_swipe

lex = load_lexicon("en", force_fallback=True, verbose=False)
dec = Decoder(lex)
inj = DryRunInjector()
s = Session(dec, inj)
rng = random.Random(5)

def stroke(pts):
    s.pen_down(*pts[0])
    for p in pts[1:]:
        s.pen_move(*p)
    s.pen_up()

def swipe(word, sigma=0.15):
    stroke(generate_swipe(word, rng, sigma=sigma, offset=0.1))

def tap(x, y):
    stroke([(x, y), (x + 0.02, y)])

def key(name):
    x0, x1, y0, y1 = FUNCTION_KEYS[name]
    tap((x0 + x1) / 2, (y0 + y1) / 2)

def check(label, got, want):
    ok = got == want
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else f"  got {got!r} want {want!r}"))
    assert ok

swipe("hello"); swipe("world")
check("two swiped words, auto-spaced", inj.buffer, "hello world ")

key("period")
check("period removes the auto-space then adds '. '", inj.buffer, "hello world. ")
check("shift auto-armed after period", s.shift, True)

swipe("this")
check("shift capitalises next swiped word", inj.buffer, "hello world. This ")
check("shift consumed", s.shift, False)

key("backspace")
check("backspace after a swipe deletes the whole word", inj.buffer, "hello world. ")

# tap the letter 'a' directly (single letter words)
kx, ky = KEY_CENTER["a"]
tap(kx, ky)
check("tap on a letter types that letter", inj.buffer, "hello world. a")
key("space")
check("space after a tap (live fix capitalises the new sentence)", inj.buffer, "hello world. A ")

key("enter")
check("enter drops the trailing space then newline", inj.buffer, "hello world. A\n")

# candidate replacement: swipe something ambiguous then pick candidate 2
inj.buffer = ""; s.last = None; s.trailing_space = False; s.shift = False
swipe("good", sigma=0.3)
first = inj.buffer
alts = s.last.cands
if len(alts) > 1:
    w = CANVAS_W / STRIP_CELLS
    tap(w * 1 + w / 2, -0.5)    # second strip cell
    check("candidate tap replaces the word", inj.buffer, alts[1] + " ")
    print("   (swiped 'good': first choice", repr(first.strip()), "-> replaced by", repr(alts[1]), ")")

# swipes starting on a function key are ignored (no crash, no text)
before = inj.buffer
stroke([(5.0, 3.5), (3.0, 3.5), (1.0, 3.5)])
check("long stroke starting on space bar is ignored", inj.buffer, before)

# ---- edit gestures --------------------------------------------------------------
def drag(start, dx, steps=12):
    x, y = start
    pts = [(x + dx * i / steps, y) for i in range(steps + 1)]
    s.pen_down(*pts[0])
    for p in pts[1:]:
        s.pen_move(*p)
    return pts

def reset(text, pos=None):
    inj.buffer, inj.pos, inj.anchor = text, len(text) if pos is None else pos, None
    s.last, s.trailing_space, s.shift = None, False, False

BK = (9.5, 2.5)
reset("one two three four ")
drag(BK, -0.4); s.pen_up()
check("short left drag on backspace is just a backspace tap", inj.buffer, "one two three four")

reset("one two three four ")
drag(BK, -1.2)
check("1 word selected live", inj.selected_text(), "four ")
s.pen_up()
check("release erases 1 word", inj.buffer, "one two three ")

reset("one two three four ")
drag(BK, -3.0)
check("longer drag selects 3 words", inj.selected_text(), "two three four ")
s.pen_up()
check("release erases 3 words", inj.buffer, "one ")

reset("one two three four ")
s.pen_down(*BK)
for i in range(13):
    s.pen_move(BK[0] - 3.0 * i / 12, BK[1])
check("dragging far selects 3 words", inj.selected_text(), "two three four ")
for i in range(13):
    s.pen_move(BK[0] - 3.0 + 2.0 * i / 12, BK[1])
check("going back right reduces the selection", inj.selected_text(), "four ")
s.pen_up()
check("release erases only what is highlighted", inj.buffer, "one two three ")

reset("one two ")
drag(BK, -8.0); s.pen_up()
check("erasing more words than exist clears the text", inj.buffer, "")

reset("one two three ")
drag(BK, -2.0); s.pen_up()
swipe("hello")
check("typing after erasing continues normally", inj.buffer, "one hello ")
reset("a b ")
key("backspace")
check("backspace tap still works after gestures", inj.buffer, "a b")

reset("one two three ")
drag(BK, -2.0)
s.cancel_stroke()
check("cancel_stroke drops the highlight", inj.selected_text(), "")
check("cancel_stroke erases nothing", inj.buffer, "one two three ")

SP = (4.5, 3.5)
reset("hello world", pos=5)
drag(SP, -1.5); s.pen_up()
check("swipe left on space moves the caret left (a few characters)", 1 <= inj.pos <= 4, True)
check("no space typed after cursor move", inj.buffer, "hello world")
moved_left = inj.pos
drag(SP, 1.5); s.pen_up()
check("swipe right on space moves it right", (inj.pos > moved_left, inj.buffer), (True, "hello world"))

reset("ab", pos=1)
drag(SP, -0.9, steps=20)
s.pen_up()
check("caret moved to the start", inj.pos, 0)
swipe("hello")
check("swipe-typing after moving the caret inserts at the caret", inj.buffer, "hello ab")

reset("hi")
stroke([(4.5, 3.5), (4.6, 3.5), (4.7, 3.55)])
check("tiny wiggle on space is still a space tap", inj.buffer, "hi ")
reset("hi", pos=1)
tap(*SP)
check("space tap types a space at the caret", inj.buffer, "h i")

# ---- cursor momentum at the edge ------------------------------------------------
clock = [100.0]
s.clock = lambda: clock[0]

def sweep_to_edge(x0, x1, seconds, steps=10):
    s.pen_down(x0, 3.5)
    for i in range(1, steps + 1):
        clock[0] += seconds / steps
        s.pen_move(x0 + (x1 - x0) * i / steps, 3.5)

def hold(seconds, dt=0.016):
    start = inj.pos
    t = 0.0
    while t < seconds:
        clock[0] += dt
        s.tick()
        t += dt
    return start - inj.pos      # characters moved to the left

text = "word " * 400
reset(text)
sweep_to_edge(4.5, 0.0, 0.4)
at_edge = inj.pos
check("reaching the left edge moved the caret the normal way", at_edge < len(text), True)
first = hold(1.0)
check("holding the pen at the edge keeps the caret going", first > 10, True)
second = hold(1.0)
check("the longer it is held, the faster it goes", second > first, True)
later = hold(3.0) / 3
check("it speeds up but stays under the cap", second < later <= 71, True)
before = inj.pos
s.pen_move(3.0, 3.5)         # leave the edge
a = inj.pos
hold(1.0)
check("moving away from the edge stops the momentum", inj.pos, a)
s.pen_up()
check("lifting the pen types no space", inj.buffer, text)

reset(text)
sweep_to_edge(4.5, 0.0, 0.15)
fast = hold(0.5)
s.pen_up()
reset(text)
sweep_to_edge(4.5, 0.0, 1.5)
slow = hold(0.5)
s.pen_up()
check("a faster swipe into the edge starts faster (momentum)", fast > slow, True)

reset(text, pos=100)
sweep_to_edge(4.5, 10.0, 0.4)
p0 = inj.pos
moved = -hold(1.0)
check("the right edge scrolls to the right", moved > 10, True)
s.pen_up()

reset(text)
sweep_to_edge(4.5, 4.0, 0.2)
check("no momentum away from the edges", hold(1.0), 0)
s.pen_up()

reset(text)
sweep_to_edge(4.5, 0.0, 0.4)
hold(0.5)
s.cancel_stroke()
p = inj.pos
hold(1.0)
check("cancel_stroke stops the momentum", inj.pos, p)
s.clock = __import__("time").monotonic

print("\nAll session tests passed.")
