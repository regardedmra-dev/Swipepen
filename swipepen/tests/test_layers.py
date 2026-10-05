"""Numbers & symbols layers, caps lock, undo, typewriter scrolling."""
import os, random, tempfile
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
from swipepen import lexicon
from swipepen.engine import Decoder, FUNCTION_KEYS, SYM_CENTER, KEY_CENTER, classify
from swipepen.inject import DryRunInjector
from swipepen.session import Session
from swipepen.simulate import generate_swipe

def check(label, got, want=True):
    ok = got == want
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else f"  got {got!r} want {want!r}"))
    assert ok

dec = Decoder(lexicon.load_lexicon("en", force_fallback=True, verbose=False))
rng = random.Random(11)
t = [100.0]
def fresh():
    global inj, s
    inj = DryRunInjector(); s = Session(dec, inj); s.clock = lambda: t[0]
def swipe(w, sigma=0.08):
    pts = generate_swipe(w, rng, sigma=sigma, offset=0.04); s.pen_down(*pts[0]); [s.pen_move(*p) for p in pts[1:]]; s.pen_up()
def tap(x, y): s.pen_down(x, y); s.pen_move(x + 0.02, y); s.pen_up()
def key(n): x0, x1, y0, y1 = FUNCTION_KEYS["shift" if n == "page" else n]; tap((x0 + x1) / 2, (y0 + y1) / 2)
def letter(c): tap(*KEY_CENTER[c])
def sym(c, layer="sym1"): tap(*SYM_CENTER[layer][c])
def drag(start, dx, steps=12):
    x, y = start
    s.pen_down(x, y)
    for i in range(1, steps + 1): s.pen_move(x + dx * i / steps, y)

# ---- number & symbol layers -------------------------------------------------------------------
fresh()
key("sym")
check("?123 opens the symbol layer", s.layer, "sym1")
for c in "2025": sym(c)
check("digits are typed", inj.buffer, "2025")
sym("-"); sym("1"); sym("2")
check("symbols from the first page", inj.buffer, "2025-12")
key("page")
check("the shift key flips to the second symbol page", s.layer, "sym2")
sym("[", "sym2"); sym("¿", "sym2")
check("second page symbols (incl. ¿)", inj.buffer, "2025-12[¿")
key("sym")
check("ABC goes back to letters", s.layer, "letters")
key("sym"); key("space")
check("space in a symbol layer returns to letters", s.layer, "letters")

fresh()
swipe("hello")
key("sym"); sym("!")
check("! hugs the word and starts a new one", inj.buffer, "hello! ")
check("... and the next letter is a capital", s.shift, True)
fresh()
swipe("hello"); key("sym"); sym("?")
check("? likewise", inj.buffer, "hello? ")
fresh()
swipe("write"); key("sym"); sym(":")
check(": hugs the word", inj.buffer, "write: ")
fresh()
swipe("price"); key("sym"); sym("$"); sym("5")
check("$ and a number go after the word's space", inj.buffer, "price $5")
fresh()
key("sym"); sym("("); 
key("sym"); swipe("write"); key("sym"); sym(")")
check("( word ) closes tight", inj.buffer, "(write)")
fresh()
key("sym")
pts = generate_swipe("hello", rng, sigma=0.05, offset=0.02)
s.pen_down(*pts[0]); [s.pen_move(*p) for p in pts[1:]]; s.pen_up()
check("swiping on a symbol layer types nothing", inj.buffer, "")
check("backspace still works in the symbol layer", (sym("1"), key("backspace"), inj.buffer)[2], "")
check("the apostrophe key is the same on every layer", classify(2.5, 3.5, "sym1"), ("key", "apostrophe"))

# ---- caps lock ------------------------------------------------------------------------------------
fresh()
key("shift"); t[0] += 0.2; key("shift")
check("double-tap shift: caps lock", (s.caps, s.shift), (True, False))
swipe("hello"); letter("a")
check("caps lock: swiped words and letters in capitals", inj.buffer, "HELLO A")
swipe("world")
check("caps lock stays on", (inj.buffer.endswith("WORLD "), s.caps), (True, True))
t[0] += 5; key("shift")
check("one tap turns it off", (s.caps, s.shift), (False, False))
swipe("again")
check("back to lowercase", inj.buffer.endswith("again "), True)
fresh()
key("shift"); t[0] += 2.0; key("shift")
check("two slow taps = shift on then off (not caps)", (s.caps, s.shift), (False, False))
fresh()
key("shift"); t[0] += 0.2; key("shift"); swipe("think")
inj2 = inj.buffer
check("caps word candidate pick keeps capitals", inj2.strip().isupper(), True)
if len(s.last.cands) > 1:
    tap(2.5 * 1 + 1.25, -0.5)
    check("picking another candidate keeps the capitals", inj.buffer.strip().isupper(), True)

# ---- undo -------------------------------------------------------------------------------------------
fresh()
for c in "dont": letter(c)
key("space")
check("live fix happened", inj.buffer, "don't ")
check("undo is available", s.can_undo(), True)
key("backspace")
check("Backspace right after a fix takes the fix back", inj.buffer, "dont ")
for c in "go": letter(c)
key("space")
check("the reverted word stays as typed", inj.buffer, "dont go ")

fresh()
for c in "dont": letter(c)
key("space")
s.undo()
check("undo() reverts a live fix", inj.buffer, "dont ")
check("... and then nothing more to undo", s.undo(), False)

fresh()
inj.buffer = "i am hel lo"; inj.pos = len(inj.buffer)
s.tidy()
check("tidy ran", inj.buffer, "I am hello")
check("tidy can be undone", s.can_undo(), True)
tap(1.25, -0.5)                                   # strip cell 0 = undo
check("tapping undo in the strip restores the paragraph", (inj.buffer, inj.pos), ("i am hel lo", len("i am hel lo")))

fresh()
inj.buffer = "one two three "; inj.pos = len(inj.buffer)
drag((9.5, 2.5), -2.0); s.pen_up()
check("erase ran", inj.buffer, "one ")
tap(1.25, -0.5)
check("undo after erase brings the words back (editor Ctrl+Z)", inj.buffer, "one two three ")

fresh()
for c in "dont": letter(c)
key("space"); letter("a")
check("typing something else makes undo unavailable", s.can_undo(), False)

# ---- typewriter scrolling -----------------------------------------------------------------------------
fresh()
s.set_typewriter(True, chars_per_line=20, notches_per_line=0.5)
inj.scrolled = 0.0
s.inj.type_text("x" * 19); s.inj.flush_scroll()
check("no scrolling while the text stays on one line", inj.scrolled, 0.0)
s.inj.type_text("xx"); s.inj.flush_scroll()
check("running onto a new line scrolls half a notch down", inj.scrolled, 0.5)
s.inj.type_text("y" * 40); s.inj.flush_scroll()
check("two more lines", inj.scrolled, 1.5)
s.inj.enter(); s.inj.flush_scroll()
check("Enter is a line too", inj.scrolled, 2.0)
s.inj.backspace(1); s.inj.flush_scroll()
check("backspacing onto the previous line scrolls back up", inj.scrolled, 1.5)
fresh()
s.set_typewriter(True, 40, 0.5); inj.scrolled = 0.0
swipe("hello"); swipe("world"); swipe("think"); swipe("write")
check("a few short words: still no scroll", inj.scrolled, 0.0)
for w in ("write", "hello", "world", "think", "write", "hello"): swipe(w)
check("a swiping session scrolls as lines fill", inj.scrolled > 0, True)
s.set_typewriter(False)
before = inj.scrolled
swipe("hello"); swipe("world"); swipe("write"); swipe("think")
check("switched off: no more scrolling", inj.scrolled, before)

print("\nAll layer / caps / undo / scroll tests passed.")
