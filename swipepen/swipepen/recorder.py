"""Opt-in local swipe recorder, and the loader that turns a recording into labelled samples.

OFF by default. When you switch it on (Settings -> "Save my swipes ...", or `swipepen run --record FILE`),
every swiped word is appended to ONE file on this computer (default ~/.config/swipepen/swipes.jsonl).
Nothing is ever sent anywhere. What is stored: the pen path in key units, the words the decoder offered, the
few words before it, and what you did next (kept it / picked another word / erased it). That is text you
typed, so switch it off when you write something private. `swipepen swipes clear` deletes the file.

File format, one JSON object per line ("ev" says which):
    swipe   {id, pts, cands, ctx, shift, caps, ys, loose, [redo_of]}
    final   {id, word, how}   how = "kept" | "accept" | "pick" | "erased"   (word is None when erased)
Older recordings ({"points", "cands"} / {"correction"}) still load.

Labels (what the word really was) come from your behaviour, best evidence first:
    pick / accept   you tapped a candidate or tapped the word to confirm it       -> explicit
    redo            you erased the word and swiped again, and that one was kept    -> explicit
    kept            you carried on typing                                           -> implicit
An implicit label only says "the decoder was good enough at the time", so it cannot show an improvement;
the replay report therefore lists explicit and implicit samples separately.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

MAX_BYTES = 20_000_000          # about 14,000 swipes; past that the old file is kept as swipes.jsonl.1


def default_path() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "swipepen", "swipes.jsonl")


class Recorder:
    def __init__(self, path: str | None = None, enabled: bool = False):
        self.path = path or default_path()
        self.enabled = bool(enabled)
        self._next = 0

    def new_id(self) -> int:
        """A number that ties one swipe to what happened to it afterwards (unique within a recording)."""
        self._next = max(self._next, int(time.time() * 1000) % 10**9)
        self._next += 1
        return self._next

    def write(self, obj: dict) -> None:
        if not self.enabled:
            return
        obj = dict(obj, t=round(time.time(), 2))
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            if os.path.exists(self.path) and os.path.getsize(self.path) > MAX_BYTES:
                os.replace(self.path, self.path + ".1")
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(obj, ensure_ascii=False) + "\n")
        except (OSError, ValueError):
            pass                                    # recording must never get in the way of typing

    def info(self) -> tuple[int, int]:
        """(lines, bytes) of the current recording; (0, 0) if there is none."""
        try:
            size = os.path.getsize(self.path)
            with open(self.path, encoding="utf-8", errors="replace") as fh:
                return sum(1 for _ in fh), size
        except OSError:
            return 0, 0

    def clear(self) -> bool:
        gone = False
        for p in (self.path, self.path + ".1"):
            try:
                os.remove(p)
                gone = True
            except OSError:
                pass
        return gone


@dataclass
class Sample:
    id: int
    pts: list
    cands: list                 # what the decoder offered when it was recorded
    truth: str | None           # the word you meant, or None if we cannot tell
    source: str                 # "pick" | "accept" | "redo" | "kept" | "unknown"
    ctx: list = field(default_factory=list)
    ys: float | None = None
    loose: float | None = None

    @property
    def explicit(self) -> bool:
        return self.source in ("pick", "accept", "redo")


def _read(path):
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if isinstance(obj, dict):
                    out.append(obj)
    except OSError:
        pass
    return out


def load_samples(path: str | None = None) -> list[Sample]:
    """Read a recording and attach the best available label to every swipe."""
    rows = _read(path or default_path())
    swipes: dict[int, dict] = {}
    finals: dict[int, dict] = {}
    order: list[int] = []
    legacy: list[Sample] = []
    legacy_n = 0
    for obj in rows:
        ev = obj.get("ev")
        if ev == "swipe" and isinstance(obj.get("pts"), list) and isinstance(obj.get("id"), int):
            swipes[obj["id"]] = obj
            order.append(obj["id"])
        elif ev == "final" and isinstance(obj.get("id"), int):
            finals[obj["id"]] = obj
        elif "points" in obj and "cands" in obj:                    # 0.5.x recording
            legacy_n -= 1
            cands = [str(c) for c in obj["cands"]]
            legacy.append(Sample(legacy_n, [tuple(p) for p in obj["points"]], cands,
                                 cands[0] if cands else None, "kept" if cands else "unknown"))
        elif "correction" in obj and legacy:                        # 0.5.x: the word picked instead
            legacy[-1].truth, legacy[-1].source = str(obj["correction"]), "pick"

    redo_of = {i: s["redo_of"] for i, s in swipes.items() if isinstance(s.get("redo_of"), int)}
    follow = {old: new for new, old in redo_of.items()}              # erased swipe -> the swipe that redid it

    def resolve(i, depth=0):
        fin = finals.get(i)
        if fin is None:
            return None, "unknown"
        how, word = fin.get("how"), fin.get("word")
        if how in ("pick", "accept", "kept") and word:
            return str(word), how
        if how == "erased" and i in follow and depth < 3:
            w, src = resolve(follow[i], depth + 1)
            return (w, "redo") if w else (None, "unknown")
        return None, "unknown"

    out = []
    for i in order:
        s = swipes[i]
        truth, source = resolve(i)
        out.append(Sample(i, [tuple(p) for p in s["pts"]], [str(c) for c in s.get("cands", [])], truth, source,
                          [str(w) for w in s.get("ctx", [])], s.get("ys"), s.get("loose")))
    return legacy + out
