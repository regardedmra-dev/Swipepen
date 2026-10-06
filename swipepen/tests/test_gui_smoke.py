"""Smoke test of gui.App with a mocked tkinter: catches typos and wiring errors
(it cannot check how the window looks)."""
import os, queue, random, sys, tempfile, types
from unittest import mock

os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
fake_tk = mock.MagicMock()
fake_tk.TclError = type("TclError", (Exception,), {})
sys.modules["tkinter"] = fake_tk

from swipepen.area import config_path, load_config
from swipepen.engine import Decoder
from swipepen.gui import App, ROTATIONS
from swipepen.inject import DryRunInjector
from swipepen.lexicon import load_lexicon
from swipepen.session import Session
from swipepen.simulate import generate_swipe

def check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else "  " + str(detail)))
    assert ok

class FakeReader:
    def __init__(self):
        self.events = queue.Queue(); self.active = False; self.rotate = 0; self._base = 1.6; self.aspect = 1.6
    def set_active(self, on): self.active = on
    def set_rotate(self, r):
        self.rotate = r; self.aspect = 1 / self._base if r in (90, 270) else self._base

dec = Decoder(load_lexicon("en", force_fallback=True, verbose=False))
inj = DryRunInjector()
sess = Session(dec, inj)
rd = FakeReader()
cfg0 = load_config(); cfg0["key_aspect"] = 1.0
app = App(sess, rd, dry=None, mouse=False, cfg=cfg0)
check("window builds with a pen attached", True)
check("pen is grabbed at start", rd.active is True)
check("settings are hidden at start (clean keyboard window)", app._settings is None and not app._settings_open)
check("keep-on-top was requested", any(c.args[:1] == ("-topmost",) for c in app.root.attributes.call_args_list))

app._redraw(); app._keep_on_top(); app._poll()
check("redraw / poll / keep-on-top run without errors", True)

# --- resizing: the keyboard scales with the window ---------------------------------------
app._on_resize(types.SimpleNamespace(width=150, height=75))
check("window resized to 150x75 -> 15 px per key", abs(app.S - 15.0) < 1e-9, app.S)
app._on_resize(types.SimpleNamespace(width=300, height=100))
check("a wider-than-tall window keeps the keyboard shape and centres it",
      abs(app.S - 20.0) < 1e-9 and abs(app.ox - 50.0) < 1e-9 and app.oy == 0, (app.S, app.ox, app.oy))
app._redraw()
app.root.winfo_width.return_value = 200
app.root.winfo_height.return_value = 100
app.canvas.winfo_height.return_value = 100
app._grip_press(types.SimpleNamespace(x_root=500, y_root=400))
app._grip_drag(types.SimpleNamespace(x_root=450, y_root=380))     # drag left/up = smaller
geo = app.root.geometry.call_args_list[-1].args[0]
w, h = (int(v) for v in geo.split("x"))
check("dragging the corner grip shrinks the window and keeps the 2:1 shape", w == 150 and h == 75, geo)
app._grip_press(types.SimpleNamespace(x_root=500, y_root=400))
app._grip_drag(types.SimpleNamespace(x_root=0, y_root=0))
w, h = (int(v) for v in app.root.geometry.call_args_list[-1].args[0].split("x"))
check("the window cannot be dragged smaller than the minimum", w == 100 and h == 50, (w, h))
app._grip_release(None)
app._on_resize(types.SimpleNamespace(width=w, height=h))          # real Tk sends this after the resize
app._save()
check("window size is remembered", load_config()["scale"] == 10, load_config()["scale"])
app._on_resize(types.SimpleNamespace(width=5, height=5))          # garbage sizes during startup are ignored
check("tiny bogus resize events are ignored", abs(app.S - 20.0) < 1e-9 or app.S >= 4)

# right-click menu
app._popup(types.SimpleNamespace(x_root=10, y_root=10))
check("right-click menu opens", app.menu.tk_popup.called)

# --- settings window --------------------------------------------------------------------------
app.open_settings()
check("settings open on request", app._settings is not None and app._settings_open)
app._redraw()
app._on_size("26"); app._mini_click(types.SimpleNamespace(x=20, y=10)); app._save()
cfg = load_config()
check("size 26% is saved", abs(cfg["size"] - 0.26) < 1e-6, cfg)
check("config file exists", os.path.exists(config_path()))
# --- key shape (squished, tall keys like Gboard) -------------------------------------------------
app._on_key_aspect("1.5")
check("key shape 1.5 is applied to the window and the tablet area", app.ka == 1.5 and app.area.key_aspect == 1.5)
check("the decoder is told about the tall keys", dec.ys == 1.5, dec.ys)
app._on_resize(types.SimpleNamespace(width=300, height=225))
check("tall keys: 300x225 window -> 30 px per key width", abs(app.S - 30.0) < 1e-9 and abs(app.oy) < 1e-9, (app.S, app.oy))
check("a key is 1.5x taller than wide on screen", abs((app._py(1.0) - app._py(0.0)) - 45.0) < 1e-9)
app._save()
check("key shape is remembered", abs(load_config()["key_aspect"] - 1.5) < 1e-9)
app._on_key_aspect("1.0"); app._on_key_aspect("1.5")

# --- cursor speed, typo fixing, my words ----------------------------------------------------------------
app._on_edge_speed("2.0"); app._save()
check("cursor speed slider reaches the session", sess.edge_speed == 2.0)
check("cursor speed is remembered", abs(load_config()["edge_speed"] - 2.0) < 1e-9, load_config())
app.autofix_var.get.return_value = False
app._on_autofix(); app._save()
check("fix-typos switch reaches the session and is remembered", sess.autofix is False and load_config()["autofix"] is False)
app.autofix_var.get.return_value = True
app._on_autofix()
from swipepen import lexicon
app.word_entry.get.return_value = "Valentina"
app._add_word()
check("adding a word in settings stores it", "Valentina" in lexicon.read_user_words())
check("... and the decoder knows it at once", dec.logp("valentina") is not None)
app.word_entry.get.return_value = "x1"
app._add_word()
check("an invalid word is refused with a message", sess.message.startswith("error"))
app.words_list.curselection.return_value = (0,)
app.words_list.get.return_value = "Valentina"
app._remove_word()
check("removing a word in settings", "Valentina" not in lexicon.read_user_words())
lexicon.add_user_word("Nico")                      # like `swipepen words add Nico` from a terminal
app._check_words()
check("a word added from a terminal is picked up", dec.logp("nico") is not None)
lexicon.remove_user_word("Nico"); app._check_words()
rd.events.put(("tidy",)); inj.buffer = "i am"; inj.pos = 4; app._poll()
check("the pen's tidy button fixes the text", inj.buffer == "I am", inj.buffer)
inj.buffer = ""; inj.pos = 0

label = [l for l, d in ROTATIONS if d == 180][0]
app._on_rotate(label); app._save()
check("left-handed switches the pen to 180 degrees", rd.rotate == 180)
check("left-handed is remembered in the config", load_config()["rotate"] == 180)
app.follow_var.get.return_value = False
app._on_follow(); app._save()
check("follow can be switched off and is remembered", app.router.follow is False and load_config()["follow"] is False)
app.follow_var.get.return_value = True
app._on_follow()
check("follow can be switched back on", app.router.follow is True)
app._settings_flag = True; app._poll()
check("'swipepen settings' (signal) opens the settings window", app._settings_open)
app._close_settings()
check("closing the settings hides them", not app._settings_open)

# --- events flow through the router into the session --------------------------------------------
app.area.set_size(0.3)
u0, v0, _, _ = app.area.rect()
def to_tab(x, y): return u0 + (x / 10) * app.area.w, v0 + ((y + 1) / 5) * app.area.h
pts = [to_tab(x, y) for x, y in generate_swipe("hello", random.Random(2), sigma=0.1, offset=0.05, ka=app.ka)]
rd.events.put(("hover", *pts[0])); rd.events.put(("down", *pts[0]))
for p in pts[1:]: rd.events.put(("move", *p))
rd.events.put(("up",))
app._poll()
check("a swipe delivered through the reader queue types the word", inj.buffer == "hello ", inj.buffer)

# follow mode through the window: hover far away, the area follows
rd.events.put(("leave",)); rd.events.put(("hover", 0.9, 0.9)); app._poll()
u0, v0, u1, v1 = app.area.rect()
check("hovering somewhere new moves the keyboard box to the pen", u0 <= 0.9 <= u1 and v0 <= 0.9 <= v1, app.area.rect())

# paused
app.toggle()
check("toggle releases the pen", rd.active is False)
app._redraw()
check("paused keyboard draws (dimmed) without errors", True)
rd.events.put(("down", 0.5, 0.5)); app._poll()
check("events are ignored while paused", sess.pen_down_now is False)
app.toggle(); app.close()
check("close works", True)

# --- mouse-only dry-run test mode ----------------------------------------------------------------
dry = DryRunInjector()
app2 = App(Session(dec, dry), None, dry=dry, mouse=True, cfg=load_config())
app2._redraw()
check("mouse test mode builds and draws", True)
a2 = app2
a2._on_resize(types.SimpleNamespace(width=500, height=250))      # 50 px per key, no offset
def mouse_stroke(pts_units):
    px = [((x * a2.S) + a2.ox, ((y + 1) * a2.S * a2.ka) + a2.oy) for x, y in pts_units]
    a2._mouse("down", types.SimpleNamespace(x=px[0][0], y=px[0][1]))
    for x, y in px[1:]: a2._mouse("move", types.SimpleNamespace(x=x, y=y))
    a2._mouse("up", types.SimpleNamespace(x=px[-1][0], y=px[-1][1]))
mouse_stroke(generate_swipe("write", random.Random(4), sigma=0.1, offset=0.05, ka=a2.ka))
check("swiping with the mouse in test mode types the word (also when the window is resized)", dry.buffer == "write ", dry.buffer)
# --- stage 2: layers, caps, panels, typewriter settings ---------------------------------------------------
dry3 = DryRunInjector(); sess3 = Session(dec, dry3)
app3 = App(sess3, None, dry=dry3, mouse=True, cfg=load_config())
app3._redraw()
sess3.layer = "sym1"; app3._redraw()
check("changing layer redraws the keys", app3._drawn_layer == "sym1")
sess3.layer = "letters"; sess3.caps = True; app3._redraw()
check("caps lock draws", True)
sess3.caps = False
sess3.open_tools(); app3._redraw()
check("tools panel draws", sess3.panel is not None)
sess3.close_panel()
dry3.buffer, dry3.pos = "I am very happy ", 16
sess3._dictionary = None
sess3.open_dictionary(); app3._redraw(); sess3.wait_jobs(); app3._redraw()
check("dictionary panel draws before and after the lookup", sess3.panel is not None)
sess3.close_panel()
app3.open_settings()
check("settings window has a scrollable area", getattr(app3, "_settings_canvas", None) is not None)
check("settings window builds with the typewriter controls", hasattr(app3, "cpl_scale") and hasattr(app3, "test_btn"))
app3.typewriter_var.get.return_value = True
app3._on_typewriter()
check("typewriter checkbox turns the page-scroll on", sess3.typewriter and sess3.inj.scroller is not None)
app3.cpl_scale, app3.npl_scale = mock.MagicMock(), mock.MagicMock()
app3.cpl_scale.get.return_value = 60; app3.npl_scale.get.return_value = 0.4
app3._on_scroll_tuning()
check("sliders tune it", (sess3.chars_per_line, sess3.notches_per_line) == (60, 0.4), (sess3.chars_per_line, sess3.notches_per_line))
app3._save()
c = load_config()
check("typewriter settings are remembered", (c["typewriter"], c["chars_per_line"], c["notches_per_line"]) == (True, 60, 0.4), c)
sess3.set_setting("typewriter", False)
check("a toggle in the tools panel updates the checkbox", True)
app3._test_scroll()
check("calibration button schedules a test scroll", app3.root.after.called)
# --- stage 3: prediction strip, looseness ------------------------------------------------------------------
sess3.predict = True
dry3.buffer, dry3.pos = "", 0
sess3.inj.tail = "thank "
app3._redraw()
check("the next-word strip draws", sess3.strip()["mode"] == "predict" and sess3.strip()["cells"][0] == "you")
sess3.inj.tail = "pl"; sess3.inj.version += 1
app3._redraw()
check("the completion strip draws", sess3.strip()["mode"] == "complete")
app3._on_looseness(80)
check("looseness slider reaches the decoder and the config", abs(dec.looseness - 0.8) < 1e-9 and app3.cfg["looseness"] == 0.8)
app3.predict_var.get.return_value = False
app3._on_predict()
check("next-word checkbox switches suggestions off", sess3.predict is False)
sess3.get_predictor().path = None
app3._forget_phrases()
check("forget button clears what was learned", sess3.message == "forgot learned phrases and fixes")
app3._save()
check("looseness / prediction settings are remembered", load_config()["looseness"] == 0.8 and load_config()["predict"] is False)
app3._on_docs_delay(0.4)
check("Docs pause slider reaches the session", abs(sess3.docs_delay - 0.4) < 1e-9)
app3._save()
check("Docs settings are remembered", load_config()["docs_delay"] == 0.4 and load_config()["docs_menu_key"] == "ctrl+shift+\\")
# --- stage 4 (0.7): swipe trail, key highlights, break reminders, pressure ------------------------------------------
import time as _time
for name in ("trail_var", "hilite_var", "press_var"):         # tk is mocked: give each switch its own value
    setattr(app3, name, mock.MagicMock()); getattr(app3, name).get.return_value = True
app3._on_resize(types.SimpleNamespace(width=500, height=250))      # 50 px per key
app3.s.layer = "letters"; app3.s.panel = None
c3 = app3.canvas
def fills(method): return [call.kwargs.get("fill") for call in getattr(c3, method).call_args_list]
def px(x, y): return types.SimpleNamespace(x=x * app3.S + app3.ox, y=(y + 1) * app3.S * app3.ka + app3.oy)

c3.reset_mock()
app3._mouse("hover", px(6.0, 1.5)); app3._redraw()
check("hovering over a key lights it (and redraws its label)",
      "#5b93e6" in fills("create_rectangle") and any(call.kwargs.get("text") == "h" for call in c3.create_text.call_args_list))

app3._mouse("down", px(1.0, 1.5))
for x in (2.0, 3.0, 4.0, 5.0, 6.0): app3._mouse("move", px(x, 1.5))
c3.reset_mock(); app3._redraw()
lines = c3.create_line.call_args_list
check("a stroke in progress draws a trail made of several pieces", len(lines) >= 2, len(lines))
check("older pieces are dimmer than the newest", len({call.kwargs["fill"] for call in lines}) >= 2 and lines[-1].kwargs["fill"] == "#ffb454", [call.kwargs["fill"] for call in lines])
check("the trail pieces are smooth and rounded", all(call.kwargs.get("smooth") and call.kwargs.get("capstyle") == "round" for call in lines))
check("keys passed over are tinted", "#2f4f86" in fills("create_rectangle"), set(fills("create_rectangle")))
check("only a few canvas items for the trail (cheap to redraw)", len(lines) <= 10)

app3._mouse("up", px(6.0, 1.5))
c3.reset_mock(); app3._redraw()
check("after pen-up the finished path lingers and fades (ghost)", len(c3.create_line.call_args_list) >= 1 and app3.fx.ghost is not None)
app3.fx.ghost = (app3.fx.ghost[0], _time.time() - 0.3)             # part-way through the fade
c3.reset_mock(); app3._redraw()
check("...getting dimmer as it fades", 0 < len(c3.create_line.call_args_list) and c3.create_line.call_args_list[-1].kwargs["fill"] != "#ffb454", [call.kwargs["fill"] for call in c3.create_line.call_args_list])
app3.fx.ghost = (app3.fx.ghost[0], _time.time() - 5)
c3.reset_mock(); app3._redraw()
check("...and is gone after a moment", len(c3.create_line.call_args_list) == 0)

app3.trail_var.get.return_value = False
app3._mouse("down", px(1.0, 1.5)); app3._mouse("move", px(3.0, 1.5)); app3._mouse("move", px(5.0, 1.5))
c3.reset_mock(); app3._redraw()
check("trail switched off: no trail drawn", len(c3.create_line.call_args_list) == 0)
app3._mouse("up", px(5.0, 1.5))
app3.trail_var.get.return_value = True

app3.hilite_var.get.return_value = False
c3.reset_mock(); app3._mouse("hover", px(6.0, 1.5)); app3._redraw()
check("highlights switched off: nothing is lit", "#5b93e6" not in fills("create_rectangle") and "#2f4f86" not in fills("create_rectangle"))
app3.hilite_var.get.return_value = True
app3._on_hilite()
check("the highlight switch reaches the tracker", app3.fx.track_keys is True)

# panels: the box under the pen is lit
app3.s.open_tools(); c3.reset_mock()
b = next(b for b in app3.s.panel.layout() if b.text.startswith("Dictionary"))
app3._mouse("hover", px((b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2)); app3._redraw()
check("a tappable panel box under the pen is lit", fills("create_rectangle").count("#5b93e6") == 1, fills("create_rectangle").count("#5b93e6"))
app3.s.close_panel()

# pressure colours the pen cursor
app3.s.pressure.enabled, app3.s.pressure.limit = True, 0.6
app3._mouse("down", px(5.0, 1.5)); app3.s.set_pressure(0.9)
c3.reset_mock(); app3._redraw()
oval = c3.create_oval.call_args_list[-1].kwargs
check("pressing hard turns the pen cursor red", oval["outline"] == "#ff4040" and oval["fill"] == "#ff4040", oval)
app3.s.pressure.abandon(); app3.s.set_pressure(0.12)
c3.reset_mock(); app3._redraw()
oval = c3.create_oval.call_args_list[-1].kwargs
check("a light touch keeps it pale", oval["outline"] not in ("#ff4040", "#ff5c5c") and oval["outline"].startswith("#ff"), oval)
app3.s.pressure.enabled = False
c3.reset_mock(); app3._redraw()
check("pressure hint off: the cursor stays the normal red", c3.create_oval.call_args_list[-1].kwargs["outline"] == "#ff5c5c")
app3.s.pressure.enabled = True
app3._mouse("up", px(5.0, 1.5))

# the "lighter touch" hint
app3.s.show_hint("lighter touch is enough"); c3.reset_mock(); app3._redraw()
check("the hint is written over the strip", any(call.kwargs.get("text") == "lighter touch is enough" for call in c3.create_text.call_args_list))
app3.s.hint_until = 0; c3.reset_mock(); app3._redraw()
check("...and goes away", not any(call.kwargs.get("text") == "lighter touch is enough" for call in c3.create_text.call_args_list))

# settings: break reminders, pressure, trail
app3.open_settings()
check("settings have the new controls", all(hasattr(app3, a) for a in ("break_scale", "plimit_scale", "well_label")))
app3._on_break(45); app3._on_plimit(70)
app3.press_var.get.return_value = False; app3._on_press()
app3.trail_var.get.return_value = False; app3._on_trail()
app3.hilite_var.get.return_value = False; app3._on_hilite()
app3._save(); cfg = load_config()
check("break interval reaches the session and the config file", sess3.well.break_minutes == 45 and cfg["break_minutes"] == 45, cfg["break_minutes"])
check("pressure level reaches the session and the config file", abs(sess3.pressure.limit - 0.7) < 1e-9 and abs(cfg["pressure_limit"] - 0.7) < 1e-9)
check("the pressure hint switch is remembered", sess3.pressure.enabled is False and cfg["pressure_hint"] is False)
check("trail and highlight switches are remembered", cfg["show_trail"] is False and cfg["highlight_keys"] is False)
check("switching the trail off clears what was on screen", app3.fx.pts == [] and app3.fx.ghost is None)
app3.trail_var.get.return_value = True; app3.hilite_var.get.return_value = True; app3.press_var.get.return_value = True
app3._on_trail(); app3._on_hilite(); app3._on_press()

# a change made in the tools panel moves the slider (without feeding back)
app3.break_scale.set.reset_mock()
sess3.set_setting("break_minutes", 0)
check("a setting changed from the pen's tools panel moves the slider", app3.break_scale.set.call_args.args == (0,), app3.break_scale.set.call_args)
check("...without a feedback loop", app3._syncing is False and sess3.well.break_minutes == 0)
app3._on_break(30)
check("the slider works again afterwards", sess3.well.break_minutes == 30)

# the settings window shows the stroke count
app3.well_label.configure.reset_mock(); app3._well_text = None
app3._redraw()
check("the settings window shows today's strokes", any("Strokes today" in str(call.kwargs.get("text", "")) for call in app3.well_label.configure.call_args_list))
sess3.well.stroke(); sess3.well.stroke()
app3._redraw()
check("...and the count follows", f"Strokes today: {sess3.well.today_strokes}" in app3._well_text, app3._well_text)
app3._reset_strokes()
check("the reset button clears today's count", sess3.well.today_strokes == 0 and sess3.message == "stroke count reset")

# a break reminder is drawn like any panel
sess3.well.set_break_minutes(1); sess3.well.active_s = 90; sess3.well.last_t = sess3.clock() - 5
sess3.tick(); app3._redraw()
check("a due break opens its panel in the window", getattr(sess3.panel, "is_break", False))
sess3.close_panel()

# the usage file is written next to the config, with counts only
app3.s.flush()
usage = os.path.join(os.path.dirname(config_path()), "usage.json")
check("the daily counts are saved when the window closes", os.path.exists(usage) and "days" in open(usage).read())
check("...and only counts (no text, no times of day)", set(__import__("json").load(open(usage))) == {"days"})
app3.close()
check("closing saves what was learned", True)
print("\nAll GUI smoke tests passed.")
