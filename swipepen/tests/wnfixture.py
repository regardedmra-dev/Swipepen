"""A miniature WordNet in the real file format, for tests."""
import os

HEADER = ["  1 This software and database is being provided to you, the LICENSEE, by Princeton University,\n",
          "  2 under the following license.\n"]
# name: (file, ss_type, [words], [(symbol, target_name, target_pos, source_target)], gloss)
SYN = {
    "dog": ("noun", "n", ["dog", "domestic_dog", "Canis_familiaris"], [("@", "canine", "n", "0000"), ("~", "puppy", "n", "0000")],
            'a member of the genus Canis; "the dog barked all night"'),
    "canine": ("noun", "n", ["canine", "canid"], [("~", "dog", "n", "0000")], "any of various fissiped mammals"),
    "puppy": ("noun", "n", ["puppy"], [("@", "dog", "n", "0000")], "a young dog"),
    "run1": ("verb", "v", ["run"], [], "move fast by using one's feet; \"Don't run\""),
    "run2": ("verb", "v", ["run", "operate"], [], "direct or control"),
    "happy": ("adj", "a", ["happy"], [("!", "unhappy", "a", "0101"), ("&", "glad", "s", "0000")],
              'enjoying or showing or marked by joy or pleasure; "a happy smile"'),
    "glad": ("adj", "s", ["glad"], [("&", "happy", "a", "0000")], "showing or causing joy and pleasure"),
    "unhappy": ("adj", "a", ["unhappy"], [("!", "happy", "a", "0101")], "experiencing or marked by sadness"),
}
INDEX = {"dog": [("n", ["dog"])], "domestic dog": [("n", ["dog"])], "canine": [("n", ["canine"])],
         "puppy": [("n", ["puppy"])], "run": [("v", ["run1", "run2"])], "operate": [("v", ["run2"])],
         "happy": [("a", ["happy"])], "glad": [("a", ["glad"])], "unhappy": [("a", ["unhappy"])]}

def build(folder):
    offsets = {}
    for fname in ("noun", "verb", "adj"):
        pos = HEADER[:]
        cursor = sum(len(h.encode()) for h in pos)
        for name, (f, t, words, ptrs, gloss) in SYN.items():
            if f != fname:
                continue
            offsets[name] = cursor
            line = render(name, 0, offsets=None)
            cursor += len(line.encode())
    lines = {"noun": HEADER[:], "verb": HEADER[:], "adj": HEADER[:], "adv": HEADER[:]}
    for name, (f, *_rest) in SYN.items():
        lines[f].append(render(name, offsets[name], offsets))
    for f, ls in lines.items():
        with open(os.path.join(folder, "data." + f), "w", encoding="utf-8") as fh:
            fh.write("".join(ls))
    idx = {"noun": HEADER[:], "verb": HEADER[:], "adj": HEADER[:], "adv": HEADER[:]}
    names = {"n": "noun", "v": "verb", "a": "adj"}
    for lemma, entries in sorted(INDEX.items()):
        for pos, syns in entries:
            idx[names[pos]].append(f"{lemma.replace(' ', '_')} {pos} {len(syns)} 0 {len(syns)} 0 " +
                                   " ".join("%08d" % offsets[s] for s in syns) + "  \n")
    for f, ls in idx.items():
        with open(os.path.join(folder, "index." + f), "w", encoding="utf-8") as fh:
            fh.write("".join(ls))
    open(os.path.join(folder, "verb.exc"), "w").write("ran run\nrunning run\n")
    open(os.path.join(folder, "adj.exc"), "w").write("happier happy\nhappiest happy\n")
    open(os.path.join(folder, "noun.exc"), "w").write("")
    open(os.path.join(folder, "adv.exc"), "w").write("")

def render(name, offset, offsets):
    f, t, words, ptrs, gloss = SYN[name]
    out = "%08d 00 %s %02x " % (offset, t, len(words))
    out += " ".join("%s 0" % w for w in words) + " "
    out += "%03d " % len(ptrs)
    for sym, target, tpos, st in ptrs:
        out += "%s %08d %s %s " % (sym, offsets[target] if offsets else 0, tpos, st)
    return out + "| " + gloss + "  \n"

