"""Text injection.

UInputInjector creates a virtual keyboard through /dev/uinput, so it works in
any app (Google Docs in Firefox/Chrome, KDE apps, terminals) on both X11 and
Wayland. It sends physical key codes, so the active keyboard layout matters:
letters are in the same place on US, Spanish and Latin-American layouts, but
the apostrophe key differs (see the layout table below).

Every injector offers the same methods:
    type_text(s)            type characters
    backspace(n)            press Backspace n times (deletes the selection if there is one)
    enter()
    move_cursor(n)          n > 0: n characters right, n < 0: n characters left
    select_word_left()      extend the selection one word to the left (Ctrl+Shift+Left)
    collapse_selection()    drop the selection, caret back where it started (Right arrow)
    press(combo)            press a key combination such as "ctrl+z", "f7", "ctrl+'" or "enter"
    undo_key()              Ctrl+Z
    grab_paragraph_before() the text of the paragraph before the caret (caret stays where it was)
    grab_word_before()      the word before the caret (caret stays where it was)
The two grab_* methods raise RuntimeError with a readable message when the document cannot be read.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time

NO_CLIPBOARD = ("Cannot read the document: install a clipboard tool with\n"
                "    sudo dnf install wl-clipboard xclip")


class DryRunInjector:
    """Keeps the text in memory (with a caret and a selection) instead of typing it.
    Used for tests and --dry-run."""

    def __init__(self, echo: bool = False):
        self.buffer = ""
        self.pos = 0            # caret position
        self.anchor = None      # selection anchor, if a selection is being made
        self.echo = echo
        self.pressed = []       # combos sent with press()
        self.scrolled = 0.0     # total wheel notches sent with scroll() (positive = view moved down)
        self._snapshots = []    # what undo_key() goes back to

    # -- helpers ------------------------------------------------------------
    def _fix(self):
        self.pos = min(self.pos, len(self.buffer))
        if self.anchor is not None and self.anchor > len(self.buffer):
            self.anchor = None

    def _selection(self):
        self._fix()
        if self.anchor is None or self.anchor == self.pos:
            return None
        return min(self.anchor, self.pos), max(self.anchor, self.pos)

    def selected_text(self) -> str:
        sel = self._selection()
        return self.buffer[sel[0]:sel[1]] if sel else ""

    def _delete_selection(self) -> bool:
        sel = self._selection()
        self.anchor = None
        if not sel:
            return False
        self.buffer = self.buffer[:sel[0]] + self.buffer[sel[1]:]
        self.pos = sel[0]
        return True

    def view(self, width: int = 60) -> str:
        """The text with the caret shown as | and the selection in [ ]."""
        self._fix()
        sel = self._selection()
        if sel:
            text = (self.buffer[:sel[0]] + "[" + self.buffer[sel[0]:sel[1]] + "]" + self.buffer[sel[1]:])
            caret = sel[1] + 1 if self.pos == sel[1] else sel[0]
        else:
            text, caret = self.buffer, self.pos
        text = text[:caret] + "|" + text[caret:]
        start = max(0, caret - width // 2)
        return text[start:start + width + 1].replace("\n", "\\n")

    # -- injector API ----------------------------------------------------------
    def type_text(self, s: str):
        self._fix()
        self._delete_selection()
        self.buffer = self.buffer[:self.pos] + s + self.buffer[self.pos:]
        self.pos += len(s)
        self._show()

    def backspace(self, n: int = 1):
        for _ in range(n):
            self._fix()
            if self._selection():
                self._snapshots.append((self.buffer, self.pos))   # a deleted selection is one undo step
            if self._delete_selection():
                continue
            if self.pos > 0:
                self.buffer = self.buffer[:self.pos - 1] + self.buffer[self.pos:]
                self.pos -= 1
        self._show()

    def enter(self):
        self.type_text("\n")

    def move_cursor(self, n: int):
        self._fix()
        self.anchor = None
        self.pos = max(0, min(len(self.buffer), self.pos + n))
        self._show()

    def select_word_left(self):
        self._fix()
        if self.anchor is None:
            self.anchor = self.pos
        i = self.pos
        while i > 0 and self.buffer[i - 1].isspace():
            i -= 1
        while i > 0 and not self.buffer[i - 1].isspace():
            i -= 1
        self.pos = i
        self._show()

    def collapse_selection(self):
        sel = self._selection()
        if sel:
            self.pos = sel[1]
        self.anchor = None
        self._show()

    def scroll(self, notches: float):
        self.scrolled += notches

    def press(self, combo: str):
        self.pressed.append(combo.lower())
        if combo.lower() == "ctrl+z":
            self.undo_key()

    def undo_key(self):
        if self._snapshots:
            self.buffer, self.pos = self._snapshots.pop()
            self.anchor = None
        self._show()

    def grab_paragraph_before(self) -> str:
        """Like Ctrl+Shift+Up in Google Docs: at the start of a paragraph it reaches into the previous one."""
        self._fix()
        i = self.pos
        if i > 0 and self.buffer[i - 1] == "\n":
            i -= 1
        while i > 0 and self.buffer[i - 1] != "\n":
            i -= 1
        return self.buffer[i:self.pos]

    def grab_word_before(self) -> str:
        self._fix()
        i = self.pos
        while i > 0 and self.buffer[i - 1].isspace():
            i -= 1
        while i > 0 and not self.buffer[i - 1].isspace():
            i -= 1
        return self.buffer[i:self.pos]

    def _show(self):
        if self.echo:
            print(self.view())


class Clipboard:
    """Text clipboard through wl-clipboard (Wayland) or xclip / xsel (X11)."""

    def __init__(self):
        self.kind = None
        if shutil.which("wl-paste") and shutil.which("wl-copy") and os.environ.get("WAYLAND_DISPLAY"):
            self.kind = "wl"
        elif shutil.which("xclip"):
            self.kind = "xclip"
        elif shutil.which("xsel"):
            self.kind = "xsel"

    def _run(self, cmd, text=None):
        try:
            r = subprocess.run(cmd, input=None if text is None else text.encode("utf-8"),
                               stdout=subprocess.PIPE if text is None else subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=2)
        except (OSError, subprocess.SubprocessError):
            return None
        return r.stdout.decode("utf-8", "replace") if text is None and r.returncode == 0 else (
            "" if text is not None and r.returncode == 0 else None)

    def get(self):
        cmd = {"wl": ["wl-paste", "--no-newline"],
               "xclip": ["xclip", "-selection", "clipboard", "-o"],
               "xsel": ["xsel", "--clipboard", "--output"]}.get(self.kind)
        return self._run(cmd) if cmd else None

    def set(self, text: str):
        cmd = {"wl": ["wl-copy"], "xclip": ["xclip", "-selection", "clipboard"],
               "xsel": ["xsel", "--clipboard", "--input"]}.get(self.kind)
        if cmd:
            self._run(cmd, text)

    def clear(self):
        if self.kind == "wl":
            self._run(["wl-copy", "--clear"], "")
        else:
            self.set("")


class UInputInjector:
    def __init__(self, layout: str = "us", key_delay: float = 0.004):
        try:
            from evdev import UInput, ecodes as e
        except ImportError:
            raise SystemExit("python-evdev is missing:  sudo dnf install python3-evdev")
        self.e = e
        self._UInput = UInput
        self.wheel = None
        self.delay = key_delay

        apostrophe = {"us": e.KEY_APOSTROPHE, "es": e.KEY_MINUS, "latam": e.KEY_MINUS}
        if layout not in apostrophe:
            raise SystemExit(f"unknown layout {layout!r}; use us, es or latam")
        self.layout = layout
        self.keymap = {c: getattr(e, "KEY_" + c.upper()) for c in "abcdefghijklmnopqrstuvwxyz"}
        self.keymap.update({" ": e.KEY_SPACE, ",": e.KEY_COMMA, ".": e.KEY_DOT,
                            "'": apostrophe[layout]})
        for d in "0123456789":                        # the number row is the same on every layout
            self.keymap[d] = getattr(e, "KEY_" + d)
        # Other symbols: key codes only for the US layout. Elsewhere they are pasted, which works on any layout.
        self.shifted = {}
        if layout == "us":
            for ch, name in (("-", "MINUS"), ("=", "EQUAL"), ("[", "LEFTBRACE"), ("]", "RIGHTBRACE"),
                             ("\\", "BACKSLASH"), (";", "SEMICOLON"), ("/", "SLASH"), ("`", "GRAVE")):
                self.keymap[ch] = getattr(e, "KEY_" + name)
            for ch, base in (("!", "1"), ("@", "2"), ("#", "3"), ("$", "4"), ("%", "5"), ("^", "6"),
                             ("&", "7"), ("*", "8"), ("(", "9"), (")", "0"), ("_", "-"), ("+", "="),
                             ("{", "["), ("}", "]"), ("|", "\\"), (":", ";"), ('"', "'"), ("<", ","),
                             (">", "."), ("?", "/"), ("~", "`")):
                self.shifted[ch] = self.keymap[base]
        self.combo_keys = {name: getattr(e, "KEY_" + name.upper()) for name in
                           ("f7", "f10", "tab", "esc", "z", "leftalt", "up", "down", "left", "right", "enter",
                            "backspace", "delete", "home", "end")}
        keys = set(self.keymap.values()) | set(self.shifted.values()) | set(self.combo_keys.values())
        keys |= {e.KEY_BACKSPACE, e.KEY_ENTER, e.KEY_LEFTSHIFT, e.KEY_LEFTCTRL, e.KEY_LEFT, e.KEY_RIGHT,
                 e.KEY_UP}
        self.clip = Clipboard()
        try:
            self.ui = UInput({e.EV_KEY: sorted(keys)}, name="swipepen virtual keyboard")
        except PermissionError:
            raise SystemExit(
                "No permission for /dev/uinput. See the 'Permissions' section of the README.")
        time.sleep(0.6)  # give the desktop a moment to notice the new keyboard

    def _press(self, code, value):
        self.ui.write(self.e.EV_KEY, code, value)
        self.ui.syn()

    def _tap(self, code, mods=()):
        for m in mods:
            self._press(m, 1)
        self._press(code, 1)
        self._press(code, 0)
        for m in reversed(mods):
            self._press(m, 0)
        time.sleep(self.delay)

    def type_text(self, s: str):
        for ch in s:
            if ch.isupper() and ch.lower() in self.keymap and ch.lower().isalpha():
                self._tap(self.keymap[ch.lower()], mods=(self.e.KEY_LEFTSHIFT,))
            elif ch in self.keymap:
                self._tap(self.keymap[ch])
            elif ch in self.shifted:
                self._tap(self.shifted[ch], mods=(self.e.KEY_LEFTSHIFT,))
            elif ch == "\n":
                self.enter()
            else:
                self._paste(ch)              # accents, ¿ ¡ € and symbols of other layouts

    def _paste(self, text: str):
        """Type text the layout-independent way: put it on the clipboard and press Ctrl+V."""
        if self.clip.kind is None:
            return
        saved = self.clip.get()
        self.clip.set(text)
        time.sleep(0.05)
        self._tap(self.keymap["v"], mods=(self.e.KEY_LEFTCTRL,))
        time.sleep(0.12)                     # let the app read the clipboard before it is restored
        if saved is None:
            self.clip.clear()
        else:
            self.clip.set(saved)

    def press(self, combo: str):
        """"ctrl+shift+left", "f7", "ctrl+'" ... (letters, digits and the names in combo_keys)."""
        e = self.e
        mods, key = [], None
        for part in combo.lower().split("+"):
            if part in ("ctrl", "control"):
                mods.append(e.KEY_LEFTCTRL)
            elif part == "shift":
                mods.append(e.KEY_LEFTSHIFT)
            elif part == "alt":
                mods.append(self.combo_keys["leftalt"])
            else:
                key = part
        code = self.combo_keys.get(key) or self.keymap.get(key)
        if code is not None:
            self._tap(code, mods=tuple(mods))

    def undo_key(self):
        self.press("ctrl+z")

    def scroll(self, notches: float):
        """Turn the mouse wheel: notches > 0 scrolls the view down (later text comes up). Works on the
        window under the mouse pointer, like any wheel."""
        e = self.e
        if getattr(self, "wheel", None) is None:
            try:
                self.wheel = self._UInput({e.EV_REL: [e.REL_WHEEL, e.REL_WHEEL_HI_RES]},
                                          name="swipepen virtual wheel")
            except (PermissionError, OSError):
                self.wheel = False
            self._wheel_acc = 0
            time.sleep(0.3)
        if not self.wheel:
            return
        hi = -int(round(notches * 120))
        if hi == 0:
            return
        self.wheel.write(e.EV_REL, e.REL_WHEEL_HI_RES, hi)
        self._wheel_acc += hi
        while abs(self._wheel_acc) >= 120:
            step = 1 if self._wheel_acc > 0 else -1
            self.wheel.write(e.EV_REL, e.REL_WHEEL, step)
            self._wheel_acc -= 120 * step
        self.wheel.syn()

    def backspace(self, n: int = 1):
        for _ in range(n):
            self._tap(self.e.KEY_BACKSPACE)

    def enter(self):
        self._tap(self.e.KEY_ENTER)

    def move_cursor(self, n: int):
        code = self.e.KEY_RIGHT if n > 0 else self.e.KEY_LEFT
        for _ in range(abs(n)):
            self._tap(code)

    def select_word_left(self):
        self._tap(self.e.KEY_LEFT, mods=(self.e.KEY_LEFTCTRL, self.e.KEY_LEFTSHIFT))

    def collapse_selection(self):
        self._tap(self.e.KEY_RIGHT)

    def _grab(self, key, mods) -> str | None:
        """Select with a keyboard chord, copy, read the clipboard, put the old clipboard back,
        and drop the selection so the caret is exactly where it was. None: nothing was selected."""
        if self.clip.kind is None:
            raise RuntimeError(NO_CLIPBOARD)
        e = self.e
        saved = self.clip.get()
        sentinel = f"swipepen-{time.time_ns()}"
        self.clip.set(sentinel)
        time.sleep(0.05)
        self._tap(key, mods=mods)
        time.sleep(0.06)
        self._tap(self.keymap["c"], mods=(e.KEY_LEFTCTRL,))
        text = None
        for _ in range(30):
            time.sleep(0.04)
            cur = self.clip.get()
            if cur is not None and cur != sentinel:
                text = cur
                break
        if saved is None:
            self.clip.clear()
        else:
            self.clip.set(saved)
        if text is not None:
            self._tap(e.KEY_RIGHT)          # collapses the selection at its right end = where the caret was
        return text

    def grab_paragraph_before(self) -> str:
        e = self.e
        return self._grab(e.KEY_UP, (e.KEY_LEFTCTRL, e.KEY_LEFTSHIFT)) or ""

    def grab_word_before(self) -> str:
        e = self.e
        return self._grab(e.KEY_LEFT, (e.KEY_LEFTCTRL, e.KEY_LEFTSHIFT)) or ""

    def close(self):
        self.ui.close()
