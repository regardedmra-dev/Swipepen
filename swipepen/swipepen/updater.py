"""`swipepen update`: install a new version from the archive you just downloaded.

Download swipepen.tar.gz (it lands in ~/Downloads), then run `swipepen update`
or use "Update from Downloads" in the keyboard's right-click menu. It:

  1. finds the newest swipepen*.tar.gz in your Downloads folder
  2. replaces the installed program (no password, no reinstall of system packages)
  3. also refreshes your swipepen folder (the one install.sh was run from), if there is one
  4. restarts swipepen if it was running
  5. renames the archive to *.installed so it is not used twice
"""
from __future__ import annotations

import glob
import os
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time


def dest_dir() -> str:
    return os.environ.get("SWIPEPEN_HOME") or os.path.expanduser("~/.local/share/swipepen")


def downloads_dir() -> str:
    try:
        out = subprocess.run(["xdg-user-dir", "DOWNLOAD"], capture_output=True, text=True, timeout=3).stdout.strip()
        if out and os.path.isdir(out) and out != os.path.expanduser("~"):
            return out
    except (OSError, subprocess.SubprocessError):
        pass
    return os.path.expanduser("~/Downloads")


def find_archive(folder: str | None = None) -> str | None:
    folder = folder or downloads_dir()
    found = glob.glob(os.path.join(glob.escape(folder), "swipepen*.tar.gz"))
    return max(found, key=os.path.getmtime) if found else None


def _safe_extract(tar: tarfile.TarFile, target: str):
    base = os.path.realpath(target)
    for m in tar.getmembers():
        path = os.path.realpath(os.path.join(target, m.name))
        if not (path == base or path.startswith(base + os.sep)) or m.issym() or m.islnk() or m.isdev():
            raise SystemExit(f"The archive contains an unsafe entry ({m.name}); not installing it.")
    tar.extractall(target)


def _find_root(folder: str) -> str:
    for dirpath, dirnames, filenames in os.walk(folder):
        if "install.sh" in filenames and os.path.isfile(os.path.join(dirpath, "swipepen", "__init__.py")):
            return dirpath
    raise SystemExit("That archive does not look like swipepen (no install.sh / swipepen package inside).")


def _version_of(root: str) -> str:
    try:
        with open(os.path.join(root, "swipepen", "__init__.py"), encoding="utf-8") as fh:
            m = re.search(r'__version__\s*=\s*"([^"]+)"', fh.read())
        return m.group(1) if m else "?"
    except OSError:
        return "?"


def _replace_dir(src: str, dst: str):
    tmp, old = dst + ".new", dst + ".old"
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(old, ignore_errors=True)
    shutil.copytree(src, tmp, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    if os.path.exists(dst):
        os.rename(dst, old)
    os.rename(tmp, dst)
    shutil.rmtree(old, ignore_errors=True)


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


def apply_update(archive: str, dest: str | None = None) -> dict:
    """Install `archive`. Returns a dict describing what happened."""
    dest = dest or dest_dir()
    app = os.path.join(dest, "app")
    if not os.path.isdir(app):
        raise SystemExit("swipepen is not installed yet. Run ./install.sh from the swipepen folder first.")
    try:
        tar = tarfile.open(archive)
    except (OSError, tarfile.TarError) as exc:
        raise SystemExit(f"Could not open {archive}: {exc}")
    with tempfile.TemporaryDirectory(prefix="swipepen-update-") as tmp, tar:
        _safe_extract(tar, tmp)
        root = _find_root(tmp)
        new_version = _version_of(root)
        try:
            from . import __version__ as old_version
        except ImportError:
            old_version = "?"

        info = {"old": old_version, "new": new_version, "source": None, "reinstall_hint": False}
        _replace_dir(os.path.join(root, "swipepen"), os.path.join(app, "swipepen"))

        source = _read(os.path.join(dest, "source")).strip()
        if source and os.path.isdir(source) and os.path.realpath(source) != os.path.realpath(root):
            info["reinstall_hint"] = _read(os.path.join(source, "install.sh")) != _read(os.path.join(root, "install.sh"))
            for name in os.listdir(root):
                s, d = os.path.join(root, name), os.path.join(source, name)
                if os.path.isdir(s):
                    _replace_dir(s, d)
                else:
                    shutil.copy2(s, d)
            info["source"] = source
    return info


def restart_if_running() -> bool:
    """Stop a running swipepen and start it again. Returns True if one was running."""
    from .__main__ import PID_FILE
    try:
        pid = int(_read(PID_FILE).strip())
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False
    os.kill(pid, signal.SIGTERM)
    for _ in range(40):
        time.sleep(0.1)
        try:
            os.kill(pid, 0)
        except OSError:
            break
    exe = os.path.expanduser("~/.local/bin/swipepen")
    cmd = [exe, "run"] if os.path.exists(exe) else [sys.executable, "-m", "swipepen", "run"]
    subprocess.Popen(cmd, start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def run_update(archive: str | None = None, window: bool = False, restart: bool = True) -> int:
    def say(title, text, ok=True):
        if window:
            from .doctor import show_dialog
            show_dialog(title, text)
        else:
            print(text, file=sys.stdout if ok else sys.stderr)

    try:
        found = archive or find_archive()
        if not found:
            raise SystemExit(f"No swipepen*.tar.gz found in {downloads_dir()}.\n"
                             "Download the new version first, then run this again.")
        info = apply_update(found)
        try:
            os.rename(found, found + ".installed")
        except OSError:
            pass
        restarted = restart_if_running() if restart else False
        lines = [f"Updated swipepen {info['old']} -> {info['new']}."]
        if info["source"]:
            lines.append(f"Your folder was refreshed too: {info['source']}")
        lines.append("It was restarted for you." if restarted else "Open it from the application menu to use the new version.")
        from .inject import Clipboard
        if Clipboard().kind is None:
            lines.append("To let swipepen read your document (tidy / + word), run once:  sudo dnf install wl-clipboard xclip")
        if info["reinstall_hint"]:
            lines.append("The installer itself changed. If something misbehaves, run ./install.sh once in your swipepen folder.")
        say("swipepen updated", "\n".join(lines))
        return 0
    except SystemExit as exc:
        say("swipepen update failed", str(exc.code) if exc.code else "update failed", ok=False)
        return 1
