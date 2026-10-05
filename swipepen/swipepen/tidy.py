"""Find and fix common typing slips in a piece of text.

Pure functions, no I/O, so they can be tested without a keyboard or a document.

    fix_text(text, logp)   -> corrected text
    edits(old, new)        -> [(start, end, replacement), ...] describing the change

`logp(word)` returns the log10 frequency of a lowercase word, or None if the
word is unknown (see Decoder.logp).

What is fixed:
  * words split by a stray space:   "hel lo" / "hell o"  ->  "hello"
  * a lone "i":                     "i think i'm"       ->  "I think I'm"
  * an "i" glued to the next word:  "iwant", "idon't"   ->  "I want", "I don't"
  * missing apostrophes:            "dont", "im", "thats" -> "don't", "I'm", "that's"
  * a few classic typos:            "teh", "recieve", "alot" ...
  * repeated words:                 "the the"           ->  "the"
  * spacing:                        double spaces, "word ," and "a,b"
  * a small letter after . ! ?      ("it ended. then" -> "it ended. Then")
"""
from __future__ import annotations

import difflib
import re

APOS = "'’"
TOKEN = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)*")

MISSING_APOSTROPHE = {
    "dont": "don't", "doesnt": "doesn't", "didnt": "didn't", "isnt": "isn't", "wasnt": "wasn't",
    "arent": "aren't", "werent": "weren't", "cant": "can't", "couldnt": "couldn't",
    "shouldnt": "shouldn't", "wouldnt": "wouldn't", "havent": "haven't", "hasnt": "hasn't",
    "hadnt": "hadn't", "wont": "won't", "im": "I'm", "ive": "I've", "youre": "you're",
    "theyre": "they're", "thats": "that's", "whats": "what's", "youve": "you've",
    "theyve": "they've", "weve": "we've", "youll": "you'll", "theyll": "they'll",
    "wouldve": "would've", "couldve": "could've", "shouldve": "should've", "mustnt": "mustn't",
    "whos": "who's", "theres": "there's",
}
TYPOS = {
    "teh": "the", "adn": "and", "taht": "that", "waht": "what", "hte": "the", "recieve": "receive",
    "definately": "definitely", "seperate": "separate", "occured": "occurred", "untill": "until",
    "wich": "which", "becuase": "because", "becasue": "because", "thier": "their", "alot": "a lot",
    "freind": "friend", "beleive": "believe", "tommorow": "tomorrow", "wierd": "weird",
    "accomodate": "accommodate", "thnaks": "thanks", "thankyou": "thank you", "wiht": "with",
    "jsut": "just", "knwo": "know", "realy": "really", "peice": "piece", "goverment": "government",
}
NO_REPEAT = {"that", "had", "is", "very", "no", "so", "yeah", "ha", "bye", "knock", "really",
             "many", "far", "much", "blah", "can", "do", "go", "boo", "la", "tut"}
ABBREV = {"etc", "vs", "mr", "mrs", "ms", "dr", "inc", "eg", "ie", "st", "jr", "sr", "no", "fig"}

# Words that follow "I": a tapped "i" glued to one of these ("iwant", "idon't") is split again.
I_FOLLOWERS = set("""am was wasn't wasnt were want wanna wish think thought know knew love like hate need have
haven't havent had hadn't hadnt will won't wont would wouldn't wouldnt can can't cant could couldn't couldnt
should shouldn't shouldnt did didn't didnt do don't dont never just really hope guess see saw feel felt get
got go went miss mean said say believe wonder remember forgot forget promise agree suppose understand thank
appreciate always still also only must might may shall""".split())

FRAGMENT_LOGP = -5.6     # words rarer than this look like pieces of a split word
MERGE_MIN_LOGP = -5.8    # a merged word must be at least this common to be believed


def norm(word: str) -> str:
    return word.lower().replace("’", "'")


def _case_like(src: str, dst: str) -> str:
    if src.isupper() and len(src) > 1:
        return dst.upper()
    if src[:1].isupper():
        return dst[:1].upper() + dst[1:]
    return dst


def _is_fragment(word: str, logp) -> bool:
    if len(word) == 1:
        return word.lower() not in ("a", "i")
    lp = logp(norm(word))
    return lp is None or lp < FRAGMENT_LOGP


def _merge_splits(text: str, logp) -> str:
    for _ in range(60):
        toks = list(TOKEN.finditer(text))
        for m1, m2 in zip(toks, toks[1:]):
            if text[m1.end():m2.start()] != " ":
                continue
            a, b = m1.group(), m2.group()
            if not (a.isalpha() and b.isalpha()) or a.isupper() or b.isupper() or not b[0].islower():
                continue
            join = a + b
            lp = logp(join.lower())
            if len(join) < 3 or lp is None or lp < MERGE_MIN_LOGP:
                continue
            if not (_is_fragment(a, logp) or _is_fragment(b, logp)):
                continue                        # two real words: leave them alone ("in to", "any one")
            text = text[:m1.end()] + text[m2.start():]
            break
        else:
            return text
    return text


def _split_i(text: str) -> str:
    """"iwant" -> "I want", "idon’t" -> "I don’t": a tapped i that got glued to the next word."""
    def fix(m):
        tok = m.group()
        if len(tok) >= 3 and tok[0] in "iI" and norm(tok[1:]) in I_FOLLOWERS:
            return "I " + tok[1:]
        return tok
    return TOKEN.sub(fix, text)


def _lone_i(text: str) -> str:
    return re.sub(r"(?<![\w'’.@/-])i(?=(?:['’](?:m|ll|ve|d))?(?![\w]))", "I", text)


def _dictionary_fixes(text: str) -> str:
    def fix(m):
        tok = m.group()
        low = tok.lower()
        if low in MISSING_APOSTROPHE:
            rep = MISSING_APOSTROPHE[low]
            return rep if rep.startswith("I") else _case_like(tok, rep)
        if low in TYPOS:
            return _case_like(tok, TYPOS[low])
        return tok
    return TOKEN.sub(fix, text)


def _repeats(text: str) -> str:
    def fix(m):
        return m.group(0) if m.group(1).lower() in NO_REPEAT else m.group(1)
    for _ in range(5):
        new = re.sub(r"\b([A-Za-z]{2,}) \1\b", fix, text, flags=re.IGNORECASE)
        if new == text:
            break
        text = new
    return text


def _spacing(text: str) -> str:
    text = re.sub(r"(?<=\S) {2,}(?=\S)", " ", text)
    text = re.sub(r"(?<=[A-Za-z0-9]) +([,.!?])(?=\s|$)", r"\1", text)
    text = re.sub(r"(?<=[A-Za-z]),(?=[A-Za-z])", ", ", text)
    return text


def _sentence_caps(text: str, sentence_start: bool) -> str:
    chars = list(text)
    if sentence_start:
        m = re.match(r"\s*([a-z])", text)
        if m:
            chars[m.start(1)] = m.group(1).upper()
    for m in re.finditer(r"([.!?])['\")\]”’]*\s+([a-z])", text):
        prev = re.search(r"([A-Za-z]+)$", text[:m.start()])
        if m.group(1) == "." and (prev is None or len(prev.group(1)) == 1 or prev.group(1).lower() in ABBREV):
            continue
        chars[m.start(2)] = m.group(2).upper()
    return "".join(chars)


def fix_text(text: str, logp, sentence_start: bool = False) -> str:
    """Return `text` with common slips fixed. `sentence_start`: the text begins a sentence."""
    text = _merge_splits(text, logp)
    text = _split_i(text)
    text = _dictionary_fixes(text)
    text = _lone_i(text)
    text = _repeats(text)
    text = _spacing(text)
    return _sentence_caps(text, sentence_start)


def edits(old: str, new: str):
    """The changes that turn `old` into `new`: [(start, end, replacement)], in order, in old's coordinates."""
    if old == new:
        return []
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        if out and out[-1][1] == i1:               # touching changes become one
            out[-1] = (out[-1][0], i2, out[-1][2] + new[j1:j2])
        else:
            out.append((i1, i2, new[j1:j2]))
    return out
