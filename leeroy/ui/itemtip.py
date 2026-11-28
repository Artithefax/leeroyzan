"""Gegenstands-Tooltip wie im Spiel: kleines Fenster ohne Rahmen neben dem Mauszeiger.

Die Zeilen kommen aus wowhead.tooltip_lines (oder aus dem, was Leeroyzan selbst weiß):
[{"left": [(Text, Farbe)], "right": [(Text, Farbe)]}, None = Leerzeile, …]. Die erste Zeile ist der Name.
"""
from __future__ import annotations

import re
import tkinter as tk
import tkinter.font as tkfont

from ..reports import QUALITY_COLORS
from .theme import THEME

TIP_BG = "#070b16"              # Nachtblau wie der Tooltip im Spiel
TIP_PAD = 9
TIP_MAX_W = 310                 # breiter wird der Text nicht, längere Zeilen brechen um
TIP_GAP = 18                    # Abstand zwischen linker und rechter Spalte („Kopf … Stoff“)
TIP_OFFSET = (18, 14)           # Abstand zum Mauszeiger – das Fenster darf nie unter der Maus liegen

# Farben aus Wowheads Tooltip-Klassen; die Qualitäten wie in den Listen von Leeroyzan
TIP_COLORS = {f"q{i}": c for i, c in enumerate(QUALITY_COLORS)}
TIP_COLORS.update({
    "": "#ffffff", "q": "#ffd100", "q7": "#00ccff", "q8": "#ffd100", "q9": "#ffd100", "q10": "#ff2020",
    "c1": "#c79c6e", "c2": "#f58cba", "c3": "#abd473", "c4": "#fff569", "c5": "#ffffff", "c6": "#c41f3b",
    "c7": "#0070de", "c8": "#69ccf0", "c9": "#9482c9", "c10": "#00ff96", "c11": "#ff7d0a",
    "gold": "#ffd700", "silver": "#c7c7cf", "copper": "#eda55f", "dim": "#8e9694",
})


def tip_color(key: str) -> str:
    return TIP_COLORS.get(key or "", TIP_COLORS[""])


def layout_tip(lines, measure, linespace, max_w: int = TIP_MAX_W, gap: int = TIP_GAP):
    """Zeilen → (Breite, Höhe, Elemente). measure(text, big) und linespace(big) kommen von der Schrift;
    die erste Zeile ist groß (der Name). Elemente: (x, y, Text, Farbe, big). Ohne Tk testbar."""
    rows: list[tuple[int, list, list, bool]] = []          # (y, links [(x, Text, Farbe)], rechts [(Text, Farbe)], big)
    y = 0
    widest = 0
    for n, line in enumerate(lines or []):
        big = n == 0
        if line is None:
            y += linespace(False) // 2
            continue
        right = [(t, c) for t, c in line.get("right", []) if t]
        right_w = sum(measure(t, big) for t, _ in right)
        limit = max(80, max_w - (right_w + gap if right else 0))
        cur: list = []
        x = 0
        line_rows = []
        for text, color in line.get("left", []):
            for token in re.findall(r"\S+\s*|\s+", text):
                w = measure(token.rstrip(), big)
                if cur and x + w > limit and token.strip():         # umbrechen
                    line_rows.append((cur, x))
                    cur, x = [], 0
                if not cur:
                    token = token.lstrip()
                    if not token:
                        continue
                if cur and cur[-1][2] == color:
                    cur[-1] = (cur[-1][0], cur[-1][1] + token, color)
                else:
                    cur.append((x, token, color))
                x += measure(token, big)
        if cur or right:
            line_rows.append((cur, x))
        for i, (items, w) in enumerate(line_rows):
            items = [(ix, t.rstrip() if j == len(items) - 1 else t, c) for j, (ix, t, c) in enumerate(items)]
            r = right if i == 0 else []
            natural = measure("".join(t for _, t, _ in items).rstrip(), big) if items else 0
            widest = max(widest, natural + (gap + right_w if r else 0))
            rows.append((y, items, r, big))
            y += linespace(big)
    width = min(max(widest, 120), max_w)
    out = []
    for ry, items, right, big in rows:
        out += [(ix, ry, t, c, big) for ix, t, c in items]
        rx = width - sum(measure(t, big) for t, _ in right)
        for t, c in right:
            out.append((rx, ry, t, c, big))
            rx += measure(t, big)
    return width, y, out


class ItemTip:
    """Ein wiederverwendetes Fenster ohne Rahmen; show() zeichnet neu, move() folgt der Maus."""

    def __init__(self, master, fonts: dict):
        self.master = master
        base = fonts.get("base") or ("TkDefaultFont", 10, "normal")
        self.font = tkfont.Font(root=master, font=base)
        name = tkfont.Font(root=master, font=fonts.get("bold") or base)
        name.configure(size=max(abs(int(name.cget("size"))) + 2, 11), weight="bold")
        self.name_font = name
        self.win = None
        self.cv = None
        self.size = (0, 0)
        self.visible = False

    def _window(self):
        if self.win is None or not self.win.winfo_exists():
            self.win = tk.Toplevel(self.master)
            self.win.withdraw()
            self.win.overrideredirect(True)
            try:
                self.win.attributes("-topmost", True)
            except tk.TclError:
                pass
            self.win.configure(bg=THEME["border"])          # 1 px Goldrahmen
            self.cv = tk.Canvas(self.win, bg=TIP_BG, highlightthickness=0, bd=0)
            self.cv.pack(padx=1, pady=1)
        return self.win

    def _measure(self, text: str, big: bool) -> int:
        return (self.name_font if big else self.font).measure(text)

    def _linespace(self, big: bool) -> int:
        return (self.name_font if big else self.font).metrics("linespace") + (3 if big else 1)

    def show(self, lines, x_root: int, y_root: int):
        win = self._window()
        w, h, items = layout_tip(lines, self._measure, self._linespace)
        cv = self.cv
        cv.delete("all")
        for x, y, text, color, big in items:
            cv.create_text(TIP_PAD + x, TIP_PAD + y, text=text, anchor="nw", fill=tip_color(color),
                           font=self.name_font if big else self.font)
        self.size = (w + 2 * TIP_PAD + 2, h + 2 * TIP_PAD + 2)
        cv.configure(width=w + 2 * TIP_PAD, height=h + 2 * TIP_PAD)
        self.move(x_root, y_root)
        if not self.visible:
            win.deiconify()
            self.visible = True
        win.lift()

    def move(self, x_root: int, y_root: int):
        if self.win is None:
            return
        w, h = self.size
        sw, sh = self.master.winfo_screenwidth(), self.master.winfo_screenheight()
        x, y = x_root + TIP_OFFSET[0], y_root + TIP_OFFSET[1]
        if 0 <= x_root < sw and x + w > sw:            # rechts kein Platz: links vom Mauszeiger
            x = x_root - w - TIP_OFFSET[0]
        if 0 <= y_root < sh and y + h > sh:
            y = max(0, sh - h - 4)
            if x <= x_root <= x + w:                   # nie unter dem Mauszeiger
                x = x_root - w - TIP_OFFSET[0]
        self.win.geometry(f"+{int(x)}+{int(y)}")

    def hide(self):
        if self.win is not None and self.visible:
            try:
                self.win.withdraw()
            except tk.TclError:
                pass
        self.visible = False
