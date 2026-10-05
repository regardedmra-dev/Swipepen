"""Setup check and message dialogs.

`swipepen doctor` tells you exactly what is missing. The same report is shown
in a popup when swipepen fails to start from the application menu (where there
is no terminal to print errors into).
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
import tempfile


def state_dir() -> str:
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    path = os.path.join(base, "swipepen")
    os.makedirs(path, exist_ok=True)
    return path


def log_path() -> str:
    return os.path.join(state_dir(), "swipepen.log")


def write_log(text: str):
    try:
        with open(log_path(), "w", encoding="utf-8") as fh:
            fh.write(text)
    except OSError:
        pass


PROC_DEVICES = "/proc/bus/input/devices"   # world-readable list of every input device
TABLET_WORDS = ("wacom", "tablet", "bamboo", "intuos", "cintiq", "huion", "xp-pen", "gaomon", "ugee")


def tablets_in_proc():
    """Tablet-like input devices the kernel knows about: [(name, '/dev/input/eventN')].

    Unlike /dev/input itself, /proc/bus/input/devices can be read by anyone, so this
    sees the tablet even when its device node is not readable by you.
    """
    found = []
    try:
        with open(PROC_DEVICES, encoding="utf-8", errors="ignore") as fh:
            blocks = fh.read().split("\n\n")
    except OSError:
        return found
    import re
    for block in blocks:
        m_name = re.search(r'^N: Name="(.*)"', block, re.M)
        m_ev = re.search(r"^H: Handlers=.*\b(event\d+)\b", block, re.M)
        if not (m_name and m_ev):
            continue
        name = m_name.group(1)
        low = name.lower()
        if any(w in low for w in TABLET_WORDS) or low.endswith(" pen"):
            found.append((name, "/dev/input/" + m_ev.group(1)))
    return found


def pen_nodes_in_proc():
    """Like tablets_in_proc but only the pen (not the Pad buttons or Finger touch)."""
    pens = [t for t in tablets_in_proc()
            if not any(w in t[0].lower() for w in ("pad", "finger", "touch"))]
    return pens or tablets_in_proc()


def tablet_access_problem() -> bool:
    """True when the system has a tablet but none of its pen nodes is readable by us."""
    pens = pen_nodes_in_proc()
    return bool(pens) and not any(os.access(p, os.R_OK) for _, p in pens)


def run_checks():
    """Returns a list of (name, ok, detail, fix)."""
    out = []

    def add(name, ok, detail="", fix=""):
        out.append((name, ok, detail, fix))

    evdev = None
    try:
        import evdev  # noqa: F811
        add("python-evdev installed", True)
    except ImportError:
        add("python-evdev installed", False, "", "sudo dnf install python3-evdev")

    try:
        import tkinter  # noqa: F401
        add("tkinter installed (preview window)", True)
    except ImportError:
        add("tkinter installed (preview window)", False, "", "sudo dnf install python3-tkinter")

    has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    add("graphical session found", has_display, "" if has_display else "no DISPLAY / WAYLAND_DISPLAY",
        "run this from inside your desktop session")

    uinput = "/dev/uinput"
    if not os.path.exists(uinput):
        add("virtual keyboard (/dev/uinput)", False, "device does not exist",
            "sudo modprobe uinput")
    elif not os.access(uinput, os.W_OK):
        add("virtual keyboard (/dev/uinput)", False, "exists but you cannot write to it",
            "log out and back in; if it persists: sudo usermod -aG input $USER and log in again")
    else:
        add("virtual keyboard (/dev/uinput)", True)

    from .inject import Clipboard
    clip = Clipboard()
    add("clipboard tool (for 'tidy' and '+ word')", clip.kind is not None,
        f"{clip.kind}" if clip.kind else "optional: without it swipepen cannot read your document",
        "sudo dnf install wl-clipboard xclip")

    from .lookup import find_wordnet
    wn = find_wordnet()
    add("dictionary for synonyms (WordNet)", wn is not None,
        wn if wn else "optional: without it the dictionary needs the internet",
        "sudo dnf install wordnet")

    all_events = sorted(glob.glob("/dev/input/event*"))
    readable = [p for p in all_events if os.access(p, os.R_OK)]
    if not all_events:
        add("input devices visible", False, "no /dev/input/event* at all", "")
    elif not readable:
        add("input devices readable", False,
            f"{len(all_events)} devices, none readable by you",
            "sudo usermod -aG input $USER   then log out and back in")
    else:
        add("input devices readable", True, f"{len(readable)} of {len(all_events)}")

    seen = pen_nodes_in_proc()
    if not seen:
        add("pen tablet detected", False, "the system sees no tablet at all",
            "plug the tablet in (check with `lsusb`); on a laptop try another USB port")
    elif tablet_access_problem():
        names = "; ".join(f"{n} ({p})" for n, p in seen)
        add("pen tablet detected", False,
            f"the system sees your tablet [{names}] but you are not allowed to read it",
            "run ./install.sh again from the swipepen folder (it fixes this); if it still fails: "
            "sudo usermod -aG input $USER   then log out and back in")
    elif evdev is not None:
        try:
            from .pen import list_pen_candidates
            pens = list_pen_candidates()
            if pens:
                add("pen tablet detected", True, "; ".join(f"{d.name} ({d.path})" for d in pens))
            else:
                add("pen tablet detected", False,
                    "readable tablet found but it does not report pen events",
                    "tell me the output of `swipepen devices`, or try: swipepen run --device /dev/input/eventN")
        except Exception as exc:  # pragma: no cover
            add("pen tablet detected", False, repr(exc), "")

    try:
        import wordfreq  # noqa: F401
        add("word frequencies (wordfreq)", True)
    except ImportError:
        add("word frequencies (wordfreq)", False, "optional; suggestions are weaker without it",
            "~/.local/share/swipepen/venv/bin/pip install wordfreq")
    return out


def format_report(results) -> str:
    lines = []
    for name, ok, detail, fix in results:
        lines.append(f"[ OK ] {name}" + (f" - {detail}" if detail else ""))
        if not ok:
            lines[-1] = f"[FAIL] {name}" + (f" - {detail}" if detail else "")
            if fix:
                lines.append(f"       fix: {fix}")
    return "\n".join(lines)


def show_dialog(title: str, text: str):
    """Show text in kdialog / zenity / tkinter; fall back to stderr."""
    if sys.stderr.isatty():
        print(text, file=sys.stderr)
        return
    path = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as fh:
            fh.write(text)
            path = fh.name
        if shutil.which("kdialog"):
            subprocess.run(["kdialog", "--title", title, "--textbox", path, "700", "420"], check=False)
            return
        if shutil.which("zenity"):
            subprocess.run(["zenity", "--text-info", "--title", title, "--filename", path,
                            "--width", "700", "--height", "420"], check=False)
            return
        try:
            import tkinter as tk
            root = tk.Tk()
            root.title(title)
            box = tk.Text(root, width=90, height=22, wrap="word")
            box.insert("1.0", text)
            box.configure(state="disabled")
            box.pack(fill="both", expand=True)
            tk.Button(root, text="Close", command=root.destroy).pack()
            root.mainloop()
            return
        except Exception:
            pass
    finally:
        if path:
            try:
                os.remove(path)
            except OSError:
                pass
    print(text, file=sys.stderr)
