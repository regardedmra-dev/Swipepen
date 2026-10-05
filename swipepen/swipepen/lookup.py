"""A real dictionary and thesaurus: definitions, synonyms, antonyms, related words, spelling help.

Offline: Princeton WordNet. Install it with   sudo dnf install wordnet   and swipepen finds the
database files by itself (index.noun, data.noun ... in a "dict" folder). Nothing is sent anywhere.

Online fallback (only used when no WordNet is installed, and it can be turned off with
"online_lookup": false in the settings file): Datamuse (synonyms, antonyms, "means like", rhymes)
and dictionaryapi.dev (definitions). Only the single word you look up is sent.

Also offline and always available: words that start with some letters, and spelling suggestions,
both from swipepen's own word list.
"""
from __future__ import annotations

import glob
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

POS_NAMES = {"n": "noun", "v": "verb", "a": "adjective", "s": "adjective", "r": "adverb"}
FILES = {"n": "noun", "v": "verb", "a": "adj", "r": "adv"}
RULES = {
    "n": [("s", ""), ("ses", "s"), ("ves", "f"), ("xes", "x"), ("zes", "z"), ("ches", "ch"),
          ("shes", "sh"), ("men", "man"), ("ies", "y")],
    "v": [("s", ""), ("ies", "y"), ("es", "e"), ("es", ""), ("ed", "e"), ("ed", ""),
          ("ing", "e"), ("ing", "")],
    "a": [("er", ""), ("est", ""), ("er", "e"), ("est", "e")],
    "r": [],
}


@dataclass
class Sense:
    pos: str
    gloss: str
    examples: list = field(default_factory=list)
    synonyms: list = field(default_factory=list)
    antonyms: list = field(default_factory=list)
    broader: list = field(default_factory=list)
    narrower: list = field(default_factory=list)
    similar: list = field(default_factory=list)


@dataclass
class Result:
    word: str
    senses: list = field(default_factory=list)
    source: str = ""                         # "WordNet", "online" or ""
    more: dict = field(default_factory=dict)  # extra lists, e.g. {"Means like": [...], "Rhymes": [...]}

    @property
    def found(self) -> bool:
        return bool(self.senses) or any(self.more.values())

    def merged(self, attr: str, limit: int = 60):
        """All words of one kind over all senses, best sense first, no repeats."""
        out, seen = [], {self.word.lower()}
        for sense in self.senses:
            for w in getattr(sense, attr):
                if w.lower() not in seen:
                    seen.add(w.lower())
                    out.append(w)
        return out[:limit]


# --------------------------------------------------------------------------
# WordNet (reads the database files directly, nothing to install in Python)
# --------------------------------------------------------------------------
def find_wordnet() -> str | None:
    """The folder that holds index.noun and data.noun, or None."""
    wanted = ("index.noun", "data.noun")
    fixed = [os.environ.get("WNHOME", "") + "/dict", os.environ.get("WNSEARCHDIR", ""),
             os.path.expanduser("~/.local/share/swipepen/wordnet"),
             os.path.expanduser("~/nltk_data/corpora/wordnet"), "/usr/share/nltk_data/corpora/wordnet",
             "/usr/share/wordnet/dict", "/usr/share/wordnet", "/usr/share/dict/wordnet",
             "/usr/local/WordNet-3.0/dict", "/usr/share/wordnet-3.0/dict", "/usr/share/wordnet-3.0"]
    globbed = sorted(glob.glob("/usr/share/wordnet*/dict") + glob.glob("/usr/share/wordnet*")
                     + glob.glob("/usr/share/*/wordnet*/dict") + glob.glob("/usr/lib/wordnet*/dict"))
    for d in fixed + globbed:
        if d and all(os.path.isfile(os.path.join(d, f)) for f in wanted):
            return d
    return None


class WordNet:
    def __init__(self, path: str):
        self.path = path
        self._index = None                      # (pos, lemma) -> [synset offsets]
        self._exc = {}                          # (pos, inflected) -> [base forms]
        self._files = {}
        self._cache = {}

    # ---- loading ----
    def _load(self):
        if self._index is not None:
            return
        index = {}
        for pos, name in FILES.items():
            try:
                with open(os.path.join(self.path, "index." + name), encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        if line.startswith("  "):
                            continue
                        parts = line.split()
                        if len(parts) < 6:
                            continue
                        p_cnt = int(parts[3])
                        offsets = parts[6 + p_cnt:]
                        index[(pos, parts[0])] = [int(o) for o in offsets]
            except OSError:
                pass
            try:
                with open(os.path.join(self.path, name + ".exc"), encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        parts = line.split()
                        if len(parts) >= 2:
                            self._exc[(pos, parts[0])] = parts[1:]
            except OSError:
                pass
        self._index = index

    def _line(self, pos, offset):
        name = FILES[pos]
        fh = self._files.get(name)
        if fh is None:
            fh = self._files[name] = open(os.path.join(self.path, "data." + name), "rb")
        fh.seek(offset)
        return fh.readline().decode("utf-8", "replace")

    def _synset(self, pos, offset):
        key = (pos, offset)
        if key in self._cache:
            return self._cache[key]
        line = self._line(pos, offset)
        body, _, gloss = line.partition(" | ")
        parts = body.split()
        w_cnt = int(parts[3], 16)
        words, i = [], 4
        for _ in range(w_cnt):
            words.append(re.sub(r"\([a-z]+\)$", "", parts[i]).replace("_", " "))
            i += 2
        p_cnt = int(parts[i])
        i += 1
        ptrs = []
        for _ in range(p_cnt):
            sym, off, ppos, st = parts[i:i + 4]
            ptrs.append((sym, int(off), ppos, st))
            i += 4
        gloss = gloss.strip()
        defn = re.split(r';\s+"', gloss, maxsplit=1)[0].strip().rstrip(";")
        examples = re.findall(r'"([^"]+)"', gloss)
        syn = {"type": parts[2], "words": words, "ptrs": ptrs, "gloss": defn, "examples": examples}
        self._cache[key] = syn
        return syn

    # ---- word forms ----
    def _base_forms(self, word: str):
        w = word.lower().strip().replace(" ", "_")
        found = []
        for pos in "nvar":
            cands = [w] + self._exc.get((pos, w), [])
            for suffix, repl in RULES[pos]:
                if w.endswith(suffix) and len(w) > len(suffix):
                    cands.append(w[:len(w) - len(suffix)] + repl)
            for c in cands:
                if (pos, c) in self._index and (pos, c) not in found:
                    found.append((pos, c))
        return found

    def _words_of(self, pos, offset, limit=8):
        return self._synset(pos, offset)["words"][:limit]

    # ---- lookup ----
    def lookup(self, word: str) -> Result:
        self._load()
        result = Result(word=word, source="WordNet")
        for pos, lemma in self._base_forms(word):
            for offset in self._index[(pos, lemma)][:8]:
                syn = self._synset(pos, offset)
                me = lemma.replace("_", " ")
                sense = Sense(pos=POS_NAMES.get(syn["type"], POS_NAMES[pos]), gloss=syn["gloss"],
                              examples=syn["examples"][:2])
                sense.synonyms = [w for w in syn["words"] if w.lower() != me]
                src_idx = [i + 1 for i, w in enumerate(syn["words"]) if w.lower() == me] or [0]
                heads = []
                for sym, off, ppos, st in syn["ptrs"]:
                    spos = "a" if ppos == "s" else ppos
                    if sym == "!":                      # antonym: lexical, from this word to one word
                        src, tgt = int(st[:2], 16), int(st[2:], 16)
                        if src in src_idx and tgt:
                            sense.antonyms.append(self._synset(spos, off)["words"][tgt - 1])
                    elif sym in ("@", "@i"):
                        sense.broader += self._words_of(spos, off, 3)
                    elif sym in ("~", "~i"):
                        sense.narrower += self._words_of(spos, off, 6)
                    elif sym == "&":
                        sense.similar += self._words_of(spos, off, 6)
                        heads.append((spos, off))
                if syn["type"] == "s" and not sense.antonyms:   # a satellite adjective: borrow its head's antonym
                    for spos, off in heads:
                        for sym, aoff, apos, st in self._synset(spos, off)["ptrs"]:
                            if sym == "!":
                                sense.antonyms += self._words_of("a" if apos == "s" else apos, aoff, 4)
                for attr in ("synonyms", "antonyms", "broader", "narrower", "similar"):
                    setattr(sense, attr, list(dict.fromkeys(getattr(sense, attr))))
                result.senses.append(sense)
        return result


# --------------------------------------------------------------------------
# Online fallback
# --------------------------------------------------------------------------
class Online:
    def __init__(self, datamuse="https://api.datamuse.com", dictionary="https://api.dictionaryapi.dev/api/v2/entries/en",
                 timeout: float = 4.0):
        self.datamuse, self.dictionary, self.timeout = datamuse.rstrip("/"), dictionary.rstrip("/"), timeout

    def _get(self, url):
        req = urllib.request.Request(url, headers={"User-Agent": "swipepen"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))

    def _words(self, **params):
        try:
            data = self._get(f"{self.datamuse}/words?" + urllib.parse.urlencode({**params, "max": 20}))
            return [d["word"] for d in data if isinstance(d, dict) and "word" in d]
        except (OSError, ValueError, urllib.error.URLError):
            return []

    def lookup(self, word: str) -> Result:
        result = Result(word=word, source="online")
        try:
            data = self._get(f"{self.dictionary}/{urllib.parse.quote(word.lower())}")
            for entry in data if isinstance(data, list) else []:
                for meaning in entry.get("meanings", []):
                    pos = meaning.get("partOfSpeech", "")
                    for d in meaning.get("definitions", [])[:3]:
                        result.senses.append(Sense(
                            pos=pos, gloss=d.get("definition", ""),
                            examples=[d["example"]] if d.get("example") else [],
                            synonyms=d.get("synonyms", []) or meaning.get("synonyms", [])[:8],
                            antonyms=d.get("antonyms", []) or meaning.get("antonyms", [])[:8]))
        except (OSError, ValueError, urllib.error.URLError):
            pass
        syn = self._words(rel_syn=word)
        ant = self._words(rel_ant=word)
        if syn or ant:
            if not result.senses:
                result.senses.append(Sense(pos="", gloss=""))
            result.senses[0].synonyms = list(dict.fromkeys(syn + result.senses[0].synonyms))
            result.senses[0].antonyms = list(dict.fromkeys(ant + result.senses[0].antonyms))
        means = [w for w in self._words(ml=word) if w.lower() != word.lower()]
        rhymes = self._words(rel_rhy=word)
        if means:
            result.more["Means like"] = means
        if rhymes:
            result.more["Rhymes"] = rhymes
        return result


# --------------------------------------------------------------------------
# The dictionary the keyboard uses
# --------------------------------------------------------------------------
class Dictionary:
    def __init__(self, wordnet_path: str | None = "auto", online: bool = True, online_client=None):
        self.wn = None
        if wordnet_path == "auto":
            wordnet_path = find_wordnet()
        if wordnet_path:
            self.wn = WordNet(wordnet_path)
        self.online = online_client if online_client is not None else (Online() if online else None)

    @property
    def source(self) -> str:
        return "WordNet" if self.wn else ("online" if self.online else "none")

    def lookup(self, word: str) -> Result:
        word = word.strip()
        if self.wn:
            res = self.wn.lookup(word)
            if res.found or not self.online:
                return res
        if self.online and not self.wn:
            return self.online.lookup(word)
        return Result(word=word, source="")


# --------------------------------------------------------------------------
# Word list helpers: completions and spelling suggestions
# --------------------------------------------------------------------------
LETTERS = "abcdefghijklmnopqrstuvwxyz'"


def edits1(w: str):
    splits = [(w[:i], w[i:]) for i in range(len(w) + 1)]
    out = {a + b[1:] for a, b in splits if b}
    out |= {a + b[1] + b[0] + b[2:] for a, b in splits if len(b) > 1}
    out |= {a + c + b[1:] for a, b in splits if b for c in LETTERS}
    out |= {a + c + b for a, b in splits for c in LETTERS}
    out.discard(w)
    return out


class Speller:
    """Words that start with some letters, and the nearest real words to a misspelling."""

    def __init__(self, decoder):
        self.d = decoder

    def _known(self):
        d = self.d
        merged = dict(d.freq)
        for w, lp in d.user_freq.items():
            merged[w] = max(lp, merged.get(w, -99.0))
        return merged

    def completions(self, prefix: str, n: int = 12):
        p = prefix.lower()
        if len(p) < 2:
            return []
        words = self._known()
        hits = [(lp, w) for w, lp in words.items() if w.startswith(p) and w != p]
        hits.sort(reverse=True)
        return [w for _, w in hits[:n]]

    def suggest(self, word: str, n: int = 6):
        w = word.lower()
        words = self._known()
        if w in words or len(w) < 2:
            return []
        near = [c for c in edits1(w) if c in words]
        if not near and len(w) <= 10:
            near = list({c2 for c1 in edits1(w) for c2 in edits1(c1) if c2 in words})
        near.sort(key=lambda c: (-words[c], c))
        return near[:n]

    def similar(self, word: str, n: int = 8):
        """Real words one edit away (to catch the wrong-but-valid word)."""
        words = self._known()
        near = [c for c in edits1(word.lower()) if c in words]
        near.sort(key=lambda c: (-words[c], c))
        return near[:n]
