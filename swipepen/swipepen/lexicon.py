"""Word lists with frequency priors.

Preferred source: the `wordfreq` package (pip install wordfreq) - real
frequencies, many languages. Fallback (used for offline testing): the system
hunspell dictionary plus a small bundled list of very common English words.

Each entry is (surface, letters_key, log10_probability). `letters_key` is the
lowercase word with apostrophes removed, because you cannot swipe an apostrophe
("don't" is swiped as d-o-n-t and comes out with its apostrophe).
"""
from __future__ import annotations

import math
import os
import re

WORD_RE = re.compile(r"^[a-z]+(?:'[a-z]+)*$")
HERE = os.path.dirname(os.path.abspath(__file__))
USER_RE = re.compile(r"^[A-Za-z]+(?:'[A-Za-z]+)*$")
USER_LOGP = -3.0       # your own words rank like fairly common words
HUNSPELL_PATHS = (
    "/usr/share/hunspell/en_US.dic",
    "/usr/share/myspell/en_US.dic",
    "/usr/share/myspell/dicts/en_US.dic",
)


def _entry(surface: str, logp: float):
    return (surface, surface.replace("'", "").lower(), logp)


def _from_wordfreq(lang: str, max_words: int):
    from wordfreq import top_n_list, word_frequency  # may raise ImportError

    out = []
    for w in top_n_list(lang, max_words, wordlist="best"):
        if len(w) < 2 or len(w) > 22 or not WORD_RE.match(w):
            continue
        f = word_frequency(w, lang, wordlist="best")
        out.append(_entry(w, math.log10(f) if f > 0 else -9.0))
    return out


def _from_fallback():
    ranks = {}
    with open(os.path.join(HERE, "data", "common_en.txt"), encoding="utf-8") as fh:
        for line in fh:
            w = line.strip()
            if w and w not in ranks:
                ranks[w] = len(ranks)

    words = set(ranks)
    for path in HUNSPELL_PATHS:
        if os.path.exists(path):
            with open(path, encoding="utf-8", errors="ignore") as fh:
                next(fh, None)  # first line is the entry count
                for line in fh:
                    w = line.split("/")[0].strip()
                    if WORD_RE.match(w):  # lowercase only: skips proper nouns
                        words.add(w)
            break

    out = []
    for w in words:
        if len(w) < 2 or len(w) > 22:
            continue
        r = ranks.get(w)
        logp = math.log10(0.07 / (r + 1)) if r is not None else -5.5
        out.append(_entry(w, logp))
    return out


def load_lexicon(lang: str = "en", max_words: int = 60000, force_fallback: bool = False,
                 verbose: bool = True):
    source = "fallback"
    entries = None
    if not force_fallback:
        try:
            entries = _from_wordfreq(lang, max_words)
            source = "wordfreq"
        except ImportError:
            if lang != "en":
                raise SystemExit("Only English works without wordfreq: pip install --user wordfreq")
    if entries is None:
        if lang != "en":
            raise SystemExit("The offline fallback only has English.")
        entries = _from_fallback()

    if verbose:
        print(f"[swipepen] lexicon: {len(entries)} words from {source}")
    return entries


# --------------------------------------------------------------------------
# Your personal dictionary: ~/.config/swipepen/words.txt, one word per line.
# Capitals are kept, so names come out as "Marcos" (and "iPhone" stays "iPhone").
# --------------------------------------------------------------------------
def user_words_path() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "swipepen", "words.txt")


def clean_user_word(word: str):
    """The word as it would be stored, or None if it cannot be swiped (letters and ' only)."""
    w = word.strip().replace("’", "'")
    return w if len(w) >= 2 and USER_RE.match(w) else None


def read_user_words() -> list[str]:
    try:
        with open(user_words_path(), encoding="utf-8") as fh:
            lines = [ln.strip() for ln in fh if ln.strip() and not ln.lstrip().startswith("#")]
    except OSError:
        return []
    out, seen = [], set()
    for ln in lines:
        w = clean_user_word(ln)
        if w and w not in seen:
            seen.add(w)
            out.append(w)
    return out


def _write_user_words(words: list[str]):
    path = user_words_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(words) + ("\n" if words else ""))


def add_user_word(word: str) -> bool:
    """Returns True if the word was added (False: invalid, or already there)."""
    w = clean_user_word(word)
    words = read_user_words()
    if not w or w in words:
        return False
    _write_user_words(words + [w])
    return True


def remove_user_word(word: str) -> bool:
    words = read_user_words()
    keep = [w for w in words if w != word.strip()]
    if len(keep) == len(words):
        return False
    _write_user_words(keep)
    return True


def user_entries():
    return [_entry(w, USER_LOGP) for w in read_user_words()]
