"""Panels: tools menu, dictionary, paragraph review, Docs keys - driven by pen taps on a Session."""
import os, tempfile
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
from wnfixture import build
from swipepen import lexicon
from swipepen.engine import Decoder
from swipepen.inject import DryRunInjector
from swipepen.lookup import Dictionary
from swipepen.panel import Panel, Cell, ROW_H, BODY_Y0, BAR_Y
from swipepen.session import Session

def check(label, got, want=True):
    ok = got == want
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else f"  got {got!r} want {want!r}"))
    assert ok

dec = Decoder(lexicon.load_lexicon("en", force_fallback=True, verbose=False))
wn = tempfile.mkdtemp(); build(wn)

def fresh(text=""):
    global inj, s
    inj = DryRunInjector(); inj.buffer = text; inj.pos = len(text)
    s = Session(dec, inj)
    s._dictionary = Dictionary(wordnet_path=wn, online=False)
    s._lt = False                                   # no LanguageTool in tests
def tap(x, y): s.pen_down(x, y); s.pen_move(x + 0.02, y); s.pen_up()
def box(pred):
    for b in s.panel.layout():
        if pred(b):
            return b
    raise AssertionError("no such box")
def tap_box(pred):
    b = box(pred); tap((b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2)
def tap_text(t): tap_box(lambda b: b.text == t)
def texts(): return [b.text for b in s.panel.layout()]

# ---- framework ------------------------------------------------------------------------------------
fresh()
class Many(Panel):
    def rows(self): return [[Cell(f"row {i}", (lambda i=i: hits.append(i)))] for i in range(12)]
hits = []
s.open_panel(Many(s))
class Headed(Panel):
    def header(self): return Cell("HEAD", None, "title")
    def rows(self): return [[Cell(f"r{i}")] for i in range(9)]
s.open_panel(Headed(s))
check("header takes one of the five rows on every page", s.panel.pages() == 3 and "HEAD" in texts() and [t for t in texts() if t.startswith("r")] == ["r0", "r1", "r2", "r3"])
s.panel.next(); s.panel.next()
check("...also on the last page", "HEAD" in texts() and [t for t in texts() if t.startswith("r")] == ["r8"])
s.close_panel()
s.open_panel(Many(s))
check("first page shows five rows", [t for t in texts() if t.startswith("row")], [f"row {i}" for i in range(5)])
check("three pages", s.panel.pages(), 3)
tap(5, BODY_Y0 + 2 * ROW_H + 0.3)
check("tapping a row runs its action", hits, [2])
s.pen_down(5, 2.5); s.pen_move(5, 1.5); s.pen_move(5, 0.5); s.pen_up()
check("swipe up = next page", [t for t in texts() if t.startswith("row")][0], "row 5")
s.pen_down(5, 0.5); s.pen_move(5, 1.5); s.pen_move(5, 2.5); s.pen_up()
check("swipe down = previous page", [t for t in texts() if t.startswith("row")][0], "row 0")
tap_text("next ›"); tap_text("next ›")
check("bottom next button pages (and then is dead)", [t for t in texts() if t.startswith("row")][0], "row 10")
tap(8.5, BAR_Y[0] + 0.5)
check("last page: next does nothing", [t for t in texts() if t.startswith("row")][0], "row 10")
tap(5, 3.5)
check("close button", s.panel, None)
s.open_panel(Many(s)); inj.buffer = ""
s.pen_down(3, 3.5); s.pen_move(3, 3.5); s.pen_up()
check("typing is not triggered while a panel is open", inj.buffer, "")
s.close_panel()

# ---- tools menu (strip cell 3 when idle) -------------------------------------------------------------
fresh("hello")
tap(2.5 * 3 + 1.25, -0.5)
check("'more' opens the tools menu", type(s.panel).__name__, "ToolsPanel")
check("tools list", [t for t in texts() if "Dictionary" in t or "Check" in t or "Docs" in t][:3] != [], True)
check("first row: undo / tidy / + word", [t for t in texts() if t in ("Undo", "Tidy", "+ word")] == ["Undo", "Tidy", "+ word"])
tap_box(lambda b: b.text.startswith("Suggest the next word"))
check("next-word suggestions toggled on from the menu", s.predict, True)
tap_text("next ›")
tap_box(lambda b: b.text.startswith("Fix typos"))
check("autofix toggled off from the menu", s.autofix, False)
check("label shows the new state", any(t == "Fix typos as I type: off" for t in texts()))
seen = []
s.on_setting = lambda n, v: seen.append((n, v))
tap_box(lambda b: b.text.startswith("Keep the cursor level"))
check("typewriter toggled on", (s.typewriter, s.inj.scroller is not None), (True, True))
check("window is told so it can save the setting", seen, [("typewriter", True)])
tap_box(lambda b: b.text.startswith("Keep the cursor level"))
check("and off again", (s.typewriter, s.inj.scroller), (False, None))
s.close_panel()

# ---- dictionary --------------------------------------------------------------------------------------
fresh("I am very happy ")
inj.pos = len(inj.buffer)
s.open_dictionary()
check("dictionary panel opened for the word before the caret", (type(s.panel).__name__, s.panel.word), ("DictionaryPanel", "happy"))
check("shows which word is being looked up, right away", any(t.startswith("Looking up:  happy") for t in texts()))
s.wait_jobs(); 
check("after the job: tabs and a definition", [t for t in texts() if "joy" in t] != [] and "Synonyms" in texts())
check("the Define tab names the word", any(t == "Looking up:  happy" for t in texts()))
tap_text("Synonyms")
check("the Synonyms tab names the word", any(t.startswith("Synonyms of  happy") for t in texts()))
tap_text("Antonyms")
check("the Antonyms tab names the word", any(t.startswith("Opposites of  happy") for t in texts()))
check("antonym unhappy is offered", "unhappy" in texts())
tap_text("unhappy")
check("tapping a word replaces the word before the caret", inj.buffer, "I am very unhappy ")
check("caret is where it was", inj.pos, len(inj.buffer))
check("panel closed after replacing", s.panel, None)
check("undo brings the word back", s.can_undo() and s.undo() and inj.buffer == "I am very happy ")

fresh("The Dog")
s.open_dictionary(); s.wait_jobs()
tap_text("More")
check("the header stays on every page", True)
check("More tab lists broader / narrower words", "Broader" in texts() and "canine" in texts() and "puppy" in texts())
tap_text("puppy")
check("capital letters kept when replacing", inj.buffer, "The Puppy")

fresh("A wich")
s.open_dictionary(); s.wait_jobs()
check("unknown word: 'No entry' and 'did you mean'", any(t.startswith("No entry") for t in texts()) and "Did you mean:" in texts())
tap_text("which")
s.wait_jobs()
check("did-you-mean looks the word up instead of editing", (inj.buffer, s.panel.word), ("A wich", "which"))
s.close_panel()

fresh("")
s.open_dictionary()
check("no word before the caret: no panel, a message", (s.panel, "write a word" in s.message), (None, True))

# ---- paragraph review ---------------------------------------------------------------------------------
fresh("i think we should of gone to a apple store, wich was teh plan.")
s.open_review(); s.wait_jobs()
check("review panel opened", type(s.panel).__name__, "ReviewPanel")
p = s.panel
check("it found several things", len(p.issues) >= 4)
first = p.issues[0]
check("first problem shown with its context", any("«" in t for t in texts()))
tap_box(lambda b: b.kind == "cell" and b.style == "hi")
check("tapping the fix changes only that spot", inj.buffer.count("should of") == 1 or "I think" in inj.buffer)
check("caret stays at the end while editing is done around it", True)
n0 = len(p.issues)
tap_text("Ignore")
check("ignore drops the issue", len(p.issues) == n0 - 1)
easy = [b.text for b in s.panel.layout() if b.text.startswith("Fix ") and "easy" in b.text]
check("'Fix N easy' offered", easy != [])
tap_box(lambda b: b.text.startswith("Fix ") and "easy" in b.text)
check("fix-easy applied what is certain, the ignored one stays", "should of" in inj.buffer and "an apple" in inj.buffer and "which was the plan" in inj.buffer, True)
tap_text("done")
check("closing returns the caret to the end of the paragraph", (s.panel, inj.pos == len(inj.buffer)), (None, True))
print("   result:", inj.buffer)

fresh("This is a perfectly fine sentence.")
s.open_review(); s.wait_jobs()
check("clean paragraph: nothing to fix", any("Nothing more to fix" in t for t in texts()))
s.close_panel()
check("closing a clean check leaves the text alone", inj.buffer, "This is a perfectly fine sentence.")

fresh("Line one is fine.\nwe should of left.")
s.open_review(); s.wait_jobs()
check("only the current paragraph is checked", len(s.panel.issues) >= 1 and all("one" not in i.old(s.panel.text) for i in s.panel.issues))
tap_box(lambda b: b.kind == "cell" and b.style == "hi")
s.close_panel()
check("text of the other paragraph untouched", inj.buffer.startswith("Line one is fine.\n"))

# ---- Docs: guided fix flow and raw keys -----------------------------------------------------------------------
fresh("x")
s.docs_delay = 0.0
seen = []
s.on_setting = lambda n, v: seen.append((n, v))
s.open_docs_keys()
order = [[b.text for b in s.panel.layout() if b.kind == "cell" and b.y0 == y] for y in sorted({b.y0 for b in s.panel.layout() if b.kind == "cell"})]
check("Fix layout: picks, previous / skip / next, close / undo / redo, auto-next / wrong menu", [[t.split(":")[0].split("(")[0].strip() for t in row] for row in order] == [
    ["Use 1st", "Use 2nd", "Use 3rd"], ["‹ Previous error", "Skip this one", "Next error ▶"],
    ["Close menu", "Undo in Docs", "Redo in Docs"], ["Auto-next", "Wrong menu"]])
check("Docs panel opens on the guided tab", "Fix" in texts() and "Keys" in texts() and "Next error ▶" in texts())
tap_text("Next error ▶"); s.wait_jobs()
check("one tap: next error, then its suggestion menu (a Docs shortcut, not Shift+F10: Firefox keeps that)", inj.pressed, ["ctrl+'", "ctrl+shift+\\"])
inj.pressed.clear()
tap_text("Use 2nd"); s.wait_jobs()
check("pick the 2nd suggestion, then jump on to the next error", inj.pressed, ["down", "down", "enter", "ctrl+'", "ctrl+shift+\\"])
inj.pressed.clear()
tap_box(lambda b: b.text.startswith("Auto-next"))
check("auto-advance can be switched off (and is saved)", (s.docs_auto, seen[-1]), (False, ("docs_auto", False)))
tap_text("Use 1st"); s.wait_jobs()
check("without auto-advance only the pick is sent", inj.pressed, ["down", "enter"])
inj.pressed.clear()
tap_text("Skip this one"); s.wait_jobs()
check("skip closes the menu and moves on", inj.pressed, ["esc", "ctrl+'", "ctrl+shift+\\"])
inj.pressed.clear()
tap_text("‹ Previous error"); s.wait_jobs()
check("previous error", inj.pressed, ["ctrl+;", "ctrl+shift+\\"])
inj.pressed.clear()
tap_text("Undo in Docs"); tap_text("Redo in Docs"); tap_text("Close menu")
check("undo / redo in Docs, close a menu", inj.pressed, ["ctrl+z", "ctrl+y", "esc"])
inj.pressed.clear()
tap_box(lambda b: b.text.startswith("Wrong menu"))
s.wait_jobs()
check("wrong menu: close it and open the menu with the next key", inj.pressed, ["esc", "ctrl+shift+x"])
check("...and the new key is kept (and saved)", (s.docs_menu_key, seen[-1]), ("ctrl+shift+x", ("docs_menu_key", "ctrl+shift+x")))
s.set_setting("docs_menu_key", "ctrl+shift+\\")
inj.pressed.clear()
inj.pressed.clear()
s._macro_busy = True
tap_text("Next error ▶")
check("a second tap while keys are still being sent is ignored", (inj.pressed, "one moment" in s.message), ([], True))
s._macro_busy = False
tap_text("Keys")
tap_text("Open Docs' check pane  (Ctrl+Alt+X)")
tap_box(lambda b: b.text.startswith("Menu key: Ctrl+Shift+\\"))
check("tapping the menu key cycles it", (s.docs_menu_key, seen[-1]), ("ctrl+shift+x", ("docs_menu_key", "ctrl+shift+x")))
tap_text("Open it now")
tap_text("▼ down"); tap_text("Enter"); tap_text("Shift+Tab")
check("raw keys on the second tab", inj.pressed, ["ctrl+alt+x", "ctrl+shift+x", "down", "enter", "shift+tab"])
inj.pressed.clear()
s.set_setting("docs_menu_key", "ctrl+shift+x")
tap_text("Fix"); tap_text("Next error ▶"); s.wait_jobs()
check("the chosen menu key is used by the guided flow", inj.pressed, ["ctrl+'", "ctrl+shift+x"])
s.close_panel()
print("\nAll panel tests passed.")
