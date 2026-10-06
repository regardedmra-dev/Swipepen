"""Opt-in swipe recorder, labels from behaviour, learning from corrections, replay / sweep."""
import json, os, random, tempfile
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
from swipepen import lexicon, recorder as recmod
from swipepen.corrections import CorrectionModel
from swipepen.engine import Decoder, FUNCTION_KEYS, CANVAS_W, STRIP_CELLS
from swipepen.inject import DryRunInjector
from swipepen.recorder import Recorder, load_samples
from swipepen.replay import apply_setting, build_decoder, format_report, parse_assignments, replay
from swipepen.session import Session
from swipepen.simulate import generate_swipe

def check(label, got, want=True):
    ok = got == want
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else f"  got {got!r} want {want!r}"))
    assert ok

lex = lexicon.load_lexicon("en", force_fallback=True, verbose=False)
dec = Decoder(lex)
rng = random.Random(8)
tmp = tempfile.mkdtemp()

# ---- Recorder ------------------------------------------------------------------------------------------------
path = os.path.join(tmp, "a.jsonl")
r = Recorder(path)
r.write({"ev": "x"})
check("off by default: nothing is written", os.path.exists(path), False)
r.enabled = True
r.write({"ev": "x"})
check("on: one line per record", r.info()[0], 1)
ids = {r.new_id() for _ in range(50)}
check("record ids are unique", len(ids), 50)
old_max, recmod.MAX_BYTES = recmod.MAX_BYTES, 50
r.write({"ev": "y" * 80}); r.write({"ev": "z"})
check("a big recording rolls over to .1 (one old file kept)", os.path.exists(path + ".1"))
recmod.MAX_BYTES = old_max
check("clear deletes the recording and its roll-over", r.clear() and not os.path.exists(path) and not os.path.exists(path + ".1"))
check("clear on nothing says so", r.clear(), False)
bad = Recorder(os.path.join(tmp, "no", "such", "\0dir", "f.jsonl"), enabled=True)
bad.write({"ev": "x"})
check("a write that cannot happen never raises", True)

# ---- a session with the recorder on ----------------------------------------------------------------------------
def make(path=None, learn=False):
    inj = DryRunInjector()
    s = Session(dec, inj, record_path=path)
    s.learn_corrections = learn
    if learn:
        s.corrections = CorrectionModel(path=None)
    now = [0.0]
    s.clock = lambda: now[0]
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
    def cell(i):
        w = CANVAS_W / STRIP_CELLS
        tap(w * i + w / 2, -0.5)
    return s, inj, swipe, key, cell, now

p1 = os.path.join(tmp, "s1.jsonl")
s, inj, swipe, key, cell, now = make(p1)
swipe("hello"); swipe("world"); key("space")
smp = load_samples(p1)
check("two swipes recorded", len(smp), 2)
check("moving on = kept (implicit label)", (smp[0].truth, smp[0].source), ("hello", "kept"))
check("the word the decoder offered is stored", smp[0].cands[0], "hello")
check("the pen path is stored", len(smp[0].pts) > 10)
check("key shape and tolerance are stored", smp[0].ys == dec.ys and smp[0].loose == dec.looseness)
check("the previous words are stored as context", smp[1].ctx, ["hello"])

s2 = make(None)[0]
check("no --record, no recording", s2.recorder.enabled, False)
s2.set_setting("record_swipes", True)
check("the setting switches it on", s2.recorder.enabled)

# explicit labels: confirm, pick, erase + redo
p2 = os.path.join(tmp, "s2.jsonl")
s, inj, swipe, key, cell, now = make(p2)
swipe("hello"); cell(0)                                  # tap the word that is already in: accept
swipe("good", sigma=0.3)
alts = list(s.last.cands)
check("'good' gives alternatives to pick from", len(alts) > 1)
cell(1); key("space")                                    # pick the second candidate
swipe("world"); key("backspace")                         # erase it ...
check("backspace after a swipe erases the whole word", inj.buffer.endswith(alts[1] + " "))
swipe("world")                                           # ... and swipe the same word again
key("space")
smp = load_samples(p2)
check("4 swipes", len(smp), 4)
check("accept is an explicit label", (smp[0].truth, smp[0].source), ("hello", "accept"))
check("a picked candidate is the explicit label", (smp[1].truth, smp[1].source), (alts[1], "pick"))
check("erased then redone = the redo's word, explicit", (smp[2].source, smp[2].truth), ("redo", smp[3].cands[0]))
check("the redo itself was kept", smp[3].source, "kept")

# a different word after an erase is not a redo; neither is a late one
p3 = os.path.join(tmp, "s3.jsonl")
s, inj, swipe, key, cell, now = make(p3)
swipe("hello"); key("backspace"); swipe("because"); key("space")
smp = load_samples(p3)
check("erase then a different word: the erased swipe stays unlabelled", smp[0].source, "unknown")
swipe("hello"); key("backspace"); now[0] += 30; swipe("hello"); key("space")
smp = load_samples(p3)
check("erase then the same word much later is not a redo", smp[2].source, "unknown")
rows = [json.loads(l) for l in open(p3, encoding="utf-8")]
check("redo_of is stored only on real redos", not any("redo_of" in o for o in rows))

# legacy 0.5.x recordings still load
leg = os.path.join(tmp, "legacy.jsonl")
with open(leg, "w", encoding="utf-8") as fh:
    fh.write(json.dumps({"points": [[1, 1], [2, 1]], "cands": ["we", "he"], "t": 1}) + "\n")
    fh.write(json.dumps({"points": [[1, 1], [2, 1]], "cands": ["we", "he"], "t": 2}) + "\n")
    fh.write(json.dumps({"correction": "he", "t": 3}) + "\n")
    fh.write("not json\n")
smp = load_samples(leg)
check("legacy recording loads", [(x.truth, x.source) for x in smp], [("we", "kept"), ("he", "pick")])

# ---- CorrectionModel ----------------------------------------------------------------------------------------------
m = CorrectionModel(path=None)
check("nothing learned: no change", m.adjust(["from", "form"]), {})
m.learn("form", "from")
a = m.adjust(["from", "form"])
check("a fix pushes the word you meant up and the wrong one down", a["form"] < 0 < a["from"])
for _ in range(200):
    m.learn("form", "from")
a = m.adjust(["from", "form"])
check("the push is capped", min(a.values()) >= -0.45 and max(a.values()) <= 0.45)
m.learn("same", "same")
check("learning a word as its own correction does nothing", ("same", "same") not in m.pair)
mp = os.path.join(tmp, "corr.json")
m2 = CorrectionModel(path=mp)
for _ in range(5):
    m2.learn("quiet", "quite")
m3 = CorrectionModel(path=mp)
check("saved and loaded", m3.adjust(["quite", "quiet"])["quiet"] < 0)
m3.forget()
check("forget wipes it", len(CorrectionModel(path=mp)) == 0 and not os.path.exists(mp))

# ---- corrections in the session ------------------------------------------------------------------------------------------
s, inj, swipe, key, cell, now = make(None, learn=True)
check("close call, nothing learned yet: order kept", [w for w, _ in s._rerank([("from", 1.00), ("form", 1.05)])], ["from", "form"])
for _ in range(3):
    s.get_corrections().learn("form", "from")
check("close call after 3 fixes: your word first", [w for w, _ in s._rerank([("from", 1.00), ("form", 1.05)])], ["form", "from"])
check("a clear swipe is not overruled", [w for w, _ in s._rerank([("from", 0.40), ("form", 1.50)])], ["from", "form"])
s.learn_corrections = False
check("learning off: no push", [w for w, _ in s._rerank([("from", 1.00), ("form", 1.05)])], ["from", "form"])
s.learn_corrections = True

s, inj, swipe, key, cell, now = make(None, learn=True)
swipe("good", sigma=0.3)
top, alt = s.last.cands[0], s.last.cands[1]
cell(1); key("space")
check("picking a candidate teaches: you meant it, not the first", s.corrections.pair.get((alt, top)), 1)
swipe("hello"); cell(0); swipe("world"); key("space")
check("confirming or carrying on teaches nothing", sum(s.corrections.pair.values()), 1)

s, inj, swipe, key, cell, now = make(None, learn=True)
swipe("world"); key("backspace"); swipe("world"); cell(1)
key("space")
check("a word that is not on offer is not touched", "fork" not in CorrectionModel(path=None).adjust(["from", "fork"]))
check("erase + redo + pick teaches the fixes", len(s.corrections) >= 1)

# ---- replay -----------------------------------------------------------------------------------------------------------------
words = ["hello", "world", "people", "because", "there", "would", "about", "which", "other", "think",
         "first", "after", "water", "little", "great", "right", "house", "place", "again", "found"]
pr = os.path.join(tmp, "rep.jsonl")
rr = Recorder(pr, enabled=True)
rrng = random.Random(3)
for i, w in enumerate(words * 2):
    rr.write({"ev": "swipe", "id": i + 1, "pts": [[round(x, 3), round(y, 3)] for x, y in generate_swipe(w, rrng, sigma=0.15, offset=0.1)],
              "cands": [w], "ctx": [], "ys": 1.0, "loose": 0.5})
    rr.write({"ev": "final", "id": i + 1, "word": w, "how": "pick" if i % 2 else "kept"})
rr.write({"ev": "swipe", "id": 999, "pts": [[1, 1], [2, 1]], "cands": ["zzqx"], "ctx": []})
rr.write({"ev": "final", "id": 999, "word": "zzqx", "how": "kept"})
rr.write({"ev": "swipe", "id": 1000, "pts": [[1, 1], [2, 1]], "cands": ["we"], "ctx": []})
smp = load_samples(pr)
res = replay(smp, build_decoder("en", 0.5, force_fallback=True), ys=1.0)
check("replay counts explicit and implicit separately", (res["explicit"]["n"], res["implicit"]["n"]), (20, 20))
check("low-noise synthetic swipes decode well", res["explicit"][3] >= 14 and res["implicit"][3] >= 14)
check("a word the dictionary does not have is left out and said so", res["skipped"]["not in dictionary"], 1)
check("a swipe with no outcome is left out and said so", res["skipped"]["unlabelled"], 1)
check("'as typed' reports what the live decode got right", res["explicit"]["live"], 20)
check("report prints", "explicit" in format_report(res) and "top-1" in format_report(res))
only = replay(smp, build_decoder("en", 0.5, force_fallback=True), ys=1.0, explicit_only=True)
check("explicit-only skips the rest", (only["explicit"]["n"], only["implicit"]["n"]), (20, 0))

d = build_decoder("en", 0.5, force_fallback=True)
apply_setting(d, "prior_weight", 0.3); apply_setting(d, "looseness", 1.0)
check("settings apply by name", (d.prior_weight, d.looseness), (0.18 + 0.08, 1.0))
try:
    apply_setting(d, "no_such_thing", 1.0)
    check("an unknown setting is an error", False)
except ValueError:
    check("an unknown setting is an error", True)
check("name=value parsing", parse_assignments(["a=1", "b=0.5"]), {"a": 1.0, "b": 0.5})
try:
    parse_assignments(["oops"]); check("bad name=value is an error", False)
except ValueError:
    check("bad name=value is an error", True)

# the CLI end to end
import io, contextlib
from swipepen.__main__ import main
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    main(["replay", pr, "--ys", "1.0", "--sweep", "looseness=0,1", "--limit", "20"])
out = buf.getvalue()
check("sweep prints one row per value", out.count("\n") >= 5 and "looseness" in out)
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    main(["swipes", "info", pr])
check("swipes info reports the size", "records" in buf.getvalue())
with contextlib.redirect_stdout(io.StringIO()):
    main(["swipes", "clear", pr])
check("swipes clear deletes it", not os.path.exists(pr))

print("\nAll recorder / corrections / replay tests passed.")
