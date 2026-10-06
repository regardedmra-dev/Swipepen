"""Command line entry point.

    swipepen                 # same as `swipepen run`
    swipepen run --dry-run --no-pen --mouse   # try it with the mouse, types nothing
    swipepen doctor          # check your setup and say what to fix
    swipepen devices         # list input devices (to find your pen)
    swipepen toggle          # pause/resume a running instance (bind to a KDE shortcut)
    swipepen settings        # open the settings window of a running instance
    swipepen tidy            # fix typos in the paragraph before the cursor (bind to a KDE shortcut)
    swipepen learn           # add the word before the cursor to your personal dictionary
    swipepen words list|add|remove WORD...   # your personal dictionary (names, jargon)
    swipepen define WORD     # definition, synonyms and antonyms in the terminal (same dictionary as the pen's)
    swipepen update          # install the newest swipepen*.tar.gz from your Downloads folder
"""
from __future__ import annotations

import argparse
import os
import signal
import sys
import traceback

PID_FILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "swipepen.pid")
CMD_FILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "swipepen.cmd")


def cmd_doctor(args):
    from .doctor import format_report, run_checks, show_dialog, tablet_access_problem

    if args.probe_access:      # used by install.sh: exit 3 = tablet exists but is not readable
        sys.exit(3 if tablet_access_problem() else 0)

    results = run_checks()
    report = format_report(results)
    if args.window:
        bad = [r for r in results if not r[1] and "optional" not in r[2]]
        head = "Everything looks fine." if not bad else "Something needs fixing:"
        show_dialog("swipepen setup check", head + "\n\n" + report)
    else:
        print(report)
    sys.exit(0 if all(ok for _, ok, d, _ in results if "optional" not in d) else 1)


def cmd_devices(_args):
    try:
        import evdev
    except ImportError:
        raise SystemExit("python-evdev is missing:  sudo dnf install python3-evdev")
    from .pen import list_pen_candidates

    paths = evdev.list_devices()
    if not paths:
        print("No readable input devices. Run `swipepen doctor`.")
    likely = {d.path for d in list_pen_candidates()}
    for p in paths:
        d = evdev.InputDevice(p)
        print(f"{'*' if p in likely else ' '} {p:<22} {d.name}")
    print("\n* = looks like a pen tablet")


def _signal_running(sig):
    try:
        with open(PID_FILE) as fh:
            os.kill(int(fh.read().strip()), sig)
    except (OSError, ValueError):
        raise SystemExit("swipepen is not running")


def cmd_toggle(_args):
    _signal_running(signal.SIGUSR1)


def cmd_settings(_args):
    _signal_running(signal.SIGUSR2)


def _send_command(name):
    _signal_running(0)                       # raises "swipepen is not running" if it is not
    with open(CMD_FILE, "w", encoding="utf-8") as fh:
        fh.write(name)
    _signal_running(signal.SIGHUP)


def cmd_tidy(_args):
    _send_command("tidy")


def cmd_learn(_args):
    _send_command("learn")


def cmd_words(args):
    from . import lexicon
    if args.action == "list":
        words = lexicon.read_user_words()
        print("\n".join(words) if words else f"(no words yet; add some with: swipepen words add Name)")
        print(f"\n[{lexicon.user_words_path()}]")
        return
    for w in args.words:
        if args.action == "add":
            print(("added: " if lexicon.add_user_word(w) else "skipped (invalid or already there): ") + w)
        else:
            print(("removed: " if lexicon.remove_user_word(w) else "not found: ") + w)
    print("A running swipepen picks the change up within a second.")


def cmd_define(args):
    from .lookup import Dictionary
    d = Dictionary(online=not args.offline)
    res = d.lookup(args.word)
    if not res.found:
        print(f"No entry for '{args.word}'" + ("" if d.wn else "  (no WordNet found: sudo dnf install wordnet)"))
        return
    print(f"{res.word}   [{res.source}]")
    for sense in res.senses[:8]:
        print(f"\n  {sense.pos}: {sense.gloss}")
        for ex in sense.examples[:1]:
            print(f'     "{ex}"')
    for label, attr in (("Synonyms", "synonyms"), ("Antonyms", "antonyms"), ("Broader", "broader"),
                        ("Narrower", "narrower"), ("Similar", "similar")):
        words = res.merged(attr, 25)
        if words:
            print(f"\n{label}: " + ", ".join(words))
    for label, words in res.more.items():
        print(f"\n{label}: " + ", ".join(words))


def cmd_swipes(args):
    from .recorder import Recorder, default_path
    rec = Recorder(args.file or default_path())
    if args.action == "path":
        print(rec.path)
    elif args.action == "clear":
        print("deleted " + rec.path if rec.clear() else "nothing to delete: " + rec.path)
    else:
        lines, size = rec.info()
        print(f"{rec.path}\n{lines} records, {size / 1024:.0f} KB" if lines else f"no recording at {rec.path}")
        print("Recording is off unless you switch it on in Settings (or run with --record FILE).")


def cmd_replay(args):
    from .replay import run_cli
    try:
        code = run_cli(args)
    except ValueError as exc:
        raise SystemExit(str(exc))
    if code:
        sys.exit(code)


def cmd_build_ngrams(args):
    from . import lexicon, ngrams
    from .predict import Predictor
    files = ngrams.find_files(args.paths)
    if not files:
        raise SystemExit("no text files found (looked for " + " ".join(ngrams.TEXT_EXT) + ")")
    known = {w.lower(): lp for w, _k, lp in lexicon.load_lexicon(args.lang, verbose=False)}.get

    def stream():
        for f in files:
            yield from ngrams.sentences(ngrams.read_text(f))

    out = args.out or ngrams.config_file(args.lang)
    if args.evaluate:
        train, test = ngrams.split_sentences(list(stream()), 0.1)
        counts = ngrams.count_pairs(train, known)
        table = ngrams.shares(ngrams.trim(counts, args.top, args.min_count))
        base = Predictor(known, path=None, learning=False, corpus={})
        withtab = Predictor(known, path=None, learning=False, corpus=table)
        a, b = ngrams.evaluate(test, base), ngrams.evaluate(test, withtab)
        n = max(1, a["n"])
        print(f"held-back words: {a['n']}   (the table was built from the other {len(train)} sentences)")
        print(f"  {'':<22}{'1st suggestion':>16}{'in the 3 shown':>16}")
        print(f"  {'built-in list only':<22}{a[1] / n:>16.1%}{a[3] / n:>16.1%}")
        print(f"  {'+ your table':<22}{b[1] / n:>16.1%}{b[3] / n:>16.1%}\n")
        counts += ngrams.count_pairs(test, known)
    else:
        counts = ngrams.count_pairs(stream(), known)
    table = ngrams.trim(counts, args.top, args.min_count)
    if not table:
        raise SystemExit("not enough text: no word pair was seen " + str(args.min_count) + " times (try --min-count 2)")
    n = ngrams.write_table(table, out)
    print(f"{len(files)} files, {sum(counts.values())} word pairs counted -> {n} kept for {len(table)} words\n[{out}]")
    print("A running swipepen picks it up at its next start.")


def cmd_update(args):
    from .updater import run_update
    sys.exit(run_update(args.archive, window=args.window, restart=not args.no_restart))


def cmd_run(args):
    if args.mouse and not args.dry_run:
        raise SystemExit("--mouse only makes sense with --dry-run (the window would steal the typed text)")

    from .engine import Decoder
    from .gui import App
    from .inject import DryRunInjector, UInputInjector
    from .lexicon import load_lexicon
    from .session import Session

    from . import lexicon
    decoder = Decoder(load_lexicon(args.lang))
    decoder.set_user_words(lexicon.user_entries())
    inj = DryRunInjector() if args.dry_run else UInputInjector(args.layout)
    session = Session(decoder, inj, record_path=args.record)

    from .area import load_config
    cfg = load_config()
    if args.rotate is not None:
        cfg["rotate"] = args.rotate
    if args.scale:
        cfg["scale"] = args.scale
    if args.size:
        cfg["size"] = args.size / 100.0

    reader = None
    if not args.no_pen:
        from .pen import PenReader
        reader = PenReader(args.device, cfg["rotate"], args.toggle_button)
        reader.start()

    app = App(session, reader, dry=inj if args.dry_run else None, mouse=args.mouse,
              cfg=cfg, start_active=not args.start_paused)

    with open(PID_FILE, "w") as fh:
        fh.write(str(os.getpid()))
    signal.signal(signal.SIGUSR1, lambda *_: app.request_toggle())
    signal.signal(signal.SIGUSR2, lambda *_: app.request_settings())
    signal.signal(signal.SIGTERM, lambda *_: app.request_quit())
    signal.signal(signal.SIGHUP, lambda *_: app.request_command())
    try:
        app.run()
    finally:
        if reader:
            reader.set_active(False)
        if hasattr(inj, "close"):
            inj.close()
        try:
            os.remove(PID_FILE)
        except OSError:
            pass


def _fail(message: str, with_report: bool):
    """Startup failed. From the app menu there is no terminal, so show a popup and keep a log."""
    from .doctor import format_report, log_path, run_checks, show_dialog, write_log

    text = message.strip()
    if with_report:
        try:
            text += "\n\nSetup check:\n" + format_report(run_checks())
        except Exception:
            pass
    write_log(text + "\n")
    show_dialog("swipepen could not start", text + f"\n\n(also saved to {log_path()})")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="swipepen", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    run = sub.add_parser("run", help="start swipe typing")
    run.add_argument("--device", help="pen device, e.g. /dev/input/event7 (default: auto-detect)")
    run.add_argument("--rotate", type=int, choices=(0, 90, 180, 270), default=None,
                     help="tablet rotation (180 = left-handed); normally set in the window and remembered")
    run.add_argument("--scale", type=int, metavar="PX", help="preview keyboard size in pixels per key (default 60)")
    run.add_argument("--size", type=int, metavar="PCT",
                     help="keyboard size on the tablet in percent of its width (default 50; slider in the window)")
    run.add_argument("--layout", choices=("us", "es", "latam"), default="us",
                     help="your active keyboard layout (affects only the apostrophe key)")
    run.add_argument("--lang", default="en")
    run.add_argument("--toggle-button", choices=("auto", "stylus", "stylus2"), default="auto")
    run.add_argument("--record", metavar="FILE", help="append every swipe to FILE (jsonl) for tuning")
    run.add_argument("--dry-run", action="store_true", help="do not type anything, show text in the window")
    run.add_argument("--no-pen", action="store_true", help="do not read a tablet")
    run.add_argument("--mouse", action="store_true", help="swipe with the mouse in the window (needs --dry-run)")
    run.add_argument("--start-paused", action="store_true")
    run.set_defaults(func=cmd_run)

    doc = sub.add_parser("doctor", help="check your setup")
    doc.add_argument("--window", action="store_true", help="show the result in a popup window")
    doc.add_argument("--probe-access", action="store_true", help=argparse.SUPPRESS)
    doc.set_defaults(func=cmd_doctor)

    sub.add_parser("devices", help="list input devices").set_defaults(func=cmd_devices)
    sub.add_parser("toggle", help="pause/resume a running instance").set_defaults(func=cmd_toggle)
    sub.add_parser("settings", help="open the settings window of a running instance").set_defaults(func=cmd_settings)

    sub.add_parser("tidy", help="fix typos in the paragraph before the cursor").set_defaults(func=cmd_tidy)
    sub.add_parser("learn", help="add the word before the cursor to your dictionary").set_defaults(func=cmd_learn)
    wd = sub.add_parser("words", help="your personal dictionary")
    wd.add_argument("action", choices=("list", "add", "remove"))
    wd.add_argument("words", nargs="*")
    wd.set_defaults(func=cmd_words)
    df = sub.add_parser("define", help="definition, synonyms and antonyms of a word")
    df.add_argument("word")
    df.add_argument("--offline", action="store_true", help="never use the internet")
    df.set_defaults(func=cmd_define)

    sw = sub.add_parser("swipes", help="your recorded swipes (off unless you switch it on): info, path, clear")
    sw.add_argument("action", choices=("info", "path", "clear"), nargs="?", default="info")
    sw.add_argument("file", nargs="?", help="a recording other than the default")
    sw.set_defaults(func=cmd_swipes)
    rp = sub.add_parser("replay", help="replay recorded swipes: accuracy report, or compare settings with --sweep")
    rp.add_argument("file", nargs="?", help="a recording (default: the one in ~/.config/swipepen)")
    rp.add_argument("--lang", default="en")
    rp.add_argument("--looseness", type=float, help="swipe tolerance 0..1 (default: your setting)")
    rp.add_argument("--ys", type=float, help="key height / width (default: what was recorded)")
    rp.add_argument("--set", action="append", metavar="NAME=VALUE",
                    help="override a decoder setting, e.g. prior_weight=0.2 (repeatable)")
    rp.add_argument("--sweep", metavar="NAME=V1,V2,...", help="try several values of one setting, e.g. looseness=0,0.5,1")
    rp.add_argument("--explicit-only", action="store_true", help="only swipes whose word you fixed or confirmed")
    rp.add_argument("--limit", type=int, help="only the newest N swipes")
    rp.set_defaults(func=cmd_replay)

    ng = sub.add_parser("build-ngrams", help="make a word-pair table from text you choose, for better next-word suggestions")
    ng.add_argument("paths", nargs="+", help="text files or folders (.txt .md .html .docx)")
    ng.add_argument("--out", help="where to save (default: your swipepen folder, used automatically)")
    ng.add_argument("--lang", default="en")
    ng.add_argument("--top", type=int, default=8, help="followers kept per word (default 8)")
    ng.add_argument("--min-count", type=int, default=3, help="a pair must be seen this often (default 3)")
    ng.add_argument("--evaluate", action="store_true", help="first measure it on 10%% of the text held back")
    ng.set_defaults(func=cmd_build_ngrams)

    up = sub.add_parser("update", help="install the newest swipepen*.tar.gz from your Downloads folder")
    up.add_argument("archive", nargs="?", help="a specific .tar.gz (default: newest in Downloads)")
    up.add_argument("--window", action="store_true", help="show the result in a popup window")
    up.add_argument("--no-restart", action="store_true")
    up.set_defaults(func=cmd_update)

    args = ap.parse_args(argv if argv is not None else (sys.argv[1:] or ["run"]))
    if not args.cmd:
        args = ap.parse_args(["run"])

    running = args.cmd == "run"
    try:
        args.func(args)
    except SystemExit as exc:
        if isinstance(exc.code, str) and running:   # our own friendly error messages
            _fail(exc.code, with_report=True)
            sys.exit(1)
        raise
    except Exception:
        if running:
            _fail("swipepen crashed:\n\n" + traceback.format_exc()[-1800:], with_report=True)
            sys.exit(1)
        raise


if __name__ == "__main__":
    main()
