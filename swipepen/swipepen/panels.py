"""The panels themselves: tools menu, dictionary, paragraph review, Google Docs keys."""
from __future__ import annotations

import re

from . import checker
from .panel import Cell, Panel, lines, word_rows
from .wellbeing import SNOOZE_MINUTES

WORD_RE = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)*")


def match_case(orig: str, new: str) -> str:
    if len(orig) > 1 and orig.isupper():
        return new.upper()
    if orig[:1].isupper():
        return new[:1].upper() + new[1:]
    return new


# --------------------------------------------------------------------------------------------
class ToolsPanel(Panel):
    def __init__(self, session):
        super().__init__(session)
        self.tabs = ["Tools"]

    def rows(self):
        s = self.s
        def toggle(name, label, on):
            return [Cell(f"{label}: {'ON' if on else 'off'}", lambda: self._toggle(name, not on), "on" if on else "item")]
        return [
            [Cell("Undo", self._then(s.undo), "item" if s.can_undo() else "dim"),
             Cell("Tidy", self._then(s.tidy)), Cell("+ word", self._then(s.learn_word))],
            [Cell("Dictionary  (word before the cursor)", s.open_dictionary)],
            [Cell("Check the paragraph  (fix suggestions)", s.open_review)],
            [Cell("Google Docs' own check  (keys)", s.open_docs_keys)],
            toggle("predict", "Suggest the next word", s.predict),
            toggle("autofix", "Fix typos as I type", s.autofix),
            toggle("typewriter", "Keep the cursor level", s.typewriter),
            self._break_row(),
            toggle("pressure_hint", "Lighter-touch hint", s.pressure.enabled),
            [Cell(s.well.summary(), None, "dim")],
        ]

    def _break_row(self):
        s = self.s
        on = s.well.break_minutes > 0
        label = f"Break reminders: every {s.well.break_minutes} min" if on else "Break reminders: off"
        return [Cell(label, lambda: self._toggle("break_minutes", 0 if on else s.well.toggle_minutes),
                     "on" if on else "item")]

    def _then(self, fn):
        def go():
            self.s.close_panel()
            fn()
        return go

    def _toggle(self, name, value):
        self.s.set_setting(name, value)


# --------------------------------------------------------------------------------------------
class BreakPanel(Panel):
    """The break reminder: rest now, snooze, or skip. It only appears between strokes (see Session._break_check)."""
    is_break = True

    def __init__(self, session):
        super().__init__(session)
        w = session.well
        self.tabs = [f"{w.work_minutes()} min of writing, {w.today_strokes} strokes today"]
        self.decided = False

    def rows(self):
        w = self.s.well
        return [
            [Cell("Take a break now", self._take, "on")],
            [Cell(f"Remind me in {SNOOZE_MINUTES} minutes", self._snooze)],
            [Cell(f"Skip this one (next in {w.break_minutes} min)", self._skip)],
        ] + lines("Put the pen down. Open and close your hands slowly and roll your wrists.", "dim")

    def _take(self):
        self.decided = True
        self.s.well.take_break()
        self.s.message = "rest well"
        self.s.close_panel()

    def _snooze(self):
        self.decided = True
        self.s.well.snooze(SNOOZE_MINUTES)
        self.s.close_panel()

    def _skip(self):
        self.decided = True
        self.s.well.skip()
        self.s.close_panel()

    def on_close(self):
        if not self.decided and self.s.well.due():       # closed without choosing: ask again soon
            self.s.well.snooze(5)


# --------------------------------------------------------------------------------------------
class DictionaryPanel(Panel):
    TABS = ["Define", "Synonyms", "Antonyms", "More"]

    def __init__(self, session, word: str):
        super().__init__(session)
        self.word = word
        self.tabs = list(self.TABS)
        self.result = None
        self.extras: dict = {}
        self.didyoumean: list = []
        self.error = ""
        self.busy = True
        session.start_job(self._work, self._done)

    # runs in a background thread
    def _work(self):
        s = self.s
        res = s.get_dictionary().lookup(self.word)
        sp = s.get_speller()
        extras = {}
        if res.senses:
            for label, attr in (("Broader", "broader"), ("Narrower", "narrower"), ("Similar", "similar")):
                v = res.merged(attr, 12)
                if v:
                    extras[label] = v
        for k, v in res.more.items():
            extras[k] = v[:12]
        comp = sp.completions(self.word, 9)
        if comp:
            extras["Starts with"] = comp
        sim = sp.similar(self.word, 6)
        if sim:
            extras["Looks like"] = sim
        return res, extras, ([] if res.found else sp.suggest(self.word, 6))

    def _done(self, result, error):
        self.busy = False
        if error is not None:
            self.error = str(error)
            return
        self.result, self.extras, self.didyoumean = result

    # ---- rows ------------------------------------------------------------------------------------
    def header(self):
        name = self.TABS[self.tab]
        if self.busy:
            return Cell(f"Looking up:  {self.word} …", None, "title")
        if self.result is not None and not self.result.found:
            return Cell(f"Looking up:  {self.word}", None, "title")
        text = {"Define": f"Looking up:  {self.word}",
                "Synonyms": f"Synonyms of  {self.word}  (tap to use)",
                "Antonyms": f"Opposites of  {self.word}  (tap to use)",
                "More": f"More about  {self.word}  (tap to use)"}[name]
        return Cell(text, None, "title")

    def rows(self):
        if self.busy:
            return [[Cell("one moment …", None, "dim")]]
        if self.error:
            return lines("Lookup failed: " + self.error, "dim")
        res = self.result
        name = self.TABS[self.tab]
        if not res.found:
            out = [[Cell(f"No entry for “{self.word}”", None, "head")]]
            if self.didyoumean:
                out.append([Cell("Did you mean:", None, "dim")])
                out += word_rows(self.didyoumean, lambda w: (lambda: self.lookup(w)))
            elif not self.s.get_dictionary().wn and not self.s.online_lookup:
                out += lines("No dictionary installed. Run: sudo dnf install wordnet", "dim")
            if name == "More" and self.extras:
                out += self._more()
            return out
        if name == "Define":
            out = []
            for sense in res.senses[:6]:
                head = f"{sense.pos}: {sense.gloss}" if sense.pos else sense.gloss
                out += lines(head, "text")
                for ex in sense.examples[:1]:
                    out += lines(f"“{ex}”", "dim")
            return out
        if name in ("Synonyms", "Antonyms"):
            words = res.merged(name.lower(), 30)
            if not words:
                return [[Cell(f"no {name.lower()} found", None, "dim")]]
            return word_rows(words, self._pick_action)
        return self._more()

    def _more(self):
        out = []
        for label, words in self.extras.items():
            out.append([Cell(label, None, "head")])
            out += word_rows(words, self._pick_action)
        return out or [[Cell("nothing more", None, "dim")]]

    def _pick_action(self, w):
        return lambda: self.pick(w)

    # ---- actions -----------------------------------------------------------------------------------
    def lookup(self, word):
        self.word, self.busy, self.tab, self.page = word, True, 0, 0
        self.result = None
        self.s.start_job(self._work, self._done)

    def pick(self, new):
        if self.s.replace_word_before(new):
            self.s.close_panel()


# --------------------------------------------------------------------------------------------
KIND = {"grammar": "grammar", "typo": "typo", "spelling": "spelling", "languagetool": "grammar"}


class ReviewPanel(Panel):
    """One problem at a time: tap the fix. Edits are made with the arrow keys around the caret."""

    def __init__(self, session, text: str, whole: bool):
        super().__init__(session)
        self.tabs = ["Check"]
        self.text = text
        self.pos = len(text)          # where the caret is, counted from the start of `text`
        self.issues: list = []
        self.notes: list = []
        self.idx = 0
        self.alt = 0
        self.fixed = 0
        self.busy = True
        self.error = ""
        session.start_job(lambda: checker.check(text, session.decoder, session.lt_url(), sentence_start=whole),
                          self._done)

    def _done(self, result, error):
        self.busy = False
        if error is not None:
            self.error = str(error)
            return
        self.issues, self.notes = result

    # ---- rows ----------------------------------------------------------------------------------------
    def rows(self):
        if self.busy:
            return [[Cell("checking the paragraph …", None, "dim")]]
        if self.error:
            return lines("Check failed: " + self.error, "dim")
        if not self.issues:
            done = f"✓ Nothing more to fix" + (f"  ({self.fixed} fixed)" if self.fixed else "")
            out = [[Cell(done, None, "head")]]
            if self.notes and any("did not" in n for n in self.notes):
                out += lines(self.notes[0] + " - used the built-in checks only.", "dim")
            return out
        self.idx = min(self.idx, len(self.issues) - 1)
        it = self.issues[self.idx]
        head = f"{self.idx + 1}/{len(self.issues)}  {it.message}"
        out = [[Cell(head[:48], None, "head")]]
        a = max(0, it.start - 24)
        b = min(len(self.text), it.end + 32)
        ctx = ("…" if a else "") + self.text[a:it.start].replace("\n", " ") + "«" + \
            self.text[it.start:it.end].replace("\n", " ") + "»" + self.text[it.end:b].replace("\n", " ") + \
            ("…" if b < len(self.text) else "")
        out += lines(ctx, "text", limit=2)
        sugg = it.suggestions
        window = sugg[self.alt:self.alt + 3] or sugg[:3]
        if window:
            out.append([Cell(w if w.strip() else "(remove)", (lambda w=w: self.apply(it, w)),
                             "hi" if (i == 0 and self.alt == 0) else "item") for i, w in enumerate(window)])
        else:
            out.append([Cell("no suggestion", None, "dim")])
        easy = sum(1 for i in self.issues if i.easy)
        acts = [Cell("Ignore", self.ignore, "item")]
        if len(sugg) > 3:
            acts.append(Cell("More ▸", self.more, "item"))
        if easy > 1 or (easy == 1 and not it.easy):
            acts.append(Cell(f"Fix {easy} easy", self.fix_easy, "item"))
        out.append(acts)
        return out

    # paging here means moving through the problems
    def pages(self):
        return 1

    def prev_label(self):
        return "‹ previous"

    def next_label(self):
        return "next ›"

    def close_label(self):
        return "done"

    def prev_enabled(self):
        return not self.busy and self.idx > 0

    def next_enabled(self):
        return not self.busy and self.idx < len(self.issues) - 1

    def prev(self):
        self.idx, self.alt = max(0, self.idx - 1), 0

    def next(self):
        self.idx, self.alt = min(len(self.issues) - 1, self.idx + 1), 0

    # ---- actions ------------------------------------------------------------------------------------------
    def more(self):
        it = self.issues[self.idx]
        self.alt = 0 if self.alt + 3 >= len(it.suggestions) else self.alt + 3

    def ignore(self):
        if self.issues:
            del self.issues[self.idx]
            self.alt = 0

    def apply(self, issue, repl):
        self._edit(issue.start, issue.end, repl)
        self.issues = [i for i in self.issues if i is not issue]
        self.alt = 0
        self.fixed += 1
        self.s.message = "fixed: " + (repl.strip() or "removed")[:30]

    def fix_easy(self):
        todo = [i for i in self.issues if i.easy and i.suggestions]
        for it in sorted(todo, key=lambda i: -i.start):      # last first: earlier offsets stay valid
            self.apply(it, it.suggestions[0])
        self.s.message = f"fixed {len(todo)}"

    def _edit(self, start, end, rep):
        inj = self.s.inj
        if self.pos > end:
            inj.move_cursor(-(self.pos - end))
        elif self.pos < end:
            inj.move_cursor(end - self.pos)
        if end > start:
            inj.backspace(end - start)
        if rep:
            inj.type_text(rep)
        delta = len(rep) - (end - start)
        self.text = self.text[:start] + rep + self.text[end:]
        self.pos = start + len(rep)
        for i in self.issues:
            if i.start >= end:
                i.start += delta
                i.end += delta

    def on_close(self):
        inj = self.s.inj
        if self.pos < len(self.text):
            inj.move_cursor(len(self.text) - self.pos)
            self.pos = len(self.text)
        if self.fixed:
            inj.tail = ""
            self.s.last = None
            self.s.trailing_space = self.text.endswith(" ")
            self.s.message = f"checked: {self.fixed} fixed"
        inj.flush_scroll()


# --------------------------------------------------------------------------------------------
MENU_KEYS = [("ctrl+shift+\\", "Ctrl+Shift+\\"), ("ctrl+shift+x", "Ctrl+Shift+X"), ("shift+f10", "Shift+F10")]


class DocsKeysPanel(Panel):
    """Drive Google Docs' own spelling and grammar suggestions with the pen.

    swipepen cannot see what Docs underlines, so it steps through the errors with Docs' own keys: "next error"
    (Ctrl+'), then the right-click menu of the underlined word, where the suggestions are the first entries.
    You look at the screen, then tap which suggestion you want. The second tab has every key on its own."""

    def __init__(self, session):
        super().__init__(session)
        self.tabs = ["Fix", "Keys"]

    # ---- sequences ----------------------------------------------------------------------------
    def _wait(self, k=1.0):
        return self.s.docs_delay * k

    def _next(self):
        s = self.s
        return ["ctrl+'", self._wait(), s.docs_menu_key]

    def go_next(self):
        self.s.run_keys(self._next(), "Docs: next error")

    def go_previous(self):
        self.s.run_keys(["ctrl+;", self._wait(), self.s.docs_menu_key], "Docs: previous error")

    def pick(self, n):
        steps = ["down"] * n
        steps = [x for key in steps for x in (key, self._wait(0.3))] + ["enter"]
        label = f"Docs: suggestion {n}"
        if self.s.docs_auto:
            steps += [self._wait(1.5)] + self._next()
            label += ", then the next error"
        self.s.run_keys(steps, label)

    def skip(self):
        self.s.run_keys(["esc", self._wait(0.5)] + self._next(), "Docs: skipped, next error")

    def _other_key(self):
        keys = [k for k, _ in MENU_KEYS]
        cur = self.s.docs_menu_key
        return keys[(keys.index(cur) + 1) % len(keys)] if cur in keys else keys[0]

    def cycle_menu_key(self):
        self.s.set_setting("docs_menu_key", self._other_key())

    def try_other_key(self):
        """The wrong menu came up (the browser's own, say): close it and open the menu with the next key."""
        nxt = self._other_key()
        self.s.set_setting("docs_menu_key", nxt)
        self.s.run_keys(["esc", self._wait(0.6), nxt], "Docs: trying " + dict(MENU_KEYS).get(nxt, nxt))

    def _key(self, combo, label):
        def go():
            self.s.inj.press(combo)
            self.s.message = f"sent {label}"
        return go

    def _auto(self, on):
        self.s.set_setting("docs_auto", not on)

    # ---- rows ----------------------------------------------------------------------------------------
    def rows(self):
        s = self.s
        k = self._key
        label = dict(MENU_KEYS).get(s.docs_menu_key, s.docs_menu_key)
        if self.tab == 0:
            nxt = dict(MENU_KEYS).get(self._other_key(), self._other_key())
            return [
                [Cell("Use 1st", lambda: self.pick(1)), Cell("Use 2nd", lambda: self.pick(2)),
                 Cell("Use 3rd", lambda: self.pick(3))],
                [Cell("‹ Previous error", self.go_previous), Cell("Skip this one", self.skip),
                 Cell("Next error ▶", self.go_next, "hi")],
                [Cell("Close menu", k("esc", "Esc")), Cell("Undo in Docs", k("ctrl+z", "Ctrl+Z")),
                 Cell("Redo in Docs", k("ctrl+y", "Ctrl+Y"))],
                [Cell(f"Auto-next: {'ON' if s.docs_auto else 'off'}",
                      lambda on=s.docs_auto: self._auto(on), "on" if s.docs_auto else "item"),
                 Cell(f"Wrong menu (browser's)?  Try {nxt} ▸", self.try_other_key)],
            ]
        return [
            [Cell("Open Docs' check pane  (Ctrl+Alt+X)", k("ctrl+alt+x", "Ctrl+Alt+X"))],
            [Cell("Next error  Ctrl+'", k("ctrl+'", "Ctrl+'")), Cell("Previous  Ctrl+;", k("ctrl+;", "Ctrl+;"))],
            [Cell(f"Menu key: {label} ▸", self.cycle_menu_key),
             Cell("Open it now", k(s.docs_menu_key, label))],
            [Cell("▲ up", k("up", "Up")), Cell("▼ down", k("down", "Down")), Cell("Enter", k("enter", "Enter"))],
            [Cell("Tab", k("tab", "Tab")), Cell("Shift+Tab", k("shift+tab", "Shift+Tab")), Cell("Esc", k("esc", "Esc"))],
        ]
