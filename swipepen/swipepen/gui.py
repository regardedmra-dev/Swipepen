"""Keyboard window (Tk).

The main window shows only the keyboard: the keys, the word suggestions, your
swipe trail and the pen position. Because the tablet is not a screen, this
window is how you see where the pen is.

- Resize it by dragging the small grip in the bottom-right corner (or by
  dragging the window border); the keyboard scales with the window.
- Right-click the keyboard for the menu: Settings, pause, keep on top, follow.
- Settings (size of the keyboard on the tablet, the tablet map, rotation /
  left-handed, ...) live in a separate window that is hidden until you ask.

Subtle signals instead of text: a dimmed keyboard means paused, a thin red
border means this window has focus (click your Google Docs tab so the typed
text goes there), and "no match" flashes in the suggestion strip.

Typing does not need this window to have focus: text goes in through a virtual
keyboard, so it lands in whatever app has focus.
"""
from __future__ import annotations

import os
import queue
import time
import tkinter as tk

from . import lexicon
from .area import Area, PenRouter, load_config, save_config
from .engine import (CANVAS_H, CANVAS_W, CANVAS_Y0, FUNCTION_KEYS, KEY_CENTER, STRIP_CELLS, SYM_CENTER,
                     function_label)

BG, KEY, KEY_FN, KEY_HI = "#1e1e24", "#34343e", "#2a2a33", "#3d7bd9"
TEXT, DIM = "#e8e8ee", "#8a8a98"
MAP_W = 170
MIN_W = 100            # smallest window width in pixels
GRIP = 14              # size of the resize grip in the corner
ROTATIONS = [("Normal", 0), ("Left-handed (rotate 180°)", 180), ("Rotate 90°", 90), ("Rotate 270°", 270)]


class App:
    def __init__(self, session, reader=None, dry=None, mouse=False, cfg=None,
                 start_active: bool = True):
        self.s = session
        self.reader = reader
        self.dry = dry
        self.mouse = mouse
        self.cfg = cfg if cfg is not None else load_config()
        self.S = float(self.cfg["scale"])          # pixels per key width
        self.ka = float(self.cfg["key_aspect"])    # key height / key width (1.5 like Gboard)
        self.ox = self.oy = 0.0                    # where the keyboard starts inside the canvas
        self.W, self.H = int(CANVAS_W * self.S), int(CANVAS_H * self.S * self.ka)
        self.active = bool(reader) and start_active
        self._toggle_flag = self._settings_flag = self._cmd_flag = False
        self._words_mtime = self._mtime(lexicon.user_words_path())
        self._save_job = None
        self._grip = None
        self._settings = None
        self._settings_open = False
        self._last_msg, self._flash_until = "", 0.0

        if reader:
            reader.set_rotate(self.cfg["rotate"])
        aspect = reader.aspect if reader else 1.6
        self.area = Area(aspect, self.cfg["size"], self.cfg["cx"], self.cfg["cy"], key_aspect=self.ka)
        self.router = PenRouter(session, self.area, follow=bool(self.cfg["follow"]))
        decoder = getattr(session, "decoder", None)
        if hasattr(decoder, "set_ys"):
            decoder.set_ys(self.ka)                # match swipes to the real (tall) key shape

        session.edge_speed = float(self.cfg["edge_speed"])
        session.autofix = bool(self.cfg["autofix"])
        session.languagetool_url = str(self.cfg["languagetool_url"])
        session.online_lookup = bool(self.cfg["online_lookup"])
        if hasattr(session, "set_typewriter"):
            session.set_typewriter(bool(self.cfg["typewriter"]), self.cfg["chars_per_line"],
                                   self.cfg["notches_per_line"])
        session.predict = bool(self.cfg["predict"])
        session.learn_typing = bool(self.cfg["learn_typing"])
        if hasattr(decoder, "set_looseness"):
            decoder.set_looseness(float(self.cfg["looseness"]))
        session.docs_menu_key = str(self.cfg["docs_menu_key"])
        session.docs_delay = float(self.cfg["docs_delay"])
        session.docs_auto = bool(self.cfg["docs_auto"])
        session.on_setting = self._on_session_setting
        self._drawn_layer = "letters"

        self.root = tk.Tk(className="Swipepen")
        self.root.title("swipepen")
        self.root.configure(bg=BG)
        self.root.report_callback_exception = self._on_callback_error
        self.root.geometry(f"{self.W}x{self.H}")
        self.root.minsize(MIN_W, int(MIN_W * CANVAS_H * self.ka / CANVAS_W))

        self.top_var = tk.BooleanVar(value=bool(self.cfg["topmost"]))
        self.follow_var = tk.BooleanVar(value=bool(self.cfg["follow"]))
        self.autofix_var = tk.BooleanVar(value=bool(self.cfg["autofix"]))
        self.typewriter_var = tk.BooleanVar(value=bool(self.cfg["typewriter"]))
        self.predict_var = tk.BooleanVar(value=bool(self.cfg["predict"]))
        self.learn_var = tk.BooleanVar(value=bool(self.cfg["learn_typing"]))
        self.rot_var = tk.StringVar(value=next(
            (lbl for lbl, deg in ROTATIONS if deg == self.cfg["rotate"]), ROTATIONS[0][0]))

        self.status = None
        if dry is not None:                       # mouse-test mode: show what would be typed
            self.status = tk.Label(self.root, anchor="w", bg=BG, fg=TEXT, font=("monospace", 10))
            self.status.pack(side="bottom", fill="x")
        self.canvas = tk.Canvas(self.root, bg=BG, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Settings...", command=self.open_settings)
        self.menu.add_command(label="Pause / resume pen", command=self.toggle)
        self.menu.add_checkbutton(label="Keep on top", variable=self.top_var, command=self._on_topmost)
        self.menu.add_checkbutton(label="Keyboard follows the pen", variable=self.follow_var,
                                  command=self._on_follow)
        self.menu.add_checkbutton(label="Fix typos as I type", variable=self.autofix_var,
                                  command=self._on_autofix)
        self.menu.add_checkbutton(label="Suggest the next word", variable=self.predict_var, command=self._on_predict)
        self.menu.add_checkbutton(label="Keep the cursor level while writing", variable=self.typewriter_var,
                                  command=self._on_typewriter)
        self.menu.add_command(label="Tools (dictionary, check paragraph)...", command=self.s.open_tools)
        self.menu.add_separator()
        self.menu.add_command(label="Update from Downloads", command=self._update)
        self.menu.add_command(label="Quit", command=self.close)

        c = self.canvas
        c.bind("<Configure>", self._on_resize)
        c.bind("<Button-3>", self._popup)
        c.tag_bind("grip", "<ButtonPress-1>", self._grip_press)
        c.tag_bind("grip", "<B1-Motion>", self._grip_drag)
        c.tag_bind("grip", "<ButtonRelease-1>", self._grip_release)
        c.tag_bind("grip", "<Enter>", lambda ev: c.configure(cursor="bottom_right_corner"))
        c.tag_bind("grip", "<Leave>", lambda ev: c.configure(cursor=""))
        if mouse:
            c.bind("<ButtonPress-1>", lambda ev: self._mouse("down", ev))
            c.bind("<B1-Motion>", lambda ev: self._mouse("move", ev))
            c.bind("<ButtonRelease-1>", lambda ev: self._mouse("up", ev))
            c.bind("<Motion>", lambda ev: self._mouse("hover", ev))

        self._relayout(self.W, self.H)
        if self.reader:
            self.reader.set_active(self.active)
        self._refresh_state()
        self._apply_topmost()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(8, self._poll)
        self.root.after(20, self._redraw)
        self.root.after(1000, self._keep_on_top)

    # ---- layout / resizing ------------------------------------------------------
    def _relayout(self, W, H):
        S = max(4.0, min(W / CANVAS_W, H / (CANVAS_H * self.ka)))
        self.W, self.H = W, H
        self.ox, self.oy = (W - S * CANVAS_W) / 2, (H - S * CANVAS_H * self.ka) / 2
        self.S = S
        self.canvas.delete("static")
        self._draw_static()

    def _on_resize(self, ev):
        if ev.width < 20 or ev.height < 20:
            return
        if (ev.width, ev.height) != (self.W, self.H):
            self._relayout(ev.width, ev.height)
            self.cfg["scale"] = max(8, int(self.S))
            self._schedule_save()

    def _grip_press(self, ev):
        self._grip = (ev.x_root, self.root.winfo_width())

    def _grip_drag(self, ev):
        if not self._grip:
            return
        x0, w0 = self._grip
        w = max(MIN_W, int(w0 + (ev.x_root - x0)))
        extra = max(0, self.root.winfo_height() - self.canvas.winfo_height())   # label in test mode
        h = max(int(MIN_W * CANVAS_H * self.ka / CANVAS_W), int(w * CANVAS_H * self.ka / CANVAS_W)) + extra
        self.root.geometry(f"{w}x{h}")

    def _grip_release(self, ev):
        self._grip = None

    def _popup(self, ev):
        try:
            self.menu.tk_popup(ev.x_root, ev.y_root)
        finally:
            self.menu.grab_release()

    # ---- settings window (hidden until asked for) ---------------------------------------
    def request_settings(self):         # called from the SIGUSR2 handler
        self._settings_flag = True

    def open_settings(self):
        if self._settings is None:
            self._build_settings()
        self._settings.deiconify()
        self._settings.lift()
        self._settings_open = True

    def _close_settings(self):
        self._settings.withdraw()
        self._settings_open = False

    def _build_settings(self):
        top = self._settings = tk.Toplevel(self.root)
        top.title("swipepen settings")
        top.configure(bg=BG)
        top.protocol("WM_DELETE_WINDOW", self._close_settings)
        pad = dict(padx=8, pady=4)

        # The status line and the Close button stay at the bottom; everything else scrolls.
        bottom = tk.Frame(top, bg=BG)
        bottom.pack(side="bottom", fill="x")
        body = tk.Frame(top, bg=BG)
        body.pack(side="top", fill="both", expand=True)
        canvas = tk.Canvas(body, bg=BG, highlightthickness=0)
        scrollbar = tk.Scrollbar(body, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        win = tk.Frame(canvas, bg=BG)                 # all the settings widgets live in here
        inner = canvas.create_window((0, 0), window=win, anchor="nw")
        win.bind("<Configure>", lambda ev: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda ev: canvas.itemconfigure(inner, width=ev.width))

        def wheel(ev):                                 # mouse wheel / touchpad scrolls the settings
            try:
                if ev.widget.winfo_class() == "Listbox":
                    return                             # the word list scrolls itself
            except tk.TclError:
                pass
            num = getattr(ev, "num", 0)
            step = -1 if num == 4 or getattr(ev, "delta", 0) > 0 else 1
            canvas.yview_scroll(step, "units")
        top.bind("<Enter>", lambda ev: [top.bind_all(seq, wheel) for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>")])
        top.bind("<Leave>", lambda ev: [top.unbind_all(seq) for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>")])
        self._settings_canvas = canvas

        if self.reader:
            self.mini_w, self.mini_h = MAP_W, self._mini_h()
            self.mini = tk.Canvas(win, width=self.mini_w, height=self.mini_h, bg="#15151a",
                                  highlightthickness=1, highlightbackground=DIM)
            self.mini.pack(**pad)
            self.mini.bind("<Button-1>", self._mini_click)
            self.mini.bind("<B1-Motion>", self._mini_click)
            tk.Label(win, text="Your tablet. The blue box is the keyboard - click to move it.",
                     bg=BG, fg=DIM, font=("sans", 9)).pack()

            self._ready = False
            self.size_scale = tk.Scale(win, from_=5, to=100, orient="horizontal",
                                       label="Keyboard size on the tablet (%)", command=self._on_size,
                                       bg=BG, fg=TEXT, highlightthickness=0, troughcolor=KEY, length=260)
            self.size_scale.set(int(round(self.area.size * 100)))
            self.size_scale.pack(**pad)
            self._ready = True

            self.ka_scale = tk.Scale(win, from_=1.0, to=2.0, resolution=0.05, orient="horizontal",
                                     label="Key shape: height / width  (1.0 square, 1.5 like Gboard)",
                                     command=self._on_key_aspect, bg=BG, fg=TEXT, highlightthickness=0,
                                     troughcolor=KEY, length=260)
            self.ka_scale.set(self.ka)
            self.ka_scale.pack(**pad)

            tk.OptionMenu(win, self.rot_var, *[lbl for lbl, _ in ROTATIONS],
                          command=self._on_rotate).pack(**pad)
            tk.Checkbutton(win, text="Keyboard follows the pen", variable=self.follow_var,
                           command=self._on_follow, bg=BG, fg=TEXT, selectcolor=KEY,
                           activebackground=BG, activeforeground=TEXT).pack(**pad)
        self.speed_scale = tk.Scale(win, from_=0.3, to=3.0, resolution=0.1, orient="horizontal",
                                    label="Cursor speed when holding the pen at the edge (x)",
                                    bg=BG, fg=TEXT, highlightthickness=0, troughcolor=KEY, length=260)
        self.speed_scale.set(self.s.edge_speed)
        self.speed_scale.configure(command=self._on_edge_speed)     # after set(): opening settings saves nothing
        self.speed_scale.pack(**pad)
        tk.Checkbutton(win, text="Fix typos as I type (hel lo, lone i, dont ...)", variable=self.autofix_var,
                       command=self._on_autofix, bg=BG, fg=TEXT, selectcolor=KEY,
                       activebackground=BG, activeforeground=TEXT).pack(**pad)
        self.loose_scale = tk.Scale(win, from_=0, to=100, orient="horizontal",
                                    label="Swipe tolerance: strict (0)  ...  loose (100)",
                                    bg=BG, fg=TEXT, highlightthickness=0, troughcolor=KEY, length=260)
        self.loose_scale.set(int(round(float(self.cfg["looseness"]) * 100)))
        self.loose_scale.configure(command=self._on_looseness)
        self.loose_scale.pack(**pad)
        tk.Checkbutton(win, text="Suggest the next word (tap the boxes to write)", variable=self.predict_var,
                       command=self._on_predict, bg=BG, fg=TEXT, selectcolor=KEY,
                       activebackground=BG, activeforeground=TEXT).pack(**pad)
        tk.Checkbutton(win, text="Learn which words I use after which (kept on this computer)",
                       variable=self.learn_var, command=self._on_learn, bg=BG, fg=TEXT, selectcolor=KEY,
                       activebackground=BG, activeforeground=TEXT).pack(**pad)
        tk.Button(win, text="Forget everything it learned from my typing", command=self._forget_phrases).pack(
            fill="x", **pad)
        self.docs_scale = tk.Scale(win, from_=0.05, to=1.0, resolution=0.05, orient="horizontal",
                                   label="Google Docs check: pause between keys (seconds)",
                                   bg=BG, fg=TEXT, highlightthickness=0, troughcolor=KEY, length=260)
        self.docs_scale.set(self.s.docs_delay)
        self.docs_scale.configure(command=self._on_docs_delay)
        self.docs_scale.pack(**pad)
        tk.Checkbutton(win, text="Keep the cursor level: scroll the page as text grows", variable=self.typewriter_var,
                       command=self._on_typewriter, bg=BG, fg=TEXT, selectcolor=KEY,
                       activebackground=BG, activeforeground=TEXT).pack(**pad)
        self.cpl_scale = tk.Scale(win, from_=20, to=160, orient="horizontal",
                                  label="Characters that fit on one line of your document",
                                  bg=BG, fg=TEXT, highlightthickness=0, troughcolor=KEY, length=260)
        self.cpl_scale.set(self.s.chars_per_line)
        self.cpl_scale.configure(command=self._on_scroll_tuning)
        self.cpl_scale.pack(**pad)
        self.npl_scale = tk.Scale(win, from_=0.05, to=1.0, resolution=0.01, orient="horizontal",
                                  label="Mouse-wheel clicks per line of text",
                                  bg=BG, fg=TEXT, highlightthickness=0, troughcolor=KEY, length=260)
        self.npl_scale.set(self.s.notches_per_line)
        self.npl_scale.configure(command=self._on_scroll_tuning)
        self.npl_scale.pack(**pad)
        self.test_btn = tk.Button(win, text="Test: scroll 10 lines in 4 seconds (put the mouse over your document)",
                                  command=self._test_scroll, wraplength=280)
        self.test_btn.pack(fill="x", **pad)
        self._build_words(win, pad)
        tk.Checkbutton(win, text="Keep keyboard window on top", variable=self.top_var,
                       command=self._on_topmost, bg=BG, fg=TEXT, selectcolor=KEY,
                       activebackground=BG, activeforeground=TEXT).pack(**pad)
        self.pause_btn = tk.Button(win, command=self.toggle)
        self.pause_btn.pack(fill="x", **pad)
        self.set_status = tk.Label(bottom, anchor="w", bg=BG, fg=DIM, font=("monospace", 9), wraplength=300)
        self.set_status.pack(fill="x", **pad)
        tk.Button(bottom, text="Close (settings are saved)", command=self._close_settings).pack(fill="x", **pad)
        self._refresh_state()
        try:                                           # as tall as the content, but never taller than the screen
            top.update_idletasks()
            width = win.winfo_reqwidth() + scrollbar.winfo_reqwidth() + 4
            height = min(win.winfo_reqheight() + bottom.winfo_reqheight(), top.winfo_screenheight() - 120)
            top.geometry(f"{max(300, int(width))}x{max(300, int(height))}")
        except (tk.TclError, TypeError, ValueError):
            pass

    # ---- my words (personal dictionary) ---------------------------------------------------
    def _build_words(self, win, pad):
        tk.Label(win, text="My words: names and jargon you can swipe like any word",
                 bg=BG, fg=DIM, font=("sans", 9)).pack()
        frame = tk.Frame(win, bg=BG)
        frame.pack(fill="x", **pad)
        self.words_list = tk.Listbox(frame, height=5, bg=KEY, fg=TEXT, exportselection=False,
                                     highlightthickness=0)
        self.words_list.pack(side="left", fill="both", expand=True)
        bar = tk.Scrollbar(frame, command=self.words_list.yview)
        bar.pack(side="right", fill="y")
        self.words_list.configure(yscrollcommand=bar.set)
        row = tk.Frame(win, bg=BG)
        row.pack(fill="x", **pad)
        self.word_entry = tk.Entry(row)
        self.word_entry.pack(side="left", fill="x", expand=True)
        self.word_entry.bind("<Return>", lambda ev: self._add_word())
        tk.Button(row, text="Add", command=self._add_word).pack(side="left", padx=(4, 0))
        tk.Button(win, text="Remove selected word", command=self._remove_word).pack(fill="x", **pad)
        self._fill_words()

    def _fill_words(self):
        if getattr(self, "words_list", None) is None:
            return
        self.words_list.delete(0, "end")
        for w in lexicon.read_user_words():
            self.words_list.insert("end", w)

    def _add_word(self):
        raw = self.word_entry.get()
        word = lexicon.clean_user_word(raw)
        if not word:
            self.s.message = "error: a word is letters (and ') only, at least 2"
            return
        lexicon.add_user_word(word)
        self.s.reload_words()
        self.word_entry.delete(0, "end")
        self._words_mtime = self._mtime(lexicon.user_words_path())
        self._fill_words()
        self.s.message = f"learned: {word}"

    def _remove_word(self):
        for idx in reversed(list(self.words_list.curselection())):
            lexicon.remove_user_word(self.words_list.get(idx))
        self.s.reload_words()
        self._words_mtime = self._mtime(lexicon.user_words_path())
        self._fill_words()

    @staticmethod
    def _mtime(path):
        try:
            return os.stat(path).st_mtime
        except OSError:
            return 0.0

    def _check_words(self):
        """`swipepen words add ...` from a terminal: pick up changes to the words file."""
        m = self._mtime(lexicon.user_words_path())
        if m != self._words_mtime:
            self._words_mtime = m
            self.s.reload_words()
            self._fill_words()

    def _on_edge_speed(self, value):
        self.s.edge_speed = float(value)
        self.cfg["edge_speed"] = round(float(value), 2)
        self._schedule_save()

    def _on_autofix(self):
        self.s.autofix = bool(self.autofix_var.get())
        self._schedule_save()

    def _on_docs_delay(self, value):
        self.s.set_setting("docs_delay", round(float(value), 2))

    def _on_predict(self):
        self.s.set_setting("predict", bool(self.predict_var.get()))

    def _on_learn(self):
        self.s.set_setting("learn_typing", bool(self.learn_var.get()))

    def _forget_phrases(self):
        self.s.get_predictor().forget()
        self.s.message = "forgot learned phrases"

    def _on_looseness(self, value):
        v = float(value) / 100.0
        self.cfg["looseness"] = round(v, 2)
        decoder = getattr(self.s, "decoder", None)
        if hasattr(decoder, "set_looseness"):
            decoder.set_looseness(v)
        self._schedule_save()

    def _on_typewriter(self):
        self.s.set_typewriter(bool(self.typewriter_var.get()), self.s.chars_per_line, self.s.notches_per_line)
        self._schedule_save()

    def _on_scroll_tuning(self, _value=None):
        self.s.set_typewriter(bool(self.typewriter_var.get()), int(self.cpl_scale.get()),
                              float(self.npl_scale.get()))
        self._schedule_save()

    def _test_scroll(self):
        """Scroll exactly ten lines (by the current settings) so you can see whether the numbers are right."""
        notches = 10 * self.s.notches_per_line
        self.test_btn.configure(text="scrolling in 4 seconds - move the mouse over your document")
        def go():
            self.s.inj.scroll(notches)
            self.test_btn.configure(text="Did the page move 10 lines? Adjust the sliders, test again.")
        self.root.after(4000, go)

    def _on_session_setting(self, name, value):
        """A setting was changed from the pen's tools panel: reflect and save it."""
        if name == "autofix":
            self.autofix_var.set(bool(value))
        elif name == "typewriter":
            self.typewriter_var.set(bool(value))
        elif name == "predict":
            self.predict_var.set(bool(value))
        elif name == "learn_typing":
            self.learn_var.set(bool(value))
        self._schedule_save()

    def _mini_h(self) -> int:
        return max(40, int(MAP_W / self.area.aspect))

    def _mini_click(self, ev):
        self.area.set_center(ev.x / self.mini_w, ev.y / self.mini_h)
        self._schedule_save()

    def _on_size(self, value):
        if not getattr(self, "_ready", False):
            return
        self.area.set_size(float(value) / 100.0)
        self._schedule_save()

    def _on_key_aspect(self, value):
        ka = round(float(value), 2)
        if not getattr(self, "_ready", False) or abs(ka - self.ka) < 1e-9:
            return
        self.ka = ka
        self.cfg["key_aspect"] = ka
        self.area.key_aspect = ka
        self.area.set_size(self.area.size)        # re-clamp for the new shape
        decoder = getattr(self.s, "decoder", None)
        if hasattr(decoder, "set_ys"):
            decoder.set_ys(ka)
        extra = max(0, self.root.winfo_height() - self.canvas.winfo_height())
        w = self.root.winfo_width()
        self.root.minsize(MIN_W, int(MIN_W * CANVAS_H * ka / CANVAS_W))
        self.root.geometry(f"{w}x{int(w * CANVAS_H * ka / CANVAS_W) + extra}")
        self._relayout(self.W, int(self.canvas.winfo_height()) or self.H)
        self._schedule_save()

    def _on_rotate(self, label):
        deg = dict(ROTATIONS)[label]
        self.reader.set_rotate(deg)
        self.area.aspect = self.reader.aspect
        self.area.set_size(self.area.size)        # re-clamp for the new shape
        self.cfg["rotate"] = deg
        self.mini_h = self._mini_h()
        self.mini.configure(height=self.mini_h)
        self._cancel_stroke()
        self._schedule_save()

    def _on_follow(self):
        self.router.follow = bool(self.follow_var.get())
        self._schedule_save()

    def _on_topmost(self):
        self._apply_topmost()
        self._schedule_save()

    def _apply_topmost(self):
        try:
            self.root.attributes("-topmost", bool(self.top_var.get()))
        except tk.TclError:
            pass

    def _keep_on_top(self):
        """Re-assert 'always on top' now and then; some window managers drop it."""
        self._apply_topmost()
        self._check_words()
        self.root.after(1000, self._keep_on_top)

    # ---- settings file ------------------------------------------------------------
    def _schedule_save(self):
        if self._save_job is not None:
            self.root.after_cancel(self._save_job)
        self._save_job = self.root.after(400, self._save)

    def _save(self):
        self._save_job = None
        self.cfg.update(size=round(self.area.size, 3), cx=round(self.area.cx, 3),
                        cy=round(self.area.cy, 3), topmost=bool(self.top_var.get()),
                        follow=bool(self.follow_var.get()), key_aspect=round(self.ka, 2),
                        edge_speed=round(float(self.s.edge_speed), 2), autofix=bool(self.s.autofix),
                        typewriter=bool(self.s.typewriter), predict=bool(self.s.predict),
                        docs_menu_key=str(self.s.docs_menu_key), docs_delay=round(float(self.s.docs_delay), 2),
                        docs_auto=bool(self.s.docs_auto),
                        learn_typing=bool(self.s.learn_typing), chars_per_line=int(self.s.chars_per_line),
                        notches_per_line=round(float(self.s.notches_per_line), 2))
        save_config(self.cfg)

    # ---- plumbing ---------------------------------------------------------
    def _on_callback_error(self, exc, val, tb):
        """Errors inside window callbacks: keep running, but never lose them silently."""
        import traceback
        from .doctor import log_path, write_log
        text = "".join(traceback.format_exception(exc, val, tb))
        write_log(text)
        print(text)
        self.s.message = f"error (see {log_path()}): {val}"

    def run(self):
        self.root.mainloop()

    def close(self):
        self._save()
        if hasattr(self.s, "flush"):
            self.s.flush()
        if self.reader:
            self.reader.set_active(False)
        self.root.destroy()

    def _update(self):
        """Install the newest swipepen*.tar.gz from Downloads (restarts this window)."""
        import subprocess, sys
        subprocess.Popen([sys.executable, "-m", "swipepen", "update", "--window"], start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def request_quit(self):            # called from the SIGTERM handler
        self._quit_flag = True

    def request_command(self):         # called from the SIGHUP handler (`swipepen tidy` / `swipepen learn`)
        self._cmd_flag = True

    def request_toggle(self):          # called from the SIGUSR1 handler
        self._toggle_flag = True

    def _run_command(self):
        from .__main__ import CMD_FILE
        try:
            with open(CMD_FILE, encoding="utf-8") as fh:
                cmd = fh.read().strip()
            os.remove(CMD_FILE)
        except OSError:
            return
        if cmd == "tidy":
            self.s.tidy()
        elif cmd == "learn":
            self.s.learn_word()

    def _cancel_stroke(self):
        self.router.reset()
        self.s.cancel_stroke()
        self.s.hover_pos = None

    def toggle(self):
        if not self.reader:
            return
        self.active = not self.active
        self.reader.set_active(self.active)
        self._cancel_stroke()
        self._refresh_state()

    def _refresh_state(self):
        self.root.title("swipepen" if self.active or not self.reader else "swipepen (paused)")
        btn = getattr(self, "pause_btn", None)
        if btn is not None:
            if not self.reader:
                btn.configure(text="pen not in use (mouse test mode)", state="disabled")
            elif self.active:
                btn.configure(text="Pen is the swipe keyboard  (click to pause)")
            else:
                btn.configure(text="PAUSED - pen works as a normal tablet  (click to resume)")

    def _mouse(self, kind, ev):
        if self._grip:
            return
        x, y = (ev.x - self.ox) / self.S, (ev.y - self.oy) / (self.S * self.ka) + CANVAS_Y0
        if kind == "down":
            self.s.pen_down(x, y)
        elif kind == "move":
            self.s.pen_move(x, y)
        elif kind == "up":
            self.s.pen_up()
        else:
            self.s.hover(x, y)

    def _poll(self):
        if getattr(self, "_quit_flag", False):
            self.close()
            return
        if self._toggle_flag:
            self._toggle_flag = False
            self.toggle()
        if self._settings_flag:
            self._settings_flag = False
            self.open_settings()
        if self._cmd_flag:
            self._cmd_flag = False
            self._run_command()
        if self.reader:
            while True:
                try:
                    ev = self.reader.events.get_nowait()
                except queue.Empty:
                    break
                if ev[0] == "toggle":
                    self.toggle()
                elif ev[0] == "tidy":
                    if self.active:
                        self.s.tidy()
                elif self.active:
                    self.router.handle(ev)
        self.s.tick()
        self.root.after(8, self._poll)

    # ---- drawing ------------------------------------------------------------
    def _px(self, x):
        return self.ox + x * self.S

    def _py(self, y):
        return self.oy + (y - CANVAS_Y0) * self.S * self.ka

    def _rect(self, x0, y0, x1, y1, **kw):
        kw.setdefault("tags", "static")
        return self.canvas.create_rectangle(self._px(x0), self._py(y0), self._px(x1), self._py(y1), **kw)

    def _text(self, x, y, text, size, **kw):
        kw.setdefault("tags", "static")
        return self.canvas.create_text(self._px(x), self._py(y), text=text,
                                       font=("sans", -max(6, int(self.S * size))), **kw)

    def _draw_static(self):
        layer = self.s.layer
        self._drawn_layer = layer
        w = CANVAS_W / STRIP_CELLS
        for i in range(STRIP_CELLS):
            self._rect(i * w + 0.03, -0.97, (i + 1) * w - 0.03, -0.03, fill=BG, outline=DIM)
        centers = KEY_CENTER if layer == "letters" else SYM_CENTER[layer]
        for ch, (cx, cy) in centers.items():
            self._rect(cx - 0.47, cy - 0.47, cx + 0.47, cy + 0.47, fill=KEY, outline="")
            self._text(cx, cy, ch, 0.38, fill=TEXT)
        for name, (x0, x1, y0, y1) in FUNCTION_KEYS.items():
            self._rect(x0 + 0.03, y0 + 0.03, x1 - 0.03, y1 - 0.03, fill=KEY_FN, outline="")
            self._text((x0 + x1) / 2, (y0 + y1) / 2, function_label(name, layer), 0.26, fill=DIM)
        W, H = self.W, self.H                      # the resize grip, very subtle
        self.canvas.create_polygon(W - GRIP, H, W, H, W, H - GRIP, fill="#4a4a56", outline="",
                                   tags=("static", "grip"))

    def _draw_mini(self):
        m, W, H = self.mini, self.mini_w, self.mini_h
        m.delete("all")
        u0, v0, u1, v1 = self.area.rect()
        m.create_rectangle(u0 * W, v0 * H, u1 * W, v1 * H, fill="#2f4f86", outline="#6a9cf5")
        m.create_text((u0 + u1) / 2 * W, (v0 + v1) / 2 * H, text="keyboard", fill=TEXT,
                      font=("sans", -11))
        if self.router.pen_uv:
            u, v = self.router.pen_uv
            r = 4
            m.create_oval(u * W - r, v * H - r, u * W + r, v * H + r,
                          fill="#ff5c5c" if self.s.pen_down_now else "", outline="#ff5c5c", width=2)

    def _draw_panel(self, panel):
        c = self.canvas
        self._rect(-0.2, CANVAS_Y0 - 0.2, CANVAS_W + 0.2, CANVAS_H + CANVAS_Y0 + 0.2, fill=BG, outline="", tags="dyn")
        fills = {"item": KEY, "hi": KEY_HI, "on": "#2f6f4f", "dim": KEY_FN, "head": BG, "text": BG, "title": KEY_FN}
        for b in panel.layout():
            tappable = b.action is not None
            fill = fills.get(b.style, KEY)
            if b.kind in ("tab", "prev", "close", "next"):
                fill = KEY_HI if b.style == "hi" else KEY_FN if not tappable or b.kind == "tab" else KEY
            if b.kind == "cell" and b.style in ("text", "head", "dim") and not tappable:
                fill = BG
            self._rect(b.x0, b.y0, b.x1, b.y1, fill=fill, outline="", tags="dyn")
            colour = {"head": "#9ad0ff", "dim": DIM, "text": TEXT, "title": "#ffd479"}.get(b.style, TEXT if tappable else DIM)
            if b.kind != "cell":
                colour = TEXT if tappable or b.style == "hi" else "#55555f"
            width_units = b.x1 - b.x0 - 0.2
            size = max(0.14, min(0.3, width_units / (0.56 * max(1, len(b.text)))))
            left = b.kind == "cell" and not tappable
            x = b.x0 + 0.12 if left else (b.x0 + b.x1) / 2
            self._text(x, (b.y0 + b.y1) / 2, b.text, size, fill=colour, anchor="w" if left else "center",
                       tags="dyn")

    def _redraw(self):
        c, S, s = self.canvas, self.S, self.s
        c.delete("dyn")
        if s.layer != self._drawn_layer:
            c.delete("static")
            self._draw_static()
        w = CANVAS_W / STRIP_CELLS
        cands = s.last.cands if s.last else []
        if s.panel:
            self._draw_panel(s.panel)
        else:
            st = s.strip()
            for i, label in enumerate(st["cells"]):
                if not label:
                    continue
                if st["chosen"] == i:
                    self._rect(i * w + 0.03, -0.97, (i + 1) * w - 0.03, -0.03, fill=KEY_HI, outline="", tags="dyn")
                if st["mode"] == "tools":
                    colour = "#55555f" if i in st["dim"] else DIM
                    size = 0.3
                else:
                    colour = DIM if label == "⋯" else TEXT
                    size = max(0.2, min(0.34, (w - 0.3) / (0.56 * max(1, len(label)))))
                self._text(i * w + w / 2, -0.5, label, size, fill=colour, tags="dyn")
            if s.shift or s.caps:
                x0, x1, y0, y1 = FUNCTION_KEYS["shift"]
                self._rect(x0 + 0.03, y0 + 0.03, x1 - 0.03, y1 - 0.03, fill=KEY_HI, outline="", tags="dyn")
                self._text((x0 + x1) / 2, (y0 + y1) / 2, "CAPS" if s.caps else "SHIFT", 0.26, fill=TEXT, tags="dyn")
        if len(s.trail) > 1:
            flat = []
            for x, y in s.trail:
                flat += [self._px(x), self._py(y)]
            c.create_line(*flat, fill="#ffb454", width=max(2, int(S * 0.07)), smooth=True, tags="dyn")
        if s.hover_pos:
            x, y = s.hover_pos
            r = max(3, S * (0.1 if s.pen_down_now else 0.07))
            c.create_oval(self._px(x) - r, self._py(y) - r, self._px(x) + r, self._py(y) + r,
                          fill="#ff5c5c" if s.pen_down_now else "", outline="#ff5c5c", width=2, tags="dyn")

        # short messages flash in the suggestion strip instead of a status line
        if s.message != self._last_msg:
            self._last_msg, self._flash_until = s.message, time.time() + 1.6
        if time.time() < self._flash_until and not s.panel:
            if s.message.startswith(("no match", "error")):
                self._text(CANVAS_W / 2, -0.5, s.message[:40], 0.28, fill="#ff8a8a", tags="dyn")
            elif s.message.startswith(("erase", "cursor", "tidy", "learn", "fixed", "already", "undo", "replaced",
                                       "checked", "dictionary", "check", "replace")):
                self._text(CANVAS_W / 2, -0.5, s.message[:40], 0.28, fill="#9ad0ff", tags="dyn")

        if self.reader and not self.active:        # paused: dim the keyboard
            c.create_rectangle(0, 0, self.W, self.H, fill="#000000", stipple="gray50",
                               outline="", tags="dyn")
            self._text(CANVAS_W / 2, 1.5, "paused", 0.8, fill=TEXT, tags="dyn")
        elif self.active and self.dry is None and self.root.focus_displayof() is not None:
            c.create_rectangle(2, 2, self.W - 2, self.H - 2, outline="#ff5c5c", width=3, tags="dyn")

        if self.status is not None and self.dry is not None:
            self.status.configure(text=f"{s.message}   |   text: {self.dry.view()!r}")
        if self._settings_open:
            if self.reader:
                self._draw_mini()
            text = s.message
            if self.active and self.reader and self.router.pen_uv and not s.hover_pos and not s.pen_down_now:
                text = "pen is outside the keyboard area (turn on 'follow', or move onto the blue box)"
            self.set_status.configure(text=text)
        self.root.after(20, self._redraw)
