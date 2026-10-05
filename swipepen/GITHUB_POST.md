# Swipepen ✍️ — swipe typing with a pen tablet (like Gboard, but on your desktop)

**Write whole words with one stroke of a pen, instead of pressing keys one at a time.**

Swipepen puts a small on-screen keyboard under your pen tablet. You drag the pen across the letters of a word
and lift. Swipepen works out which word you meant and types it into whatever app has focus (Google Docs, a
browser, a text editor…). It is the same idea as swipe typing on a phone, built for a Wacom-style tablet.

I made it because typing hurts my finger joints. Writing with a light pen stroke is far gentler on the hands.

> **Status: v0.5.3 — works on Linux only today.** It was built and tested on **Fedora KDE + Wacom Bamboo +
> Firefox + Google Docs**. The decoder and all the "smart" parts are plain Python and portable, but the three
> small pieces that talk to the operating system are Linux-specific. **macOS and Windows ports are not done yet,
> and this post explains exactly what they need — contributions are very welcome.** See
> [Porting to macOS and Windows](#porting-to-macos-and-windows).

---

## What it can do

**Typing**
- **Swipe a word** across the letters. Taps type single letters, so you can still fix or spell things.
- **Loose swipes work.** Like Gboard, you do not have to be exact, and you do not have to finish the word:
  swiping "thin…" will still offer "think" and "thing". A *looseness* slider in Settings tunes this.
- **Suggestion strip** above the keys: tap an alternative to swap the word you just typed.
- **Next-word prediction and completions**, like Gboard. You can build whole sentences by tapping suggestions.
  It learns the phrases you write (stored **only on your computer**, in `~/.config/swipepen/phrases.json`;
  you can turn learning off or wipe it).
- Auto-space, one-shot Shift, **Caps Lock** (double-tap), number/symbol layers (`?123` / `ABC`).
- **Swipe over Backspace to erase** words, **swipe over Space to move the cursor** (with edge momentum).
- Layouts for the apostrophe key: `us`, `es`, `latam` (other characters are pasted via the clipboard).

**Fixing mistakes**
- **Live typo fixes** while you type (only the last two words, only after you finish a word; can be switched off).
- **Tidy** the paragraph before the cursor in one tap, and a **+ word** button to add names/jargon to your
  personal dictionary.
- **Undo** (and Redo in the Google Docs panel).
- **Paragraph check**: built-in grammar rules and spelling suggestions, plus **LanguageTool** if you run a
  local server (auto-detected on `127.0.0.1:8081` / `8010`, or set `languagetool_url`).

**Dictionary**
- Tap a word to see its **definition, synonyms and antonyms**. Offline through WordNet
  (`sudo dnf install wordnet`), with an online fallback (Datamuse, dictionaryapi.dev).
  Also from the terminal: `swipepen define WORD`.

**Google Docs helpers**
- A guided **spelling / grammar flow**: jump to the next or previous error, pick suggestion **1 / 2 / 3** with one
  tap, skip, undo / redo. It drives the normal Docs shortcuts (`Ctrl+'`, `Ctrl+;`, the context-menu key,
  `Ctrl+Alt+X`) so it is not a hack on the page.
- **Keep the cursor at a stable height** ("typewriter scrolling"): as you write, Swipepen scrolls the page for
  you so the line you are typing on never creeps down to the bottom of the screen. Needs the tiny userscript
  below.

**Pen handling**
- The pen is **grabbed** while Swipepen runs (it does not move your desktop cursor). Press the pen's side
  button, click the button in the window, or run `swipepen toggle` to use the pen as a normal tablet again.

---

## Install on Linux (Fedora, tested)

```bash
tar xzf swipepen.tar.gz     # or: git clone <this repo> && cd swipepen
cd swipepen
./install.sh
```

The installer asks for your password once, installs `python3-evdev`, `python3-tkinter`, `wl-clipboard`, `xclip`
(and `wordnet` if available), adds the permission rules that let Swipepen read the tablet and type for you,
downloads a word-frequency list, and adds **Swipepen** to your application menu. `./uninstall.sh` removes it.

Then:
1. Open **Swipepen** from the menu (or run `swipepen`). The pen is found automatically.
2. Click your **Google Docs tab** once so it has focus.
3. Swipe words with the pen.

Try it without typing anything first: `swipepen run --dry-run --no-pen --mouse`, then drag the mouse over the
letters in the window.

**Something wrong?** Run `swipepen doctor` — it lists what is missing and the exact fix for each item.
`swipepen devices` shows which input device is your pen (marked `*`).

**Other Linux distros:** install the equivalents of the packages above (Debian/Ubuntu: `python3-evdev python3-tk
wl-clipboard xclip wordnet`), make `/dev/uinput` writable for your user, and make your tablet readable
(add yourself to the `input` group, or use the udev rules in `install.sh` as a template). Not tested by me,
but nothing in the code is Fedora-specific besides `install.sh`.

### Commands

| Command | What it does |
|---|---|
| `swipepen` / `swipepen run` | start swipe typing |
| `swipepen doctor` | check setup, show fixes |
| `swipepen devices` | list input devices, find your pen |
| `swipepen toggle` | pause/resume a running instance (bind it to a keyboard shortcut) |
| `swipepen settings` | open the settings window |
| `swipepen tidy` | fix typos in the paragraph before the cursor |
| `swipepen learn` | add the word before the cursor to your dictionary |
| `swipepen words list|add|remove WORD…` | manage your personal dictionary |
| `swipepen define WORD` | definition, synonyms, antonyms in the terminal |
| `swipepen update` | install the newest `swipepen*.tar.gz` from Downloads |

---

## Google Docs setup (for the best experience)

### 1) Add scroll room, so "keep the cursor at a stable height" works

Typewriter scrolling needs room to scroll *below* the last line of your document. Google Docs does not give you
that, so you cannot scroll the text up when you are at the end of the document. This tiny userscript adds
extra space at the bottom of the page.

1. Install **[Violentmonkey](https://violentmonkey.github.io/)** (or Tampermonkey) in Firefox / Chrome.
2. Create a new script and paste this in (also saved in this repo as `extras/docs-extended-scrolling.user.js`):

```js
// ==UserScript==
// @name         Docs Extended Scrolling (Firefox)
// @namespace    http://tampermonkey.net/
// @version      1.0
// @description  Adds extra scroll space at the bottom of Google Docs
// @match        https://docs.google.com/document/*
// @grant        none
// ==/UserScript==

(function() {
    'use strict';
    function addPadding() {
        const pageContainer = document.querySelector('.kix-rotatingtilemanager');
        if (pageContainer) {
            pageContainer.style.paddingBottom = '90vh';
        }
    }
    // Run once and also after Docs finishes loading
    addPadding();
    setTimeout(addPadding, 2000);
    setTimeout(addPadding, 5000);
})();
```

3. Reload your Google Doc. You should now be able to scroll the last line up to the middle of the screen.

If Google changes the page and the padding stops appearing, the class name `.kix-rotatingtilemanager` is the
thing to update (inspect the page area in your browser's developer tools).

### 2) Teach Swipepen how fast your page scrolls

Open **Settings** and use the *characters per line* and *scroll per line* sliders, then the **10-line test**
button, until ten lines of text scroll by about ten lines. This depends on your zoom level and window size.
**The mouse pointer has to be over the document** for scrolling to reach it.

### 3) Spelling and grammar in Docs

Turn on *Tools → Spelling and grammar → Show spelling suggestions* in Docs. Swipepen's Docs panel then walks you
through the errors. The default key for opening the suggestion menu is `Ctrl+Shift+\`. If your browser shows
its own menu instead, the **Wrong menu? Try …** button cycles through other keys. If suggestions feel too quick
or too slow, change the *Docs pause* in Settings.

---

## How it works (and why porting is realistic)

```
 pen tablet ──► [1] read the pen ──► decoder ──► session ──► [2] type keys / scroll ──► the focused app
                                      (pure Python, portable)        │
                                                  [3] clipboard (for tidy and for odd characters)
                  [4] always-on-top keyboard window (Tk)  ◄── draws the keys, strip, panels
```

- The **decoder** matches your stroke against the ideal path of every word (a SHARK2-style template matcher with
  partial-word matching and re-ranking by the previous word). It takes about 0.1 s per swipe.
- The **session** handles taps, swipes, layers, undo, suggestions, panels, typo fixes and Docs flows.
- The **window** is a Tk window that draws the keyboard.

Decoder, session, panels, predictor, checker, dictionary lookup and tidy are plain Python with a headless test
suite (`tests/`). Only **[1] reading the pen**, **[2] typing/scrolling** and **[3] the clipboard** are
OS-specific.

## Porting to macOS and Windows

> ⚠️ Not implemented. Everything below is a guide for contributors, not a claim that it works.

| Piece | Linux (today) | Windows (to do) | macOS (to do) |
|---|---|---|---|
| **[1] Read the pen, ideally exclusively** (`swipepen/pen.py`) | `python-evdev`, grab the device | Raw Input / WinTab / Windows Ink pointer events; to hide the pen from the desktop cursor, use a low-level hook or a transparent full-screen overlay window that captures it | Quartz event tap or IOKit HID; may need *Input Monitoring* permission |
| **[2] Type keys and scroll** (`swipepen/inject.py`) | `/dev/uinput` virtual keyboard + virtual wheel | `SendInput` (keyboard + `MOUSEEVENTF_WHEEL`) | `CGEventPost` (keyboard + scroll wheel events); needs *Accessibility* permission |
| **[3] Clipboard** (`swipepen/inject.py`) | `wl-paste`/`wl-copy` or `xclip` | `pyperclip` or the Win32 clipboard API | `pbpaste` / `pbcopy` |
| **[4] The window** | Tk, always on top | Tk works; make sure it does not take focus | Tk works; needs a non-activating window so it does not steal focus from the app you type in |

Things to watch for when porting:
- **Focus:** the keyboard window must never take keyboard focus, or the typed text goes to the wrong place.
- **Shortcuts differ.** On macOS Docs uses `Cmd` where Linux/Windows use `Ctrl` (for example `Cmd+Option+X` instead
  of `Ctrl+Alt+X`), so the Docs key table needs a per-OS version.
- **Permissions:** macOS asks for Accessibility / Input Monitoring. Windows may block injecting into windows running
  as administrator, and some games' anti-cheat blocks injected input.
- **Pen on a screen vs. a pen tablet.** Swipepen maps the *tablet surface* to the keyboard. On a pen display
  (Wacom Cintiq, iPad-style) you could draw directly on the on-screen keyboard instead.

A good way to start: implement a replacement for `PenReader` (`pen.py`) and for the injector (`inject.py`) with the same methods as the Linux
ones, then run `swipepen run --dry-run --no-pen --mouse` to check the decoder and window on your OS before touching
real input. `DryRunInjector` in `inject.py` shows the minimal set of methods an injector needs.

---

## Honest limitations

- **Linux only** at the moment, tested by one person on one setup (Fedora KDE, Wacom Bamboo, Firefox).
  Other tablets, desktops and distros are untested.
- **English** word list and grammar rules. Layouts only affect the apostrophe key.
- **Google Docs automation depends on Docs' own shortcuts and menu**; if Google changes them, the flow may need
  tweaks. Browsers can show their own menu over Docs' menu — use *Wrong menu? Try …*.
- **Scroll-to-keep-level is an estimate** (it counts characters and lines); it needs calibration and works best
  with the mouse pointer over the document.
- The paragraph check is a helper, not a replacement for a real grammar checker. Running LanguageTool locally
  makes it much better.
- Swipepen types for you through a virtual keyboard, so only run software you trust with that permission.

## Contributing

Ports (Windows, macOS, X11-only and Wayland-only setups), other keyboard layouts and languages, other tablets,
and bug reports are all welcome. Please include the output of `swipepen doctor` and your tablet model in bug
reports.

## License

_(add your license here — MIT is a common, permissive choice)_
