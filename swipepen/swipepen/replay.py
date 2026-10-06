"""Replay recorded swipes through the decoder: measure accuracy, compare settings.

    swipepen replay                          # your recording (~/.config/swipepen/swipes.jsonl)
    swipepen replay FILE --sweep looseness=0,0.25,0.5,0.75,1
    swipepen replay --sweep prior_weight=0.1,0.18,0.26 --explicit-only
    swipepen replay --set coverage_weight=0.3 --looseness 0.7

Only the swipe decoder is replayed (shape + word frequency). The live typing also nudges the order by the word
before and by your past corrections; the report shows how often that live result was right ("as typed") next to
the replayed one, so you can see what the decoder alone does.

Two groups are reported, because they mean different things:
  explicit  you tapped a candidate, confirmed the word, or erased it and swiped again: the word is known for sure.
            These are the swipes that went wrong at least sometimes, so improvements show up here.
  implicit  you just carried on typing: the word was right "as typed", so it can show regressions, not gains.
"""
from __future__ import annotations

import time
from collections import defaultdict

from .recorder import Sample, load_samples

KS = (1, 3, 5)


def build_decoder(lang: str = "en", looseness: float | None = None, force_fallback: bool = False):
    from . import lexicon
    from .engine import Decoder
    dec = Decoder(lexicon.load_lexicon(lang, force_fallback=force_fallback, verbose=False))
    try:
        dec.set_user_words(lexicon.user_entries())
    except OSError:
        pass
    if looseness is not None:
        dec.set_looseness(looseness)
    return dec


def apply_setting(dec, name: str, value: float):
    """Set one decoder parameter by name ('looseness' and 'ys' have their own setters)."""
    if name == "looseness":
        dec.set_looseness(value)
    elif name == "ys":
        dec.set_ys(value)
    elif hasattr(dec, name) and isinstance(getattr(dec, name), (int, float)) and not isinstance(getattr(dec, name), bool):
        setattr(dec, name, type(getattr(dec, name))(value))
    else:
        raise ValueError(f"unknown decoder setting: {name}")


def replay(samples: list[Sample], dec, ys: float | None = None, explicit_only: bool = False,
           settings: dict | None = None) -> dict:
    """Decode every labelled sample. Returns {"explicit": stats, "implicit": stats, "skipped": {...}}."""
    groups = {"explicit": _blank(), "implicit": _blank()}
    skipped = {"unlabelled": 0, "not in dictionary": 0}
    by_ys = defaultdict(list)
    for s in samples:
        by_ys[ys if ys is not None else (s.ys or 1.5)].append(s)
    for y, group in by_ys.items():
        dec.set_ys(y)
        for name, value in sorted((settings or {}).items(), key=lambda kv: kv[0] != "looseness"):
            apply_setting(dec, name, value)                # looseness first: it resets the weights the others set
        for s in group:
            if not s.truth or s.source == "unknown":
                skipped["unlabelled"] += 1
                continue
            if explicit_only and not s.explicit:
                continue
            if dec.logp(s.truth.lower()) is None:
                skipped["not in dictionary"] += 1
                continue
            g = groups["explicit" if s.explicit else "implicit"]
            t0 = time.perf_counter()
            res = [w for w, _ in dec.decode(s.pts, k=max(KS))]
            g["ms"] += (time.perf_counter() - t0) * 1000
            g["n"] += 1
            truth = s.truth.lower()
            for k in KS:
                if truth in [w.lower() for w in res[:k]]:
                    g[k] += 1
            if s.cands and s.cands[0].lower() == truth:
                g["live"] += 1
    return {**groups, "skipped": skipped}


def _blank():
    return {"n": 0, "ms": 0.0, "live": 0, **{k: 0 for k in KS}}


def _pct(a, n):
    return f"{a / n:6.1%}" if n else "     -"


def format_report(result: dict, title: str = "") -> str:
    lines = [title] if title else []
    lines.append(f"{'group':<10}{'swipes':>8}{'top-1':>8}{'top-3':>8}{'top-5':>8}{'as typed':>10}{'ms/swipe':>10}")
    for name in ("explicit", "implicit"):
        g = result[name]
        n = g["n"]
        lines.append(f"{name:<10}{n:>8}{_pct(g[1], n):>8}{_pct(g[3], n):>8}{_pct(g[5], n):>8}"
                     f"{_pct(g['live'], n):>10}{(g['ms'] / n if n else 0):>10.1f}")
    sk = result["skipped"]
    lines.append(f"(left out: {sk['unlabelled']} without a known word, {sk['not in dictionary']} whose word is not in the dictionary)")
    return "\n".join(lines)


def parse_assignments(items) -> dict:
    out = {}
    for item in items or ():
        name, sep, val = item.partition("=")
        if not sep:
            raise ValueError(f"expected name=value, got {item!r}")
        out[name.strip()] = float(val)
    return out


def run_cli(args) -> int:
    samples = load_samples(args.file)
    if args.limit:
        samples = samples[-args.limit:]
    if not samples:
        print("No swipes recorded yet. Switch on Settings -> \"Save my swipes ...\" (or run with --record FILE),\n"
              "write for a while, and run this again.")
        return 1
    from .area import load_config
    cfg = load_config()
    loose = args.looseness if args.looseness is not None else float(cfg["looseness"])
    dec = build_decoder(args.lang, loose)
    base = parse_assignments(args.set)
    n_exp = sum(1 for s in samples if s.explicit)
    print(f"{len(samples)} swipes ({n_exp} with a known word you fixed or confirmed); "
          f"looseness {loose}" + (f", {base}" if base else "") + "\n")
    if args.sweep:
        name, _, vals = args.sweep.partition("=")
        values = [float(v) for v in vals.split(",") if v.strip()]
        if not values:
            raise SystemExit("--sweep needs name=v1,v2,...")
        rows = []
        for v in values:
            res = replay(samples, dec, args.ys, args.explicit_only, {**base, name: v})
            rows.append((v, res))
        print(f"{name:<16}{'explicit top-1':>16}{'top-3':>8}{'implicit top-1':>16}{'top-3':>8}")
        for v, res in rows:
            e, i = res["explicit"], res["implicit"]
            print(f"{v:<16g}{_pct(e[1], e['n']):>16}{_pct(e[3], e['n']):>8}{_pct(i[1], i['n']):>16}{_pct(i[3], i['n']):>8}")
        print(f"\n(explicit n={rows[0][1]['explicit']['n']}, implicit n={rows[0][1]['implicit']['n']})")
        return 0
    print(format_report(replay(samples, dec, args.ys, args.explicit_only, base)))
    return 0
