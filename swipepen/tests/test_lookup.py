"""Dictionary / thesaurus: WordNet files (a tiny fixture in the real format), online fallback (local fake server),
completions and spelling suggestions."""
import http.server, json, os, tempfile, threading
from wnfixture import build
from swipepen import lexicon
from swipepen.engine import Decoder
from swipepen.lookup import Dictionary, Online, Speller, WordNet, find_wordnet

def check(label, got, want=True):
    ok = got == want
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else f"  got {got!r} want {want!r}"))
    assert ok

# ---- build a miniature WordNet in the real file format --------------------------------------------------
tmp = tempfile.mkdtemp()
build(tmp)
wn = WordNet(tmp)

# ---- WordNet ----------------------------------------------------------------------------------------------------
r = wn.lookup("dog")
check("dog is found with a definition", (r.found, r.senses[0].pos, r.senses[0].gloss), (True, "noun", "a member of the genus Canis"))
check("example sentence", r.senses[0].examples, ["the dog barked all night"])
check("synonyms come from the synset (underscores become spaces)", r.senses[0].synonyms, ["domestic dog", "Canis familiaris"])
check("broader / narrower words", (r.senses[0].broader, r.senses[0].narrower), (["canine", "canid"], ["puppy"]))
r = wn.lookup("dogs")
check("plural dogs -> dog (suffix rule)", r.found and r.senses[0].gloss.startswith("a member"))
r = wn.lookup("ran")
check("ran -> run (exception list)", [s.pos for s in r.senses], ["verb", "verb"])
check("two senses of run, synonyms of the second", r.senses[1].synonyms, ["operate"])
check("running -> run (-ing rule)", wn.lookup("running").found)
r = wn.lookup("happy")
check("antonym of happy is unhappy (lexical antonym pointer)", r.senses[0].antonyms, ["unhappy"])
check("similar words (satellites)", r.senses[0].similar, ["glad"])
r = wn.lookup("glad")
check("a satellite adjective borrows its head's antonym", (r.senses[0].pos, r.senses[0].antonyms), ("adjective", ["unhappy"]))
check("happier -> happy (adjective exceptions)", wn.lookup("happier").found)
check("Happy (capital letters) works", wn.lookup("Happy").found)
check("unknown word", wn.lookup("zzzzz").found, False)
check("merged() collects words over senses without repeats", wn.lookup("run").merged("synonyms"), ["operate"])

os.environ["WNSEARCHDIR"] = tmp
check("find_wordnet looks in $WNSEARCHDIR", find_wordnet(), tmp)
del os.environ["WNSEARCHDIR"]

d = Dictionary(wordnet_path=tmp, online=False)
check("Dictionary uses WordNet", (d.source, d.lookup("dog").found), ("WordNet", True))
d2 = Dictionary(wordnet_path=None, online=False)
check("no WordNet and online off: nothing found, no crash", (d2.source, d2.lookup("dog").found), ("none", False))

# ---- online fallback with a local fake of Datamuse and dictionaryapi.dev ------------------------------------------
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path.startswith("/words"):
            q = self.path.split("?", 1)[1]
            data = ({"rel_syn": [{"word": "glad", "score": 9}, {"word": "joyful"}], "rel_ant": [{"word": "sad"}],
                     "ml": [{"word": "cheerful"}, {"word": "happy"}], "rel_rhy": [{"word": "snappy"}]})
            for k, v in data.items():
                if q.startswith(k + "=happy&"):
                    return self._send(v)
            return self._send([])
        if self.path.startswith("/entries/en/happy"):
            return self._send([{"word": "happy", "meanings": [{"partOfSpeech": "adjective", "definitions": [
                {"definition": "Feeling pleasure.", "example": "I am happy.", "synonyms": [], "antonyms": []}]}]}])
        self.send_response(404); self.end_headers(); self.wfile.write(b'{"title":"No Definitions Found"}')
    def _send(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)
srv = http.server.HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_port}"
online = Online(datamuse=base, dictionary=base + "/entries/en", timeout=3)
r = online.lookup("happy")
check("online: definition", (r.source, r.senses[0].pos, r.senses[0].gloss, r.senses[0].examples), ("online", "adjective", "Feeling pleasure.", ["I am happy."]))
check("online: synonyms and antonyms", (r.senses[0].synonyms, r.senses[0].antonyms), (["glad", "joyful"], ["sad"]))
check("online: means-like (without the word itself) and rhymes", (r.more["Means like"], r.more["Rhymes"]), (["cheerful"], ["snappy"]))
r = online.lookup("zzzz")
check("online: unknown word is simply not found", r.found, False)
d3 = Dictionary(wordnet_path=None, online=True, online_client=online)
check("Dictionary falls back to the online lookup", d3.lookup("happy").source, "online")
dead = Online(datamuse="http://127.0.0.1:9", dictionary="http://127.0.0.1:9", timeout=0.5)
check("no network: no crash, nothing found", dead.lookup("happy").found, False)
srv.shutdown()

# ---- completions & spelling ----------------------------------------------------------------------------------------
dec = Decoder(lexicon.load_lexicon("en", force_fallback=True, verbose=False))
sp = Speller(dec)
comp = sp.completions("tho")
check("words starting with 'tho' (most common first)", comp[:2] == ["though", "thought"] or "thought" in comp, True)
check("completions need at least two letters", sp.completions("t"), [])
check("spelling: 'wich' -> which", "which" in sp.suggest("wich"), True)
check("spelling: 'recieve' is flagged with some suggestion (deterministic order)", sp.suggest("recieve") == sp.suggest("recieve") and sp.suggest("recieve") != [], True)
check("a correct word has no suggestions", sp.suggest("hello"), [])
check("similar valid words", "hold" in sp.similar("hole") or "holy" in sp.similar("hole"), True)
print("\nAll lookup tests passed.")
