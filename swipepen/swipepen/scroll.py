"""Typewriter scrolling: keep the caret at the same height on screen while you write.

swipepen cannot see where the caret is on your screen. What it can do is count: every time
the text it types runs onto a new visual line (or you press Enter), the page has to move up
by one line to keep the caret level, and every time Backspace takes a line away it moves back.
So it estimates the line breaks from "characters per line" and scrolls the page with a
virtual mouse wheel, a calibrated amount ("wheel notches per line") for every line.

It is an estimate: tune the two numbers in Settings so that it feels right, and keep the mouse
pointer over the document (a wheel turns the window under the pointer).
"""
from __future__ import annotations


class Typewriter:
    def __init__(self, scroll, chars_per_line: int = 80, notches_per_line: float = 0.25):
        self.scroll = scroll            # scroll(notches): > 0 moves the view down (later text comes up)
        self.cpl = max(10, int(chars_per_line))
        self.npl = float(notches_per_line)
        self.col = 0                    # estimated column of the caret on its visual line
        self.pending = 0                # whole lines gained (+) or lost (-) and not scrolled yet

    def typed(self, text: str):
        for ch in text:
            if ch == "\n":
                self.col = 0
                self.pending += 1
            else:
                self.col += 1
                if self.col > self.cpl:         # ran past the end of the line: it wrapped
                    self.col = 1
                    self.pending += 1

    def erased(self, n: int):
        for _ in range(n):
            self.col -= 1
            if self.col < 0:                    # backed up onto the previous visual line
                self.col = self.cpl - 1
                self.pending -= 1

    def flush(self):
        """Scroll for the lines gained or lost since the last flush (called when an action is done)."""
        if self.pending:
            n, self.pending = self.pending, 0
            self.scroll(n * self.npl)
