"""Seite „Builds“: Talentplaner mit den Bäumen von Wowhead, gespeicherte Builds und Guides. (Mixin, wird in App eingemischt)."""
from __future__ import annotations

import time
import webbrowser

from tkinter import ttk
import tkinter as tk

from ..i18n import tr
from ..config import log, save_config
from ..guides import delete_guide, fetch_guide, guide_builds, is_guide_url, list_guides, load_guide, render_guide, save_guide
from ..images import background_url, cached_image, can_convert, fetch_images, icon_url
from ..reports import QUALITY_COLORS
from ..talents import TALENT_EDITIONS, Build, load_talents, parse_build_link, talent_class, talent_classes
from ..wowhead import wowhead_base
from .dialogs import Placeholder
from .discordshare import DISCORD_BTN
from .theme import THEME

ICON_SIZES = (28, 32, 36, 40, 44, 48, 56, 64)
TREE_COLS = 4
GREEN = "#40d040"            # Farben der Rang-Anzeige wie im Spiel und bei Wowhead
GOLD = "#ffd100"
GREY = "#6a6a6a"


class BuildsPage:
    """Teil des Hauptfensters (wird in App eingemischt)."""

    BUILD_VIEWS = (("planner", "Talentplaner"), ("guides", "Guides"))

    # --- Aufbau ----------------------------------------------------------------------- #
    def _page_builds(self):
        page, head = self._page("builds", tr("Planen"), "Builds")
        self.bld_data: dict | None = None          # Talentdaten der gewählten Ausgabe
        self.bld_build: Build | None = None
        self.bld_loading = ""
        self.bld_imgs: dict = {}                    # (Adresse, Größe) -> PhotoImage
        self.bld_img_asked: set = set()
        self.bld_hits: list = []                    # anklickbare Flächen: (x0, y0, x1, y1, Talent-ID)
        self.bld_hover = None
        self.bld_draw_job = None
        self.bld_saved_rows: list[dict] = []
        self.gd_rows: list[dict] = []
        self.gd_current: dict | None = None
        self.bld_view = self.cfg.get("builds_view") if self.cfg.get("builds_view") in dict(self.BUILD_VIEWS) else "planner"
        edition = self.cfg.get("builds_edition")
        if edition not in TALENT_EDITIONS:
            edition = "forever" if "forever" in (self.cfg.get("flavor") or "") or not self.cfg.get("flavor") else "classic"
        self.bld_edition = edition
        self.bld_link_var = tk.StringVar()
        self.bld_ed_var = tk.StringVar(value=tr(TALENT_EDITIONS[edition][0]))
        self.bld_class_var = tk.StringVar()
        self.bld_saved_var = tk.StringVar()
        self.bld_status_var = tk.StringVar()

        row = ttk.Frame(page)
        row.pack(fill="x", pady=(12, 0))
        self.bld_view_btns = {}
        for i, (key, label) in enumerate(self.BUILD_VIEWS):
            b = ttk.Button(row, text=tr(label), command=lambda k=key: self.bld_set_view(k))
            b.pack(side="left", padx=(0 if not i else 6, 0))
            self.bld_view_btns[key] = b
        ttk.Button(row, text=tr("Laden"), style="Primary.TButton", command=self.bld_paste).pack(side="right")
        self.bld_link_entry = ttk.Entry(row, textvariable=self.bld_link_var)
        self.bld_link_entry.pack(side="right", fill="x", expand=True, padx=(16, 8))
        Placeholder(self.bld_link_entry, self.bld_link_var, tr("Wowhead-Link einfügen: Talentrechner oder Guide"))
        self.bld_link_entry.bind("<Return>", lambda e: self.bld_paste())

        self.bld_frames = {"planner": ttk.Frame(page), "guides": ttk.Frame(page)}
        self._bld_planner(self.bld_frames["planner"])
        self._bld_guides(self.bld_frames["guides"])
        self.bld_set_view(self.bld_view, save=False)

    def _bld_planner(self, frame):
        t = THEME
        bar = ttk.Frame(frame)
        bar.pack(fill="x", pady=(10, 0))
        cb = ttk.Combobox(bar, textvariable=self.bld_ed_var, state="readonly", width=24,
                          values=[tr(label) for label, _ in TALENT_EDITIONS.values()])
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: self._bld_edition_changed())
        self.bld_class_cb = ttk.Combobox(bar, textvariable=self.bld_class_var, state="readonly", width=14)
        self.bld_class_cb.pack(side="left", padx=(6, 0))
        self.bld_class_cb.bind("<<ComboboxSelected>>", lambda e: self._bld_class_changed())
        self.bld_saved_cb = ttk.Combobox(bar, textvariable=self.bld_saved_var, state="readonly", width=30)
        self.bld_saved_cb.pack(side="left", padx=(6, 0), fill="x", expand=True)
        self.bld_saved_cb.bind("<<ComboboxSelected>>", lambda e: self._bld_saved_chosen())
        ttk.Button(bar, text=tr("Speichern"), command=self.bld_save).pack(side="left", padx=(6, 0))
        self.bld_del_btn = ttk.Button(bar, text=tr("Löschen"), command=self.bld_delete, state="disabled")
        self.bld_del_btn.pack(side="left", padx=(6, 0))

        bar2 = ttk.Frame(frame)
        bar2.pack(fill="x", pady=(8, 0))
        # erst die Knöpfe, dann der Status: Ein langer Status wird gekürzt, nicht die Knöpfe
        ttk.Button(bar2, text=DISCORD_BTN, command=self.share_build_discord).pack(side="right")
        ttk.Button(bar2, text=tr("Auf Wowhead öffnen ↗"), command=self.bld_open).pack(side="right", padx=(0, 6))
        ttk.Button(bar2, text=tr("Link kopieren"), command=self.bld_copy).pack(side="right", padx=(0, 6))
        ttk.Button(bar2, text=tr("Punkte zurücksetzen"), command=lambda: self.bld_reset()).pack(side="right", padx=(0, 6))
        ttk.Label(bar2, textvariable=self.bld_status_var, style="Body.TLabel", width=1).pack(side="left", fill="x", expand=True)

        body = ttk.Frame(frame)
        body.pack(fill="both", expand=True, pady=(8, 0))
        side = ttk.Frame(body, width=270)
        side.pack(side="right", fill="y", padx=(12, 0))
        side.pack_propagate(False)
        box = self._card_box(side, pady=(0, 0), fill="both", expand=True, title=tr("Talent"))
        tf, self.bld_text = self._text(box, height=9)
        tf.pack(fill="both", expand=True)
        self._bld_tags(self.bld_text)
        box2 = self._card_box(side, pady=(10, 0), fill="both", expand=True, title=tr("Skill-Reihenfolge"))
        tf2, self.bld_order_text = self._text(box2, height=8)
        tf2.pack(fill="both", expand=True)
        self._bld_tags(self.bld_order_text)
        self.bld_order_text.configure(tabs=(48,), wrap="none")
        self.bld_canvas = tk.Canvas(body, bg=t["bg"], highlightthickness=0, width=420, height=300)
        self.bld_canvas.pack(side="left", fill="both", expand=True)
        cv = self.bld_canvas
        cv.bind("<Configure>", lambda e: self._bld_schedule_draw())
        cv.bind("<Motion>", self._bld_motion)
        cv.bind("<Leave>", lambda e: self._bld_set_hover(None))
        cv.bind("<Button-1>", lambda e: self._bld_click(e, add=True))
        cv.bind("<Button-3>", lambda e: self._bld_click(e, add=False))
        cv.bind("<Button-2>", lambda e: self._bld_click(e, add=False))
        self._bld_show_talent(None)

    def _bld_guides(self, frame):
        body = ttk.Frame(frame)
        body.pack(fill="both", expand=True, pady=(10, 0))
        left = ttk.Frame(body, width=330)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        lf, self.gd_tree = self._list(left, (("title", tr("Guide")), ("ed", tr("Ausgabe"))), (230, 80), stretch=("title",))
        lf.pack(fill="both", expand=True)
        self.gd_tree.bind("<<TreeviewSelect>>", lambda e: self._gd_show())
        self.gd_tree.bind("<Delete>", lambda e: self.gd_delete())
        self.gd_tree.bind("<Double-1>", lambda e: self.gd_open())
        box = self._card_box(body, pady=(0, 0), side="left", fill="both", expand=True, padx=(14, 0), title=tr("Guide"))
        tf, self.gd_text = self._text(box, height=8)
        tf.pack(fill="both", expand=True)
        self._bld_tags(self.gd_text)
        btns = ttk.Frame(box, style="Panel.TFrame")
        btns.pack(fill="x", pady=(10, 0))
        self.gd_open_btn = ttk.Button(btns, text=tr("Auf Wowhead öffnen ↗"), style="Primary.TButton", command=self.gd_open, state="disabled")
        self.gd_open_btn.pack(side="left")
        self.gd_refresh_btn = ttk.Button(btns, text=tr("Aktualisieren"), command=self.gd_refresh, state="disabled")
        self.gd_refresh_btn.pack(side="left", padx=(6, 0))
        self.gd_discord_btn = ttk.Button(btns, text=DISCORD_BTN, command=self.share_guide_discord, state="disabled")
        self.gd_discord_btn.pack(side="left", padx=(6, 0))
        self.gd_del_btn = ttk.Button(btns, text=tr("Entfernen"), command=self.gd_delete, state="disabled")
        self.gd_del_btn.pack(side="right")

    def _bld_tags(self, txt):
        t = THEME
        txt.configure(spacing1=1, spacing3=1, padx=12, pady=10)
        txt.tag_configure("title", foreground=t["gold"], font=self.fonts["card"], spacing3=2)
        txt.tag_configure("h2", foreground=t["gold"], font=self.fonts["card"], spacing1=10, spacing3=4)
        txt.tag_configure("h3", foreground=t["gold"], font=self.fonts["bold"], spacing1=6, spacing3=2)
        txt.tag_configure("b", font=self.fonts["bold"])
        txt.tag_configure("i", font=self.fonts["sub"])
        txt.tag_configure("mono", font=("Consolas", 9), foreground=t["text_dim"])
        txt.tag_configure("ok", foreground=GREEN)
        txt.tag_configure("max", foreground=GOLD)
        txt.tag_configure("warn", foreground=t["warn"])
        txt.tag_configure("ent", foreground="#6ab7ff")
        txt.tag_configure("build", foreground=t["gold"], font=self.fonts["bold"])
        for i, color in enumerate(QUALITY_COLORS):
            txt.tag_configure(f"q{i}", foreground=color)
        txt.tag_configure("link", underline=False)
        txt.tag_bind("link", "<Enter>", lambda e: txt.configure(cursor="hand2"))
        txt.tag_bind("link", "<Leave>", lambda e: txt.configure(cursor=""))
        txt.tag_bind("link", "<Button-1>", lambda e, w=txt: self._bld_link_click(w, e))

    # --- Ansicht und Laden -------------------------------------------------------------- #
    def bld_set_view(self, key: str, save: bool = True):
        self.bld_view = key
        for k, f in self.bld_frames.items():
            f.pack_forget()
            self.bld_view_btns[k].configure(style="ToggleOn.TButton" if k == key else "ToggleOff.TButton")
        self.bld_frames[key].pack(fill="both", expand=True)
        if save:
            self.cfg["builds_view"] = key
            save_config(self.cfg)
            self.builds_open()

    def builds_open(self):
        """Beim Zeigen der Seite: Talentdaten laden (einmal je Ausgabe) bzw. die Guide-Liste füllen."""
        if self.bld_view == "guides":
            self._gd_fill()
        elif not self.bld_data or self.bld_data.get("edition") != self.bld_edition:
            self._bld_load_data()
        else:
            self._bld_schedule_draw()

    def _bld_load_data(self, refresh: bool = False, then=None):
        edition = self.bld_edition
        if self.bld_loading == edition:
            return
        self.bld_loading = edition
        self.bld_status_var.set(tr("Lade Talentbäume von Wowhead …"))

        def done(data, err):
            if self.bld_loading == edition:
                self.bld_loading = ""
            if edition != self.bld_edition:
                return
            if err or not data:
                log.warning("Talentdaten %s: %s", edition, err)
                self.bld_data, self.bld_build = None, None
                self.bld_status_var.set(tr("Die Talentbäume ließen sich nicht von Wowhead laden ({0}).", str(err)[:140]))
                self._bld_schedule_draw()
                return
            self.bld_data = data
            classes = talent_classes(edition)
            self.bld_class_cb.configure(values=[c.name for c in classes])
            last = self.cfg.get("builds_last", {}).get(edition, "")
            build = None
            if last:
                p = parse_build_link(last)
                if p and any(c.slug == p["cls"] for c in classes):
                    build = Build(data, p["cls"], edition).load(p["hash"], p["order"])
            self._bld_use(build or Build(data, classes[0].slug, edition))
            if then:
                then()
        self.run_quiet(lambda: load_talents(edition, refresh=refresh), done)

    def _bld_use(self, build: Build, name: str = ""):
        self.bld_build = build
        self.bld_class_var.set(build.cls.name)
        self._bld_fill_saved(select=name)
        self._bld_changed(remember=False)

    def _bld_edition_changed(self):
        label = self.bld_ed_var.get()
        edition = next((k for k, (l, _) in TALENT_EDITIONS.items() if tr(l) == label), "forever")
        if edition == self.bld_edition:
            return
        self.bld_edition = edition
        self.cfg["builds_edition"] = edition
        save_config(self.cfg)
        self.bld_data, self.bld_build = None, None
        self._bld_load_data()

    def _bld_class_changed(self):
        if not self.bld_data:
            return
        cls = next((c for c in talent_classes(self.bld_edition) if c.name == self.bld_class_var.get()), None)
        if cls and (not self.bld_build or cls.slug != self.bld_build.cls.slug):
            self._bld_use(Build(self.bld_data, cls.slug, self.bld_edition))

    # --- Gespeicherte Builds ------------------------------------------------------------ #
    def _bld_store(self) -> list:
        rows = self.cfg.get("builds")
        if not isinstance(rows, list):
            rows = self.cfg["builds"] = []
        return rows

    def _bld_fill_saved(self, select: str = ""):
        rows = [r for r in self._bld_store() if isinstance(r, dict) and r.get("edition") == self.bld_edition]
        self.bld_saved_rows = rows
        labels = []
        for r in rows:
            p = parse_build_link(r.get("link", ""))
            cls = talent_class(p["cls"]) if p else None
            labels.append(f"{r.get('name', '?')}  ·  {cls.name if cls else '?'} {r.get('summary', '')}")
        self.bld_saved_labels = labels
        self.bld_saved_cb.configure(values=labels)
        idx = next((i for i, r in enumerate(rows) if r.get("name") == select), -1) if select else -1
        self.bld_saved_var.set(labels[idx] if idx >= 0 else tr("Gespeicherte Builds ({0})", len(rows)))
        self.bld_del_btn.configure(state="normal" if idx >= 0 else "disabled")

    def _bld_saved_row(self) -> dict | None:
        try:
            return self.bld_saved_rows[self.bld_saved_labels.index(self.bld_saved_var.get())]
        except (ValueError, AttributeError, IndexError):
            return None

    def _bld_saved_chosen(self):
        r = self._bld_saved_row()
        self.bld_saved_cb.selection_clear()
        if not r or not self.bld_data:
            return
        p = parse_build_link(r.get("link", ""))
        if not p:
            return
        self._bld_use(Build(self.bld_data, p["cls"], self.bld_edition).load(p["hash"], p["order"]), name=r.get("name", ""))
        self.set_status(tr("Build geladen: {0}", r.get("name", "")))

    def bld_save(self):
        b = self.bld_build
        if not b:
            return
        current = self._bld_saved_row()
        name = self.ask_text(tr("Name für diesen Build ({0} {1}):", b.cls.name, b.summary()),
                             initial=current.get("name", "") if current else f"{b.cls.name} {b.summary()}", ok=tr("Speichern"))
        if not name:
            return
        rows = self._bld_store()
        rows[:] = [r for r in rows if not (isinstance(r, dict) and r.get("edition") == b.edition and r.get("name") == name)]
        rows.insert(0, {"name": name, "edition": b.edition, "link": b.link(), "summary": b.summary(), "saved": int(time.time())})
        save_config(self.cfg)
        self._bld_fill_saved(select=name)
        self.set_status(tr("Build gespeichert: {0}", name))

    def bld_delete(self):
        r = self._bld_saved_row()
        if not r or not self.ask(tr("Build „{0}“ löschen?", r.get("name", "")), yes=tr("Löschen")):
            return
        rows = self._bld_store()
        rows[:] = [x for x in rows if x is not r]
        save_config(self.cfg)
        self._bld_fill_saved()

    # --- Aktionen ----------------------------------------------------------------------- #
    def _bld_link_text(self) -> str:
        return self.bld_link_var.get().strip()

    def bld_paste(self):
        """Link aus dem Feld (oder der Zwischenablage): Talentrechner -> Planer, Guide -> speichern."""
        text = self._bld_link_text()
        if not text:
            try:
                text = self.clipboard_get().strip()
            except tk.TclError:
                text = ""
        if is_guide_url(text) and "talent-calc" not in text:
            self.gd_add(text)
        elif "talent-calc" in text and parse_build_link(text):
            self.bld_open_link(text)
        else:
            self.warn(tr("Das ist kein Link zu einem Wowhead-Talentrechner oder -Guide. Beispiel: "
                         "https://www.wowhead.com/forever/de/talent-calc/shaman/…"))
            return
        self.bld_link_var.set("")

    def bld_open_link(self, link: str, edition: str = ""):
        """Öffnet einen Build im Planer (wechselt dafür bei Bedarf die Ausgabe)."""
        p = parse_build_link(link)
        if not p:
            return
        edition = p["edition"] or edition or self.bld_edition
        if edition not in TALENT_EDITIONS:
            edition = self.bld_edition

        def apply():
            if not self.bld_data:
                return
            b = Build(self.bld_data, p["cls"], edition).load(p["hash"], p["order"])
            self._bld_use(b)
            self._bld_remember()
            notes = self._bld_notes(b)
            if notes:
                self.warn(notes)
            else:
                self.set_status(tr("Build geladen: {0} {1}", b.cls.name, b.summary()))
        if self.bld_view != "planner":
            self.bld_set_view("planner", save=False)
            self.cfg["builds_view"] = "planner"
        if edition != self.bld_edition or not self.bld_data:
            self.bld_edition = edition
            self.cfg["builds_edition"] = edition
            self.bld_ed_var.set(tr(TALENT_EDITIONS[edition][0]))
            self.bld_data, self.bld_build = None, None
            self._bld_load_data(then=apply)
        else:
            apply()

    @staticmethod
    def _bld_notes(b: Build) -> str:
        """Hinweise nach dem Einlesen eines Links, der nicht mehr ganz zu den aktuellen Bäumen passt."""
        if "version" in b.notes or "format" in b.notes:
            return tr("Der Link stammt aus einer Fassung der Talentbäume, die Leeroyzan nicht kennt – die Punkte konnten nicht übernommen werden.")
        gone = [n.split(":", 1)[1] for n in b.notes if n.startswith(("removed:", "unreachable:"))]
        if gone or "over" in b.notes or "extra" in b.notes:
            return tr("Der Build passt nicht mehr ganz zu den aktuellen Talentbäumen. Nicht übernommen: {0}",
                      ", ".join(dict.fromkeys(gone)) or "–")
        return ""

    def bld_reset(self, tree: int | None = None):
        if self.bld_build:
            self.bld_build.reset(tree)
            self._bld_changed()

    def bld_copy(self):
        if self.bld_build:
            url = self.bld_build.url()
            self.clipboard_clear()
            self.clipboard_append(url)
            self.set_status(tr("Link kopiert: {0}", url))

    def bld_open(self):
        if self.bld_build:
            self.open_link(self.bld_build.url())
        else:
            self.open_link(f"{wowhead_base(self.bld_edition)}/talent-calc")

    def _bld_remember(self):
        if self.bld_build:
            self.cfg.setdefault("builds_last", {})[self.bld_edition] = self.bld_build.link()
            save_config(self.cfg)

    def _bld_changed(self, remember: bool = True):
        b = self.bld_build
        if b:
            left = b.max_points - b.spent
            text = tr("{0}  {1}  ·  {2} von {3} Punkten", b.cls.name, b.summary(), b.spent, b.max_points)
            if b.spent:
                text += "  ·  " + tr("ab Stufe {0}", b.required_level)
            if not left:
                text += "  ·  " + tr("alle Punkte verteilt")
            self.bld_status_var.set(text)
            if remember:
                self._bld_remember()
        self._bld_fill_order()
        self._bld_show_talent(self.bld_hover)
        self._bld_schedule_draw()

    def _bld_fill_order(self):
        b = self.bld_build
        parts: list = []
        if b and b.order:
            steps = b.steps()
            i = 0
            while i < len(steps):
                j = i
                while j + 1 < len(steps) and steps[j + 1]["id"] == steps[i]["id"]:
                    j += 1
                s, e = steps[i], steps[j]
                level = str(s["level"]) if i == j else f"{s['level']}–{e['level']}"
                parts.append((level + "\t", "dim"))
                parts.append((s["name"], ""))
                parts.append((f"  {e['rank']}/{s['max']}\n", "max" if e["rank"] == s["max"] else "ok"))
                i = j + 1
        else:
            parts.append((tr("Hier steht, in welcher Reihenfolge und auf welcher Stufe du die Punkte setzt."), "dim"))
        self._set_text(self.bld_order_text, parts=parts)

    # --- Zeichnen ----------------------------------------------------------------------- #
    def _bld_schedule_draw(self):
        if self.bld_draw_job:
            try:
                self.after_cancel(self.bld_draw_job)
            except tk.TclError:
                pass
        self.bld_draw_job = self.after(30, self._bld_draw)

    def _bld_image(self, url: str, size: tuple[int, int], wanted: list):
        key = (url, size)
        img = self.bld_imgs.get(key)
        if img is None:
            path = cached_image(url, size, fetch=False)
            if path:
                try:
                    img = self.bld_imgs[key] = tk.PhotoImage(master=self, file=str(path))
                except tk.TclError as e:
                    log.info("Bild %s nicht lesbar: %s", path, e)
                    self.bld_imgs[key] = img = False
            elif key not in self.bld_img_asked:
                wanted.append(key)
        return img or None

    def _bld_draw(self):
        self.bld_draw_job = None
        cv, t = self.bld_canvas, THEME
        try:
            w, h = cv.winfo_width(), cv.winfo_height()
        except tk.TclError:
            return
        cv.delete("all")
        self.bld_hits = []
        b = self.bld_build
        if not b:
            cv.create_text(max(w, 200) // 2, max(h, 100) // 2, fill=t["text_dim"], font=self.fonts["base"], width=max(200, w - 40),
                           justify="center", text=self.bld_status_var.get() or tr("Lade Talentbäume von Wowhead …"))
            return
        ntrees = len(b.trees)
        rows = max([t2["row"] for tree in b.trees for t2 in tree] + [6]) + 1
        gap, head, pad = 10, 30, 8
        cell = int(min((w - gap * (ntrees - 1) - 2 * pad * ntrees) / (TREE_COLS * ntrees), (h - head - 2 * pad - 2) / rows))
        cell = max(34, min(84, cell))
        icon = max([s for s in ICON_SIZES if s <= cell - 12] or [ICON_SIZES[0]])
        tw, th = TREE_COLS * cell + 2 * pad, rows * cell + 2 * pad
        x0 = max(0, (w - (tw * ntrees + gap * (ntrees - 1))) // 2)
        wanted: list = []
        env = self.bld_data.get("env") or "classic"
        badge_font = (self.fonts["small"][0], 8 if icon >= 40 else 7, "bold")
        for ti, tree in enumerate(b.trees):
            tx = x0 + ti * (tw + gap)
            info = b.cls.trees[ti]
            # Kopf: Icon, Name, Punkte
            cv.create_rectangle(tx, 0, tx + tw, head, fill=t["panel"], outline=t["border_soft"])
            himg = self._bld_image(icon_url(info["icon"], "medium"), (20, 20), wanted)
            if himg:
                cv.create_image(tx + 6, head // 2, image=himg, anchor="w")
            cv.create_text(tx + 32, head // 2, anchor="w", fill=t["text"], font=self.fonts["bold"], text=info["name"])
            cv.create_text(tx + tw - 8, head // 2, anchor="e", fill=t["text_dim"], font=self.fonts["bold"],
                           text=f"{b.tree_points(ti)} / {b.max_points}")
            # Hintergrund des Baums
            cv.create_rectangle(tx, head, tx + tw, head + th, fill="#0b0d10", outline=t["border_soft"])
            bg = self._bld_image(background_url(env, info["tab"]), (tw - 2, th - 2), wanted)
            if bg:
                cv.create_image(tx + 1, head + 1, image=bg, anchor="nw")

            def center(talent, tx=tx):
                return tx + pad + talent["col"] * cell + cell // 2, head + pad + talent["row"] * cell + cell // 2
            # Pfeile zwischen Talenten
            for talent in tree:
                for rid, qty in talent["req"]:
                    if rid not in b.by_id or b.by_id[rid][0] != ti:
                        continue
                    src = b.by_id[rid][2]
                    sx, sy = center(src)
                    ex, ey = center(talent)
                    half = icon // 2 + 2
                    met = b.rank(rid) >= qty and b.tree_points(ti) >= talent["req_points"]
                    color = GOLD if met else GREY
                    if src["col"] == talent["col"]:
                        pts = [sx, sy + half, ex, ey - half]
                    elif src["row"] == talent["row"]:
                        d = 1 if ex > sx else -1
                        pts = [sx + d * half, sy, ex - d * half, ey]
                    else:
                        d = 1 if ex > sx else -1
                        pts = [sx + d * half, sy, ex, sy, ex, ey - half]
                    cv.create_line(*pts, fill="#000000", width=7, arrow="last", arrowshape=(10, 11, 6))
                    cv.create_line(*pts, fill=color, width=4, arrow="last", arrowshape=(9, 10, 5))
            # Talente
            for talent in tree:
                cx, cy = center(talent)
                r = icon // 2
                tid, rank = talent["id"], b.rank(talent["id"])
                reason = b.why_not(tid)
                open_ = not reason or (rank and reason in ("max", "points"))
                color = GOLD if rank >= talent["max"] else GREEN if (rank or not reason) else GREY
                cv.create_rectangle(cx - r - 2, cy - r - 2, cx + r + 2, cy + r + 2, fill="#000000", outline=color, width=2)
                img = self._bld_image(icon_url(talent["icon"]), (icon, icon), wanted)
                if img:
                    cv.create_image(cx, cy, image=img)
                else:
                    cv.create_rectangle(cx - r, cy - r, cx + r, cy + r, fill=t["pill"], outline="")
                    cv.create_text(cx, cy, fill=t["text_dim"], font=self.fonts["bold"], text=talent["name"][:2])
                if not open_ and not rank:
                    cv.create_rectangle(cx - r, cy - r, cx + r, cy + r, fill="#000000", outline="", stipple="gray50")
                if rank or not reason:
                    label = f"{rank}/{talent['max']}"
                    bw = 9 + 5 * len(label) if icon < 40 else 10 + 6 * len(label)
                    bx, by = cx + r + 4, cy + r + 4
                    cv.create_rectangle(bx - bw, by - 14, bx, by, fill="#000000", outline="#2a2a2a")
                    cv.create_text(bx - bw / 2, by - 7, fill=color, font=badge_font, text=label)
                if self.bld_hover == tid:
                    cv.create_rectangle(cx - r - 4, cy - r - 4, cx + r + 4, cy + r + 4, outline=t["text"], width=1)
                self.bld_hits.append((cx - r - 3, cy - r - 3, cx + r + 3, cy + r + 3, tid))
        if wanted and can_convert():
            self.bld_img_asked.update(wanted)
            self.run_quiet(lambda: fetch_images(wanted), lambda n, err: n and self._bld_schedule_draw())

    # --- Maus --------------------------------------------------------------------------- #
    def _bld_at(self, x: int, y: int):
        return next((tid for x0, y0, x1, y1, tid in self.bld_hits if x0 <= x <= x1 and y0 <= y <= y1), None)

    def _bld_motion(self, e):
        self._bld_set_hover(self._bld_at(e.x, e.y))

    def _bld_set_hover(self, tid):
        if tid == self.bld_hover:
            return
        self.bld_hover = tid
        try:
            self.bld_canvas.configure(cursor="hand2" if tid is not None else "")
        except tk.TclError:
            return
        if tid is not None:
            self._bld_show_talent(tid)
        self._bld_schedule_draw()

    def _bld_click(self, e, add: bool):
        b, tid = self.bld_build, self._bld_at(e.x, e.y)
        if not b or tid is None:
            return
        full = bool(e.state & 0x0001)                  # Umschalt: alle Ränge
        n = b.add(tid, full) if add else b.remove(tid, full)
        self.bld_hover = tid
        if n:
            self._bld_changed()
        else:
            self._bld_show_talent(tid)

    def _bld_show_talent(self, tid):
        b = self.bld_build
        if not b or tid not in b.by_id:
            self._set_text(self.bld_text, parts=[
                (tr("Zeige mit der Maus auf ein Talent, um die Beschreibung zu sehen."), "dim"), ("\n\n", ""),
                (tr("Linksklick setzt einen Punkt, Rechtsklick nimmt ihn zurück. Mit Umschalt gleich alle Ränge."), "dim")])
            return
        ti, _, t = b.by_id[tid]
        rank = b.rank(tid)
        parts = [(t["name"] + "\n", "title"),
                 (tr("Rang {0}/{1}", rank, t["max"]) + "\n", "max" if rank >= t["max"] else "ok" if rank else "dim")]
        if t["req_points"]:
            ok = b.tree_points(ti) >= t["req_points"]
            parts.append((tr("Benötigt {0} Punkte in {1}", t["req_points"], b.cls.trees[ti]["name"]) + "\n", "dim" if ok else "warn"))
        for rid, qty in t["req"]:
            if rid in b.by_id:
                ok = b.rank(rid) >= qty
                parts.append((tr("Benötigt {0} Punkte in {1}", qty, b.by_id[rid][2]["name"]) + "\n", "dim" if ok else "warn"))
        desc = t["desc"]
        if rank and desc[rank - 1]:
            parts.append(("\n" + desc[rank - 1] + "\n", ""))
        if rank < t["max"] and desc[rank]:
            if rank:
                parts.append(("\n" + tr("Nächster Rang:") + "\n", "dim"))
                parts.append((desc[rank] + "\n", "dim"))
            else:
                parts.append(("\n" + desc[rank] + "\n", ""))
        reason = b.why_not(tid)
        if reason == "points":
            parts.append(("\n" + tr("Alle Talentpunkte sind verteilt.") + "\n", "warn"))
        elif rank and not b.can_remove(tid):
            parts.append(("\n" + tr("Lässt sich gerade nicht zurücknehmen – andere Talente bauen darauf auf.") + "\n", "dim"))
        self._set_text(self.bld_text, parts=parts)

    # --- Guides ------------------------------------------------------------------------- #
    def _gd_fill(self, select: str = ""):
        self.gd_rows = list_guides()
        tv = self.gd_tree
        keep = select or (tv.selection()[0] if tv.selection() else "")
        tv.delete(*tv.get_children())
        for i, g in enumerate(self.gd_rows):
            ed = TALENT_EDITIONS.get(g["edition"], ("Retail" if not g["edition"] else g["edition"], 0))[0].split(" (")[0]
            tv.insert("", "end", iid=g["id"], values=(g["title"], ed.replace(" Classic", "")), tags=("odd",) if i % 2 else ())
        if self.gd_rows:
            tv.selection_set(keep if keep and tv.exists(keep) else self.gd_rows[0]["id"])
        else:
            self._gd_show()

    def _gd_selected(self) -> str:
        sel = self.gd_tree.selection()
        return sel[0] if sel else ""

    def _gd_show(self):
        gid = self._gd_selected()
        g = load_guide(gid) if gid else None
        self.gd_current = g
        state = "normal" if g else "disabled"
        for btn in (self.gd_open_btn, self.gd_refresh_btn, self.gd_discord_btn, self.gd_del_btn):
            btn.configure(state=state)
        txt = self.gd_text
        txt.configure(state="normal")
        txt.delete("1.0", "end")
        if not g:
            txt.insert("end", tr("Noch kein Guide gespeichert. Füge oben den Link eines Wowhead-Guides ein und klicke auf „Laden“ – "
                                 "Leeroyzan speichert ihn, damit du ihn auch ohne Internet lesen kannst. Talent-Builds aus dem "
                                 "Guide lassen sich direkt im Talentplaner öffnen."), "dim")
            txt.configure(state="disabled")
            return
        txt.insert("end", g.get("title", "") + "\n", "title")
        meta = [x for x in (g.get("author") and tr("von {0}", g["author"]), g.get("updated") and tr("Stand {0}", g["updated"]),
                            tr("gespeichert am {0}", time.strftime("%d.%m.%Y", time.localtime(float(g.get("saved") or 0))))) if x]
        txt.insert("end", "  ·  ".join(meta) + "\n", "dim")
        builds = guide_builds(g)
        for i, p in enumerate(builds):
            cls = talent_class(p["cls"])
            txt.insert("end", tr("▶ Talent-Build im Planer öffnen ({0})", cls.name if cls else p["cls"]) + "\n",
                       ("build", f"build:{i}", "link"))
        txt.insert("end", "\n")
        for text, tags in render_guide(g, wowhead_base(g.get("edition") or "")):
            txt.insert("end", text, tags)
        txt.configure(state="disabled")
        txt.yview_moveto(0)

    def _bld_link_click(self, txt, event):
        tags = txt.tag_names(txt.index(f"@{event.x},{event.y}"))
        target = next((x for x in tags if x.startswith(("url:", "build:"))), "")
        if target.startswith("build:") and self.gd_current:
            builds = guide_builds(self.gd_current)
            i = int(target[6:])
            if i < len(builds):
                self.bld_open_link(builds[i]["link"], edition=builds[i]["edition"])
        elif target.startswith(("url:https://", "url:http://")):
            self.open_link(target[4:])

    def gd_add(self, url: str, refresh: bool = False):
        url = url.strip()
        if self.bld_view != "guides":
            self.bld_set_view("guides", save=False)
            self.cfg["builds_view"] = "guides"
            self._gd_fill()
        self.set_status(tr("Lade Guide von Wowhead …"))

        def done(guide, err):
            if err or not guide:
                log.warning("Guide %s: %s", url, err)
                self.notify(tr("Der Guide ließ sich nicht laden ({0}). Du kannst ihn im Browser öffnen.", str(err)[:160]), "warn",
                            [(tr("Im Browser öffnen"), lambda: webbrowser.open(url, new=2))], key="guide-load")
                return
            gid = save_guide(guide)
            self._gd_fill(select=gid)
            self._gd_show()
            self.set_status(tr("Guide aktualisiert: {0}", guide["title"]) if refresh else tr("Guide gespeichert: {0}", guide["title"]))
        self.run_quiet(lambda: fetch_guide(url), done)

    def gd_open(self):
        if self.gd_current and self.gd_current.get("url"):
            self.open_link(self.gd_current["url"])

    def gd_refresh(self):
        if self.gd_current and self.gd_current.get("url"):
            self.gd_add(self.gd_current["url"], refresh=True)

    def gd_delete(self):
        gid = self._gd_selected()
        g = self.gd_current
        if not gid or not g or not self.ask(tr("Guide „{0}“ aus Leeroyzan entfernen?", g.get("title", "")), yes=tr("Entfernen")):
            return
        delete_guide(gid)
        self._gd_fill()
