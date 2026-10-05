"""Panels: screens you tap with the pen, drawn over the keyboard (dictionary, paragraph check, tools ...).

A panel is a list of rows. Each row has one to three cells; a cell is text, and tappable when it has an `action`.
The geometry is fixed so the window and the pen agree on what is where:

    y -1..0   tabs            (up to 4, like the suggestion strip)
    y  0..3   five body rows  (0.6 tall each)
    y  3..4   bottom bar      [ prev | close | next ]

This module draws nothing and types nothing; the window draws `layout()`, the session calls `hit()` on a tap.
"""
from __future__ import annotations

import math
import textwrap
from dataclasses import dataclass
from typing import Callable

from .engine import CANVAS_W

TAB_Y = (-1.0, 0.0)
BODY_Y0 = 0.0
ROW_H = 0.6
BODY_ROWS = 5
BAR_Y = (3.0, 4.0)
GAP = 0.04
WRAP = 40                 # characters per line for running text


@dataclass
class Cell:
    text: str
    action: Callable | None = None
    style: str = "item"   # item (tappable) | text | head | dim | hi | on


@dataclass
class Box:
    x0: float
    y0: float
    x1: float
    y1: float
    kind: str             # tab | cell | prev | close | next
    text: str
    style: str
    action: Callable | None

    def contains(self, x, y):
        return self.x0 <= x < self.x1 and self.y0 <= y < self.y1


def lines(text: str, style: str = "text", width: int = WRAP, limit: int = 99):
    """Running text as one-cell rows."""
    out = [[Cell(w, None, style)] for w in textwrap.wrap(text, width) or [""]]
    return out[:limit]


def word_rows(words, action_for, per_row: int = 3):
    """Tappable words, three to a row."""
    rows = []
    for i in range(0, len(words), per_row):
        rows.append([Cell(w, action_for(w), "item") for w in words[i:i + per_row]])
    return rows


class Panel:
    title = ""

    def __init__(self, session):
        self.s = session
        self.tabs: list[str] = []
        self.tab = 0
        self.page = 0
        self.alive = True
        self.busy = False

    # ---- what subclasses provide ------------------------------------------------------
    def rows(self) -> list:
        return []

    def header(self) -> "Cell | None":
        """A line that stays on top of every page (e.g. which word you are looking at)."""
        return None

    def on_tab(self, i: int):
        self.tab, self.page = i, 0

    def on_close(self):
        pass

    # ---- paging ---------------------------------------------------------------------------
    def per_page(self) -> int:
        return BODY_ROWS - (1 if self.header() else 0)

    def pages(self) -> int:
        return max(1, math.ceil(len(self.rows()) / self.per_page()))

    def prev(self):
        self.page = max(0, self.page - 1)

    def next(self):
        self.page = min(self.pages() - 1, self.page + 1)

    def prev_label(self) -> str:
        return "‹ prev"

    def next_label(self) -> str:
        return "next ›"

    def close_label(self) -> str:
        n = self.pages()
        return "close" if n <= 1 else f"close  {self.page + 1}/{n}"

    def prev_enabled(self) -> bool:
        return self.page > 0

    def next_enabled(self) -> bool:
        return self.page < self.pages() - 1

    def visible(self):
        self.page = min(self.page, self.pages() - 1)
        n, head = self.per_page(), self.header()
        body = self.rows()[self.page * n:(self.page + 1) * n]
        return ([[head]] if head else []) + body

    # ---- geometry ----------------------------------------------------------------------------
    def layout(self) -> list[Box]:
        boxes = []
        tabs = self.tabs[:4]
        if tabs:
            w = CANVAS_W / len(tabs)
            for i, name in enumerate(tabs):
                act = (lambda i=i: self.on_tab(i)) if len(tabs) > 1 else None
                boxes.append(Box(i * w + GAP, TAB_Y[0] + GAP, (i + 1) * w - GAP, TAB_Y[1] - GAP, "tab", name,
                                 "hi" if i == self.tab else "dim", act))
        for r, row in enumerate(self.visible()):
            n = max(1, len(row))
            w = CANVAS_W / n
            y0 = BODY_Y0 + r * ROW_H
            for c, cell in enumerate(row):
                boxes.append(Box(c * w + GAP, y0 + GAP / 2, (c + 1) * w - GAP, y0 + ROW_H - GAP / 2, "cell",
                                 cell.text, cell.style, cell.action))
        w = CANVAS_W / 3
        bar = [("prev", self.prev_label(), self.prev if self.prev_enabled() else None),
               ("close", self.close_label(), self.s.close_panel),
               ("next", self.next_label(), self.next if self.next_enabled() else None)]
        for i, (kind, text, act) in enumerate(bar):
            boxes.append(Box(i * w + GAP, BAR_Y[0] + GAP, (i + 1) * w - GAP, BAR_Y[1] - GAP, kind, text,
                             "item" if act else "dim", act))
        return boxes

    def hit(self, x, y):
        """The action under a tap, or None."""
        for b in self.layout():
            if b.contains(x, y):
                return b.action
        return None
