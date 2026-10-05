"""Next-word prediction, completions, learning, re-ranking and the strip; partial (unfinished) swipes; looseness."""
import os, random, tempfile
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
from swipepen import lexicon
from swipepen.engine import Decoder, FUNCTION_KEYS, KEY_CENTER
from swipepen.inject import DryRunInjector
from swipepen.predict import Predictor
from swipepen.session import Session
from swipepen.simulate import generate_swipe

def check(label, got, want=True):
    ok = got == want
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else f"  got {got!r} want {want!r}"))
    assert ok

dec = Decoder(lexicon.load_lexicon("en", force_fallback=True, verbose=False))
rng = random.Random(21)

# ---- Predictor ---------------------------------------------------------------------------------------------
p = Predictor(known=dec.logp, path=None)
check("thank -> you", p.next_words(["thank"], 3)[0], "you")
check("sentence start offers capitalised starters", p.next_words([], 3, sentence_start=True)[0][:1].isupper())
check("'i' is always capital", "I" in p.next_words([], 12, sentence_start=True) or "I" in p.next_words([], 12))
check("a word just used is not the first suggestion again", p.next_words(["thank", "you"], 3)[0] != "you" and "you" not in p.next_words(["you", "are"], 2))
check("unknown context still gives something (common words)", len(p.next_words(["zzyzx"], 3)) == 3)
p.learn(["purple", "elephant"]); p.learn(["purple", "elephant"])
check("it learns from what you write", p.next_words(["purple"], 3)[0], "elephant")
p.learn(["a", "purple", "monkey"]); p.learn(["a", "purple", "monkey"]); p.learn(["a", "purple", "monkey"])
check("triples beat pairs", p.next_words(["a", "purple"], 3)[0], "monkey")
check("learning off: nothing counted", (setattr(p, "learning", False), p.learn(["red", "fox"]), p.bi.get("red"))[2] in (None, {}) or not p.bi.get("red"))
p.learning = True
check("affinity: likely > unlikely", p.affinity(["thank"], "you") > p.affinity(["thank"], "banana") == 0.0)
check("completions that fit the context come first", p.rank_completions(["thanks", "thank", "thanksgiving"], ["thank"])[0] in ("thanks", "thank"))
path = os.path.join(tempfile.mkdtemp(), "phrases.json")
q = Predictor(known=dec.logp, path=path)
for _ in range(3): q.learn(["quantum", "banana"])
q.save()
q2 = Predictor(known=dec.logp, path=path)
check("learned phrases are saved and loaded", q2.next_words(["quantum"], 1) == ["banana"])
q2.forget()
check("forget wipes them (and the file)", not os.path.exists(path) and q2.next_words(["quantum"], 1) != ["banana"])

# ---- the strip in a Session ---------------------------------------------------------------------------------
def fresh():
    global inj, s
    inj = DryRunInjector(); s = Session(dec, inj)
    s.autofix = False; s.predict = True
    s.predictor = Predictor(known=dec.logp, path=None)
def swipe(w, sigma=0.06):
    pts = generate_swipe(w, rng, sigma=sigma, offset=0.03)
    s.pen_down(*pts[0]); [s.pen_move(*pt) for pt in pts[1:]]; s.pen_up()
def tap(x, y): s.pen_down(x, y); s.pen_move(x + 0.02, y); s.pen_up()
def cell(i): tap(2.5 * i + 1.25, -0.5)

fresh()
check("empty document, nothing known: the tools strip", s.strip()["mode"], "tools")
swipe("thank")
st = s.strip()
check("after a swipe the strip still offers the other readings", (st["mode"], st["cells"][0], st["chosen"]), ("cands", "thank", 0))
cell(0)
check("tapping the word already typed accepts it", inj.buffer, "thank ")
st = s.strip()
check("then the strip predicts the next word", (st["mode"], st["cells"][0], st["cells"][3]), ("predict", "you", "⋯"))
cell(0)
check("tapping a prediction types it with a space", inj.buffer, "thank you ")
st = s.strip()
check("and predicts again", st["mode"] == "predict" and st["cells"][0] != "")
first = st["cells"][1]
cell(1)
check("a paragraph by tapping only", inj.buffer, f"thank you {first} ")
check("the strip never lies about its words (tap = what it shows)", first in inj.buffer)
cell(3)
check("the fourth cell opens the tools", type(s.panel).__name__, "ToolsPanel")
s.close_panel()

fresh()
inj.type_text("Hello. "); s.inj.tail = "Hello. "; s.shift = True
st = s.strip()
check("after a full stop: capitalised starters", st["mode"] == "predict" and st["cells"][0][:1].isupper(), True)
w = st["cells"][0]
cell(0)
check("tapping it uses the capital", inj.buffer.endswith(w + " ") and s.shift is False)

fresh()
for ch in "pl":
    tap(*KEY_CENTER[ch])
st = s.strip()
check("tapped letters: completions of the unfinished word", st["mode"] == "complete" and all(c.startswith("pl") for c in st["cells"][:3] if c))
done = st["cells"][0]
cell(0)
check("tapping a completion replaces the letters", inj.buffer, done + " ")

fresh()
tap(*KEY_CENTER["p"])
check("one letter is too little to complete", s.strip()["mode"], "tools")
fresh(); s.predict = False
inj.type_text("thank "); s.inj.tail = "thank "
check("with prediction off the strip is the old tools strip", s.strip()["mode"], "tools")

# learning from what you swipe and type
fresh(); s.predictor = Predictor(known=dec.logp, path=None)
for _ in range(2):
    inj.type_text("purple "); s.inj.tail = "purple "
    s._function_key("space")
    swipe("elephant")
    s._function_key("space")
    s._function_key("period")
check("words you write are learned (swipe + space)", "elephant" in s.predictor.bi.get("purple", {}), True)

# ---- re-ranking swipe results by the word before -------------------------------------------------------------------
fresh()
inj.type_text("thank "); s.inj.tail = "thank "
re_ = s._rerank([("your", 1.00), ("you", 1.05), ("yours", 1.2)])
check("after 'thank', 'you' beats a slightly better-looking 'your'", re_[0][0], "you")
fresh(); s.predict = False
check("off: untouched", s._rerank([("your", 1.0), ("you", 1.05)])[0][0], "your")

# ---- unfinished swipes --------------------------------------------------------------------------------------------------
d2 = Decoder(lexicon.load_lexicon("en", force_fallback=True, verbose=False))
top = [w for w, _ in d2.decode(generate_swipe("tomor", random.Random(4), sigma=0.05, offset=0.03), k=5)]
check("swiping only 'tomor' finds 'tomorrow'", "tomorrow" in top)
top = [w for w, _ in d2.decode(generate_swipe("import", random.Random(4), sigma=0.05, offset=0.03), k=5)]
check("swiping 'import' also offers longer words", "important" in top)
for w in ("the", "that", "car", "for", "have", "with"):
    r = [x for x, _ in d2.decode(generate_swipe(w, random.Random(6), sigma=0.05, offset=0.03), k=3)]
    check(f"a finished word that starts a longer one still wins: {w}", r[0], w)
d3 = Decoder(lexicon.load_lexicon("en", force_fallback=True, verbose=False), partial=False)
check("partial matching can be switched off", [w for w, _ in d3.decode(generate_swipe("tomor", random.Random(4), sigma=0.05, offset=0.03), k=5)][:1] != ["tomorrow"])
d2.set_looseness(1.0)
check("looseness changes how forgiving the decoder is", (d2.endpoint_radius > 2.4, d2.partial_penalty < 0.1), (True, True))
d2.set_looseness(0.0)
check("...and back", (d2.endpoint_radius == 1.7, d2.looseness == 0.0), (True, True))
print("\nAll prediction / partial swipe tests passed.")
