"""Typo fixing (tidy.py), apostrophes, personal dictionary, live fixes and the 'tidy' action."""
import os, random, tempfile

os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
from swipepen import lexicon, tidy
from swipepen.engine import Decoder, FUNCTION_KEYS, KEY_CENTER, classify
from swipepen.inject import DryRunInjector
from swipepen.session import Session
from swipepen.simulate import generate_swipe

def check(label, got, want=True):
    ok = got == want
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else f"  got {got!r} want {want!r}"))
    assert ok

dec = Decoder(lexicon.load_lexicon("en", force_fallback=True, verbose=False))
lp = dec.logp
fix = lambda t, **kw: tidy.fix_text(t, lp, **kw)

# ---- pure text fixes -----------------------------------------------------------------
check("hel lo -> hello", fix("say hel lo now"), "say hello now")
check("hell o -> hello", fix("say hell o now"), "say hello now")
check("hel l o -> hello (three pieces)", fix("hel l o"), "hello")
check("two real words stay apart (in to)", fix("log in to it"), "log in to it")
check("a b c list is left alone", fix("a b c"), "a b c")
check("lone i and contractions", fix("i think i'm late and i'll go"), "I think I'm late and I'll go")
check("i inside words untouched", fix("this is it"), "this is it")
check("missing apostrophes", fix("dont go, im here, thats it"), "don't go, I'm here, that's it")
check("capital kept: Dont", fix("Dont go"), "Don't go")
check("classic typos", fix("teh cat recieve it"), "the cat receive it".replace("receive", "receive"))
check("repeated word", fix("the the cat"), "the cat")
check("'that that' is allowed", fix("so that that works"), "so that that works")
check("double space and space before comma", fix("a  b , c"), "a b, c")
check("capital after a full stop", fix("it ended. then it began"), "it ended. Then it began")
check("no capital after e.g. / etc.", fix("e.g. this and etc. that"), "e.g. this and etc. that")
check("sentence start only when asked", (fix("hello there"), fix("hello there", sentence_start=True)), ("hello there", "Hello there"))
check("curly apostrophe: I’m", fix("i’m here"), "I’m here")
check("already-correct text is unchanged", fix("Hello world. This is fine."), "Hello world. This is fine.")
check("edits(): split word", tidy.edits("hel lo", "hello"), [(3, 4, "")])
check("edits(): apostrophe", tidy.edits("dont", "don't"), [(3, 3, "'")])

# ---- apostrophe key + contractions in the swipe decoder -------------------------------------
x0, x1, y0, y1 = FUNCTION_KEYS["apostrophe"]
check("the apostrophe key is on the bottom row", classify((x0 + x1) / 2, 3.5), ("key", "apostrophe"))
rng = random.Random(3)
ranked = [w for w, _ in dec.decode(generate_swipe("dont", rng, sigma=0.12, offset=0.05), k=5)]
check("swiping d-o-n-t offers don't first", ranked[:1], ["don't"])
check("the bare typo 'dont' is not offered", "dont" not in ranked)

inj = DryRunInjector()
s = Session(dec, inj)
def swipe(w, sigma=0.12): 
    pts = generate_swipe(w, rng, sigma=sigma, offset=0.05); s.pen_down(*pts[0]); [s.pen_move(*p) for p in pts[1:]]; s.pen_up()
def tap(x, y): s.pen_down(x, y); s.pen_move(x + 0.02, y); s.pen_up()
def key(n): tap((FUNCTION_KEYS[n][0] + FUNCTION_KEYS[n][1]) / 2, (FUNCTION_KEYS[n][2] + FUNCTION_KEYS[n][3]) / 2)
def letter(c): tap(*KEY_CENTER[c])

swipe("dont")
check("swipe types don't with its apostrophe", inj.buffer, "don't ")

inj.buffer = ""; inj.pos = 0; s.last = None; s.trailing_space = False; s.inj.tail = ""
for c in "don": letter(c)
key("apostrophe"); letter("t")
check("tap letters + apostrophe key", inj.buffer, "don't")
key("space")
check("space after that", inj.buffer, "don't ")

swipe("hello")
key("apostrophe")
check("apostrophe after a swiped word replaces the auto space", inj.buffer, "don't hello'")

# ---- the "i" glued to the next word ------------------------------------------------------------
check("iwant -> I want", fix("iwant it"), "I want it")
check("iwasnt -> I wasn't", fix("iwasnt there"), "I wasn't there")
check("curly apostrophe: iwasn’t -> I wasn’t", fix("iwasn’t there"), "I wasn’t there")
check("idon’t think -> I don’t think", fix("idon’t think"), "I don’t think")
check("ithink / iknow / ilove", fix("ithink iknow ilove"), "I think I know I love")
check("real words that start with i are left alone", fix("ipad iron island ill"), "ipad iron island ill")

# a word list that, like a big frequency list, also contains the bare typos
bigdec = Decoder(lexicon.load_lexicon("en", force_fallback=True, verbose=False)
                 + [("dont", "dont", -3.0), ("isnt", "isnt", -3.5), ("wasnt", "wasnt", -3.5)])
for w, want in (("dont", "don't"), ("isnt", "isn't"), ("wasnt", None)):
    got = [x for x, _ in bigdec.decode(generate_swipe(w, random.Random(5), sigma=0.1, offset=0.05), k=5)]
    check(f"bare typo {w!r} is never offered", w not in got, True)
    if want:
        check(f"... and {want!r} is", want in got, True)
check("the contraction exists even when the word list lacks it",
      Decoder([("hello", "hello", -4.0), ("dont", "dont", -3.0)]).logp("don't") is not None)

# ---- live fixes ------------------------------------------------------------------------------
def fresh(autofix=True):
    global inj, s
    inj = DryRunInjector(); s = Session(dec, inj); s.autofix = autofix

fresh()
for c in "hel": letter(c)
key("space")
for c in "lo": letter(c)
key("space")
check("live: 'hel lo ' becomes 'hello '", inj.buffer, "hello ")
fresh()
dec.partial = False                                  # (with partial matching on, swiping "thin" already offers "think")
swipe("thin", sigma=0.03); letter("k"); key("space")
dec.partial = True
check("live: swiped 'thin' + tapped k -> think", inj.buffer, "think ")
fresh()
letter("i"); key("space")
check("live: a lone i becomes I", inj.buffer, "I ")
fresh()
swipe("think"); letter("i"); key("space")
check("live: ... think I", inj.buffer, "think I ")
fresh(autofix=False)
letter("i"); key("space")
check("autofix off: left as typed", inj.buffer, "i ")
fresh()
key("period"); letter("a"); key("space")
check("live: sentence start capital after a period", inj.buffer, ". A ")
fresh()
swipe("hello"); inj.move_cursor(-3); s.inj.tail = ""  # caret moved: nothing we typed is rewritten
check("live: nothing typed since the caret moved, nothing to fix", s.inj.tail, "")

# tapped "i" then swiped words (the case that gave "iwant", "idon't")
fresh()
letter("i")
for w in ("want", "think"):
    swipe(w, sigma=0.08)
check("tap i + swipe: a space goes in between, and the lone i becomes I", inj.buffer, "I want think ")
fresh()
letter("i"); swipe("dont", sigma=0.08)
check("tap i + swipe dont -> I don't", inj.buffer, "I don't ")
fresh()
for c in "ab": letter(c)
swipe("think", sigma=0.08)
check("a swipe after tapped letters starts a new word", inj.buffer, "ab think ")
fresh()
swipe("think", sigma=0.08)
check("a swipe after a swipe: single space", inj.buffer, "think ")
fresh()
for c in "dont": letter(c)
key("space")
for c in "isnt": letter(c)
key("space")
check("live: tapped 'dont isnt ' -> don't isn't", inj.buffer, "don't isn't ")
fresh()
inj.buffer = "iwant dont isnt iwasnt "; inj.pos = len(inj.buffer); s.tidy()
check("tidy on the reported text", inj.buffer, "I want don't isn't I wasn't ")

# ---- tidy: text that is already in the document ------------------------------------------------
fresh()
inj.buffer = "First line stays.\ni think hel lo wor ld, dont  worry"
inj.pos = len(inj.buffer)
s.tidy()
check("tidy fixes the whole paragraph before the caret",
      inj.buffer, "First line stays.\nI think hello world, don't worry")
check("tidy leaves the caret where it was (at the end)", inj.pos, len(inj.buffer))
check("tidy reports", s.message.startswith("tidied"))

fresh()
inj.buffer = "teh start. then more. end of text"
inj.pos = len("teh start. then more.")
s.tidy()
check("tidy in the middle: edits before the caret, text after is untouched, caret stays",
      (inj.buffer, inj.pos), ("The start. Then more. end of text", len("The start. Then more.")))
s.tidy()
check("tidy again: nothing to fix", s.message, "tidy: nothing to fix")

fresh()
inj.buffer = "Done.\n"; inj.pos = len(inj.buffer)
s.tidy()
check("tidy at the start of a paragraph reaches into the previous one", s.message, "tidy: nothing to fix")
inj.buffer = "teh end.\n"; inj.pos = len(inj.buffer); s.tidy()
check("... and fixes it", inj.buffer, "The end.\n")

fresh()
inj.buffer = ""; s.tidy()
check("tidy with nothing there", s.message, "tidy: nothing before the cursor")

# strip tools: tap the 3rd cell when no word is being suggested
fresh()
inj.buffer = "i am here"; inj.pos = len(inj.buffer)
tap(2.5 * 1 + 1.25, -0.5)
check("tapping 'tidy' in the idle strip tidies", inj.buffer, "I am here")

# ---- personal dictionary ------------------------------------------------------------------------
check("no words yet", lexicon.read_user_words(), [])
check("add a name", lexicon.add_user_word("Marcos"))
check("duplicates are refused", lexicon.add_user_word("Marcos"), False)
check("non-words are refused", (lexicon.add_user_word("a1"), lexicon.add_user_word("x")), (False, False))
check("curly apostrophe is stored straight", lexicon.add_user_word("O’Neil") and "O'Neil" in lexicon.read_user_words())
dec2 = Decoder(lexicon.load_lexicon("en", force_fallback=True, verbose=False))
before = [w for w, _ in dec2.decode(generate_swipe("marcos", random.Random(1), sigma=0.12, offset=0.05), k=5)]
dec2.set_user_words(lexicon.user_entries())
after = [w for w, _ in dec2.decode(generate_swipe("marcos", random.Random(1), sigma=0.12, offset=0.05), k=5)]
check("before adding it, Marcos is not offered", "Marcos" not in before)
check("after adding it, a swipe gives Marcos (capital kept)", after[:1], ["Marcos"])
check("a user word counts as known for typo fixing", dec2.logp("marcos") is not None)
check("O'Neil swipes as o-n-e-i-l", [w for w, _ in dec2.decode(generate_swipe("oneil", random.Random(2), sigma=0.1, offset=0.05), k=3)][:1], ["O'Neil"])
check("removing a word", lexicon.remove_user_word("Marcos") and "Marcos" not in lexicon.read_user_words())
dec2.set_user_words(lexicon.user_entries())
check("removed word is gone from the decoder", dec2.logp("marcos"), None)

# learn the word before the caret
fresh()
s.decoder = dec2
inj.buffer = "hi Valentina "; inj.pos = len(inj.buffer)
s.learn_word()
check("learn the word before the cursor", ("Valentina" in lexicon.read_user_words(), s.message), (True, "learned: Valentina"))
check("learned word is usable at once", dec2.logp("valentina") is not None)
check("the text and caret were not touched", (inj.buffer, inj.pos), ("hi Valentina ", len("hi Valentina ")))
inj.buffer = "..."; inj.pos = 3; s.learn_word()
check("nothing to learn", s.message, "learn: no word before the cursor")

# ---- cursor speed setting ------------------------------------------------------------------------
from swipepen.session import EDGE_RATE_MAX
fresh()
for factor in (0.5, 2.0):
    s.edge_speed = factor
    inj.buffer = "w " * 3000; inj.pos = len(inj.buffer)
    t = [0.0]; s.clock = lambda: t[0]
    s.pen_down(4.5, 3.5)
    for i in range(1, 11):
        t[0] += 0.04; s.pen_move(4.5 - 4.5 * i / 10, 3.5)
    p0 = inj.pos
    for _ in range(int(8 / 0.016)):
        t[0] += 0.016; s.tick()
    rate = (p0 - inj.pos) / 8
    check(f"cursor speed x{factor}: top speed scales", abs(rate - EDGE_RATE_MAX * factor) < EDGE_RATE_MAX * factor * 0.15 + 8)
    s.pen_up()

print("\nAll tidy / dictionary tests passed.")
