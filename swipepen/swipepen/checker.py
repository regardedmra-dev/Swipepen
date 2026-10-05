"""Find problems in a paragraph and say how to fix each one.

Pure code (plus one optional HTTP call), no keyboard or document needed, so it can be tested alone.

    issues = check(text, decoder)                     # built-in checks only
    issues = check(text, decoder, lt_url="http://127.0.0.1:8081")   # + LanguageTool, if it answers

An Issue says where the problem is (`start`, `end`, offsets into `text`), what kind it is, a short message and the
suggested replacements (best first). Where the checks come from, best first:

  1. LanguageTool       - only when you run one yourself (see the README); it is the one that understands real grammar
  2. grammar rules      - a small built-in list of very common mix-ups (a/an, should of, your/you're, then/than ...)
  3. typo fixes         - the same fixes the live "fix typos as I type" does (hel lo, dont, lone i ...)
  4. spelling           - unknown lowercase words that have a close real word
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from . import tidy as tidy_mod
from .lookup import Speller

WORD = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)*")
PRIORITY = {"languagetool": 0, "grammar": 1, "typo": 2, "spelling": 3}
LT_AUTO = ("http://127.0.0.1:8081", "http://127.0.0.1:8010")


@dataclass
class Issue:
    start: int
    end: int
    kind: str                    # "grammar", "typo", "spelling", "languagetool"
    message: str
    suggestions: list = field(default_factory=list)
    source: str = "builtin"
    easy: bool = False           # one clear answer: safe for "fix all easy ones"

    @property
    def length(self):
        return self.end - self.start

    def old(self, text):
        return text[self.start:self.end]


# --------------------------------------------------------------------------
# Grammar rules.  (pattern, replacement, message).  The part to change is the named group `x`;
# the replacement is a string or a function of the match.  Case of the first letter is kept.
# --------------------------------------------------------------------------
_A_NOT_AN = ("one once u uni use used useful user usual usually utility utensil unit unite united universal universe "
             "university unique unicorn uniform union euro europe european ewe eulogy").split()
_AN_NOT_A = "hour hours honest honestly honor honour honorable heir heirs".split()


def _an(m):
    return "an"


def _a(m):
    return "a"


def _a_an_ok(m):
    nxt = m.group("n").lower()
    return not any(nxt == w or nxt.startswith(w) for w in _A_NOT_AN)


def _an_a_ok(m):
    nxt = m.group("n").lower()
    return not nxt[:1] in "aeiou" and not any(nxt == w for w in _AN_NOT_A) and nxt[:1].isalpha()


RULES = [
    (r"\b(?P<x>a)\s+(?P<n>[aeiou]\w*)", _an, "Use “an” before a vowel sound", _a_an_ok),
    (r"\b(?P<x>an)\s+(?P<n>[b-df-hj-np-tv-z]\w*)", _a, "Use “a” before a consonant sound", _an_a_ok),
    (r"\b(?:should|could|would|must|might)\s+(?P<x>of)\b", "have", "It is “have”, not “of”", None),
    (r"\b(?P<x>your)\s+(?:a|an|not|going|welcome|right|wrong|being|so|very|too|really|always|never|the best|just|"
     r"gonna|doing|coming|trying)\b", "you're", "“you're” means “you are”", None),
    (r"\b(?P<x>you're)\s+(?:own|car|house|mom|dad|friend|family|name|work|job|phone|home)\b", "your",
     "“your” shows that something belongs to you", None),
    (r"\b(?P<x>their)\s+(?:is|are|was|were)\b", "there", "“there” is the place or the fact: there is…", None),
    (r"\b(?P<x>there)\s+(?:own)\b", "their", "“their” shows that something belongs to them", None),
    (r"\b(?P<x>their|there)\s+(?:going|coming|gonna|trying|being|not)\b", "they're", "“they're” means “they are”", None),
    (r"\b(?:more|less|better|worse|bigger|smaller|faster|slower|rather|other|greater|larger|older|younger|higher|"
     r"lower|easier|harder|taller|shorter|longer|cheaper)\s+(?P<x>then)\b", "than", "Comparing things: “than”", None),
    (r"\b(?:he|she|it)\s+(?P<x>don't|dont)\b", "doesn't", "Use “doesn't” after he / she / it", None),
    (r"\b(?:i|you|we|they)\s+(?P<x>doesn't|doesnt)\b", "don't", "Use “don't” after I / you / we / they", None),
    (r"\b(?:you|we|they)\s+(?P<x>was)\b", "were", "Use “were” after you / we / they", None),
    (r"\b(?:he|she|it)\s+(?P<x>have)\b", "has", "Use “has” after he / she / it", None),
    (r"\b(?:you|we|they|i)\s+(?P<x>has)\b", "have", "Use “have” after I / you / we / they", None),
    (r"\b(?P<x>its)\s+(?:a|an|been|going|not|just|true|ok|okay|fine|time to)\b", "it's", "“it's” means “it is”", None),
    (r"\b(?P<x>it's)\s+(?:own)\b", "its", "“its” shows that something belongs to it", None),
    (r"\b(?P<x>lets)\s+(?:go|get|see|try|do|start|make|take|talk|be|say|have|just|meet|find|move|eat)\b", "let's",
     "“let's” means “let us”", None),
    (r"\b(?P<x>whose)\s+(?:going|coming|there|here|been)\b", "who's", "“who's” means “who is”", None),
    (r"\b(?P<x>to\s+(?:much|many))\b(?!\s+of\b)", lambda m: "too " + m.group("x").split()[-1], "“too” means more than enough", None),
    (r"\b(?P<x>loose)\s+(?:the|my|your|his|her|our|their|weight|control|track|money|sleep|hope)\b", "lose",
     "“lose” is the verb: to lose something", None),
    (r"\b(?P<x>irregardless)\b", "regardless", "The word is “regardless”", None),
    (r"\bfor all (?P<x>intensive purposes)\b", "intents and purposes", "The phrase is “for all intents and purposes”",
     None),
    (r"\b(?P<x>could care less)\b", "couldn't care less", "Usually meant: “couldn't care less”", None),
    (r"\b(?P<x>alot)\b", "a lot", "“a lot” is two words", None),
]
_COMPILED = [(re.compile(p, re.I), r, msg, ok) for p, r, msg, ok in RULES]


def _like(src: str, dst: str) -> str:
    if src[:1].isupper() and dst:
        return dst[:1].upper() + dst[1:]
    return dst


_DELETE_RULES = [
    # (pattern, message): the span from group `x` up to group `y` is removed
    (re.compile(r"\b(?P<x>more)\s+(?P<y>better|easier|faster|bigger|worse)\b", re.I), "Double comparison: drop “more”"),
    (re.compile(r"\b(?P<x>a|an)\s+(?P<y>the)\b", re.I), "Two articles in a row"),
]


def grammar_issues(text: str):
    out = []
    for rx, repl, msg, ok in _COMPILED:
        for m in rx.finditer(text):
            if ok is not None and not ok(m):
                continue
            s, e = m.span("x")
            new = repl(m) if callable(repl) else repl
            out.append(Issue(s, e, "grammar", msg, [_like(text[s:e], new)], easy=True))
    for rx, msg in _DELETE_RULES:
        for m in rx.finditer(text):
            s, e = m.start("x"), m.start("y")                 # removes the word and the space after it
            keep = text[e:m.end("y")]
            out.append(Issue(s, m.end("y"), "grammar", msg, [_like(text[s:m.end("y")], keep)], easy=True))
    return out


# --------------------------------------------------------------------------
# Typo fixes (same engine as the live fixer) shown as issues, widened to whole words
# --------------------------------------------------------------------------
def typo_issues(text: str, logp, sentence_start: bool = True):
    new = tidy_mod.fix_text(text, logp, sentence_start=sentence_start)
    groups = []                                           # [start, end, [ops]] widened to whole words
    for start, end, rep in tidy_mod.edits(text, new):
        s, e = start, end
        while s > 0 and not text[s - 1].isspace():
            s -= 1
        while e < len(text) and not text[e].isspace():
            e += 1
        if groups and s <= groups[-1][1]:                 # same word as the previous edit: one issue for both
            groups[-1][1] = max(groups[-1][1], e)
            groups[-1][2].append((start, end, rep))
        else:
            groups.append([s, e, [(start, end, rep)]])
    out = []
    for s, e, ops in groups:
        fixed = text[s:e]
        for start, end, rep in sorted(ops, reverse=True):
            fixed = fixed[:start - s] + rep + fixed[end - s:]
        if fixed == text[s:e]:
            continue
        out.append(Issue(s, e, "typo", f"“{text[s:e].strip() or '␣'}” → “{fixed.strip() or '␣'}”", [fixed], easy=True))
    return out


# --------------------------------------------------------------------------
# Spelling
# --------------------------------------------------------------------------
_SUFFIXES = ("s", "es", "ed", "d", "ing", "ly", "ally", "ily", "er", "ers", "est", "ness", "ment", "ments",
             "ful", "less", "able", "ies", "ied", "ier", "iest", "ness")


def _derived_known(w: str, logp) -> bool:
    """Is `w` a known word plus an ending (perfectly, stopped, tried, happiness ...)?"""
    for suf in _SUFFIXES:
        if len(w) > len(suf) + 2 and w.endswith(suf):
            stem = w[:-len(suf)]
            cands = {stem, stem + "e", stem + "y" if suf in ("ies", "ied", "ier", "iest", "ily") else stem}
            if len(stem) > 2 and stem[-1] == stem[-2]:
                cands.add(stem[:-1])                      # stopped -> stop
            if suf in ("ily", "ier", "iest", "ness") and stem.endswith("i"):
                cands.add(stem[:-1] + "y")                # happily / happiness -> happy
            if any(logp(c) is not None for c in cands if len(c) > 1):
                return True
    return False


def spelling_issues(text: str, decoder, speller: Speller | None = None):
    speller = speller or Speller(decoder)
    out = []
    for m in WORD.finditer(text):
        w = m.group(0)
        if len(w) < 3 or not w.islower() or "'" in w or "’" in w:
            continue
        before = text[max(0, m.start() - 1):m.start()]
        if before in ("@", "/", "#", "_", "-", ".") or text[m.end():m.end() + 1] in ("@", "/", "_"):
            continue                                      # looks like part of an address or a tag
        if decoder.logp(w) is not None or _derived_known(w, decoder.logp):
            continue
        sugg = speller.suggest(w, 5)
        if sugg:
            out.append(Issue(m.start(), m.end(), "spelling", f"“{w}” is not in the dictionary", sugg,
                             easy=False))
    return out


# --------------------------------------------------------------------------
# LanguageTool (optional, your own server)
# --------------------------------------------------------------------------
def languagetool_issues(text: str, url: str, language: str = "auto", timeout: float = 6.0):
    """Ask a LanguageTool server (https://languagetool.org/http-api/). Returns [] when it is not there."""
    body = urllib.parse.urlencode({"text": text, "language": language}).encode()
    req = urllib.request.Request(url.rstrip("/") + "/v2/check", data=body,
                                 headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "swipepen"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except (OSError, ValueError, urllib.error.URLError):
        return None
    # LanguageTool counts UTF-16 code units; Python counts characters. Map one to the other.
    units, pos = [], 0
    for ch in text:
        units.append(pos)
        pos += 2 if ord(ch) > 0xFFFF else 1
    units.append(pos)
    to_char = {u: i for i, u in enumerate(units)}
    out = []
    for m in data.get("matches", []):
        s, e = to_char.get(m.get("offset")), to_char.get(m.get("offset", 0) + m.get("length", 0))
        if s is None or e is None:
            continue
        sugg = [r["value"] for r in m.get("replacements", []) if r.get("value") is not None][:5]
        cat = ((m.get("rule") or {}).get("category") or {}).get("id", "")
        msg = m.get("shortMessage") or m.get("message") or "possible problem"
        out.append(Issue(s, e, "languagetool", msg, sugg, source="languagetool",
                         easy=len(sugg) == 1 and cat in ("TYPOS", "GRAMMAR", "CASING", "PUNCTUATION")))
    return out


def find_languagetool(url: str = "") -> str | None:
    """The configured server, or a LanguageTool running on this computer on its usual ports."""
    for u in ([url] if url else []) + ([] if url else list(LT_AUTO)):
        try:
            with urllib.request.urlopen(u.rstrip("/") + "/v2/languages", timeout=0.6) as r:
                if r.status == 200:
                    return u
        except (OSError, ValueError, urllib.error.URLError):
            continue
    return None


# --------------------------------------------------------------------------
def merge(groups):
    """Combine issue lists; where two overlap the better source wins. Result sorted by position."""
    allv = sorted((i for g in groups for i in g), key=lambda i: (PRIORITY.get(i.kind, 9), i.start))
    kept = []
    for i in allv:
        if any(i.start < k.end and k.start < i.end for k in kept):
            continue
        kept.append(i)
    return sorted(kept, key=lambda i: (i.start, i.end))


def check(text: str, decoder, lt_url: str | None = None, sentence_start: bool = True):
    """All issues in `text`. Returns (issues, notes) where notes lists what was or wasn't used."""
    groups, notes = [], []
    if lt_url:
        lt = languagetool_issues(text, lt_url)
        if lt is None:
            notes.append("LanguageTool did not answer")
        else:
            groups.append(lt)
            notes.append("LanguageTool")
    groups.append(grammar_issues(text))
    groups.append(typo_issues(text, decoder.logp, sentence_start))
    groups.append(spelling_issues(text, decoder))
    return merge(groups), notes
