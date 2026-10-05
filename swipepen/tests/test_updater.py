"""swipepen update: archive in Downloads -> installed app + refreshed source folder."""
import os, sys, tarfile, tempfile, time
import swipepen.updater as u

def check(label, got, want=True):
    ok = got == want
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else f"  got {got!r} want {want!r}"))
    assert ok

def make_archive(path, version, install_sh="#!/bin/bash\n", evil=False):
    with tempfile.TemporaryDirectory() as t:
        top = os.path.join(t, "swipepen")
        os.makedirs(os.path.join(top, "swipepen"))
        os.makedirs(os.path.join(top, "tests"))
        open(os.path.join(top, "swipepen", "__init__.py"), "w").write(f'__version__ = "{version}"\n')
        open(os.path.join(top, "swipepen", "marker.py"), "w").write(f"V = '{version}'\n")
        open(os.path.join(top, "tests", "t.py"), "w").write("\n")
        open(os.path.join(top, "install.sh"), "w").write(install_sh)
        open(os.path.join(top, "README.md"), "w").write(version)
        with tarfile.open(path, "w:gz") as tar:
            tar.add(top, arcname="swipepen")
            if evil:
                info = tarfile.TarInfo("../escape.txt"); info.size = 0
                import io
                tar.addfile(info, io.BytesIO(b""))

with tempfile.TemporaryDirectory() as home:
    dest = os.path.join(home, "share", "swipepen")
    src = os.path.join(home, "Documents", "swipe program", "swipepen")      # note the space
    dl = os.path.join(home, "Downloads")
    os.makedirs(os.path.join(dest, "app", "swipepen")); os.makedirs(src); os.makedirs(dl)
    os.makedirs(os.path.join(dest, "venv"))
    open(os.path.join(dest, "app", "swipepen", "old.py"), "w").write("old")
    open(os.path.join(dest, "source"), "w").write(src + "\n")
    open(os.path.join(src, "install.sh"), "w").write("#!/bin/bash\n")
    open(os.path.join(src, "my-notes.txt"), "w").write("keep me")
    os.environ["SWIPEPEN_HOME"] = dest

    check("no archive found in an empty Downloads folder", u.find_archive(dl), None)
    make_archive(os.path.join(dl, "swipepen.tar.gz"), "0.8")
    time.sleep(0.05)
    make_archive(os.path.join(dl, "swipepen (1).tar.gz"), "0.9", install_sh="#!/bin/bash\n# new\n")
    arch = u.find_archive(dl)
    check("newest archive is picked", os.path.basename(arch), "swipepen (1).tar.gz")

    info = u.apply_update(arch)
    check("version reported", info["new"], "0.9")
    check("installed app has the new files", os.path.exists(os.path.join(dest, "app", "swipepen", "marker.py")))
    check("old files are gone", not os.path.exists(os.path.join(dest, "app", "swipepen", "old.py")))
    check("venv untouched", os.path.isdir(os.path.join(dest, "venv")))
    check("source folder refreshed (even with a space in its name)",
          open(os.path.join(src, "swipepen", "marker.py")).read(), "V = '0.9'\n")
    check("source folder keeps the user's own files", open(os.path.join(src, "my-notes.txt")).read(), "keep me")
    check("changed installer is flagged", info["reinstall_hint"], True)

    # whole flow incl. renaming the used archive (no running app, so nothing to restart)
    os.environ["XDG_RUNTIME_DIR"] = home
    import swipepen.__main__ as m
    m.PID_FILE = os.path.join(home, "swipepen.pid")
    u.downloads_dir = lambda: dl
    check("run_update succeeds", u.run_update(restart=True), 0)
    check("used archive renamed", os.path.exists(os.path.join(dl, "swipepen (1).tar.gz.installed")))
    check("older archive is the next candidate", os.path.basename(u.find_archive(dl)), "swipepen.tar.gz")
    check("nothing to update -> friendly failure", (os.remove(os.path.join(dl, "swipepen.tar.gz")), u.run_update())[1], 1)

    # unsafe archive refused
    make_archive(os.path.join(dl, "swipepen-evil.tar.gz"), "6.6", evil=True)
    try:
        u.apply_update(os.path.join(dl, "swipepen-evil.tar.gz"))
        check("unsafe archive refused", False)
    except SystemExit as e:
        check("unsafe archive refused", "unsafe" in str(e.code))
    check("nothing escaped", not os.path.exists(os.path.join(home, "escape.txt")))
    check("app still the good version", open(os.path.join(dest, "app", "swipepen", "marker.py")).read(), "V = '0.9'\n")

print("\nAll updater tests passed.")
