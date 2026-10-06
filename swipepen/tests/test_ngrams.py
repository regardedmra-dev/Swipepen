"""Word-pair table: reading text, counting, saving/loading, use in the predictor, evaluation, CLI."""
import contextlib, gzip, io, os, tempfile, zipfile
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
from swipepen import lexicon, ngrams
from swipepen.engine import Decoder
from swipepen.predict import Predictor

def check(label, got, want=True):
    ok = got == want
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else f"  got {got!r} want {want!r}"))
    assert ok

dec = Decoder(lexicon.load_lexicon("en", force_fallback=True, verbose=False))
known = dec.logp
tmp = tempfile.mkdtemp()

# ---- reading --------------------------------------------------------------------------------------------------------
check("sentences split on . ! ? and newlines, lowercase, curly apostrophes fixed",
      list(ngrams.sentences("Hello there. Don’t go!\nWhy?  Because I'm tired")),
      [["hello", "there"], ["don't", "go"], ["why"], ["because", "i'm", "tired"]])
d = os.path.join(tmp, "docs"); os.makedirs(os.path.join(d, "sub"))
open(os.path.join(d, "a.txt"), "w").write("Please send me the report today.")
open(os.path.join(d, "sub", "b.html"), "w").write("<html><style>p{}</style><body><p>Thank you</p><script>x()</script></body></html>")
with zipfile.ZipFile(os.path.join(d, "c.docx"), "w") as z:
    z.writestr("word/document.xml", "<w:document><w:p><w:r><w:t>Thank you very much</w:t></w:r></w:p></w:document>")
open(os.path.join(d, "ignore.png"), "w").write("x")
files = ngrams.find_files([d, os.path.join(tmp, "nope")])
check("folders are searched for text files only", sorted(os.path.basename(f) for f in files), ["a.txt", "b.html", "c.docx"])
by = {os.path.basename(f): f for f in files}
check("html tags, styles and scripts are dropped", [w for s in ngrams.sentences(ngrams.read_text(by["b.html"])) for w in s], ["thank", "you"])
check("docx text is read", [w for s in ngrams.sentences(ngrams.read_text(by["c.docx"])) for w in s], ["thank", "you", "very", "much"])
check("a broken docx is just empty", ngrams.read_text(os.path.join(d, "ignore.png")) != None and ngrams.read_text(os.path.join(tmp, "x.docx")) == "")

# ---- counting ---------------------------------------------------------------------------------------------------------
for w in ("please", "send", "me", "the", "report", "today", "thank", "you", "very", "much"):
    assert known(w) is not None, w
c = ngrams.count_pairs([["please", "send", "me", "the", "report"], ["zzqxv", "the", "report"], ["the", "zzqxv", "report"]], known)
check("pairs are counted with sentence start", (c[("<s>", "please")], c[("send", "me")], c[("the", "report")]), (1, 1, 2))
check("an unknown word breaks the chain (no pair across it)", ("zzqxv", "the") not in c and ("the", "zzqxv") not in c and c[("<s>", "the")] == 1)
check("...and the word after it is not 'at the start'", c[("<s>", "report")] == 0)

big = ngrams.count_pairs([["thank", "you"]] * 5 + [["thank", "goodness"]] * 3 + [["thank", "me"]] * 1, known)
t = ngrams.trim(big, top=2, min_count=3)
check("trim keeps the likeliest followers seen often enough", t["thank"], [(5, "you"), (3, "goodness")] if known("goodness") else [(5, "you")])
check("pairs seen too rarely are dropped", all(w != "me" for _n, w in t["thank"]))

# ---- save / load ----------------------------------------------------------------------------------------------------------
p1 = os.path.join(tmp, "one.tsv.gz")
check("write returns the number of pairs", ngrams.write_table({"a": [(4, "b"), (1, "c")]}, p1), 2)
check("table loads as shares", ngrams.load_table(paths=[p1]), {"a": [("b", 0.8), ("c", 0.2)]})
p2 = os.path.join(tmp, "two.tsv.gz")
ngrams.write_table({"a": [(4, "c")]}, p2)
check("two tables are added together", ngrams.load_table(paths=[p1, p2])["a"][0], ("c", 5 / 9))
check("a missing or corrupt table is just empty", ngrams.load_table(paths=[os.path.join(tmp, "none"), os.path.join(tmp, "docs", "ignore.png")]), {})
with gzip.open(os.path.join(tmp, "bad.gz"), "wt") as fh:
    fh.write("onlyone\nx\ty\tnotanumber\n")
check("junk lines are skipped", ngrams.load_table(paths=[os.path.join(tmp, "bad.gz")]), {})
check("no table in the config folder: nothing loaded", ngrams.load_table("en"), {})

# ---- the predictor uses it --------------------------------------------------------------------------------------------------
base = Predictor(known, path=None, corpus={})
check("without a table 'send' leads nowhere in particular", base.next_words(["send"], 1)[0] != "me")
withtab = Predictor(known, path=None, corpus={"send": [("me", 0.6), ("you", 0.3), ("zzqxv", 0.1)]})
check("with a table 'send' -> 'me'", withtab.next_words(["send"], 3)[:2], ["me", "you"])
check("words that are not real words are never offered", "zzqxv" not in withtab.ranked(["send"], 12))
check("hand-made suggestions still work", withtab.next_words(["thank"], 1)[0], "you")
withtab.learn(["send", "money"]); withtab.learn(["send", "money"])
check("what you write beats the table", withtab.next_words(["send"], 1)[0], "money")
check("the table helps re-rank swipe results", withtab.affinity(["send"], "me") > base.affinity(["send"], "me"))
auto = Predictor(known, path=None)
check("'auto' with no table on disk behaves like before", auto.corpus, {})
ngrams.write_table({"banana": [(9, "split")]}, ngrams.config_file("en"))
check("'auto' finds your table in the config folder", Predictor(known, path=None).next_words(["banana"], 1), ["split"])
os.remove(ngrams.config_file("en"))

# ---- evaluation ---------------------------------------------------------------------------------------------------------------
text = ". ".join(["Please send me the report today", "Thank you very much"] * 20)
sents = list(ngrams.sentences(text))
tr, te = ngrams.split_sentences(sents, 0.1)
check("every 10th sentence is held back", (len(tr), len(te)), (36, 4))
tab = ngrams.shares(ngrams.trim(ngrams.count_pairs(tr, known), 8, 3))
ra = ngrams.evaluate(te, Predictor(known, path=None, learning=False, corpus={}))
rb = ngrams.evaluate(te, Predictor(known, path=None, learning=False, corpus=tab))
check("evaluation counts every held-back word", ra["n"], sum(len(s) for s in te))
check("a table made from similar text raises the hit rate", rb[3] > ra[3] and rb[1] > ra[1])

# ---- CLI -------------------------------------------------------------------------------------------------------------------------
from swipepen.__main__ import main
open(os.path.join(d, "a.txt"), "w").write(text)
out = os.path.join(tmp, "cli.tsv.gz")
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    main(["build-ngrams", d, "--out", out, "--evaluate", "--min-count", "2"])
o = buf.getvalue()
check("CLI evaluates and writes the table", "built-in list only" in o and "+ your table" in o and os.path.exists(out))
check("the written table has the pairs", ("me", 1.0) in ngrams.load_table(paths=[out]).get("send", []))
try:
    main(["build-ngrams", os.path.join(tmp, "empty"), "--out", out]); check("no files is an error", False)
except SystemExit as exc:
    check("no files is an error", "no text files" in str(exc.code))

print("\nAll pair-table tests passed.")
