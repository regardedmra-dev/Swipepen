"""Typing session: turns pen strokes into typed text.

GUI-free and device-free so it can be tested headless. Positions are in key
units (see engine.py). The injector is anything with:
    type_text(str), backspace(n), enter()
"""
from __future__ import annotations

import json
import re
import time
import unicodedata
from collections import deque

from . import tidy as tidy_mod
from .engine import CANVAS_W, Decoder, classify, path_length

TAP_MAX_LENGTH = 0.8   # strokes shorter than this (key units) are taps
ERASE_FIRST = 0.8      # swipe left this far on backspace to select the first word...
ERASE_PER_WORD = 1.0   # ...and this much further for each extra word
CURSOR_DEAD = 0.5      # on space: ignore sideways movement smaller than this
CURSOR_STEP = 0.35     # then move the caret one character per this distance
# Hold the pen at the edge of the keyboard and the caret keeps going (momentum + speed-up):
CURSOR_EDGE = 0.3      # within this distance of the keyboard's left/right edge = "at the edge"
EDGE_RATE_MIN = 6.0    # characters per second when you arrive slowly...
EDGE_RATE_START_MAX = 40.0   # ...up to this: you arrive at the speed of your swipe
EDGE_RATE_MAX = 70.0   # the caret never goes faster than this
EDGE_ACCEL = 15.0      # extra characters per second, for every second the pen stays at the edge
EDGE_MAX_PER_TICK = 8  # safety: never type more than this many arrow presses in one go
SENTENCE_END = (".",)
DOUBLE_TAP = 0.45      # two taps on shift this close together = caps lock
ATTACH_LEFT = set(".,!?:;)]}%")      # these hug the word before them: "word !" -> "word!"
SPACE_AFTER = set("!?:;")            # ...and start a new word after them
TIDY_MAX_CHARS = 1200  # "tidy" looks at most this far back (more arrow presses = slower)
WORD_RE = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)*")


class _Tracked:
    """Wraps the injector and remembers the text we typed since the caret last moved
    (`tail`). That is what the live typo fixes look at; text we never typed is never touched.
    `version` counts every change we make, so "undo" can tell whether anything happened since."""

    def __init__(self, inj):
        self._inj = inj
        self.tail = ""
        self.floor = 0              # live fixes ignore tail[:floor] (text the user chose to keep as typed)
        self.version = 0
        self.scroller = None        # Typewriter, when "keep the cursor level" is on

    def _changed(self):
        self.version += 1

    def _moved(self):
        self.version += 1
        self.tail = ""
        self.floor = 0

    def type_text(self, s):
        self._inj.type_text(s)
        self._changed()
        self.tail += s
        if self.scroller:
            self.scroller.typed(s)

    def backspace(self, n=1):
        self._inj.backspace(n)
        self._changed()
        self.tail = self.tail[:-n] if 0 < n <= len(self.tail) else ""
        self.floor = min(self.floor, len(self.tail))
        if self.scroller:
            self.scroller.erased(n)

    def enter(self):
        self._inj.enter()
        self._changed()
        self.tail += "\n"
        if self.scroller:
            self.scroller.typed("\n")

    def move_cursor(self, n):
        self._inj.move_cursor(n)
        self._moved()

    def select_word_left(self):
        self._inj.select_word_left()
        self._moved()

    def collapse_selection(self):
        self._inj.collapse_selection()
        self._changed()

    def press(self, combo):
        self._inj.press(combo)
        self._moved()

    def undo_key(self):
        self._inj.undo_key()
        self._moved()

    def flush_scroll(self):
        if self.scroller:
            self.scroller.flush()

    def __getattr__(self, name):          # grab_*, scroll, close, ...
        return getattr(self._inj, name)


class _Last:
    """The last swipe-typed word, so Backspace / candidate taps can undo it."""
    __slots__ = ("typed", "cands", "chosen", "shifted", "caps")

    def __init__(self, typed, cands, shifted, caps=False):
        self.typed = typed          # text on screen, WITHOUT the trailing space
        self.cands = cands          # list of lowercase candidate surfaces
        self.chosen = 0
        self.shifted = shifted
        self.caps = caps


class Session:
    def __init__(self, decoder: Decoder, injector, record_path: str | None = None,
                 auto_cap_after_period: bool = True):
        self.decoder = decoder
        self.inj = _Tracked(injector)
        self.autofix = True           # fix typos live (hel lo -> hello, lone i -> I, ...)
        self.edge_speed = 1.0         # multiplier for the cursor momentum at the keyboard edge
        self.record_path = record_path
        self.auto_cap = auto_cap_after_period
        self.shift = False            # one-shot capital for the next letter / word
        self.caps = False             # caps lock (double-tap shift)
        self._shift_t = -99.0
        self.layer = "letters"        # "letters", "sym1" (numbers, punctuation) or "sym2" (more symbols)
        self._undo = None             # what "undo" would revert, valid until anything else changes the text
        self.trail: list[tuple[float, float]] = []
        self.hover_pos: tuple[float, float] | None = None
        self.pen_down_now = False
        self.last: _Last | None = None
        self.trailing_space = False   # did we auto-insert a space after the last word?
        self.message = ""             # short status text for the GUI
        self._gmode = None            # "erase" (started on backspace) / "cursor" (started on space)
        self._gx0 = 0.0
        self._gwords = 0              # erase: words currently selected
        self._gsteps = 0              # cursor: characters moved so far
        self._gactive = False         # did the gesture actually do something?
        self.clock = time.monotonic   # replaced in tests
        self._gtrack = deque()        # recent (time, x) of the stroke, to measure its speed
        self._gedge = 0               # -1 / +1 while the pen rests on the left / right edge
        self._gedge_t0 = 0.0
        self._gedge_last = 0.0
        self._gedge_v0 = 0.0
        self._gedge_acc = 0.0
        self._gauto = 0               # characters moved by the edge momentum (signed)
        self.predict = False          # suggest the next word / completions in the strip (the window turns it on)
        self.learn_typing = True      # remember which words follow which, from what you write
        self.predictor = None
        self._learn_ver = -1
        self._strip_key = None
        self._strip = None
        self.panel = None             # the panel (tools, dictionary, check ...) drawn over the keyboard, if open
        self._jobs = []               # background work (online lookups, LanguageTool): (thread, result box, callback)
        self.typewriter = False       # keep the cursor level (scroll as text grows)
        self.chars_per_line = 80
        self.notches_per_line = 0.25
        self.online_lookup = True     # dictionary may use the internet when WordNet is not installed
        self.languagetool_url = ""    # your own LanguageTool server ("" = look on this computer)
        self.docs_menu_key = "ctrl+shift+\\"   # opens Google Docs' right-click menu for the underlined word
        self.docs_delay = 0.25        # seconds to wait between the keys of a Docs macro (Docs needs a moment)
        self.docs_auto = True         # after picking a fix in Docs, jump to the next error
        self._macro_busy = False
        self.on_setting = None        # callback(name, value): the window saves settings changed from a panel
        self._dictionary = None
        self._speller = None
        self._lt = None               # cached LanguageTool address: str, or False for "none found"

    # ---- pen events -------------------------------------------------------
    def hover(self, x, y):
        self.hover_pos = (x, y)

    def pen_down(self, x, y):
        self.pen_down_now = True
        self.trail = [(x, y)]
        self.hover_pos = (x, y)
        self._gmode, self._gx0 = None, x
        self._gwords = self._gsteps = 0
        self._gactive = False
        self._gtrack.clear()
        self._gedge = 0
        self._gauto = 0
        if self.panel:
            return                                    # panels take taps and page swipes only
        kind, val = classify(x, y, self.layer)
        if kind == "key" and val == "backspace":
            self._gmode = "erase"
        elif kind == "key" and val == "space":
            self._gmode = "cursor"

    def pen_move(self, x, y):
        self.hover_pos = (x, y)
        if self.pen_down_now:
            self.trail.append((x, y))
            if self._gmode:
                self._gesture_move(x)

    def cancel_stroke(self):
        """Abandon the stroke in progress (pause / toggle) without typing anything."""
        if self._gmode == "erase" and self._gwords:
            self.inj.collapse_selection()
        self.pen_down_now = False
        self.trail = []
        self._gmode = None
        self._gwords = self._gsteps = 0
        self._gactive = False
        self._gedge = 0

    # ---- edit gestures ----------------------------------------------------------
    def _gesture_move(self, x):
        if self._gmode == "erase":
            left = self._gx0 - x
            n = 0 if left < ERASE_FIRST else 1 + int((left - ERASE_FIRST) / ERASE_PER_WORD)
            self._set_erase_words(n)
        else:
            now = self.clock()
            self._gtrack.append((now, x))
            while self._gtrack and now - self._gtrack[0][0] > 0.3:
                self._gtrack.popleft()
            self._edge_check(x, now)
            dx = x - self._gx0
            if abs(dx) < CURSOR_DEAD:
                steps = 0
            else:
                steps = int((abs(dx) - CURSOR_DEAD) / CURSOR_STEP) + 1
                steps = steps if dx > 0 else -steps
            steps += self._gauto
            if steps != self._gsteps:
                self.inj.move_cursor(steps - self._gsteps)
                self._gsteps = steps
                self._gactive = True
                self.message = "cursor " + ("right" if steps > 0 else "left" if steps < 0 else "back")

    def _edge_check(self, x, now):
        """Pen reached / left the left or right edge of the keyboard while moving the cursor."""
        edge = -1 if x <= CURSOR_EDGE else 1 if x >= CANVAS_W - CURSOR_EDGE else 0
        if edge == self._gedge:
            return
        self._gedge = edge
        self._gedge_acc = 0.0
        if edge:
            # arrive with the speed of the swipe that got us here
            v0 = EDGE_RATE_MIN
            if len(self._gtrack) >= 2:
                t0, x0 = self._gtrack[0]
                if now - t0 > 0.02:
                    toward = (x - x0) * edge
                    v0 = max(EDGE_RATE_MIN, min(EDGE_RATE_START_MAX, toward / (now - t0) / CURSOR_STEP))
            self._gedge_v0 = v0 * self.edge_speed
            self._gedge_t0 = self._gedge_last = now

    def tick(self):
        """Call often (the window does it every few ms). Keeps the caret moving while the
        pen rests on the keyboard's edge during a space-bar swipe, faster the longer it stays."""
        if self._jobs:
            self._poll_jobs()
        if not (self.pen_down_now and self._gmode == "cursor" and self._gedge):
            return
        now = self.clock()
        held = now - self._gedge_t0
        rate = min(EDGE_RATE_MAX * self.edge_speed, self._gedge_v0 + EDGE_ACCEL * self.edge_speed * held)
        self._gedge_acc += rate * (now - self._gedge_last)
        self._gedge_last = now
        n = min(int(self._gedge_acc), EDGE_MAX_PER_TICK)
        if n <= 0:
            return
        self._gedge_acc -= n
        self.inj.move_cursor(n * self._gedge)
        self._gauto += n * self._gedge
        self._gsteps += n * self._gedge
        self._gactive = True
        self.message = "cursor " + ("right" if self._gedge > 0 else "left") + f" ({int(rate)}/s)"

    def _set_erase_words(self, n):
        if n == self._gwords:
            return
        if n < self._gwords:
            self.inj.collapse_selection()
            self._gwords = 0
        for _ in range(n - self._gwords):
            self.inj.select_word_left()
        self._gwords = n
        self._gactive = n > 0
        self.message = f"erase {n} word{'s' if n != 1 else ''}" if n else "erase: cancelled"

    def pen_up(self):
        try:
            self._pen_up()
        finally:
            self.inj.flush_scroll()

    def _pen_up(self):
        if not self.pen_down_now:
            return
        self.pen_down_now = False
        pts, self.trail = self.trail, []
        mode, self._gmode = self._gmode, None
        if mode == "erase" and self._gwords:
            n, self._gwords = self._gwords, 0
            self.inj.backspace(1)             # deletes the highlighted words
            self.last = None
            self.trailing_space = False
            self.message = f"erased {n} word{'s' if n != 1 else ''}"
            self._set_undo("erase", label="erase")
            return
        if mode == "cursor" and self._gactive:
            self.last = None                  # moved around: no space, no undo of the last word
            self.trailing_space = False
            return
        if not pts:
            return
        if self.panel:
            self._panel_stroke(pts)
            return
        if path_length(pts) < TAP_MAX_LENGTH:
            self._tap(pts[-1])
        elif classify(*pts[0], self.layer)[0] == "letter":
            self._swipe(pts)
        # strokes that start on a function key or the strip and travel far: ignored

    # ---- actions ------------------------------------------------------------
    def _swipe(self, pts):
        ranked = self.decoder.decode(pts, k=8)
        if not ranked:
            self.message = "no match"
            return
        self._learn_tail()                             # the previous word is final now: remember the pair
        ranked = self._rerank(ranked)
        cands = [w for w, _ in ranked[:5]]
        word = cands[0]
        shifted, caps = self.shift, self.caps
        typed = self._apply_case(word, shifted, caps)
        lead = " " if self._mid_word() else ""         # tapped "i", then swiped "want": "i want", not "iwant"
        self.inj.type_text(lead + typed + " ")
        self.shift = False
        self.last = _Last(typed, cands, shifted, caps)
        self.trailing_space = True
        self.message = f"typed: {typed}"
        self._live_fix()
        self._record({"points": [[round(x, 3), round(y, 3)] for x, y in pts], "cands": cands})

    # ---- what comes next: context, strip, prediction -----------------------------------------------
    def get_predictor(self):
        if self.predictor is None:
            from .predict import Predictor
            self.predictor = Predictor(known=self.decoder.logp, learning=self.learn_typing)
        self.predictor.learning = self.learn_typing
        return self.predictor

    def _context(self):
        """What we know about the sentence being written, from the text we typed since the caret last moved:
        (words so far, at the start of a sentence, letters of an unfinished word) - or None if we know nothing."""
        tail = self.inj.tail[-400:]
        if not tail:
            return None
        m = re.search(r"[A-Za-z'’]+$", tail)
        partial = m.group(0) if m else ""
        head = tail[:len(tail) - len(partial)]
        if head and not (head[-1].isspace() or head[-1] in ".,;:!?)\"”'’-"):
            return None                                # digits, symbols: no idea
        seg = re.split(r"[.!?]+\s*|\n+", head)[-1] if head else ""
        at_start = bool(head.strip()) and not seg.strip() and (head[-1].isspace() or head[-1] in ".!?")
        words = [w.lower().replace("’", "'") for w in tidy_mod.TOKEN.findall(seg)]
        return words, at_start, partial

    def _rerank(self, ranked):
        """Swipe results that fit the word before come first (a small push, the swipe still decides)."""
        if not (self.predict and len(ranked) > 1) or self._mid_word():
            return ranked
        ctx = self._context()
        if ctx is None:
            return ranked
        words, at_start, _partial = ctx
        pred = self.get_predictor()
        context = [] if at_start else words
        return sorted(ranked, key=lambda wc: wc[1] - 0.12 * pred.affinity(context, wc[0]))

    def _learn_tail(self):
        """Count the pair / triple of words we just finished (only at a word boundary, once per change)."""
        if not (self.predict and self.learn_typing):
            return
        v = self.inj.version
        if v == self._learn_ver:
            return
        self._learn_ver = v
        tail = self.inj.tail
        if not tail or tail[-1] not in " \n.,;:!?":
            return
        ctx = self._context()
        if ctx and ctx[0]:
            self.get_predictor().learn(ctx[0])

    def strip(self):
        """What the suggestion strip shows now: {"mode", "cells": 4 labels, "chosen", "dim": indexes}.
        Modes: cands (other readings of the word you just swiped), complete (finish the letters you tapped),
        predict (the next word), tools (undo / tidy / + word / more)."""
        last = self.last
        key = (self.inj.version, self.shift, self.caps, self.predict, id(last), last.chosen if last else None,
               self.can_undo())
        if key == self._strip_key:
            return self._strip
        self._strip_key = key
        self._strip = self._build_strip()
        return self._strip

    def _build_strip(self):
        if self.last:
            cells = list(self.last.cands[:4])
            return {"mode": "cands", "cells": cells + [""] * (4 - len(cells)), "chosen": self.last.chosen, "dim": ()}
        tools = {"mode": "tools", "cells": ["undo", "tidy", "+ word", "more"], "chosen": None,
                 "dim": () if self.can_undo() else (0,)}
        if not self.predict:
            return tools
        ctx = self._context()
        if ctx is None:
            return tools
        words, at_start, partial = ctx
        context = [] if at_start else words
        pred = self.get_predictor()
        if partial:
            if len(partial) < 2:
                return tools
            from .panels import match_case
            comps = self.get_speller().completions(partial, 14)
            comps = pred.rank_completions(comps, context)[:3]
            if not comps:
                return tools
            cells = [match_case(partial, w) for w in comps]
            return {"mode": "complete", "cells": cells + [""] * (3 - len(cells)) + ["⋯"], "chosen": None, "dim": ()}
        nxt = pred.next_words(context, 3, sentence_start=at_start)
        if self.caps:
            nxt = [w.upper() for w in nxt]
        elif self.shift and not at_start:
            nxt = [w[:1].upper() + w[1:] for w in nxt]
        return {"mode": "predict", "cells": nxt + [""] * (3 - len(nxt)) + ["⋯"], "chosen": None, "dim": ()}

    def flush(self):
        """Save what was learned (the window calls this when it closes)."""
        if self.predictor:
            self.predictor.save()

    def _mid_word(self) -> bool:
        """Is the caret right behind letters we typed (so a swiped word needs a space first)?"""
        tail = self.inj.tail
        return bool(tail) and (tail[-1].isalnum())

    @staticmethod
    def _apply_case(word, shifted, caps=False):
        if caps:
            return word.upper()
        if word == "i" or word.startswith(("i'", "i’")):
            word = "I" + word[1:]                       # the lone "I" is always a capital
        if shifted and word[:1].islower():
            word = word[:1].upper() + word[1:]
        return word

    def _tap(self, p):
        kind, val = classify(*p, self.layer)
        if kind == "cand":
            self._pick_candidate(val)
        elif kind == "letter":
            ch = val.upper() if (self.shift or self.caps) else val
            self.inj.type_text(ch)
            self.shift = False
            self.last = None
            self.trailing_space = False
        elif kind == "sym":
            self._symbol(val)
        else:
            self._function_key(val)

    def _symbol(self, ch):
        """A key from the number / symbol layers."""
        if ch in ATTACH_LEFT and self.trailing_space:
            self.inj.backspace(1)                       # "word !" -> "word!"
        if ch in SPACE_AFTER:
            self.inj.type_text(ch + " ")
            self.trailing_space = True
            if ch in "!?" and self.auto_cap:
                self.shift = True
        else:
            self.inj.type_text(ch)
            self.trailing_space = False
        self.last = None

    def _pick_candidate(self, i):
        mode = self.strip()["mode"]
        if mode == "tools":                   # nothing to pick: the strip shows the tools
            if i == 0:
                self.undo()
            elif i == 1:
                self.tidy()
            elif i == 2:
                self.learn_word()
            elif i == 3:
                self.open_tools()
            return
        if mode in ("predict", "complete"):
            cells = self.strip()["cells"]
            if i == 3:
                self.open_tools()
            elif cells[i]:
                self._commit_suggestion(cells[i], mode)
            return
        if i >= len(self.last.cands):
            return
        if i == self.last.chosen:             # tap the word that is already in: accept it, show what comes next
            self.last = None
            self.message = "ok"
            return
        new = self._apply_case(self.last.cands[i], self.last.shifted, self.last.caps)
        self.inj.backspace(len(self.last.typed) + 1)   # word + the auto space
        self.inj.type_text(new + " ")
        self.last.typed = new
        self.last.chosen = i
        self.message = f"changed to: {new}"
        self._record({"correction": self.last.cands[i]})

    def _commit_suggestion(self, word, mode):
        """Tap on a next-word prediction or a completion."""
        self._learn_tail()
        if mode == "complete":
            ctx = self._context()
            partial = ctx[2] if ctx else ""
            if partial:
                self.inj.backspace(len(partial))
        self.inj.type_text(word + " ")
        self.shift = False
        self.last = None
        self.trailing_space = True
        self.message = f"typed: {word}"
        self._record({"suggestion": word, "mode": mode})

    def _function_key(self, name):
        if name == "shift":
            now = self.clock()
            if self.caps:
                self.caps = False                       # tap while caps lock is on: off
                self.shift = False
            elif self.shift and now - self._shift_t < DOUBLE_TAP:
                self.caps, self.shift = True, False     # double tap: caps lock
            else:
                self.shift = not self.shift
            self._shift_t = now
        elif name == "sym":
            self.layer = "letters" if self.layer != "letters" else "sym1"
        elif name == "page":
            self.layer = "sym2" if self.layer == "sym1" else "sym1"
        elif name == "space":
            if not self.trailing_space:       # a swipe already left a space
                self.inj.type_text(" ")
                self.trailing_space = True
            self.last = None
            self._live_fix()
            self._learn_tail()
            self.layer = "letters"            # after a number / symbol and a space: back to letters
        elif name == "apostrophe":
            if self.trailing_space:
                self.inj.backspace(1)         # "don " + ' -> "don'"
            self.inj.type_text("'")
            self.trailing_space = False
            self.last = None
        elif name == "backspace":
            if self._undo and self._undo["kind"] == "live" and self._undo["version"] == self.inj.version:
                self.undo()                   # right after an automatic fix: Backspace takes the fix back
            elif self.last:                   # after a swipe: delete the whole word
                self.inj.backspace(len(self.last.typed) + 1)
                self.last = None
                self.trailing_space = False
            else:
                self.inj.backspace(1)
                self.trailing_space = False
        elif name == "enter":
            if self.trailing_space:
                self.inj.backspace(1)
            self.inj.enter()
            self.trailing_space = False
            self.last = None
            self._live_fix()
            self.layer = "letters"
            if self.auto_cap:
                self.shift = True
        elif name in ("comma", "period"):
            ch = "," if name == "comma" else "."
            if self.trailing_space:
                self.inj.backspace(1)         # "word ." -> "word."
            self.inj.type_text(ch + " ")
            self.trailing_space = True
            self.last = None
            self._live_fix()
            self._learn_tail()
            if name == "period" and self.auto_cap:
                self.shift = True

    # ---- fixing text ---------------------------------------------------------
    def _live_fix(self):
        """After a finished word: repair slips in the last couple of words we just typed."""
        if not self.autofix:
            return
        tail = self.inj.tail
        if not tail or not (tail[-1].isspace() or tail[-1] in ".,!?;:"):
            return                                    # a word is still being typed
        floor = min(self.inj.floor, len(tail))
        toks = [m for m in tidy_mod.TOKEN.finditer(tail) if m.start() >= floor]
        start = toks[-3].start() if len(toks) >= 3 else floor
        old = tail[start:]
        new = tidy_mod.fix_text(old, self.decoder.logp)
        if new == old:
            return
        i = 0
        while i < len(old) and i < len(new) and old[i] == new[i]:
            i += 1
        self.inj.backspace(len(old) - i)
        self.inj.type_text(new[i:])
        if self.last and not new.rstrip().endswith(self.last.typed):
            self.last = None
        self.message = "fixed: " + new.strip()[-30:]
        self._set_undo("live", old=old[i:], new=new[i:], label="fix")

    def tidy(self):
        """Fix slips in the paragraph before the caret, text already in the document included."""
        if self.panel:
            self.close_panel()
        try:
            raw = self.inj.grab_paragraph_before()
        except RuntimeError as exc:
            self.message = "error: " + str(exc).splitlines()[0]
            return
        if not raw.strip():
            self.message = "tidy: nothing before the cursor"
            return
        text, whole = raw, True
        odd = [i for i, ch in enumerate(raw) if ord(ch) > 0xFFFF or ch == "\u200d" or unicodedata.combining(ch)]
        if odd:                                       # arrow keys and characters would disagree: skip past them
            text, whole = raw[odd[-1] + 1:], False
        if len(text) > TIDY_MAX_CHARS:
            text, whole = text[-TIDY_MAX_CHARS:], False
        new = tidy_mod.fix_text(text, self.decoder.logp, sentence_start=whole)
        ops = tidy_mod.edits(text, new)
        if not ops:
            self.message = "tidy: nothing to fix"
            return
        self._apply_ops(text, new, ops)
        self.last = None
        self.trailing_space = new.endswith(" ")
        self.message = f"tidied: {len(ops)} fix" + ("es" if len(ops) != 1 else "")
        self._set_undo("tidy", text=text, new=new)
        self.inj.flush_scroll()

    def _apply_ops(self, text, new, ops):
        """Turn `text` (which ends right at the caret) into `new` with arrow keys, backspace and typing,
        touching only the broken spots, and leave the caret at the end again."""
        pos = len(text)                               # where the caret is, counting from the start of `text`
        for start, end, rep in reversed(ops):         # last edit first: earlier text keeps its positions
            if pos > end:
                self.inj.move_cursor(-(pos - end))
            if end > start:
                self.inj.backspace(end - start)
            if rep:
                self.inj.type_text(rep)
            pos = start + len(rep)
        if len(new) > pos:
            self.inj.move_cursor(len(new) - pos)      # back to where the caret was
        self.inj.tail = ""

    # ---- undo ------------------------------------------------------------------
    def _set_undo(self, kind, **data):
        self._undo = dict(kind=kind, version=self.inj.version, **data)

    def can_undo(self) -> bool:
        return bool(self._undo) and self._undo["version"] == self.inj.version

    def undo(self) -> bool:
        """Take back the last automatic fix, tidy or word erase, if nothing else happened since."""
        if not self.can_undo():
            self.message = "undo: nothing to undo"
            return False
        rec, self._undo = self._undo, None
        kind = rec["kind"]
        if kind == "live":
            self.inj.backspace(len(rec["new"]))
            self.inj.type_text(rec["old"])
            self.inj.floor = len(self.inj.tail)       # from now on that text stays as the user typed it
            self.trailing_space = self.inj.tail.endswith(" ")
        elif kind == "tidy":
            try:
                raw = self.inj.grab_paragraph_before()
            except RuntimeError as exc:
                self.message = "error: " + str(exc).splitlines()[0]
                return False
            if not raw.endswith(rec["new"]):
                self.message = "undo: the text changed since"
                return False
            self._apply_ops(rec["new"], rec["text"], tidy_mod.edits(rec["new"], rec["text"]))
            self.trailing_space = rec["text"].endswith(" ")
        elif kind == "replace":
            t = rec["trailing"]
            if t:
                self.inj.move_cursor(-t)
            self.inj.backspace(len(rec["new"]))
            self.inj.type_text(rec["old"])
            if t:
                self.inj.move_cursor(t)
            self.inj.tail = ""
        elif kind == "erase":
            self.inj.undo_key()                       # the editor's own Ctrl+Z brings the words back
            self.trailing_space = False
        self.last = None
        self.message = "undone"
        self.inj.flush_scroll()
        return True

    # ---- keep the cursor level -------------------------------------------------
    def set_typewriter(self, enabled: bool, chars_per_line: int = 80, notches_per_line: float = 0.25):
        from .scroll import Typewriter
        self.typewriter, self.chars_per_line, self.notches_per_line = bool(enabled), int(chars_per_line), float(notches_per_line)
        if not enabled:
            self.inj.scroller = None
        elif self.inj.scroller is None:
            self.inj.scroller = Typewriter(self.inj.scroll, chars_per_line, notches_per_line)
        else:
            self.inj.scroller.cpl = max(10, int(chars_per_line))
            self.inj.scroller.npl = float(notches_per_line)

    # ---- panels ----------------------------------------------------------------------------
    def open_panel(self, panel):
        if self.panel:
            self.close_panel()
        self.panel = panel
        self.last = None
        self.pen_down_now = False
        self.trail = []

    def close_panel(self):
        p, self.panel = self.panel, None
        if p:
            p.alive = False
            p.on_close()

    def _panel_stroke(self, pts):
        if path_length(pts) < TAP_MAX_LENGTH:
            act = self.panel.hit(*pts[-1])
            if act:
                act()
            return
        dx, dy = pts[-1][0] - pts[0][0], pts[-1][1] - pts[0][1]
        if abs(dy) > 1.2 and abs(dy) > 2 * abs(dx):   # swipe up = next page, down = previous
            self.panel.next() if dy < 0 else self.panel.prev()

    def open_tools(self):
        from .panels import ToolsPanel
        self.open_panel(ToolsPanel(self))

    def open_dictionary(self):
        from .panels import DictionaryPanel
        try:
            raw = self.inj.grab_word_before()
        except RuntimeError as exc:
            self.message = "error: " + str(exc).splitlines()[0]
            return
        found = WORD_RE.findall(raw)
        if not found:
            self.message = "dictionary: write a word first"
            return
        self.open_panel(DictionaryPanel(self, found[-1]))

    def open_review(self):
        from .panels import ReviewPanel
        try:
            raw = self.inj.grab_paragraph_before()
        except RuntimeError as exc:
            self.message = "error: " + str(exc).splitlines()[0]
            return
        if not raw.strip():
            self.message = "check: nothing before the cursor"
            return
        text, whole = raw, True
        odd = [i for i, ch in enumerate(raw) if ord(ch) > 0xFFFF or ch == "\u200d" or unicodedata.combining(ch)]
        if odd:
            text, whole = raw[odd[-1] + 1:], False
        if len(text) > TIDY_MAX_CHARS:
            text, whole = text[-TIDY_MAX_CHARS:], False
        self.open_panel(ReviewPanel(self, text, whole))

    def open_docs_keys(self):
        from .panels import DocsKeysPanel
        self.open_panel(DocsKeysPanel(self))

    def set_setting(self, name, value):
        if name == "autofix":
            self.autofix = bool(value)
        elif name == "typewriter":
            self.set_typewriter(bool(value), self.chars_per_line, self.notches_per_line)
        elif name == "docs_auto":
            self.docs_auto = bool(value)
        elif name == "docs_menu_key":
            self.docs_menu_key = str(value)
        elif name == "docs_delay":
            self.docs_delay = float(value)
        elif name == "predict":
            self.predict = bool(value)
        elif name == "learn_typing":
            self.learn_typing = bool(value)
        if self.on_setting:
            self.on_setting(name, value)

    def run_keys(self, steps, label: str = "") -> bool:
        """Press a sequence of keys in the background: steps are key combos ("ctrl+'") or numbers (seconds
        to wait). Returns False, doing nothing, if the previous sequence is still running."""
        if self._macro_busy:
            self.message = "docs: one moment ..."
            return False
        self._macro_busy = True
        self.message = label or "sending keys ..."

        def work():
            for st in steps:
                if isinstance(st, (int, float)):
                    if st > 0:
                        time.sleep(st)
                else:
                    self.inj.press(st)

        def done(_result, error):
            self._macro_busy = False
            if error is not None:
                self.message = "error: " + str(error).splitlines()[0]
        self.start_job(work, done)
        return True

    # ---- background jobs ---------------------------------------------------------------------
    def start_job(self, fn, done):
        import threading
        box = {}

        def run():
            try:
                box["r"] = fn()
            except Exception as exc:                  # shown in the panel, never crashes the keyboard
                box["e"] = exc
        t = threading.Thread(target=run, daemon=True)
        t.start()
        self._jobs.append((t, box, done))

    def _poll_jobs(self):
        for job in list(self._jobs):
            t, box, done = job
            if not t.is_alive():
                self._jobs.remove(job)
                done(box.get("r"), box.get("e"))

    def wait_jobs(self, timeout: float = 10.0):
        """Block until background work has finished (tests, command line)."""
        end = time.monotonic() + timeout
        while self._jobs and time.monotonic() < end:
            for t, _, _ in list(self._jobs):
                t.join(0.05)
            self._poll_jobs()

    def get_dictionary(self):
        if self._dictionary is None:
            from .lookup import Dictionary
            self._dictionary = Dictionary(online=self.online_lookup)
        return self._dictionary

    def get_speller(self):
        if self._speller is None:
            from .lookup import Speller
            self._speller = Speller(self.decoder)
        return self._speller

    def lt_url(self):
        """LanguageTool server to ask: the configured one, else one running on this computer, else None."""
        if self._lt is None:
            from .checker import find_languagetool
            self._lt = find_languagetool(self.languagetool_url) or False
        return self._lt or None

    def replace_word_before(self, new: str) -> bool:
        """Swap the word before the caret for `new` (capital letters kept). Leaves the caret after it."""
        try:
            raw = self.inj.grab_word_before()
        except RuntimeError as exc:
            self.message = "error: " + str(exc).splitlines()[0]
            return False
        ms = list(WORD_RE.finditer(raw))
        if not ms:
            self.message = "replace: no word before the cursor"
            return False
        m = ms[-1]
        old, trailing = m.group(0), len(raw) - m.end()
        from .panels import match_case
        repl = match_case(old, new)
        if trailing:
            self.inj.move_cursor(-trailing)
        self.inj.backspace(len(old))
        self.inj.type_text(repl)
        if trailing:
            self.inj.move_cursor(trailing)
        self.inj.tail = ""
        self.last = None
        self.message = f"replaced: {old} → {repl}"
        self._set_undo("replace", old=old, new=repl, trailing=trailing, label="replace")
        return True

    def learn_word(self):
        """Add the word before the caret to your personal dictionary (names, jargon)."""
        from . import lexicon
        try:
            raw = self.inj.grab_word_before()
        except RuntimeError as exc:
            self.message = "error: " + str(exc).splitlines()[0]
            return
        found = WORD_RE.findall(raw)
        word = lexicon.clean_user_word(found[-1]) if found else None
        if not word:
            self.message = "learn: no word before the cursor"
            return
        added = lexicon.add_user_word(word)
        self.reload_words()
        self.message = f"learned: {word}" if added else f"already in your words: {word}"

    def reload_words(self):
        from . import lexicon
        self.decoder.set_user_words(lexicon.user_entries())

    # ---- recording ----------------------------------------------------------
    def _record(self, obj):
        if not self.record_path:
            return
        obj["t"] = round(time.time(), 2)
        with open(self.record_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(obj) + "\n")
