"""A word-pair table made from text, for stronger next-word prediction.

The built-in suggestions are a short hand-made list. A pair table made from real writing knows far more about what
follows what. swipepen does not ship one (a table is only as good, and as freely usable, as the text it came from),
so you make it from text you choose:

    swipepen build-ngrams ~/Documents/my-writing/ other.txt --evaluate

That reads .txt / .md / .html / .docx files (folders are searched), counts which word follows which, keeps the
likeliest followers of each word, and saves them to ~/.config/swipepen/bigrams_en.tsv.gz, where the predictor finds
it at the next start. With --evaluate it first holds back 10% of the sentences and reports how often the right next
word was among the three suggestions, with and without the table: your own number, from your own text.
Text that is public domain or yours is the safe choice. A table built from your own writing also learns your style.

A table file is gzip'd text, one pair per line:   previous-word <TAB> next-word <TAB> count     ("<s>" = sentence start)
If a packaged table (swipepen/data/bigrams_en.tsv.gz) and your own both exist, their counts are added.
"""
from __future__ import annotations

import gzip
import os
import re
import zipfile
from collections import Counter, defaultdict

WORD_RE = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)*")
SENT_RE = re.compile(r"[.!?]+[\s\"”')\]]*|\n+")
TEXT_EXT = (".txt", ".md", ".text", ".rst", ".html", ".htm", ".docx")
START = "<s>"
PRUNE_AT = 3_000_000          # while counting: drop pairs seen once when there are this many distinct pairs


def config_file(lang: str = "en") -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "swipepen", f"bigrams_{lang}.tsv.gz")


def packaged_file(lang: str = "en") -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", f"bigrams_{lang}.tsv.gz")


# ---- reading text -------------------------------------------------------------------------------------------------
def read_text(path: str) -> str:
    low = path.lower()
    try:
        if low.endswith(".docx"):
            with zipfile.ZipFile(path) as z:
                xml = z.read("word/document.xml").decode("utf-8", "replace")
            return re.sub(r"<[^>]+>", " ", re.sub(r"</w:p>", "\n", xml))
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except (OSError, KeyError, zipfile.BadZipFile):
        return ""
    if low.endswith((".html", ".htm")):
        text = re.sub(r"<(script|style)\b.*?</\1>", " ", text, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
    return text


def find_files(paths) -> list[str]:
    out = []
    for p in paths:
        if os.path.isdir(p):
            for root, _dirs, files in os.walk(p):
                out += [os.path.join(root, f) for f in sorted(files) if f.lower().endswith(TEXT_EXT)]
        elif os.path.isfile(p):
            out.append(p)
    return out


def sentences(text: str):
    """Yield each sentence as a list of lowercase words (apostrophes normalised)."""
    for chunk in SENT_RE.split(text):
        words = [w.lower().replace("’", "'") for w in WORD_RE.findall(chunk)]
        if words:
            yield words


# ---- counting and writing --------------------------------------------------------------------------------------------
def count_pairs(sents, known) -> Counter:
    """(previous, next) -> count. Only words `known(word)` says are real take part, so nothing odd is ever offered."""
    c: Counter = Counter()
    for words in sents:
        prev = START
        for w in words:
            if known(w) is None or len(w) > 30:
                prev = None                              # an unknown word breaks the chain: no pair across it
                continue
            if prev is not None:
                c[(prev, w)] += 1
            prev = w
        if len(c) > PRUNE_AT:
            for k in [k for k, n in c.items() if n < 2]:
                del c[k]
    return c


def trim(counts: Counter, top: int = 8, min_count: int = 3, max_contexts: int = 30000) -> dict:
    """Keep each word's likeliest followers (at least min_count sightings) and the busiest contexts."""
    by_prev = defaultdict(list)
    for (prev, nxt), n in counts.items():
        if n >= min_count:
            by_prev[prev].append((n, nxt))
    keep = sorted(by_prev, key=lambda p: -sum(n for n, _ in by_prev[p]))[:max_contexts]
    return {p: sorted(by_prev[p], key=lambda t: (-t[0], t[1]))[:top] for p in keep}


def write_table(table: dict, path: str) -> int:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    n = 0
    tmp = path + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        for prev in sorted(table):
            for count, nxt in table[prev]:
                fh.write(f"{prev}\t{nxt}\t{count}\n")
                n += 1
    os.replace(tmp, path)
    return n


def shares(table: dict) -> dict:
    """trim()'s {prev: [(count, next)]} -> the {prev: [(next, share)]} form the predictor uses."""
    out = {}
    for prev, rows in table.items():
        total = sum(n for n, _ in rows)
        if total:
            out[prev] = [(w, n / total) for n, w in rows]
    return out


def load_table(lang: str = "en", paths=None) -> dict:
    """{previous word: [(next word, share 0..1), ...]} from the packaged and your own table; {} if there is none.
    The share is the count divided by the total kept for that word, so tables of any size mix sensibly."""
    raw: dict[str, Counter] = defaultdict(Counter)
    for path in (paths if paths is not None else (packaged_file(lang), config_file(lang))):
        try:
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                for line in fh:
                    prev, _, rest = line.rstrip("\n").partition("\t")
                    nxt, _, n = rest.partition("\t")
                    if prev and nxt and n.isdigit():
                        raw[prev][nxt] += int(n)
        except (OSError, EOFError, ValueError):
            continue
    out = {}
    for prev, cnt in raw.items():
        total = sum(cnt.values())
        out[prev] = [(w, n / total) for w, n in cnt.most_common()]
    return out


# ---- measuring it ----------------------------------------------------------------------------------------------------
def split_sentences(sents: list, holdout: float = 0.1):
    """Deterministic split: every k-th sentence is held back."""
    k = max(2, round(1 / holdout)) if holdout > 0 else 0
    train, test = [], []
    for i, s in enumerate(sents):
        (test if k and i % k == k - 1 else train).append(s)
    return train, test


def evaluate(test: list, pred, n: int = 3, limit: int = 20000) -> dict:
    """How often is the word that really came next the first suggestion / among the n suggestions?
    Every word of the held-back sentences counts, the first word of a sentence included."""
    hits = {1: 0, n: 0}
    total = 0
    for words in test:
        for i, w in enumerate(words):
            if total >= limit:
                break
            got = [x.lower() for x in pred.next_words(words[:i], n, sentence_start=(i == 0))]
            total += 1
            hits[1] += got[:1] == [w]
            hits[n] += w in got
    return {"n": total, 1: hits[1], n: hits[n]}
