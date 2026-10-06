# swipepen

Swipe typing (Gboard-style glide typing) for a Wacom pen tablet on Linux.
Written for Fedora KDE + Wacom Bamboo, but nothing in it is KDE-specific.

## How it works

The **whole tablet surface becomes the keyboard**. You draw a word with the pen across the
letters; when you lift the pen, the word is typed (plus a space) into whatever app has focus -
Google Docs in your browser included. The tablet has no screen, so a small preview window shows
the keyboard, your pen position (hover shows a ring, touching fills it), your trail and the
suggestions.

```
 +--------------------------------------+
 |  sugg 1 | sugg 2 | sugg 3 | sugg 4   |   tap a suggestion to swap the last word
 |  q w e r t y u i o p                 |
 |   a s d f g h j k l                  |   swipe across letters, lift = word + space
 | shift z x c v b n m          bksp    |   tap a single letter to type just that letter
 | ?123| , ' |   space    |  .  | enter |   ?123 = numbers and symbols
 +--------------------------------------+
```

- **Swipe** across letters, lift the pen: the best word is typed with a trailing space.
- **Tap a letter** (short stroke): types only that letter. Use for "a", "I", names, etc.
- **Suggestion strip** (top row): right after a swipe it shows the other readings of that word (tap one to swap it; tap the
  highlighted one, or the space bar, to accept the word). Then it shows what you will probably write next (see below).
- **Backspace** right after a swipe deletes the whole word; otherwise one character.
- **Swipe left on Backspace** erases words, like Gboard. The words highlight as you drag and are deleted when you lift the pen.
  About 1.5 keys of travel selects one word, and roughly one more key for every extra word. Change your mind? Drag back to
  the right to shrink the selection (back to nothing cancels it).
- **Swipe left or right on the space bar** moves the text cursor one character at a time, so you can fix a typo mid-sentence.
  Nothing is typed when you lift the pen. A tiny wobble on the space bar is still a normal space.
- **Swiping right after tapped letters** puts a space in first: tap `i`, swipe `want` gives `I want` (the lone `i` is capitalised for you).
  This is how Gboard behaves too.
- **Apostrophe key** (next to the comma): types `'`. After a swiped word it replaces the auto-space, so `don` + `'` + `t` works.
  You rarely need it: swiping d-o-n-t offers **don't** (and I'm, it's, can't ... ) straight away, and the bare typo "dont" is not offered.
- **Shift** is one-shot. It re-arms itself after a period or Enter (turn off with `auto_cap_after_period=False` in `session.py`).
- `,` and `.` remove the auto-space before them. Enter removes a trailing space first.

Under the hood: a SHARK2-style template decoder (`engine.py`) compares your stroke with the ideal
path of each dictionary word, then ranks by path distance, letter coverage and word frequency.
Typing is done through a virtual keyboard (`/dev/uinput`), so it works on Wayland and X11 in any app.

## Install (Fedora)

```bash
tar xzf swipepen.tar.gz
cd swipepen
./install.sh
```

That is all. It asks for your password once, then installs the two system packages it needs,
adds the permission that lets swipepen type for you, downloads the word-frequency list, and puts
**Swipepen** in your application menu. Normally no log-out is needed (if it is, the installer says so).
`./uninstall.sh` removes everything.

### Updating (no copy and paste)

Once swipepen is installed, a new version is two steps:

1. Download the new `swipepen.tar.gz` (your browser puts it in `~/Downloads`).
2. **Right-click the keyboard -> "Update from Downloads"** (or the "Update from Downloads" entry in the Swipepen launcher's
   right-click menu, or run `swipepen update`).

It finds the newest `swipepen*.tar.gz` in Downloads, replaces the installed program (no password, no reinstall), refreshes the
folder you installed from, restarts swipepen, and renames the archive to `.installed` so it is not used twice. Your settings
are kept. If a release ever needs new system permissions it tells you to run `./install.sh` again.

## Use it

1. Open **Swipepen** from the application menu (or run `swipepen`). Your pen is found automatically.
2. Click your **Google Docs tab** once so it has focus (the window turns its status line red if it still does).
3. Swipe words with the pen.

Want to try it without typing anything first? `swipepen run --dry-run --no-pen --mouse`,
then drag the mouse across letters in the window.

While running, the pen is **grabbed**: it does not move the desktop cursor. To use the pen as a
normal tablet again, press the pen's side button (stylus2 if your pen has it, otherwise stylus), click
the button in the window, or run `swipepen toggle` (also in the launcher's right-click menu).
If the pen is not found, `swipepen devices` lists what the system can see (the pen is marked `*`).

**If it closes right away or nothing happens:** a popup now explains why (the same text is saved in
`~/.local/state/swipepen/swipepen.log`). You can also run `swipepen doctor` in a terminal, or pick
*Check setup* from the right-click menu of the Swipepen launcher. It lists what is missing and the
exact fix for each item.

**Updating** to a newer version: unpack it and run `./install.sh` again (safe to repeat). If a release
only changes the program and you want to skip the password step, `SKIP_SYSTEM=1 ./install.sh` works too.

**"The system sees your tablet but you are not allowed to read it":** the installer adds a rule for this,
so running `./install.sh` again normally fixes it at once. If it still fails, the installer adds you to the
`input` group and asks you to log out and back in once.

### Fixing mistakes, also in text that is already written

**While you type** (on by default, switch off in Settings or the right-click menu: *Fix typos as I type*). Only the last two words
you just typed are looked at, and only after you finish a word:

| you typed | you get |
|---|---|
| `hel lo`, `hell o`, `hel l o` | `hello` (a stray space splits a word; two real words like "in to" are left alone) |
| `i`, `i'm`, `i'll` | `I`, `I'm`, `I'll` |
| `iwant`, `idon't`, `iwasnt` | `I want`, `I don't`, `I wasn't` (a tapped i glued to the next word) |
| `dont`, `im`, `thats`, `cant` ... | `don't`, `I'm`, `that's`, `can't` |
| `teh`, `recieve`, `alot` ... | `the`, `receive`, `a lot` (a short list of classic typos) |
| `the the` | `the` (not for words that are fine twice, like "that that") |
| `a  b ,c` | `a b, c` |
| `it ended. then` | `it ended. Then` |

**Text that is already in your document.** swipepen cannot see Google Docs, so it reads the paragraph before the caret the same
way you would: select it, copy it, look at it, put your old clipboard back. Then it repairs only the broken spots with arrow keys,
backspace and typing (so formatting stays), and leaves the caret where it was.

- Tap **tidy** in the suggestion strip (it shows up when no word suggestions are showing, e.g. right after tapping the space bar),
  or press the pen's **first side button** (the one that is not the pause button), or run `swipepen tidy` (bind it to a KDE shortcut).
- It reads back as far as the start of the paragraph (at most 1200 characters). At the very start of a paragraph it reaches into the
  previous one.
- This needs a clipboard tool: `sudo dnf install wl-clipboard xclip` (the installer does it for new installs; `swipepen doctor` checks).

**My words.** Names and jargon that are not in the dictionary: add them and they work with swiping, capital letters included
("Valentina", "O'Neil", "iPhone").

- Settings -> *My words* box: type a word, press Enter or Add. Select one and *Remove selected word* to delete it.
- Or tap **+ word** in the suggestion strip right after typing the word (it adds the word before the caret), or `swipepen learn`.
- Or from a terminal: `swipepen words add Valentina "O'Neil"`, `swipepen words list`, `swipepen words remove Valentina`.
  A running swipepen picks the change up within a second. The list is the plain file `~/.config/swipepen/words.txt` (one word per line).

### Numbers, symbols, capitals, undo

- **?123** (bottom left) shows the numbers and punctuation: digits, `@ # $ % & - + ( ) /`, `* " ' : ; ! ?`. Tap to type. The shift key on
  that page becomes **=\<** and flips to a second page (`[ ] { } < > ^ ~ | \`, `= _ ¿ ¡ € £ ° © × ÷`, `… • · ± § ¶ ¬`). **ABC** goes back.
  Space or Enter also return to the letters, like Gboard. `! ? : ;` attach to the word before them and start the next word with a space
  (and a capital letter after `!` and `?`).
- **Caps lock**: double-tap shift (the key says CAPS); tap it once to turn it off. A single tap is still the one-shot capital.
- **Undo** (the first cell of the suggestion strip when no words are showing; it is dim when there is nothing to undo): takes back the last
  automatic typo fix, the last tidy, the last word you erased, or the last word replaced from the dictionary. Tapping Backspace right after an
  automatic fix does the same. It only works until you type something else.

### Writing by tapping suggestions (next word, completions) and looser swipes

- **Next word.** When you are between words, the strip shows three likely next words and a **⋯** cell (that opens the tools: undo,
  tidy, + word, dictionary ...). Tap a word: it is typed with a space and the strip predicts again, so you can write a whole
  paragraph with taps alone. After a full stop the suggestions start with a capital.
- **Complete a word.** Tap two or more letters and the strip offers ways to finish them (`pl` -> please, play, place).
- **Where the predictions come from.** A small built-in list of what usually follows common English words, plus **what you write**: every
  pair and triple of words you finish is counted and saved in `~/.config/swipepen/phrases.json` on this computer (nothing is sent anywhere).
  So it starts sensible but plain and gets more like you the more you use it. The same knowledge nudges the swipe: after "thank", a swipe
  that looks like both "your" and "you" gives you "you". Settings: *Suggest the next word*, *Learn which words I use after which*, and a
  *Forget* button. The prediction only knows the text swipepen typed since the cursor last moved; after you click somewhere else it starts again.
- **Looser swipes.** You do not have to finish the word any more: swipe the beginning (`tomor`) and the strip offers *tomorrow*; a finished
  word still beats a longer one when it fits. *Swipe tolerance* in Settings (strict ... loose, default middle) makes the path matching more
  forgiving and relies more on the word list. On synthetic swipes that stop after 50-80% of a word the right word is among the top three
  about 3 times out of 4 (the old decoder found almost none); full swipes are as accurate as before, to within a point or two at high noise.
  Loose settings trade a little precision on very sloppy full swipes for better completions.

### Accuracy tools (new in 0.6)

**Learns from your fixes.** When you tap another word in the strip, or erase a word and swipe it again, swipepen counts it.
Next time those two words compete, the one you meant gets a small push (capped: it reorders close calls, it never overrules
a clear swipe). Kept on this computer in `~/.config/swipepen/corrections.json`. Switch off or wipe it in Settings.

**Save my swipes (off by default).** Settings -> *Save my swipes on this computer*. Every swipe goes into
`~/.config/swipepen/swipes.jsonl`: the pen path, the words offered, the three words before it, and what you did next (kept it,
picked another word, erased it). That is text you wrote, so switch it off for anything private; it never leaves your computer.
`swipepen swipes info` shows its size, `swipepen swipes clear` (or the Settings button) deletes it.

**Measure and tune.** `swipepen replay` runs your recorded swipes through the decoder again and reports top-1 / top-3 / top-5,
split into *explicit* swipes (you fixed or confirmed the word: known for sure) and *implicit* ones (you just carried on). Compare
settings on your own hand: `swipepen replay --sweep looseness=0,0.25,0.5,0.75,1`, or any decoder number, e.g.
`--sweep prior_weight=0.1,0.18,0.26` or `--set coverage_weight=0.3`. Only the shape decoder is replayed; the report also shows how
often the word was right *as typed* live (which includes the word-before and corrections nudges). Needs a few hundred swipes to say much.

**A stronger next-word list from text you choose.** swipepen ships no word-pair table (it would only be as good, and as free to
use, as the text behind it). Make one from your own writing, or any text you may use:
`swipepen build-ngrams ~/Documents/writing/ --evaluate` reads .txt, .md, .html and .docx (Google Docs: *File -> Download*), holds back
10% of the sentences and prints how often the right word was among the three suggestions with and without the table, then saves it to
`~/.config/swipepen/bigrams_en.tsv.gz`. Restart swipepen to use it. What you write yourself still counts more than the table.

### Tools: dictionary, paragraph check, Google Docs' own check

The fourth cell of the idle suggestion strip (**more**, or **⋯** while it shows predictions; or right-click the keyboard -> *Tools*) opens a screen over the keyboard that you
operate with the pen. **Tap** a button; **swipe up / down** to turn pages; the bottom row has previous / close / next.

- **Dictionary**: looks up the word before the caret (the yellow bar on top always says which word). Tabs: *Define*, *Synonyms*, *Antonyms*, *More* (broader / narrower / similar words, words that
  start with what you wrote, words that look alike; with internet also "means like" and rhymes). **Tap a synonym and it replaces the word in your
  document**, keeping capital letters (Undo brings the old word back). For an unknown word it offers "did you mean". This is separate from *My words*.
  It reads WordNet from your disk (`sudo dnf install wordnet`, the installer does it) and only uses the internet (Datamuse and dictionaryapi.dev,
  just the word you looked up) when WordNet is not installed. Turn that off with `"online_lookup": false` in `~/.config/swipepen/config.json`.
  In a terminal: `swipepen define happy`.
- **Check the paragraph**: lists problems one at a time with the context and the fix as a big button: tap it and only that spot is edited
  (arrow keys, backspace, typing - formatting stays). *Ignore*, *More* (other suggestions), *Fix N easy* (applies every sure fix at once),
  *previous / next* walk through the problems, *done* returns the caret to where it was. What it finds, best first:
  [LanguageTool](https://languagetool.org) if you run a server (a local one on port 8081 or 8010 is found automatically, or set
  `"languagetool_url"` in the config; nothing is sent anywhere else), a built-in list of common grammar mix-ups (a / an, should of, your / you're,
  their is, then / than, he don't, you was, its / it's, lets, to much ...), the same typo fixes as the live fixer, and unknown words with spelling
  suggestions. The built-in grammar is deliberately small: it is not Grammarly.
- **Google Docs' own check** (tools -> *Google Docs' own check*): swipepen cannot see what Docs underlines, so it steps through the errors
  with Docs' own keys while **you look at the screen**. Tab *Fix*: **Next error ▶** jumps to the next underlined word and opens
  its right-click menu (where Docs lists its suggestions first); then tap **Use 1st / 2nd / 3rd** (top row) to pick one. With *Auto-next* on (default) it
  then jumps to the following error and opens its menu, so a whole document is a row of taps. *Previous error* and *Skip this one* sit beside
  *Next error*; *Close menu* (Esc), *Undo in Docs* and *Redo in Docs* are on the next row. Tap *Use ...* only when you can see Docs' suggestion menu.
  **If the browser's own menu comes up instead** ("Save Page As...", "View Page Source"; Firefox does this for Shift+F10), tap
  **Wrong menu? Try ...**: it closes that menu and opens it with the next key (Google lists three for Docs' context menu:
  Ctrl+Shift+\ (the default), Ctrl+Shift+X and Shift+F10); the one that works is remembered. Tab *Keys* has every key on its own.
  Settings has *pause between keys* (default 0.25 s): raise it if Docs misses keys, lower it if it feels slow.
- Toggles for *Fix typos as I type* and *Keep the cursor level*.

### Keeping the cursor level

Turn on *Keep the cursor level* (Settings, the right-click menu, or the Tools screen) and swipepen turns the **mouse wheel** a little as your text
grows (new lines, Enter) and the other way when you delete, so the line you are writing stays at the same height on the screen. It cannot see the page,
so it counts: lines of text from the characters typed. Two sliders in Settings calibrate it: *characters that fit on one line* of your document and
*wheel clicks per line*. The **Test** button scrolls exactly ten lines after four seconds: put the mouse over your document, see if the page moved 10 lines,
adjust the slider, repeat. The wheel acts on the window under the **mouse pointer**, so keep the pointer over the document (the pen does not move it).
It drifts a little over a long time (it is an estimate); scroll by hand whenever you like.

### Seeing what the pen does, and looking after your hand (new in 0.7)

**Swipe trail and lit keys.** While you swipe, the whole path stays on the keyboard, older parts dimmer and thinner than the part
near the pen. When you lift the pen the finished path lingers for a moment and fades. The key under the pen is lit, and so are the
letters the stroke has passed over (the ones the decoder is looking at). On the pen screens the box under the pen is lit too.
Both can be switched off in Settings.

**Pressure hint.** The pen cursor turns from pale yellow to red (and grows a little) the harder you press. If you press hard on four
strokes in a row, the strip says *lighter touch is enough* (at most once every 90 seconds). *Settings -> Counts as pressing hard
from* sets the level as a share of what your pen can report (default 60%); the switch is also in the Tools screen.
Pens that do not report pressure simply never show it.

**Break reminders.** swipepen counts the time you spend writing: the time between finished strokes, where a pause counts for at most
20 seconds (thinking) and a pause of 3 minutes or more is a real rest that starts the count over. After 30 minutes of writing
(Settings: 0 to 90 minutes, 0 = never; also a switch in the Tools screen) a small screen appears, but only once the pen has been still
for a moment, so never in the middle of a word: *Take a break now*, *Remind me in 10 minutes* or *Skip this one*. Closing it without
choosing asks again in 5 minutes, and it closes by itself if you walk away and rest.

**Stroke counter.** Every finished stroke (tap, swipe, gesture) is counted. The Tools screen and the Settings window show today's
count, yesterday's, and how long you have been writing since a rest. Only the daily totals are kept, in
`~/.config/swipepen/usage.json` (no text, no times of day); *Reset today's stroke count* in Settings clears today.

### The keyboard window and settings

The window shows **only the keyboard**, nothing else:

- **Resize it** by dragging the small grip in its bottom-right corner (or the window border). The keyboard
  scales with the window and the size is remembered.
- **Right-click** the keyboard for a menu: *Settings*, *Pause / resume pen*, *Keep on top*, *Keyboard follows the pen*, *Quit*.
- A **dimmed keyboard** means paused. A **thin red border** means the window itself has focus, so click your Google Docs
  tab. "no match" flashes briefly in the suggestion strip.

**Settings** open in their own window (right-click -> *Settings*, or `swipepen settings`, or the launcher's right-click
menu) and stay out of the way otherwise:

- **Keyboard size on the tablet** and a **map of the tablet** (click it to move the blue keyboard box). Anything from 5% to 100%
  of the tablet width. Touches that start outside the box are ignored.
- **Key shape** (1.0 to 2.0, default 1.5): how tall a key is compared with its width. 1.5 is the same squished layout as
  Gboard, so the hand travels less sideways. The decoder measures swipes in real distance, so accuracy is not hurt.
  Choose 1.0 for square keys.
- **Cursor speed** (0.3x to 3x): how fast the caret runs when you hold the pen at the edge of the keyboard after a space-bar swipe.
- **Swipe trail**, **lit keys**, **break reminders**, **pressure hint** and its level, today's **stroke count** (see above).
- **Fix typos as I type** and **My words** (see above).
- **Keep the cursor level** with its two calibration sliders and a test button (see above).
- **Rotation**: *Left-handed (rotate 180°)* if your tablet is turned the other way (90° and 270° exist too).
  KDE's own tablet orientation setting does **not** apply while swipepen is running (swipepen reads the raw pen signal),
  which is why swipepen has its own switch. KDE's setting works again as soon as you pause the pen.
- **Keyboard follows the pen** (on by default): lets you move around the whole tablet instead of staying in one spot.
  While the pen hovers and you push past an edge of the keyboard box, the box is dragged along with the pen. If you lift the
  pen away from the tablet and put it down somewhere else, the box jumps to centre on the pen. While the pen is touching
  (swiping), the box never moves. Turn it off to keep the box fixed.
- **Keep on top**: on by default. If your window manager still lets the window slip behind the browser, right-click its title
  bar -> *More Actions* -> *Keep Above* (KDE remembers it).

**Pen and mouse are separate.** swipepen reads only the pen device. Your mouse and touchpad keep working normally (use them for
the right-click menu or to click your Google Docs tab) and never move the keyboard box or type anything.

### KDE tips
- Bind a global shortcut to pause/resume (and, if you like, one for `swipepen settings`): *System Settings -> Keyboard -> Shortcuts -> Add New -> Command or Script*, command `swipepen toggle`.
- Plasma's *Drawing Tablet* area mapping does not matter while swipepen is active.

## Options

| flag | meaning |
|---|---|
| `--device /dev/input/eventN` | pick the pen manually |
| `--rotate 0/90/180/270` | tablet rotation (180 = left-handed); normally set in the window |
| `--size PCT` | keyboard size on the tablet, % of its width (default 50) |
| `--scale PX` | size of the preview keyboard on screen, pixels per key (default 60) |
| `--layout us/es/latam` | your active layout; only changes the apostrophe key |
| `--record swipes.jsonl` | save swipes to this file for this run (the same recording as Settings -> *Save my swipes*, other file) |
| `--dry-run`, `--no-pen`, `--mouse` | testing without typing / without a pen |
| `--start-paused` | start with the pen released |

More commands: `swipepen replay`, `swipepen swipes info|path|clear`, `swipepen build-ngrams PATHS`, see *Accuracy tools*.

Add your own words (names, jargon): one per line in `~/.config/swipepen/words.txt` (they get a frequency boost).

## Tests

```bash
python3 -m swipepen.simulate                     # decoder accuracy on synthetic swipes
PYTHONPATH=. python3 tests/test_session.py       # typing logic, headless
PYTHONPATH=. python3 tests/test_evdev_stub.py    # pen reader, rotation + virtual keyboard against a fake evdev
PYTHONPATH=. python3 tests/test_area.py          # keyboard area on the tablet + pen routing
PYTHONPATH=. python3 tests/test_tidy.py          # typo fixes, apostrophes, my words, tidy, cursor speed
PYTHONPATH=. python3 tests/test_updater.py       # `swipepen update` from a fake Downloads folder
PYTHONPATH=. python3 tests/test_doctor.py        # setup check
PYTHONPATH=. python3 tests/test_gui_smoke.py     # preview window wiring (mock Tk, not how it looks)
PYTHONPATH=.:tests python3 tests/test_layers.py    # numbers / symbols, caps lock, undo, keep-cursor-level
PYTHONPATH=.:tests python3 tests/test_lookup.py    # dictionary (a tiny WordNet-format fixture), online lookups, spelling
PYTHONPATH=.:tests python3 tests/test_checker.py   # paragraph check: grammar rules, spelling, LanguageTool (fake server)
PYTHONPATH=.:tests python3 tests/test_panels.py    # pen screens: tools, dictionary, paragraph check, Docs keys
PYTHONPATH=.:tests python3 tests/test_predict.py   # next-word strip, completions, learning, unfinished swipes, looseness
PYTHONPATH=.:tests python3 tests/test_recorder.py  # swipe recorder, labels, learning from fixes, replay / sweep
PYTHONPATH=.:tests python3 tests/test_ngrams.py    # word-pair table: build, load, predictor, hold-out evaluation
PYTHONPATH=.:tests python3 tests/test_trailfx.py   # swipe trail fading, lit keys (logic only, no Tk)
PYTHONPATH=.:tests python3 tests/test_wellbeing.py # stroke counter, break reminders, pressure hint, new settings
```

Synthetic results (offline word list, so frequency priors are rough; see caveats):

| hand noise | top-1 | top-3 | top-5 |
|---|---|---|---|
| low (0.15 key) | 97% | 99% | 99% |
| medium (0.30 key) | 82% | 94% | 96% |
| high (0.45 key) | 56% | 76% | 81% |

## Honest status (v0.7)

- The decoder and typing logic are tested. **The Tk window and real Wacom/uinput behaviour have not been run on actual hardware** - expect some first-run fixes. Run `devices` and the mouse test first.
- English and US-style letter positions only. Accented letters (á, é, ñ...) are not typed yet; Spanish needs a Spanish word list plus an input method for accents (planned).
- The offline fallback dictionary (used without `wordfreq`) is much worse at ranking words than `wordfreq`.
- "tidy" and "+ word" read your document through the clipboard, with Ctrl+Shift+Up / Ctrl+Shift+Left and Ctrl+C. That is how
  Google Docs in the browser behaves, but it has not been tried on real hardware yet. Docs may turn typed apostrophes into curly
  ones (that is fine, swipepen understands both).
- The erase and cursor gestures press Ctrl+Shift+Left and the arrow keys. They work in Google Docs, but this has not been tried
  on real hardware yet; if a word is selected differently than you expect, tell me what Docs highlights.
- New in 0.4, all tested only against fakes (no real Docs, Wacom or Tk here): the symbol keyboard and the way symbols are typed
  (US keycodes; other layouts and unusual symbols go through the clipboard with Ctrl+V), the pen screens, the wheel scrolling,
  and the Docs shortcuts (taken from Google's help pages; how Enter / Tab behave inside Docs' spelling panel may differ, tell me what you see).
  The wheel only works over the window under the mouse pointer and the amount per click depends on your browser. The paragraph check
  works on the paragraph before the caret only. The Dictionary reads the word before the caret, so write the word first.
- New in 0.5, tested on synthetic swipes and fakes only: the built-in next-word list is hand-written and modest (it will suggest
  plausible but plain words until it has learned you), and the unfinished-swipe decoder takes a bit longer per swipe (about 0.1 s here with a
  62,000-word list). If a short word you swipe in full keeps turning into a longer one, move *Swipe tolerance* toward strict.
- New in 0.6, tested on synthetic swipes and fakes only: the recorder, `replay`, learning from fixes and `build-ngrams`. Nothing has
  been recorded from a real hand yet, so no real-hand accuracy number exists; the synthetic table above is still the only one. The
  fix-learning thresholds (how close two paths must be to count as "swiped it again": 1.0 key; within 12 s) are first guesses: if
  `replay` shows wrong labels on your recording, tell me. No word-pair table is bundled, so suggestions stay modest until you build one.
- New in 0.7, tested against fakes only (mock Tk, a fake evdev pen, a fake clock): the trail, key highlights, break reminders, stroke
  counter and pressure hint. How they *look* in the real window (colours, trail thickness, whether lit keys feel helpful or
  distracting) has not been seen on a screen. The pressure level (60%) and "four hard strokes in a row" are guesses: pens differ, so tune
  the slider to your Bamboo. The work-timer numbers (a pause counts up to 20 s, 3 minutes is a rest) are also first guesses.
- Typing is blind-ish: expect a learning period. Turn on *Save my swipes* for a week, then `swipepen replay --sweep looseness=...` is the way to tune the decoder to your hand.
- Glide-typing is a typing aid, not a handwriting recognizer. If you actually want to *write letters by hand*, that is a different tool.

## Manual install (only if ./install.sh does not suit you)

```bash
sudo dnf install python3-evdev python3-tkinter
pip install --user wordfreq
echo 'KERNEL=="uinput", SUBSYSTEM=="misc", TAG+="uaccess", OPTIONS+="static_node=uinput"' | sudo tee /etc/udev/rules.d/60-swipepen-uinput.rules
echo uinput | sudo tee /etc/modules-load.d/uinput.conf
sudo modprobe uinput && sudo udevadm control --reload-rules && sudo udevadm trigger --name-match=uinput
python3 -m swipepen run      # from this folder
```
If `/dev/uinput` is still not writable, add yourself to the `input` group (`sudo usermod -aG input $USER`) and log in again.
