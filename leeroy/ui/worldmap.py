"""Seite „Karte“: Wege und Orte deiner Sitzungen, Quest-Ebene und Suche auf den Zonenkarten.
(Mixin, wird in App eingemischt)."""
from __future__ import annotations

import os
import webbrowser
from datetime import datetime

from tkinter import ttk
import tkinter as tk

from ..config import log
from ..i18n import cur_lang, tr
from ..mapdata import (
    DEFAULT_MAP_SIZE, PERIODS, ZoneIndex, clear_image_misses, filter_sessions, map_activity, map_image, map_search,
    parse_route, pin_title, quest_layer, read_questie_zone_maps, scaled_map_image, screenshot_for, session_pins,
    session_routes, way_command, zone_for_char,
)
from ..questdb import QuestDBError, load_questdb
from ..reports import CLASS_NAMES, fmt_dur
from ..sessions import load_sessions, link_signature
from ..wowhead import wowhead_url
from .dialogs import Placeholder
from .theme import THEME

# Ebenen: Schlüssel, Name, Farbe, Zeichen (die Zeichen gibt es in Segoe UI Symbol)
MAP_LAYERS = [
    ("route", "Wege", "#e6bb70", "〰"),
    ("death", "Tode", "#e0524a", "✝"),
    ("level", "Stufenaufstiege", "#ffd54a", "▲"),
    ("boss", "Bosse und seltene Gegner", "#c77dff", "☠"),
    ("loot", "Seltene Beute", "#4a9cff", "◆"),
    ("gather", "Sammelpunkte", "#7ddc6a", "✿"),
    ("found", "Entdeckt", "#4fc3d9", "⚑"),
    ("quests", "Angenommen und abgegeben", "#d6c37a", "!"),
    ("shot", "Screenshots", "#c8ccca", "◉"),
    ("q_active", "Aktive Quests", "#ffd100", "?"),
    ("q_avail", "Verfügbare Quests", "#ffd100", "!"),
]
LAYER_OF_PIN = {"death": "death", "level": "level", "boss": "boss", "rare": "boss", "loot": "loot", "gather": "gather",
                "found": "found", "qa": "quests", "qd": "quests", "shot": "shot"}
PIN_GLYPH = {"death": "✝", "level": "▲", "boss": "☠", "rare": "★", "loot": "◆", "found": "⚑", "qa": "!", "qd": "?",
             "shot": "◉"}
GATHER_GLYPH = {"herb": "✿", "mining": "⛏", "skinning": "✂", "fishing": "≈"}
DEFAULT_LAYERS = {k: True for k, *_ in MAP_LAYERS}
ROUTE_COLORS = ["#e6bb70", "#4fc3d9", "#c77dff", "#7ddc6a", "#ff8a65", "#4a9cff", "#f06292", "#d6c37a"]
QUEST_SPOT_COLORS = ["#ffd100", "#ff9f43", "#4fc3d9", "#c77dff", "#7ddc6a", "#f06292", "#4a9cff", "#e0e0e0"]
DIFF_COLORS = {"gray": "#9d9d9d", "green": "#40c040", "yellow": "#ffd100", "orange": "#ff8040", "red": "#ff2020"}
QUALITY = {2: "#1eff00", 3: "#4a9cff", 4: "#c77dff", 5: "#ff8000"}
ZOOMS = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0]   # fein fürs Einpassen, Mausrad springt ≥ 25 %
MAX_IMAGE_PX = 4200          # größer wird ein Kartenbild nie gerechnet (Speicher)
REPLAY_FRAMES = 450          # Bilder einer Wiedergabe (bei 40 ms je Bild: 18 s)
TYPE_DELAY = 400             # ms nach dem letzten Tastendruck, bis die getippte Karte geladen wird
SHIFT, CONTROL = 0x0001, 0x0004


def typeahead(names: list[str], current: int, typed: str, cycle: bool) -> int:
    """Index des Eintrags, der mit `typed` beginnt (Groß- und Kleinschreibung egal), sonst -1.

    cycle=True (ein Buchstabe, mehrmals gedrückt): der nächste passende nach dem aktuellen, am Ende wieder vorn.
    cycle=False (mit Umschalt getippter Wortanfang): der aktuelle, wenn er noch passt, sonst der erste passende."""
    want = (typed or "").casefold()
    n = len(names)
    if not want or not n:
        return -1

    def fits(i):
        return names[i].casefold().startswith(want)
    if not cycle and 0 <= current < n and fits(current):
        return current
    start = current + 1 if cycle and 0 <= current < n else 0
    for k in range(n):
        i = (start + k) % n
        if fits(i):
            return i
    return -1


class MapPage:
    """Teil des Hauptfensters (wird in App eingemischt)."""

    # ----- Aufbau ------------------------------------------------------------------------- #
    def _page_map(self):
        t = THEME
        page, head = self._page("map", tr("Leeroylink"), tr("Karte"))
        self.map_status_var = tk.StringVar()
        ttk.Label(head, textvariable=self.map_status_var, style="Body.TLabel").pack(side="right", anchor="s")
        self.map_zone_var, self.map_char_var, self.map_period_var = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.map_search_var, self.map_info_var, self.map_crumb_var = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.map_replay_var = tk.StringVar()
        saved = self.cfg.get("map_layers") or {}
        self.map_layer_vars = {k: tk.BooleanVar(value=bool(saved.get(k, DEFAULT_LAYERS[k]))) for k, *_ in MAP_LAYERS}
        self.map_ui = 0
        self.map_idx: ZoneIndex | None = None
        self.map_db = None
        self.map_sessions: list[dict] = []
        self._map_zone_ids: list[int] = []
        self._map_char_keys: list[str] = []
        self._map_hit: dict[int, tuple] = {}
        self._map_img = None
        self._map_img_url = ""
        self._map_img_size = DEFAULT_MAP_SIZE
        self._map_img_scaled: dict[float, tk.PhotoImage] = {}
        self._map_img_note = ""
        self._map_view = {"z": 1.0, "tx": 0.0, "ty": 0.0}
        self._map_auto_fit = True           # passt sich der Fläche an, bis man selbst zoomt oder verschiebt
        self._map_drag = None
        self._map_layer = {"routes": [], "pins": [], "quests": {"active": [], "available": [], "note": ""}}
        self._map_sel = None
        self._map_hl: list[tuple] = []
        self._map_replay = None
        self._map_seq = 0
        self._map_loaded_key = None
        self._map_search_hits: list[dict] = []

        bar = ttk.Frame(page)
        bar.pack(fill="x", pady=(12, 0))
        self.map_zone_cb = ttk.Combobox(bar, textvariable=self.map_zone_var, state="readonly", width=30, height=30)
        self.map_zone_cb.pack(side="left")
        self.map_zone_cb.bind("<<ComboboxSelected>>", lambda e: self._map_zone_picked())
        self._map_zone_names: list[str] = []
        self._map_type_buf = ""
        self._map_type_job = None
        self._map_typeahead_setup()
        self.map_char_cb = ttk.Combobox(bar, textvariable=self.map_char_var, state="readonly", width=22)
        self.map_char_cb.pack(side="left", padx=(8, 0))
        self.map_char_cb.bind("<<ComboboxSelected>>", lambda e: self._map_filter_changed())
        self.map_period_cb = ttk.Combobox(bar, textvariable=self.map_period_var, state="readonly", width=16,
                                          values=[tr(v) for v in PERIODS.values()])
        self.map_period_cb.pack(side="left", padx=(8, 0))
        self.map_period_cb.bind("<<ComboboxSelected>>", lambda e: self._map_filter_changed())
        for text, cmd in (("⤢", self.map_fit), ("−", lambda: self.map_zoom_step(-1)), ("+", lambda: self.map_zoom_step(1))):
            ttk.Button(bar, text=text, width=3, command=cmd).pack(side="right", padx=(4, 0))
        se = ttk.Entry(bar, textvariable=self.map_search_var, width=30)
        se.pack(side="right", padx=(8, 4))
        se.bind("<Return>", lambda e: self.map_search())
        Placeholder(se, self.map_search_var, tr("Suchen: Zone, NPC, Quest …"))
        self.map_search_entry = se

        body = ttk.Frame(page)
        body.pack(fill="both", expand=True, pady=(10, 0))
        side = ttk.Frame(body, width=310)
        side.pack(side="right", fill="y", padx=(12, 0))
        side.pack_propagate(False)
        left = ttk.Frame(body)
        left.pack(side="left", fill="both", expand=True)
        crumb = tk.Label(left, textvariable=self.map_crumb_var, bg=t["bg"], fg=t["gold"], font=self.fonts["bold"],
                         anchor="w", cursor="hand2")
        crumb.pack(fill="x")
        crumb.bind("<Button-1>", lambda e: self.map_up())
        frame = tk.Frame(left, bg=t["border_soft"])
        frame.pack(fill="both", expand=True, pady=(4, 0))
        self.map_cv = tk.Canvas(frame, bg="#0a0f0f", highlightthickness=0, cursor="crosshair")
        self.map_cv.pack(fill="both", expand=True, padx=1, pady=1)
        ttk.Label(left, textvariable=self.map_info_var, style="Hint.TLabel", anchor="w").pack(fill="x", pady=(4, 0))
        cv = self.map_cv
        cv.bind("<Configure>", lambda e: self._map_on_resize())
        cv.bind("<ButtonPress-1>", self._map_press)
        cv.bind("<B1-Motion>", self._map_motion_drag)
        cv.bind("<ButtonRelease-1>", self._map_release)
        cv.bind("<Double-Button-1>", lambda e: self.map_zoom_step(1, (e.x, e.y)))
        cv.bind("<Motion>", self._map_hover)
        cv.bind("<Leave>", lambda e: self._map_hover_text(""))
        cv.bind("<MouseWheel>", lambda e: self.map_zoom_step(1 if e.delta > 0 else -1, (e.x, e.y)))
        cv.bind("<Button-4>", lambda e: self.map_zoom_step(1, (e.x, e.y)))
        cv.bind("<Button-5>", lambda e: self.map_zoom_step(-1, (e.x, e.y)))
        cv.bind("<Button-3>", self._map_context)

        # Ebenen
        lbox = self._card_box(side, pady=(0, 0), title=tr("Ebenen"))
        self._map_layer_labels = {}
        for key, name, color, glyph in MAP_LAYERS:
            row = ttk.Frame(lbox, style="Panel.TFrame")
            row.pack(fill="x")
            tk.Label(row, text=glyph, fg=color, bg=t["panel"], width=2, font=self.fonts["base"]).pack(side="left")
            cb = ttk.Checkbutton(row, text=tr(name), variable=self.map_layer_vars[key], command=self._map_layers_changed)
            cb.pack(side="left", fill="x", expand=True)
            self._map_layer_labels[key] = (cb, tr(name))
        # Wiedergabe
        rbox = self._card_box(side, pady=(10, 0), title=tr("Weg abspielen"))
        self.map_replay_cb = ttk.Combobox(rbox, textvariable=self.map_replay_var, state="readonly")
        self.map_replay_cb.pack(fill="x")
        self.map_replay_cb.bind("<<ComboboxSelected>>", lambda e: self.map_replay_stop(keep=False))
        rrow = ttk.Frame(rbox, style="Panel.TFrame")
        rrow.pack(fill="x", pady=(6, 0))
        self.map_play_btn = ttk.Button(rrow, text=tr("▶ Abspielen"), command=self.map_replay_toggle, width=12)
        self.map_play_btn.pack(side="left")
        self.map_replay_scale = ttk.Scale(rrow, from_=0, to=1000, orient="horizontal", command=self._map_replay_seek)
        self.map_replay_scale.pack(side="left", fill="x", expand=True, padx=(8, 0))
        # Auswahl
        dbox = self._card_box(side, pady=(10, 0), fill="both", expand=True, title=tr("Auswahl"))
        self.map_actions = ttk.Frame(dbox, style="Panel.TFrame")
        self.map_actions.pack(side="bottom", fill="x", pady=(8, 0))
        tf, self.map_text = self._text(dbox, height=6)
        tf.pack(fill="both", expand=True)
        self._tag_text(self.map_text)
        self.map_text.tag_configure("link", foreground=t["gold"], underline=True)
        self.map_text.tag_bind("link", "<Enter>", lambda e: self.map_text.configure(cursor="hand2"))
        self.map_text.tag_bind("link", "<Leave>", lambda e: self.map_text.configure(cursor=""))
        self._map_intro()

    def _map_intro(self):
        self._map_detail([(tr("Die Karte zeigt, wo du unterwegs warst und was dort passiert ist – aufgezeichnet von "
                              "Leeroylink in jeder Sitzung. Mit QuestieDB kommen deine Quests dazu: offene Ziele, "
                              "Abgabe und Quests, die du annehmen kannst."), "dim"),
                          ("\n\n" + tr("Mausrad: zoomen · Ziehen: verschieben · Rechtsklick: /way kopieren"), "dim")])

    # ----- Daten laden ----------------------------------------------------------------------- #
    def map_open(self, force: bool = False):
        """Beim Öffnen der Seite: Sitzungen, Kartenverzeichnis und QuestieDB laden (im Hintergrund)."""
        if not self.root_path or not self.flavor:
            self.map_status_var.set(tr("Wähle zuerst den WoW-Ordner."))
            return
        if not self._sess_importing and link_signature(self.root_path, self.flavor) != self._sess_sig:
            self.import_sessions()                         # meldet sich über _link_state_changed zurück
        key = (self.root_path, self.flavor, getattr(self, "_data_gen", 0))
        if self._map_loaded_key == key and not force:
            return
        self._map_loaded_key = key
        self._map_seq += 1
        seq, root, flavor = self._map_seq, self.root_path, self.flavor
        state = self.link_state
        self.map_status_var.set(tr("Lade Kartendaten …"))

        def load():
            sessions = load_sessions(flavor)
            db, qz, note = None, None, ""
            try:
                db = load_questdb(root, flavor)
                qz = read_questie_zone_maps(db.folder, db.flavor_name)
            except QuestDBError as e:
                note = str(e)
            except Exception as e:  # noqa – Karte geht auch ohne Quests
                log.warning("Karte: QuestieDB: %s", e)
                note = tr("QuestieDB konnte nicht gelesen werden: {0}", str(e)[:120])
            idx = ZoneIndex(state.get("mapIndex"), qz, state.get("zoneNames"))
            return sessions, db, idx, note

        def done(res, err):
            if seq != self._map_seq or (root, flavor) != (self.root_path, self.flavor):
                return
            if err:
                log.error("Karte laden: %s", err)
                self.map_status_var.set(tr("Kartendaten konnten nicht geladen werden."))
                self._map_loaded_key = None
                return
            self.map_sessions, self.map_db, self.map_idx, note = res
            self._map_db_note = note
            self._map_fill_filters()
            self._map_fill_zones()
            ui = self.map_ui or int(self.cfg.get("map_zone") or 0)
            if not ui or not self.map_idx.get(ui):
                ui = zone_for_char(self._map_char(), self._map_filtered())
            if not ui or not self.map_idx.get(ui):
                conts = self.map_idx.continents()
                ui = conts[0]["id"] if conts else 0
            self.map_show(ui, fit=True)
        self.run_quiet(load, done)

    def _map_char(self) -> dict | None:
        i = self.map_char_cb.current()
        key = self._map_char_keys[i] if 0 <= i < len(self._map_char_keys) else ""
        return self.link_state.get("chars", {}).get(key) if key else None

    def _map_char_key(self) -> str:
        i = self.map_char_cb.current()
        return self._map_char_keys[i] if 0 <= i < len(self._map_char_keys) else ""

    def _map_period(self) -> str:
        i = self.map_period_cb.current()
        keys = list(PERIODS)
        return keys[i] if 0 <= i < len(keys) else "7d"

    def _map_filtered(self) -> list[dict]:
        return filter_sessions(self.map_sessions, self._map_char_key(), self._map_period())

    def _map_fill_filters(self):
        chars = dict(self.link_state.get("chars", {}))
        for s in self.map_sessions:
            if s.get("char") and s["char"] not in chars:
                chars[s["char"]] = {"key": s["char"], "name": s.get("name", s["char"]), "lastSeen": s.get("stop", 0),
                                    "class": s.get("class", ""), "level": s.get("level", {}).get("to", 0)}
        order = sorted(chars.values(), key=lambda c: -(c.get("lastSeen") or 0))
        names = [c["name"] for c in order]
        self._map_char_keys = [""] + [c["key"] for c in order]
        labels = [tr("Alle Charaktere")] + [
            (c["name"] if names.count(c["name"]) == 1 else f"{c['name']} ({c.get('realm', '')})")
            + (f" · {c['level']}" if c.get("level") else "") for c in order]
        self.map_char_cb.configure(values=labels)
        want = self.cfg.get("map_char")
        if want is None and len(self._map_char_keys) > 1:
            want = self._map_char_keys[1]                     # zuerst der zuletzt gespielte
        self.map_char_cb.current(self._map_char_keys.index(want) if want in self._map_char_keys else 0)
        keys = list(PERIODS)
        want_p = self.cfg.get("map_period", "7d")
        self.map_period_cb.current(keys.index(want_p) if want_p in keys else keys.index("7d"))

    def _map_fill_zones(self):
        idx = self.map_idx
        act = map_activity(self._map_filtered())
        values, ids, names = [], [], []
        for c in idx.continents():
            values.append(tr("{0} – Übersicht", c["name"]))
            ids.append(c["id"])
            names.append(c["name"])
            for z in idx.zones_on(c["id"]):
                values.append(("   ● " if z["id"] in act else "      ") + z["name"])
                ids.append(z["id"])
                names.append(z["name"])
        self._map_zone_ids = ids
        self._map_zone_names = names
        self.map_zone_cb.configure(values=values)
        if self.map_ui in ids:
            self.map_zone_cb.current(ids.index(self.map_ui))

    def _map_filter_changed(self):
        self.cfg["map_char"] = self._map_char_key()
        self.cfg["map_period"] = self._map_period()
        self.map_replay_stop(keep=False)
        self._map_fill_zones()
        self._map_compute()

    def _map_layers_changed(self):
        self.cfg["map_layers"] = {k: v.get() for k, v in self.map_layer_vars.items()}
        if self.map_layer_vars["q_active"].get() or self.map_layer_vars["q_avail"].get():
            self._map_compute()
        else:
            self.map_redraw()

    def _map_zone_picked(self):
        i = self.map_zone_cb.current()
        if 0 <= i < len(self._map_zone_ids):
            self.map_show(self._map_zone_ids[i], fit=True)

    # ----- Tippen in der Kartenauswahl ------------------------------------------------------ #
    def _map_typeahead_setup(self):
        """Buchstaben tippen springt durch die Kartenliste – im geschlossenen Feld und in der offenen Liste.

        Ein Buchstabe: reihum durch alle Gebiete mit diesem Anfangsbuchstaben. Umschalt gedrückt halten und
        mehrere Buchstaben tippen: direkt zum Gebiet mit diesem Wortanfang (z. B. „Stu“ -> Sturmwind)."""
        cb = self.map_zone_cb
        cb.bind("<KeyPress>", self._map_zone_key)
        for key in ("<KeyRelease-Shift_L>", "<KeyRelease-Shift_R>", "<FocusOut>"):
            cb.bind(key, self._map_type_reset, add="+")
        try:                                           # die Liste beim Aufklappen ist ein eigenes Tk-Fenster
            popdown = self.tk.call("ttk::combobox::PopdownWindow", str(cb))
            self._map_zone_lb = f"{popdown}.f.l"
            key_cmd = self.register(self._map_zone_key_list)
            reset_cmd = self.register(lambda: self._map_type_reset())
            self.tk.call("bind", self._map_zone_lb, "<KeyPress>", f"+{key_cmd} %A %s")
            for key in ("<KeyRelease-Shift_L>", "<KeyRelease-Shift_R>"):
                self.tk.call("bind", self._map_zone_lb, key, f"+{reset_cmd}")
        except tk.TclError as e:
            self._map_zone_lb = ""
            log.info("Kartenliste: Tippen in der offenen Liste nicht verfügbar: %s", e)

    def _map_type_reset(self, _e=None):
        self._map_type_buf = ""

    def _map_type_index(self, ch: str, state: int, current: int) -> int | None:
        """Index für einen Tastendruck; None, wenn die Taste nicht zum Tippen gehört (Strg-Kürzel, Pfeile …)."""
        if not ch or len(ch) != 1 or not ch.isprintable() or ch.isspace() or state & CONTROL:
            return None
        names = self._map_zone_names
        if state & SHIFT:
            self._map_type_buf += ch
            i = typeahead(names, current, self._map_type_buf, cycle=False)
            if i < 0:                                  # Tippfehler: den letzten Buchstaben vergessen
                self._map_type_buf = self._map_type_buf[:-1]
            return i
        self._map_type_buf = ""
        return typeahead(names, current, ch, cycle=True)

    def _map_zone_key(self, e):
        cb = self.map_zone_cb
        i = self._map_type_index(e.char, e.state, cb.current())
        if i is None:
            return None
        if i >= 0 and i != cb.current():
            cb.current(i)
            if self._map_type_job:
                self.after_cancel(self._map_type_job)
            self._map_type_job = self.after(TYPE_DELAY, self._map_type_apply)
        return "break"

    def _map_type_apply(self):
        self._map_type_job = None
        i = self.map_zone_cb.current()
        if 0 <= i < len(self._map_zone_ids) and self._map_zone_ids[i] != self.map_ui:
            self._map_zone_picked()

    def _map_zone_key_list(self, ch, state):
        """Tastendruck in der aufgeklappten Liste: markieren und sichtbar machen – Enter oder Klick wählt."""
        lb = self._map_zone_lb
        try:
            sel = self.tk.splitlist(self.tk.call(lb, "curselection"))
            cur = int(sel[0]) if sel else self.map_zone_cb.current()
            i = self._map_type_index(ch, int(state), cur)
            if i is not None and i >= 0:
                self.tk.call(lb, "selection", "clear", 0, "end")
                self.tk.call(lb, "selection", "set", i)
                self.tk.call(lb, "activate", i)
                self.tk.call(lb, "see", i)
        except (tk.TclError, ValueError) as e:
            log.info("Kartenliste: %s", e)

    def map_refresh(self):
        """Neue Daten aus dem Spiel (nach dem Ausloggen): neu laden, Ansicht behalten."""
        self._map_loaded_key = None
        if self.current_page == "map":
            self.map_open()

    # ----- Karte wechseln ------------------------------------------------------------------- #
    def map_show(self, ui: int, fit: bool = False, keep_highlight: bool = False):
        idx = self.map_idx
        if idx is None or not ui:
            self._map_crumbs()
            self.map_redraw()
            return
        self.map_replay_stop(keep=False)
        self.map_ui = ui
        self.cfg["map_zone"] = ui
        if not keep_highlight:
            self._map_hl = []
        if ui in self._map_zone_ids:
            self.map_zone_cb.current(self._map_zone_ids.index(ui))
        self._map_crumbs()
        self._map_img, self._map_img_url, self._map_img_scaled = None, "", {}
        self._map_img_size = DEFAULT_MAP_SIZE
        self._map_img_note = ""
        if fit:
            self._map_fit_view()
        self._map_compute()
        if not idx.is_continent(ui):
            self._map_load_image(ui)

    def _map_crumbs(self):
        idx, ui = self.map_idx, self.map_ui
        if not idx or not ui:
            self.map_crumb_var.set("")
            return
        cont = idx.continent_of(ui)
        if idx.is_continent(ui) or not cont:
            self.map_crumb_var.set(idx.name(ui))
        else:
            self.map_crumb_var.set(f"◂ {idx.name(cont)}  ›  {idx.name(ui)}")

    def map_up(self):
        if self.map_idx and self.map_ui and not self.map_idx.is_continent(self.map_ui):
            cont = self.map_idx.continent_of(self.map_ui)
            if cont:
                self.map_show(cont, fit=True)

    def _map_load_image(self, ui: int):
        area, flavor, seq = self.map_idx.area(ui), self.flavor, self._map_seq

        def done(res, err):
            if self.map_ui != ui or seq != self._map_seq:
                return
            path, how = res if not err else (None, "offline")
            if not path:
                self._map_img_note = {"offline": tr("Kartenbild konnte nicht geladen werden (offline?) – Raster statt Bild."),
                                      "noconvert": tr("Kartenbilder brauchen Windows oder Pillow – Raster statt Bild.")}.get(
                    how, tr("Wowhead hat kein Bild dieser Zone – Raster statt Bild."))
                self._map_status()
                return
            try:
                img = tk.PhotoImage(file=str(path))
            except tk.TclError as e:
                log.info("Kartenbild %s: %s", path, e)
                return
            self._map_img, self._map_img_url = img, how
            old = self._map_img_size
            self._map_img_size = (img.width(), img.height())
            if old != self._map_img_size and self._map_auto_fit:
                self._map_fit_view()
            self.map_redraw()
        self.run_quiet(lambda: map_image(flavor, area), done)

    # ----- Ebenen berechnen ---------------------------------------------------------------- #
    def _map_compute(self):
        idx, ui = self.map_idx, self.map_ui
        if idx is None or not ui:
            return
        sessions = self._map_filtered()
        if idx.is_continent(ui):
            self._map_layer = {"routes": [], "pins": [], "quests": {"active": [], "available": [], "note": ""},
                               "activity": map_activity(sessions), "sessions": sessions}
        else:
            self._map_layer = {"routes": session_routes(sessions, ui), "pins": session_pins(sessions, ui),
                               "quests": {"active": [], "available": [], "note": ""}, "sessions": sessions}
        self._map_fill_replay()
        self.map_redraw()
        want_q = self.map_layer_vars["q_active"].get() or self.map_layer_vars["q_avail"].get()
        char = self._map_char()
        if not want_q or idx.is_continent(ui):
            self._map_status()
            return
        if self.map_db is None:
            self._map_layer["quests"]["note"] = getattr(self, "_map_db_note", "") or tr("QuestieDB fehlt – ohne sie gibt es keine Quest-Ebene.")
            self._map_status()
            return
        if not char:
            self._map_layer["quests"]["note"] = tr("Für die Quest-Ebene oben einen Charakter wählen.")
            self._map_status()
            return
        seq, db, locale = self._map_seq, self.map_db, self._map_locale()
        avail = self.map_layer_vars["q_avail"].get()

        def done(res, err):
            if seq != self._map_seq or self.map_ui != ui:
                return
            if err:
                log.warning("Quest-Ebene: %s", err)
                return
            self._map_layer["quests"] = res
            self.map_redraw()
            self._map_status()
        self.run_quiet(lambda: quest_layer(db, idx, ui, char, locale, available=avail), done)

    def _map_locale(self) -> str:
        return "deDE" if cur_lang() == "de" else "enUS"

    def _map_status(self):
        L = self._map_layer
        parts = []
        if self.map_idx and self.map_ui and not self.map_idx.is_continent(self.map_ui):
            n_routes = len({r["sid"] for r in L["routes"]})
            parts.append(tr("{0} Sitzungen hier", n_routes) if n_routes != 1 else tr("1 Sitzung hier"))
            parts.append(tr("{0} Orte", len(L["pins"])))
            q = L["quests"]
            if q["active"] or q["available"]:
                parts.append(tr("{0} aktive, {1} verfügbare Quests", len(q["active"]), len(q["available"])))
        self.map_status_var.set("  ·  ".join(parts))
        notes = [n for n in (self._map_img_note, L["quests"].get("note", "")) if n]
        self._map_hover_text("")
        self._map_notes = "   ".join(notes)
        self.map_info_var.set(self._map_notes)
        counts = {k: 0 for k, *_ in MAP_LAYERS}
        for p in L["pins"]:
            counts[LAYER_OF_PIN.get(p["k"], "")] = counts.get(LAYER_OF_PIN.get(p["k"], ""), 0) + 1
        counts["route"] = len({r["sid"] for r in L["routes"]})
        counts["q_active"] = len(L["quests"]["active"])
        counts["q_avail"] = len(L["quests"]["available"])
        for key, (cb, name) in self._map_layer_labels.items():
            n = counts.get(key, 0)
            cb.configure(text=f"{name} ({n})" if n else name)

    # ----- Ansicht -------------------------------------------------------------------------- #
    def _map_space(self) -> tuple[int, int]:
        """Breite und Höhe der Karte in „Bildpunkten“ (Bild oder Ersatzgröße)."""
        return self._map_img_size if self._map_img is not None else DEFAULT_MAP_SIZE

    def _map_fit_view(self):
        self._map_auto_fit = True
        cv = self.map_cv
        cw, ch = max(cv.winfo_width(), 200), max(cv.winfo_height(), 150)
        w, h = self._map_space()
        box = self._map_cont_box()
        if box:                                          # Kontinent: die Fläche mit seinen Zonen füllen (stufenlos)
            x1, y1, x2, y2 = box[0] * w, box[1] * h, box[2] * w, box[3] * h
            z = min(cw / max(1, x2 - x1), ch / max(1, y2 - y1)) * 0.96
            self._map_view = {"z": z, "tx": (cw - (x1 + x2) * z) / 2, "ty": (ch - (y1 + y2) * z) / 2}
            return
        best = min(cw / w, ch / h)
        z = max([s for s in ZOOMS if s <= best] or [ZOOMS[0]])
        self._map_view = {"z": z, "tx": (cw - w * z) / 2, "ty": (ch - h * z) / 2}

    def _map_cont_box(self):
        """Ausdehnung der Zonen auf dem gezeigten Kontinent (Anteile 0–1) – None für Zonenkarten."""
        idx, ui = self.map_idx, self.map_ui
        if not idx or not ui or not idx.is_continent(ui):
            return None
        rects = [z["rect"] for z in idx.zones_on(ui) if z.get("rect")]
        if not rects:
            return None
        return (min(r[0] for r in rects), min(r[2] for r in rects), max(r[1] for r in rects), max(r[3] for r in rects))

    def map_fit(self):
        self._map_fit_view()
        self.map_redraw()

    def map_zoom_step(self, step: int, at=None):
        v = self._map_view
        if self._map_cont_box():
            nz = max(0.3, min(12.0, v["z"] * (1.25 if step > 0 else 0.8)))
        elif step > 0:
            top = max([z for z in ZOOMS if z * max(self._map_space()) <= MAX_IMAGE_PX] or [ZOOMS[0]])
            nz = min(top, next((z for z in ZOOMS if z >= v["z"] * 1.25 - 1e-9), ZOOMS[-1]))
        else:
            nz = next((z for z in reversed(ZOOMS) if z <= v["z"] / 1.25 + 1e-9), ZOOMS[0])
        if nz == v["z"]:
            return
        cv = self.map_cv
        self._map_auto_fit = False
        ax, ay = at or (cv.winfo_width() / 2, cv.winfo_height() / 2)
        ix, iy = (ax - v["tx"]) / v["z"], (ay - v["ty"]) / v["z"]       # Bildpunkt unter der Maus bleibt stehen
        self._map_view = {"z": nz, "tx": ax - ix * nz, "ty": ay - iy * nz}
        self.map_redraw()

    def _map_on_resize(self):
        if getattr(self, "_map_resize_job", None):
            self.after_cancel(self._map_resize_job)
        self._map_resize_job = self.after(80, self._map_resized)

    def _map_resized(self):
        self._map_resize_job = None
        if self._map_auto_fit and self.map_ui:
            self._map_fit_view()
        self.map_redraw()

    def _xy(self, px: float, py: float) -> tuple[float, float]:
        """Prozent der Karte -> Punkt auf der Zeichenfläche."""
        w, h = self._map_space()
        v = self._map_view
        return v["tx"] + px / 100 * w * v["z"], v["ty"] + py / 100 * h * v["z"]

    def _pct(self, cx: float, cy: float) -> tuple[float, float]:
        w, h = self._map_space()
        v = self._map_view
        return (cx - v["tx"]) / (w * v["z"]) * 100, (cy - v["ty"]) / (h * v["z"]) * 100

    def _map_scaled_image(self):
        z = self._map_view["z"]
        if self._map_img is None:
            return None
        if z == 1.0:
            return self._map_img
        if z in self._map_img_scaled:
            return self._map_img_scaled[z]
        w, h = self._map_img_size
        size = (max(1, round(w * z)), max(1, round(h * z)))
        img = None
        path = scaled_map_image(self._map_img_url, size) if self._map_img_url else None
        if path:
            try:
                img = tk.PhotoImage(file=str(path))
            except tk.TclError:
                img = None
        if img is None:                                     # einfache Tk-Skalierung als Rückfall
            img = self._map_img.zoom(round(z)) if z >= 1 else self._map_img.subsample(max(1, round(1 / z)))
        while len(self._map_img_scaled) >= 3:
            self._map_img_scaled.pop(next(iter(self._map_img_scaled)))
        self._map_img_scaled[z] = img
        return img

    # ----- Zeichnen ------------------------------------------------------------------------- #
    def map_redraw(self):
        cv = getattr(self, "map_cv", None)
        if cv is None or not cv.winfo_exists():
            return
        t = THEME
        cv.delete("all")
        self._map_hit = {}
        if not self.map_idx or not self.map_ui:
            cv.create_text(cv.winfo_width() / 2, cv.winfo_height() / 2, text=tr("Noch keine Kartendaten."),
                           fill=t["text_faint"], font=self.fonts["base"])
            return
        if self.map_idx.is_continent(self.map_ui):
            self._map_draw_continent()
            return
        self._map_draw_background()
        on = {k: v.get() for k, v in self.map_layer_vars.items()}
        L = self._map_layer
        rp = self._map_replay
        if on["q_avail"]:
            self._map_draw_available(L["quests"]["available"])
        if on["q_active"]:
            self._map_draw_active(L["quests"]["active"])
        if on["route"] and not rp:
            self._map_draw_routes(L["routes"])
        pins = [p for p in L["pins"] if on.get(LAYER_OF_PIN.get(p["k"], ""), True)]
        if rp:
            pins = [p for p in pins if p["sid"] == rp["sid"] and p["t"] <= rp["cur"]]
            self._map_draw_replay()
        self._map_draw_pins(pins)
        self._map_draw_player()
        self._map_draw_highlights()

    def _map_draw_background(self):
        cv, t = self.map_cv, THEME
        w, h = self._map_space()
        x0, y0 = self._xy(0, 0)
        x1, y1 = self._xy(100, 100)
        img = self._map_scaled_image()
        if img is not None:
            cv.create_image(x0, y0, image=img, anchor="nw", tags=("bg",))
        else:
            cv.create_rectangle(x0, y0, x1, y1, fill="#18201c", outline=t["border"], tags=("bg",))
            for i in range(1, 10):
                gx, _ = self._xy(i * 10, 0)
                _, gy = self._xy(0, i * 10)
                cv.create_line(gx, y0, gx, y1, fill="#24302a", tags=("bg",))
                cv.create_line(x0, gy, x1, gy, fill="#24302a", tags=("bg",))
                cv.create_text(gx + 3, y0 + 3, text=str(i * 10), anchor="nw", fill="#3c4a42", font=self.fonts["small"], tags=("bg",))
                cv.create_text(x0 + 3, gy + 3, text=str(i * 10), anchor="nw", fill="#3c4a42", font=self.fonts["small"], tags=("bg",))
            cx, cy = self._xy(50, 50)
            cv.create_text(cx, cy, text=self.map_idx.name(self.map_ui), fill="#334038",
                           font=self.fonts["hero"], tags=("bg",))

    def _route_colors(self) -> dict[str, str]:
        sids = []
        for r in self._map_layer["routes"]:
            if r["sid"] not in sids:
                sids.append(r["sid"])
        return {sid: ROUTE_COLORS[i % len(ROUTE_COLORS)] for i, sid in enumerate(sids)}

    def _map_draw_routes(self, routes):
        cv = self.map_cv
        colors = self._route_colors()
        last_of = {}
        for i, r in enumerate(routes):
            last_of[r["sid"]] = i
        for i, r in enumerate(routes):
            coords = [c for x, y, _ in r["pts"] for c in self._xy(x, y)]
            color = colors.get(r["sid"], ROUTE_COLORS[0])
            if len(coords) == 2:
                x, y = coords
                item = cv.create_oval(x - 2, y - 2, x + 2, y + 2, fill=color, outline="")
            else:
                opts = {"fill": color, "width": 2, "capstyle": "round", "joinstyle": "round"}
                if r["k"] == "t":
                    opts.update(dash=(6, 4), width=2)
                elif r["k"] == "g":
                    opts.update(dash=(2, 4), fill="#9aa3a1")
                if last_of.get(r["sid"]) == i:
                    opts.update(arrow="last", arrowshape=(10, 12, 4))
                item = cv.create_line(*coords, **opts)
            self._map_hit[item] = ("route", r)

    def _map_draw_pins(self, pins):
        cv = self.map_cv
        for p in pins:
            x, y = self._xy(p["x"], p["y"])
            layer = LAYER_OF_PIN.get(p["k"], "")
            color = next((c for k, _, c, _ in MAP_LAYERS if k == layer), "#ffffff")
            if p["k"] == "loot":
                color = QUALITY.get(p.get("q", 3), color)
            if p["k"] == "rare":
                color = "#c8ccca"
            glyph = GATHER_GLYPH.get(p.get("g", ""), "✿") if p["k"] == "gather" else PIN_GLYPH.get(p["k"], "•")
            r = 9
            sel = self._map_sel is not None and self._map_sel[0] == "pin" and self._map_sel[1] is p
            item = cv.create_oval(x - r, y - r, x + r, y + r, fill="#101615", outline=color, width=3 if sel else 2)
            label = cv.create_text(x, y, text=glyph, fill=color, font=self.fonts["small"])
            self._map_hit[item] = self._map_hit[label] = ("pin", p)

    def _map_draw_active(self, active):
        cv = self.map_cv
        for i, q in enumerate(active):
            color = QUEST_SPOT_COLORS[i % len(QUEST_SPOT_COLORS)]
            for x, y, name in q["spots"]:
                cx, cy = self._xy(x, y)
                item = cv.create_oval(cx - 2.5, cy - 2.5, cx + 2.5, cy + 2.5, fill=color, outline="#1a1a1a")
                self._map_hit[item] = ("qspot", q, name, (x, y))
        for q in active:
            for x, y, name in q["end"]:
                cx, cy = self._xy(x, y)
                fill = "#ffd100" if q["done"] else "#8a8a8a"
                item = cv.create_text(cx, cy, text="?", fill=fill, font=self.fonts["card"])
                ring = cv.create_oval(cx - 9, cy - 10, cx + 9, cy + 8, outline="", fill="")
                self._map_hit[item] = self._map_hit[ring] = ("qend", q, name, (x, y))

    def _map_draw_available(self, available):
        cv = self.map_cv
        seen = set()
        for q in available:
            for x, y, name in q["places"][:3]:
                key = (round(x, 1), round(y, 1))
                cx, cy = self._xy(x, y)
                if key in seen:                     # mehrere Quests beim selben Geber: leicht versetzt
                    cx += 6
                seen.add(key)
                item = cv.create_text(cx, cy, text="!", fill=DIFF_COLORS.get(q["color"], "#ffd100"), font=self.fonts["card"])
                self._map_hit[item] = ("qavail", q, name, (x, y))

    def _map_draw_player(self):
        char = self._map_char()
        pos = (char or {}).get("pos")
        if not pos or pos.get("m") != self.map_ui or pos.get("x") is None:
            return
        cv = self.map_cv
        x, y = self._xy(pos["x"], pos["y"])
        item = cv.create_polygon(x, y - 11, x + 8, y + 8, x, y + 3, x - 8, y + 8, fill="#ffd100", outline="#000000")
        self._map_hit[item] = ("player", char)

    def _map_draw_highlights(self):
        cv = self.map_cv
        for x, y in self._map_hl[:300]:
            cx, cy = self._xy(x, y)
            cv.create_oval(cx - 7, cy - 7, cx + 7, cy + 7, outline="#ffffff", width=1.5)
            cv.create_oval(cx - 2.5, cy - 2.5, cx + 2.5, cy + 2.5, fill="#ffffff", outline="")

    def _map_draw_continent(self):
        """Übersicht: Zonen als Felder in ihrer Lage auf dem Kontinent, Wege der Zeitspanne darüber."""
        import tkinter.font as tkfont
        cv, t, idx, ui = self.map_cv, THEME, self.map_idx, self.map_ui
        zones = idx.zones_on(ui)
        act = self._map_layer.get("activity", {})
        placed = [z for z in zones if z.get("rect")]
        if not placed:
            x0, y0 = self._xy(0, 0)
            x1, y1 = self._xy(100, 100)
            cv.create_rectangle(x0, y0, x1, y1, fill="#0f1716", outline=t["border_soft"])
            self._map_draw_zone_tiles(zones, act)
            return
        font = tkfont.Font(root=self, font=self.fonts["small"])
        big_first = sorted(placed, key=lambda z: (z["rect"][1] - z["rect"][0]) * (z["rect"][3] - z["rect"][2]), reverse=True)
        for z in big_first:
            r = z["rect"]
            a1, b1 = self._xy(r[0] * 100, r[2] * 100)
            a2, b2 = self._xy(r[1] * 100, r[3] * 100)
            busy = z["id"] in act
            item = cv.create_rectangle(a1, b1, a2, b2, fill="#2a2a1c" if busy else "#141d1c",
                                       outline=t["gold_deep"] if busy else t["border_soft"], width=2 if busy else 1)
            self._map_hit[item] = ("zone", z)
        for z in big_first:                              # Namen nach den Feldern, damit kleine Felder sie nicht verdecken
            r = z["rect"]
            a1, b1 = self._xy(r[0] * 100, r[2] * 100)
            a2, b2 = self._xy(r[1] * 100, r[3] * 100)
            w, h = a2 - a1, b2 - b1
            busy = z["id"] in act
            fits = font.measure(z["name"]) <= w - 6
            if not fits and (w < 70 or h < 34):
                continue
            lab = cv.create_text((a1 + a2) / 2, (b1 + b2) / 2, text=z["name"], width=max(30, w - 6),
                                 fill=t["gold"] if busy else t["text_faint2"], font=self.fonts["small"], justify="center")
            self._map_hit[lab] = ("zone", z)
        if not self.map_layer_vars["route"].get():
            return
        colors = {}
        for s_ in self._map_layer.get("sessions", []):
            for sg in (s_.get("map") or {}).get("segs") or []:
                z = idx.get(sg["m"])
                if not z or not z.get("rect") or idx.continent_of(sg["m"]) != ui:
                    continue
                color = colors.setdefault(s_["id"], ROUTE_COLORS[len(colors) % len(ROUTE_COLORS)])
                r = z["rect"]
                coords = []
                for x, y, _ in parse_route(sg["d"], sg["t"]):
                    coords += self._xy((r[0] + x / 100 * (r[1] - r[0])) * 100, (r[2] + y / 100 * (r[3] - r[2])) * 100)
                if len(coords) >= 4:
                    cv.create_line(*coords, fill=color, width=2, dash=(6, 4) if sg.get("k") == "t" else None)

    def _map_draw_zone_tiles(self, zones, act):
        """Ohne Lagedaten (Leeroylink noch nicht im Spiel gewesen): Zonen als Kacheln."""
        cv, t = self.map_cv, THEME
        cols = 5
        for i, z in enumerate(zones):
            r, c = divmod(i, cols)
            px, py = 2 + c * 19.5, 4 + r * 13
            a1, b1 = self._xy(px, py)
            a2, b2 = self._xy(px + 18, py + 11)
            busy = z["id"] in act
            item = cv.create_rectangle(a1, b1, a2, b2, fill="#2a2a1c" if busy else "#141d1c",
                                       outline=t["gold_deep"] if busy else t["border_soft"])
            lab = cv.create_text((a1 + a2) / 2, (b1 + b2) / 2, text=z["name"], width=max(40, a2 - a1 - 6),
                                 fill=t["gold"] if busy else t["text_faint2"], font=self.fonts["small"], justify="center")
            self._map_hit[item] = self._map_hit[lab] = ("zone", z)
        x, y = self._xy(50, 97)
        cv.create_text(x, y, text=tr("Die Lage der Zonen liefert Leeroylink 0.9 beim nächsten Einloggen."),
                       fill=t["text_faint"], font=self.fonts["small"])

    # ----- Maus ------------------------------------------------------------------------------ #
    def _map_item_at(self, x, y):
        cv = self.map_cv
        best = None
        for item in reversed(cv.find_overlapping(x - 4, y - 4, x + 4, y + 4)):
            hit = self._map_hit.get(item)
            if hit is None:
                continue
            rank = {"pin": 0, "qend": 1, "qavail": 2, "player": 2, "qspot": 3, "zone": 4, "route": 5}.get(hit[0], 9)
            if best is None or rank < best[0]:
                best = (rank, hit)
        return best[1] if best else None

    def _map_press(self, e):
        self._map_drag = {"x": e.x, "y": e.y, "moved": False}

    def _map_motion_drag(self, e):
        d = self._map_drag
        if not d:
            return
        dx, dy = e.x - d["x"], e.y - d["y"]
        if not d["moved"] and abs(dx) + abs(dy) < 4:
            return
        d["moved"] = True
        self._map_auto_fit = False
        d["x"], d["y"] = e.x, e.y
        self._map_view["tx"] += dx
        self._map_view["ty"] += dy
        self.map_cv.move("all", dx, dy)
        self.map_cv.configure(cursor="fleur")

    def _map_release(self, e):
        d, self._map_drag = self._map_drag, None
        self.map_cv.configure(cursor="crosshair")
        if d and d["moved"]:
            return
        hit = self._map_item_at(e.x, e.y)
        if hit and hit[0] == "zone":
            self.map_show(hit[1]["id"], fit=True)
            return
        if hit:
            self._map_select(hit)
        elif not self.map_idx or self.map_idx.is_continent(self.map_ui):
            return
        else:
            px, py = self._pct(e.x, e.y)
            if 0 <= px <= 100 and 0 <= py <= 100:
                self._map_select(("coord", (px, py)))

    def _map_hover(self, e):
        if self._map_drag:
            return
        hit = self._map_item_at(e.x, e.y)
        text = ""
        if self.map_idx and self.map_ui and not self.map_idx.is_continent(self.map_ui):
            px, py = self._pct(e.x, e.y)
            if 0 <= px <= 100 and 0 <= py <= 100:
                text = f"{px:.1f}, {py:.1f}"
        if hit:
            text = (text + "  ·  " if text else "") + self._hit_title(hit)
        self._map_hover_text(text)

    def _map_hover_text(self, text: str):
        notes = getattr(self, "_map_notes", "")
        self.map_info_var.set(text or notes or tr("Mausrad: zoomen · Ziehen: verschieben · Rechtsklick: /way kopieren"))

    def _hit_title(self, hit) -> str:
        kind = hit[0]
        if kind == "pin":
            return pin_title(hit[1])
        if kind in ("qspot", "qend", "qavail"):
            q = hit[1]
            pre = {"qspot": "", "qend": tr("Abgabe: "), "qavail": tr("Verfügbar: ")}[kind]
            return f"{pre}[{q['lvl']}] {q['title']} – {hit[2]}"
        if kind == "zone":
            return hit[1]["name"]
        if kind == "route":
            r = hit[1]
            return tr("Weg vom {0}", datetime.fromtimestamp(r["pts"][0][2]).strftime(tr("%d.%m.%Y  %H:%M")))
        if kind == "player":
            return tr("{0} war zuletzt hier", hit[1].get("name", "?"))
        return ""

    def _map_context(self, e):
        if not self.map_idx or not self.map_ui or self.map_idx.is_continent(self.map_ui):
            return
        px, py = self._pct(e.x, e.y)
        if not (0 <= px <= 100 and 0 <= py <= 100):
            return
        m = tk.Menu(self, tearoff=False)
        m.add_command(label=tr("{0} kopieren", way_command(px, py)), command=lambda: self._map_copy(way_command(px, py)))
        m.add_command(label=tr("Koordinaten kopieren ({0})", f"{px:.1f}, {py:.1f}"),
                      command=lambda: self._map_copy(f"{px:.1f}, {py:.1f}"))
        m.add_separator()
        m.add_command(label=tr("Hineinzoomen"), command=lambda: self.map_zoom_step(1, (e.x, e.y)))
        m.add_command(label=tr("Ganze Karte"), command=self.map_fit)
        if self._map_img is None and self.map_idx.area(self.map_ui):
            m.add_command(label=tr("Kartenbild erneut laden"), command=self._map_retry_image)
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    def _map_retry_image(self):
        clear_image_misses()
        self._map_img_note = ""
        self._map_load_image(self.map_ui)

    def _map_copy(self, text: str):
        self.clipboard_clear()
        self.clipboard_append(text)
        self.set_status(tr("Kopiert: {0}", text))

    # ----- Auswahl --------------------------------------------------------------------------- #
    def _map_detail(self, parts, actions=()):
        self._set_text(self.map_text, parts=parts)
        for w in self.map_actions.winfo_children():
            w.destroy()
        for i, (text, cb) in enumerate(actions):
            ttk.Button(self.map_actions, text=text, command=cb).grid(row=i // 2, column=i % 2, sticky="ew",
                                                                      padx=(0, 6) if i % 2 == 0 else 0, pady=(0, 4))
        self.map_actions.columnconfigure(0, weight=1)
        self.map_actions.columnconfigure(1, weight=1)

    def _map_select(self, hit):
        self._map_sel = hit
        kind = hit[0]
        parts, acts = [], []
        when = lambda ts: datetime.fromtimestamp(ts).strftime(tr("%d.%m.%Y  %H:%M"))   # noqa: E731
        if kind == "pin":
            p = hit[1]
            parts.append((pin_title(p) + "\n", "title"))
            parts.append((f"{when(p['t'])}  ·  {p.get('name_char', '')}\n", "dim"))
            parts.append((f"{self.map_idx.name(self.map_ui)}  {p['x']:.1f}, {p['y']:.1f}\n", "dim"))
            if p["k"] == "death":
                if p.get("spell"):
                    parts.append((tr("Zauber: {0}", p["spell"]) + "\n", ""))
                if p.get("lvl"):
                    parts.append((tr("Stufe {0}", p["lvl"]) + "\n", ""))
            if p.get("inst"):
                parts.append((tr("In: {0}", p["inst"]) + "\n", ""))
            if p["k"] == "loot" and p.get("by"):
                parts.append((tr("Von: {0}", p["by"]) + "\n", ""))
            if p["k"] == "found" and p.get("xp"):
                parts.append((tr("{0} Erfahrung", p["xp"]) + "\n", ""))
            if p["k"] in ("qa", "qd") and p.get("id"):
                acts.append((tr("Quest ansehen"), lambda q=p["id"]: self._map_open_quest(q)))
            if p["k"] in ("loot", "gather") and p.get("id"):
                acts.append((tr("Wowhead ↗"), lambda i=p["id"]: self._map_wowhead("item", i)))
            if p["k"] == "shot":
                shot = screenshot_for(self.root_path, self.flavor, p["t"])
                if shot:
                    acts.append((tr("Screenshot öffnen"), lambda f=shot: self._map_open_file(f)))
                else:
                    parts.append((tr("Die Bilddatei liegt nicht (mehr) im Screenshots-Ordner.") + "\n", "dim"))
            acts.append((tr("/way kopieren"), lambda x=p["x"], y=p["y"]: self._map_copy(way_command(x, y))))
        elif kind in ("qspot", "qend", "qavail"):
            q, name, (x, y) = hit[1], hit[2], hit[3]
            parts.append((f"[{q['lvl']}] {q['title']}\n", "title"))
            if kind == "qavail":
                parts.append((tr("Verfügbar bei {0}", name) + "\n", ""))
            elif kind == "qend":
                parts.append((tr("Abgabe bei {0}", name) + "\n", ""))
                parts.append(((tr("Alle Ziele erledigt.") if q["done"] else tr("Noch nicht fertig.")) + "\n", "ok" if q["done"] else "dim"))
            else:
                parts.append((name + "\n", ""))
            for text, done in q.get("objectives", []):
                parts.append((("✓ " if done else "○ ") + text + "\n", "ok" if done else ""))
            acts.append((tr("Quest ansehen"), lambda qid=q["qid"]: self._map_open_quest(qid)))
            acts.append((tr("/way kopieren"), lambda: self._map_copy(way_command(x, y))))
        elif kind == "route":
            r = hit[1]
            sess = next((s for s in self.map_sessions if s.get("id") == r["sid"]), None)
            parts.append((tr("Weg vom {0}", when(r["pts"][0][2])) + "\n", "title"))
            if sess:
                cls = CLASS_NAMES.get(sess.get("class", ""), sess.get("class", ""))
                parts.append((f"{sess.get('name', '')} · {tr(cls) if cls else ''} · {fmt_dur(sess.get('played', 0))}\n", "dim"))
            kinds = {"t": tr("Flugroute"), "g": tr("als Geist")}
            if r["k"] in kinds:
                parts.append((kinds[r["k"]] + "\n", ""))
            acts.append((tr("▶ Abspielen"), lambda sid=r["sid"]: self.map_replay_start(sid)))
        elif kind == "player":
            c = hit[1]
            parts.append((tr("{0} war zuletzt hier", c.get("name", "?")) + "\n", "title"))
            pos = c.get("pos") or {}
            if pos.get("t"):
                parts.append((when(pos["t"]) + "\n", "dim"))
            acts.append((tr("/way kopieren"), lambda: self._map_copy(way_command(pos["x"], pos["y"]))))
        elif kind == "coord":
            x, y = hit[1]
            parts.append((f"{self.map_idx.name(self.map_ui)}  {x:.1f}, {y:.1f}\n", "title"))
            parts.append((way_command(x, y) + "\n", "mono"))
            acts.append((tr("/way kopieren"), lambda: self._map_copy(way_command(x, y))))
        self._map_detail(parts, acts)
        self.map_redraw()

    def _map_open_quest(self, qid: int):
        self.show_page("quests")

        def go(tries=0):
            if self.qdb is not None:
                self.qdb_show(qid)
            elif tries < 60:
                self.after(250, lambda: go(tries + 1))
        go()

    def _map_wowhead(self, kind: str, wid: int):
        ed = {"_forever_": "forever", "_retail_": ""}.get(self.flavor, "classic")
        try:
            webbrowser.open(wowhead_url(ed, kind, wid), new=2)
        except Exception as e:  # noqa
            log.info("Wowhead öffnen: %s", e)

    def _map_open_file(self, path):
        try:
            if os.name == "nt":
                os.startfile(str(path))
            else:
                webbrowser.open(path.as_uri())
        except (OSError, AttributeError) as e:
            self.warn(tr("Die Datei ließ sich nicht öffnen: {0}", e))

    # ----- Suche ----------------------------------------------------------------------------- #
    def map_search(self):
        text = self.map_search_var.get().strip()
        if not text or self.map_idx is None:
            return
        idx, db, locale, seq = self.map_idx, self.map_db, self._map_locale(), self._map_seq
        self.map_status_var.set(tr("Suche …"))

        def done(res, err):
            if seq != self._map_seq:
                return
            self._map_status()
            if err:
                log.warning("Kartensuche: %s", err)
                return
            self._map_search_hits = res or []
            self._map_show_hits(text)
        self.run_quiet(lambda: map_search(text, idx, db, locale), done)

    def _map_show_hits(self, text: str):
        hits = self._map_search_hits
        parts = [(tr("Suche: {0}", text) + "\n", "title")]
        if not hits:
            parts.append((tr("Nichts gefunden.") if self.map_db is not None
                          else tr("Nichts gefunden. Mit QuestieDB findet die Suche auch NPCs, Objekte und Quests."), "dim"))
            self._map_detail(parts)
            return
        self._map_detail(parts)
        txt = self.map_text
        txt.configure(state="normal")
        for i, h in enumerate(hits):
            tag = f"hit{i}"
            txt.insert("end", h["name"], ("link", tag))
            txt.insert("end", f"  {h['sub']}\n", "dim")
            txt.tag_bind(tag, "<Button-1>", lambda e, k=i: self._map_pick_hit(k))
        txt.configure(state="disabled")
        if len(hits) == 1 or hits[0]["name"].lower() == text.lower():
            self._map_pick_hit(0, show_list=False)

    def _map_pick_hit(self, i: int, show_list: bool = True, target: int = 0):
        h = self._map_search_hits[i]
        places = h["places"]
        if h["kind"] == "zone":
            self.map_show(h["id"], fit=True)
            return
        counts: dict[int, int] = {}
        for ui, _, _ in places:
            counts[ui] = counts.get(ui, 0) + 1
        if not target:
            target = self.map_ui if self.map_ui in counts else max(counts, key=counts.get)
        self._map_hl = [(x, y) for ui, x, y in places if ui == target and x is not None]
        if target != self.map_ui:
            self.map_show(target, fit=True, keep_highlight=True)
        else:
            self.map_redraw()
        parts = [(h["name"] + "\n", "title"), (h["sub"] + "\n", "dim"),
                 (tr("{0} Fundorte auf dieser Karte", len(self._map_hl)) + "\n", "")]
        acts = []
        if h["kind"] == "quest":
            acts.append((tr("Quest ansehen"), lambda q=h["id"]: self._map_open_quest(q)))
        else:
            acts.append((tr("Wowhead ↗"), lambda k=h["kind"], w=h["id"]: self._map_wowhead(k, w)))
        self._map_detail(parts, acts)
        others = sorted(((self.map_idx.name(u), u, n) for u, n in counts.items() if u != target), key=lambda o: -o[2])
        if others:                                    # andere Karten mit Fundorten: anklickbar
            txt = self.map_text
            txt.configure(state="normal")
            txt.insert("end", "\n" + tr("Auch auf:") + "\n", "dim")
            for k, (name, u, n) in enumerate(others[:12]):
                tag = f"other{k}"
                txt.insert("end", name, ("link", tag))
                txt.insert("end", f" ({n})\n", "dim")
                txt.tag_bind(tag, "<Button-1>", lambda e, j=i, u=u: self._map_pick_hit(j, target=u))
            txt.configure(state="disabled")

    # ----- Wiedergabe ------------------------------------------------------------------------ #
    def _map_fill_replay(self):
        sids, labels = [], []
        for r in self._map_layer.get("routes", []):
            if r["sid"] not in sids:
                sids.append(r["sid"])
        by_id = {s["id"]: s for s in self.map_sessions}
        sids.sort(key=lambda sid: by_id.get(sid, {}).get("start", 0), reverse=True)
        for sid in sids:
            s = by_id.get(sid, {})
            labels.append(f"{datetime.fromtimestamp(s.get('start', 0)).strftime(tr('%d.%m.  %H:%M'))} · {s.get('name', '')}"
                          f" · {fmt_dur(s.get('played', 0))}")
        self._map_replay_sids = sids
        self.map_replay_cb.configure(values=labels)
        if labels:
            self.map_replay_cb.current(0)
        else:
            self.map_replay_var.set(tr("Kein Weg auf dieser Karte"))
        state = "normal" if labels else "disabled"
        self.map_play_btn.configure(state=state)

    def map_replay_toggle(self):
        rp = self._map_replay
        if rp and rp.get("playing"):
            rp["playing"] = False
            self.map_play_btn.configure(text=tr("▶ Weiter"))
            return
        i = self.map_replay_cb.current()
        if not rp:
            if not (0 <= i < len(getattr(self, "_map_replay_sids", []))):
                return
            self.map_replay_start(self._map_replay_sids[i])
            return
        if rp["cur"] >= rp["t1"]:
            rp["cur"] = rp["t0"]
        rp["playing"] = True
        self.map_play_btn.configure(text=tr("❚❚ Pause"))
        self._map_replay_tick()

    def map_replay_start(self, sid: str):
        routes = [r for r in self._map_layer.get("routes", []) if r["sid"] == sid]
        pts = sorted((p for r in routes for p in ((x, y, t, r["k"]) for x, y, t in r["pts"])), key=lambda p: p[2])
        if not pts:
            return
        if sid in getattr(self, "_map_replay_sids", []):
            self.map_replay_cb.current(self._map_replay_sids.index(sid))
        t0, t1 = pts[0][2], max(pts[-1][2], pts[0][2] + 1)
        self._map_replay = {"sid": sid, "pts": pts, "t0": t0, "t1": t1, "cur": t0, "playing": True, "routes": routes}
        self.map_play_btn.configure(text=tr("❚❚ Pause"))
        self.map_redraw()
        self._map_replay_tick()

    def map_replay_stop(self, keep: bool = True):
        if self._map_replay is None:
            return
        self._map_replay["playing"] = False
        if not keep:
            self._map_replay = None
            self.map_play_btn.configure(text=tr("▶ Abspielen"))
            try:
                self.map_replay_scale.set(0)
            except tk.TclError:
                pass
            self.map_redraw()

    def _map_replay_tick(self):
        rp = self._map_replay
        if not rp or not rp["playing"] or self.current_page != "map":
            if rp:
                rp["playing"] = False
                self.map_play_btn.configure(text=tr("▶ Weiter"))
            return
        step = (rp["t1"] - rp["t0"]) / REPLAY_FRAMES
        rp["cur"] = min(rp["t1"], rp["cur"] + step)
        self._map_replay_setting = True
        self.map_replay_scale.set((rp["cur"] - rp["t0"]) / (rp["t1"] - rp["t0"]) * 1000)
        self._map_replay_setting = False
        self.map_redraw()
        if rp["cur"] >= rp["t1"]:
            rp["playing"] = False
            self.map_play_btn.configure(text=tr("▶ Nochmal"))
            return
        self.after(40, self._map_replay_tick)

    def _map_replay_seek(self, value):
        if getattr(self, "_map_replay_setting", False):
            return
        rp = self._map_replay
        if not rp:
            i = self.map_replay_cb.current()
            sids = getattr(self, "_map_replay_sids", [])
            if not (0 <= i < len(sids)):
                return
            self.map_replay_start(sids[i])
            rp = self._map_replay
            if not rp:
                return
            rp["playing"] = False
            self.map_play_btn.configure(text=tr("▶ Weiter"))
        rp["cur"] = rp["t0"] + float(value) / 1000 * (rp["t1"] - rp["t0"])
        self.map_redraw()

    def _map_draw_replay(self):
        rp, cv = self._map_replay, self.map_cv
        cur = rp["cur"]
        # Strecke bis jetzt, Stück für Stück (Flug gestrichelt)
        for r in rp["routes"]:
            done = [(x, y) for x, y, t in r["pts"] if t <= cur]
            if len(done) >= 2:
                coords = [c for x, y in done for c in self._xy(x, y)]
                cv.create_line(*coords, fill="#ffd100", width=3, capstyle="round", joinstyle="round",
                               dash=(6, 4) if r["k"] == "t" else None)
        prev = next_ = None
        for p in rp["pts"]:
            if p[2] <= cur:
                prev = p
            else:
                next_ = p
                break
        if prev is None:
            return
        x, y = prev[0], prev[1]
        if next_ and next_[2] > prev[2] and next_[2] - prev[2] < 120:
            f = (cur - prev[2]) / (next_[2] - prev[2])
            x, y = x + (next_[0] - x) * f, y + (next_[1] - y) * f
        cx, cy = self._xy(x, y)
        cv.create_oval(cx - 7, cy - 7, cx + 7, cy + 7, fill="#ffd100", outline="#000000", width=2)
        played = int(cur - rp["t0"])
        self._map_hover_text(tr("Wiedergabe: {0}  ·  {1} seit dem Start", datetime.fromtimestamp(cur).strftime("%H:%M:%S"),
                                fmt_dur(played)))
