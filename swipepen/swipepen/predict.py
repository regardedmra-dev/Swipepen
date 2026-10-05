"""Next-word prediction (and re-ranking of swipe results by the word before).

Two sources, mixed:
  * a built-in list of what usually follows the most common English words (small, hand-made, so it is
    sensible but not clever)
  * what YOU write: every pair and triple of words you finish is counted and saved on this computer
    (~/.config/swipepen/phrases.json). Nothing is sent anywhere. It gets better the more you write, and you can
    switch learning off or wipe it in Settings.

    p = Predictor(known=decoder.logp)
    p.next_words(["thank"], n=3)                 # ['you', 'for', 'god']
    p.next_words([], sentence_start=True)        # ['I', 'The', 'It']
    p.learn(["i", "want", "to"])                 # counts want->to, i+want->to
"""
from __future__ import annotations

import json
import os
import tempfile
from collections import Counter, defaultdict

SEED = """
<s>: i the it we you this but so that he she they what if when my thank please hi hello how there yes no and
i: am have think want will was do would can know need just love like feel got had hope guess mean see
i'm: not going so sorry sure just really a very glad happy trying
i'll: be do see try get have let call send
i've: been got had never always just seen
i'd: like love be say rather
you: are can have will know want need should could were do don't think
you're: not going welcome so a the very right
we: are have can will need should could were want did do
we're: not going all in so
they: are have were will can said did don't
they're: not going all so just
he: is was has had said will would can could did
she: is was has had said will would can could did
it: is was will would has can could seems looks makes takes
it's: a not the just so been going time
that: is was the i you we it he she they would
that's: a not the what so why great right
this: is was will would could one time week morning
there: is are was were will would
there's: a no nothing been
what: is are was do did you the about a happened
when: i you we the it they he she is
where: is are did do you the
who: is are was did do can
how: are is do did much many long about to
why: is are do did not
the: same first best most only other next last new way end world people day
a: lot little few good new bit great very long big
an: hour idea example amazing important
to: be the do get see make go have a take say know
of: the a course my your all them these
in: the a my your this that order case fact time
on: the a my your this that top time monday
for: the a my your you me us him her this
with: the a my your you me us him her
at: the a my your this that least home all
by: the a my your this that
from: the a my your this that now
and: the i then a we you it he she they
but: i it the we you he she they then
or: the a i we you it
so: i the we you it that much far
if: you i we the it they he she
because: i the it we you of they
as: a the i we you well soon much long
is: a the not it there this that going
are: you the not we they going there
was: a the not it there this that going
were: you the not we they going there
be: a the able there in here sure
been: a the there to in working
have: a the to been you any
has: a the been to not
had: a the to been you
do: you not the it we i
does: it the not that he she
did: you not the it we i
will: be you not the it we
would: be you like not the it
can: you be not the it we
could: you be not have the it
should: be you not the we have
not: be the a sure going been
my: name friend family life best own
your: name friend family life best own
our: team family life best own
his: name friend own life
her: name friend own life
their: name friend own life
just: a the like want to got
very: much good well important happy
really: good well want like need
going: to be on back home
want: to the a you it
need: to the a you it
think: that it so about we
know: that what how you the
like: to a the you it
love: you to the it it's
thank: you
thanks: for so a
please: let be send do
hello: how there
hi: there how i
good: morning night afternoon evening luck idea
great: to job idea thanks
see: you the what
get: the a it to back
make: sure a the it
take: a the care it
go: to back home ahead
come: to back on with
look: at like forward
let: me us you him
let's: go see do start
don't: know want have think worry
can't: wait believe do
didn't: know want have
doesn't: matter work
won't: be
wasn't: a the
isn't: a the
no: one problem more
yes: i it we
all: the of right about
some: of other people
more: than of
much: more of better
many: of people
one: of day thing
two: of or
about: the a it
into: the a
over: the a
after: the that
before: the that
also: the a
only: a the
still: have
even: if though
never: be
always: be
well: i it
now: i
today: i we
tomorrow: i we
yesterday: i we
morning: i
night: i
time: to i
day: i
new: york
first: time
last: night week
next: week time
other: people
own: way
same: time
back: to
down: the
up: to the
out: of the
off: the
again: i
"""


def _parse_seed():
    table = defaultdict(list)
    for line in SEED.strip().splitlines():
        if ":" not in line:
            continue
        head, tail = line.split(":", 1)
        table[head.strip()] = tail.split()
    return table


def config_dir():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "swipepen")


def phrases_path():
    return os.path.join(config_dir(), "phrases.json")


class Predictor:
    SAVE_EVERY = 25
    MAX_CONTEXTS = 6000

    def __init__(self, known=None, path: str | None = "auto", learning: bool = True):
        """known: callable(word) -> truthy if the word is a real word (predictions are filtered by it)."""
        self.known = known
        self.learning = learning
        self.path = phrases_path() if path == "auto" else path
        self.seed = _parse_seed()
        self.bi: dict[str, Counter] = defaultdict(Counter)
        self.tri: dict[str, Counter] = defaultdict(Counter)
        self._dirty = 0
        self.load()

    # ---- storage ---------------------------------------------------------------------------------
    def load(self):
        if not self.path:
            return
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
            for table, key in ((self.bi, "bi"), (self.tri, "tri")):
                for ctx, nxt in data.get(key, {}).items():
                    table[ctx] = Counter({w: int(n) for w, n in nxt.items() if isinstance(n, int)})
        except (OSError, ValueError, AttributeError):
            pass

    def save(self):
        if not self.path or not self._dirty:
            return
        self._prune()
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.path), suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"v": 1, "bi": {k: dict(v) for k, v in self.bi.items()},
                           "tri": {k: dict(v) for k, v in self.tri.items()}}, fh, ensure_ascii=False)
            os.replace(tmp, self.path)
            self._dirty = 0
        except OSError:
            pass

    def forget(self):
        self.bi.clear()
        self.tri.clear()
        self._dirty = 0
        if self.path:
            try:
                os.remove(self.path)
            except OSError:
                pass

    def _prune(self):
        for table in (self.bi, self.tri):
            if len(table) > self.MAX_CONTEXTS:
                keep = sorted(table, key=lambda c: -sum(table[c].values()))[: self.MAX_CONTEXTS * 3 // 4]
                for c in [c for c in table if c not in set(keep)]:
                    del table[c]

    # ---- learning -----------------------------------------------------------------------------------
    def learn(self, words: list):
        """`words`: the finished words of one sentence so far (lowercase). Counts the last pair and triple."""
        if not self.learning or not words:
            return
        w = words[-1]
        prev = words[-2] if len(words) > 1 else "<s>"
        if len(w) < 1 or len(w) > 30:
            return
        self.bi[prev][w] += 1
        if len(words) > 2:
            self.tri[words[-3] + " " + prev][w] += 1
        self._dirty += 1
        if self._dirty >= self.SAVE_EVERY:
            self.save()

    # ---- asking ---------------------------------------------------------------------------------------
    def _scores(self, context: list):
        """word -> score for what may follow `context` (the words of the current sentence, lowercase)."""
        ctx = list(context)
        prev = ctx[-1] if ctx else "<s>"
        scores: dict[str, float] = defaultdict(float)
        if len(ctx) >= 2:
            for w, n in self.tri.get(ctx[-2] + " " + prev, {}).items():
                scores[w] += 4.0 * n
        for w, n in self.bi.get(prev, {}).items():
            scores[w] += 2.0 * n
        for rank, w in enumerate(self.seed.get(prev, ())):
            scores[w] += 1.0 / (1 + rank * 0.5)
        return scores

    def _ok(self, w: str) -> bool:
        return w in ("<s>", "i", "a") or self.known is None or self.known(w) is not None

    def ranked(self, context: list, n: int = 8):
        sc = self._scores(context)
        out = [w for w, _ in sorted(sc.items(), key=lambda kv: (-kv[1], kv[0])) if self._ok(w)]
        recent = set(context[-2:])                      # "you are you are ...": words just used come last
        out = [w for w in out if w not in recent] + [w for w in out if w in recent]
        prev = context[-1] if context else None
        for w in ("the", "to", "and", "a", "of", "in", "it", "is", "that", "you", "i"):   # filler: common words
            if len(out) >= n:
                break
            if w not in out and w != prev and self._ok(w):
                out.append(w)
        return out[:n]

    def next_words(self, context: list, n: int = 3, sentence_start: bool = False):
        ctx = [] if sentence_start else context
        words = self.ranked(ctx, max(n, 3))[:n]
        return [self._shape(w, sentence_start) for w in words]

    @staticmethod
    def _shape(w: str, capital: bool) -> str:
        if w == "i" or w.startswith("i'"):
            return "I" + w[1:]
        return w[:1].upper() + w[1:] if capital else w

    def affinity(self, context: list, word: str) -> float:
        """0..1: how well does `word` fit after `context` (used to re-rank swipe results)."""
        w = word.lower()
        ranked = self.ranked(context, 8)
        sc = self._scores(context)
        if w in ranked[:3] and sc.get(w, 0) > 0:
            return 1.0
        if w in ranked and sc.get(w, 0) > 0:
            return 0.6
        return 0.3 if sc.get(w, 0) > 0 else 0.0

    def rank_completions(self, completions: list, context: list):
        """Put the completions that fit the context first, keep the frequency order otherwise."""
        sc = self._scores(context)
        return sorted(completions, key=lambda w: (-min(sc.get(w, 0.0), 6.0), completions.index(w)))
