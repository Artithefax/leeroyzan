"""Seite „Teilen“: Download-Listen und Addon-Pakete. (Mixin, wird in App eingemischt)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from tkinter import ttk, filedialog
import tkinter as tk

from ..i18n import tr
from ..config import log, save_config
from ..files import export_pack, import_pack, open_in_explorer, read_pack
from ..github import choose_asset, github_install_asset, github_latest, parse_repo
from ..curseforge import CF_PREFIX, ManualDownload, cf_install_asset, cf_pack_item, cf_queue_item
from ..sharing import (
    LIST_EXT,
    LIST_PART_SIZES,
    ListError,
    PACK_EXT,
    build_list,
    list_readable,
    list_to_code,
    list_to_file_text,
    parse_list_text,
)
from ..reports import DISCORD_WEBHOOK_RE
from .theme import THEME
from .dialogs import SET_ALL_OFF, SET_ALL_ON


class SharePage:
    """Teil des Hauptfensters (wird in App eingemischt)."""

    # --- Teilen ------------------------------------------------------------------ #
    # Die Seite ist ein geführter Ablauf: oben wählt man, was man tun will (vier Kacheln), darunter stehen nur
    # die Schritte dafür – nummeriert, jeder mit einem Satz, was passiert.
    SHARE_TASKS = [("send", "Addons schicken", "Deine Addon-Liste an Freunde – per Discord, als Text oder als Datei."),
                   ("receive", "Addons übernehmen", "Liste oder Paket von einem Freund einfügen und installieren."),
                   ("ahsend", "AH-Preise schicken", "Deine gescannten Preise posten, damit andere nicht scannen müssen."),
                   ("ahreceive", "AH-Preise übernehmen", "Die Preisdatei eines Freundes aus Discord laden.")]

    def _page_share(self):
        t = THEME
        page, _ = self._page("share", tr("Teilen"), tr("Mit Freunden teilen"),
                             tr("Wähle, was du tun willst. Was du schickst, kommt bei deinen Freunden direkt in Leeroyzan "
                                "an. Builds, Guides, Quests und Charaktere teilst du dort, wo du sie siehst – mit dem Knopf "
                                "„Discord ↗“."))
        tiles = ttk.Frame(page)
        tiles.pack(fill="x", pady=(12, 0))
        self.share_tiles = {}
        for i, (key, title, text) in enumerate(self.SHARE_TASKS):
            tiles.columnconfigure(i, weight=1, uniform="t")
            tile = tk.Frame(tiles, bg=t["panel"], highlightthickness=1, highlightbackground=t["border_soft"],
                            highlightcolor=t["border_soft"], cursor="hand2")
            tile.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0))
            num = tk.Label(tile, text=f"{i + 1}", bg=t["panel"], fg=t["gold"], font=self.fonts["page"], cursor="hand2")
            num.pack(side="left", anchor="n", padx=(12, 6), pady=(8, 8))
            body = tk.Frame(tile, bg=t["panel"], cursor="hand2")
            body.pack(side="left", fill="both", expand=True, pady=(10, 10), padx=(0, 10))
            head = tk.Label(body, text=tr(title), bg=t["panel"], fg=t["text"], font=self.fonts["bold"], anchor="w", cursor="hand2")
            head.pack(fill="x")
            sub = tk.Label(body, text=tr(text), bg=t["panel"], fg=t["text_faint2"], font=self.fonts["small"], anchor="w",
                           justify="left", wraplength=210, cursor="hand2")
            sub.pack(fill="x")
            for w in (tile, num, body, head, sub):
                w.bind("<Button-1>", lambda e, k=key: self.share_task(k))
            self.share_tiles[key] = (tile, head)

        self.share_discord_row = ttk.Frame(page)
        self.share_discord_row.pack(fill="x", pady=(10, 0))
        self._share_discord_status()

        host = ttk.Frame(page)
        host.pack(fill="both", expand=True, pady=(10, 0))
        self.share_panels = {}

        # --- 1: Addons schicken
        box = self._card_box(host, pady=(0, 0), fill="both", expand=True)
        self.share_panels["send"] = box.master
        cols = ttk.Frame(box, style="Panel.TFrame")
        cols.pack(fill="both", expand=True)
        left = ttk.Frame(cols, style="Panel.TFrame")
        left.pack(side="left", fill="y")
        right = ttk.Frame(cols, style="Panel.TFrame")
        right.pack(side="left", fill="both", expand=True, padx=(20, 0))
        self._share_step(left, 1, tr("Welche Addons?"))
        scope = ttk.Frame(left, style="Panel.TFrame")
        scope.pack(fill="x", pady=(4, 0))
        self.share_sel_rb = ttk.Radiobutton(scope, text=tr("Ausgewählte Addons"), value="sel",
                                            variable=self.share_scope, command=self.rebuild_share)
        self.share_sel_rb.pack(anchor="w")
        self.share_all_rb = ttk.Radiobutton(scope, text=tr("Alle Addons"), value="all",
                                            variable=self.share_scope, command=self.rebuild_share)
        self.share_all_rb.pack(anchor="w", pady=(4, 0))
        ttk.Checkbutton(left, text=tr("Genau meine Versionen"), variable=self.share_exact,
                        command=self.rebuild_share).pack(anchor="w", pady=(8, 0))
        ttk.Checkbutton(left, text=tr("Addon-Sets mitsenden"), variable=self.share_sets,
                        command=self.rebuild_share).pack(anchor="w", pady=(4, 0))
        self._share_step(left, 2, tr("Wie schicken?"), pady=(16, 0))
        for label, text, cmd, primary in (
                (tr("In Discord posten"), tr("Liste mit Links und dem Code, den Freunde bei „Addons übernehmen“ einfügen."),
                 lambda: self.share_addons_discord(), True),
                (tr("Code kopieren"), tr("Für einen Chat ohne Webhook: einfügen und senden."), self.copy_share_code, False),
                (tr("Als Datei speichern"), tr("Eine .lzlist-Datei, die du verschicken kannst."), self.save_share_file, False),
                (tr("Als Paket mit Dateien"), tr("Nur nötig für Addons ohne CurseForge oder GitHub (.lzpack)."),
                 self.export_share_pack, False)):
            self._share_action(left, label, text, cmd, primary)
        ttk.Label(right, text=tr("Das bekommt dein Freund"), style="CardKicker.TLabel").pack(anchor="w")
        prow = ttk.Frame(right, style="Panel.TFrame")
        prow.pack(side="bottom", fill="x", pady=(8, 0))
        ttk.Button(prow, text=tr("Lesbare Liste kopieren"), command=self.copy_share_readable).pack(side="left")
        self.share_show_code = tk.BooleanVar(value=False)
        ttk.Checkbutton(prow, text=tr("Code anzeigen"), variable=self.share_show_code, command=self.rebuild_share).pack(
            side="left", padx=(12, 0))
        cb = ttk.Combobox(prow, textvariable=self.share_size, values=[tr(k) for k in LIST_PART_SIZES],
                          state="readonly", width=20)
        cb.pack(side="right")
        cb.bind("<<ComboboxSelected>>", lambda e: self.rebuild_share())
        ttk.Label(prow, text=tr("Nachrichtenlänge"), style="Panel.TLabel").pack(side="right", padx=(0, 8))
        ttk.Label(right, textvariable=self.share_info, style="Panel.TLabel", wraplength=560,
                  justify="left").pack(side="bottom", anchor="w", pady=(6, 0))
        sf, self.share_txt = self._text(right)
        sf.pack(fill="both", expand=True, pady=(6, 0))

        # --- 2: Addons übernehmen
        rbox = self._card_box(host, pady=(0, 0), fill="both", expand=True)
        self.share_panels["receive"] = rbox.master
        rcols = ttk.Frame(rbox, style="Panel.TFrame")
        rcols.pack(fill="both", expand=True)
        rl = ttk.Frame(rcols, style="Panel.TFrame")
        rl.pack(side="left", fill="both", expand=True)
        rr = ttk.Frame(rcols, style="Panel.TFrame", width=420)
        rr.pack(side="left", fill="y", padx=(20, 0))
        rr.pack_propagate(False)
        self._share_step(rl, 1, tr("Einfügen, was dein Freund geschickt hat"))
        ttk.Label(rl, style="Panel.TLabel", foreground=t["text_faint2"], wraplength=560, justify="left",
                  text=tr("Den Code aus Discord oder dem Chat – bei mehreren Teilen alle, die Reihenfolge ist egal.")).pack(anchor="w")
        rf2, self.import_txt = self._text(rl, readonly=False)
        rf2.pack(fill="both", expand=True, pady=(6, 0))
        self.import_txt.bind("<<Modified>>", self._import_modified)
        irow = ttk.Frame(rl, style="Panel.TFrame")
        irow.pack(fill="x", pady=(8, 0))
        ttk.Button(irow, text=tr("Aus Zwischenablage einfügen"), command=self.paste_import).pack(side="left")
        ttk.Button(irow, text=tr("Leeren"), command=lambda: self.import_txt.delete("1.0", "end")).pack(side="left", padx=(6, 0))
        ttk.Label(rl, text=tr("… oder eine Datei (.lzlist / .lzpack) öffnen – oder einfach ins Fenster ziehen:"),
                  style="Panel.TLabel").pack(anchor="w", pady=(12, 0))
        frow = ttk.Frame(rl, style="Panel.TFrame")
        frow.pack(fill="x", pady=(6, 0))
        self.recv_cb = ttk.Combobox(frow, textvariable=self.recv_file_var, state="readonly")
        self.recv_cb.pack(side="left", fill="x", expand=True)
        ttk.Button(frow, text=tr("Öffnen"), command=self.open_recv_file).pack(side="left", padx=(8, 0))
        ttk.Button(frow, text=tr("Andere …"), command=self.open_other_share_file).pack(side="left", padx=(8, 0))
        self._share_step(rr, 2, tr("Prüfen und installieren"))
        ttk.Label(rr, textvariable=self.import_preview, style="Panel.TLabel", wraplength=400,
                  justify="left").pack(anchor="w", pady=(4, 0))
        self.import_btn = ttk.Button(rr, text=tr("Installieren"), style="Primary.TButton", command=self.import_list_now)
        self.import_btn.pack(anchor="w", pady=(10, 0))
        self.import_btn.state(["disabled"])
        self._import_data = None

        # --- 3 und 4: AH-Preise
        self._ah_share_panels(host)
        self.share_task(self.cfg.get("share_task", "send"), save=False)

    def _share_step(self, parent, n: int, title: str, pady=(0, 0)):
        row = ttk.Frame(parent, style="Panel.TFrame")
        row.pack(fill="x", pady=pady)
        tk.Label(row, text=str(n), width=2, bg=THEME["btn_primary"], fg=THEME["btn_text"], font=self.fonts["bold"]).pack(side="left")
        ttk.Label(row, text=title, style="Panel.TLabel", font=self.fonts["bold"]).pack(side="left", padx=(8, 0))
        return row

    def _share_action(self, parent, label: str, text: str, cmd, primary: bool = False):
        row = ttk.Frame(parent, style="Panel.TFrame")
        row.pack(fill="x", pady=(8, 0))
        ttk.Button(row, text=label, width=22, style="Primary.TButton" if primary else "TButton", command=cmd).pack(side="left")
        ttk.Label(row, text=text, style="Panel.TLabel", foreground=THEME["text_faint2"], wraplength=300,
                  justify="left").pack(side="left", padx=(10, 0))
        return row

    def share_task(self, key: str, save: bool = True):
        """Eine der vier Aufgaben zeigen."""
        if key not in self.share_panels:
            key = "send"
        self.share_task_key = key
        t = THEME
        for k, (tile, head) in self.share_tiles.items():
            on = k == key
            tile.configure(highlightbackground=t["gold"] if on else t["border_soft"],
                           highlightcolor=t["gold"] if on else t["border_soft"], highlightthickness=2 if on else 1)
            head.configure(fg=t["gold"] if on else t["text"])
        for k, panel in self.share_panels.items():
            panel.pack_forget()
        self.share_panels[key].pack(fill="both", expand=True)
        if save:
            self.cfg["share_task"] = key
        if key == "send":
            self.rebuild_share()
        elif key == "receive":
            self.refresh_recv_files()
        else:
            self.ah_share_refresh()

    def _share_discord_status(self):
        """Ein Streifen über den Aufgaben: ist ein Discord-Kanal eingerichtet? Wenn nicht, gleich hier eintragen."""
        row = self.share_discord_row
        for w in row.winfo_children():
            w.destroy()
        t = THEME
        if self.share_hook():
            ttk.Label(row, text="✓ " + tr("Discord-Kanal eingerichtet – „In Discord posten“ schickt direkt dorthin."),
                      style="Body.TLabel", foreground=t["ok"]).pack(side="left")
            ttk.Button(row, text=tr("Ändern"), command=lambda: self.show_page("settings")).pack(side="right")
            return
        ttk.Label(row, text=tr("Discord noch nicht eingerichtet. Webhook-Adresse deines Kanals:"), style="Body.TLabel").pack(side="left")
        var = tk.StringVar()
        row.keep = var
        e = ttk.Entry(row, textvariable=var, width=46)
        e.pack(side="left", padx=(8, 0), fill="x", expand=True)

        def save(*_):
            url = var.get().strip()
            if not DISCORD_WEBHOOK_RE.match(url):
                self.set_status(tr("Das ist keine Discord-Webhook-Adresse."))
                return
            self.cfg["discord_share_webhook"] = url
            if not self.cfg.get("discord_webhook"):
                self.cfg["discord_webhook"] = url
                self.discord_var.set(url)
            self.discord_share_var.set(url)
            save_config(self.cfg)
            self.notify(tr("Discord-Kanal gespeichert."), "ok", timeout=6000)
            self._share_discord_status()
        e.bind("<Return>", save)
        ttk.Button(row, text=tr("Speichern"), style="Primary.TButton", command=save).pack(side="left", padx=(8, 0))
        ttk.Button(row, text=tr("So geht's"), command=lambda: self.info(tr(
            "In Discord: Rechtsklick auf den Kanal → Kanal bearbeiten → Integrationen → Webhooks → Neuer Webhook → "
            "„Webhook-URL kopieren“. Die Adresse hier einfügen und speichern. Ohne Webhook geht „Code kopieren“ "
            "und „Als Datei speichern“ trotzdem."))).pack(side="left", padx=(8, 0))

    # ----- Teilen-Seite ------------------------------------------------------------ #
    def share_selection(self):
        sel = self.selected_addons()
        self.share_scope.set("sel" if sel else "all")
        self.show_page("share")
        self.share_task("send")

    def _share_addons(self) -> list:
        if self.share_scope.get() == "sel":
            return self.selected_addons()
        return list(self.addons)

    def rebuild_share(self):
        if not getattr(self, "share_txt", None):
            return
        n_sel = len(self.selected_addons())
        self.share_sel_rb.configure(text=tr("Ausgewählte Addons ({0})", n_sel))
        self.share_all_rb.configure(text=tr("Alle Addons ({0})", len(self.addons)))
        if not n_sel and self.share_scope.get() == "sel":
            self.share_scope.set("all")
        self.share_sel_rb.state(["!disabled"] if n_sel else ["disabled"])
        addons = self._share_addons()
        self._share_payload, unlinked = build_list(addons, self.sources(), self.flavor, self.sets(),
                                                   self.share_exact.get(), self.share_sets.get())
        self._share_unlinked = unlinked
        if not self._share_payload["a"]:
            self._share_parts = []
            self._set_text(self.share_txt, tr("Keines dieser Addons hat eine Download-Quelle (CurseForge oder GitHub). "
                                           "Verknüpfe sie mit CurseForge oder teile sie als Paket."))
            self.share_info.set("")
            return
        size = next((v for k, v in LIST_PART_SIZES.items() if tr(k) == self.share_size.get()), 1800)
        self._share_parts = list_to_code(self._share_payload, size)
        parts = []
        if getattr(self, "share_show_code", None) is not None and self.share_show_code.get():
            for i, p in enumerate(self._share_parts, 1):
                if len(self._share_parts) > 1:
                    parts.append((tr("Teil {0} von {1} – als eigene Nachricht senden:\n", i, len(self._share_parts)), "dim"))
                parts.append((p + "\n\n", ""))
        else:
            parts.append((list_readable(self._share_payload) + "\n", ""))
        self._set_text(self.share_txt, parts=parts)
        n_c = sum(1 for e in self._share_payload["a"] if e["t"] == "c")
        info = (tr("{0} Addons ({1} CurseForge, {2} GitHub) · {3} Teil(e), {4} Zeichen.", len(self._share_payload['a']), n_c, len(self._share_payload['a']) - n_c, len(self._share_parts), sum(len(x) for x in self._share_parts)))
        if unlinked:
            info += "\n" + tr("Ohne Download-Quelle, nicht enthalten: {0} – dafür „Als Paket speichern“.",
                                 ', '.join(unlinked[:6]) + (" …" if len(unlinked) > 6 else ""))
        self.share_info.set(info)

    def _clip(self, text: str, what: str):
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()
        self.notify(what, "ok", key="clip", timeout=6000)

    def copy_share_code(self):
        if not getattr(self, "_share_parts", None):
            return
        n = len(self._share_parts)
        self._clip("\n\n".join(self._share_parts),
                   tr("Code kopiert – einfach in Discord oder eine Nachricht einfügen.") if n == 1 else
                   tr("Alle {0} Teile kopiert (getrennt durch Leerzeilen). Sende jeden Teil als eigene Nachricht.", n))

    def copy_share_readable(self):
        if getattr(self, "_share_payload", None) and self._share_payload["a"]:
            self._clip(list_readable(self._share_payload), tr("Lesbare Liste mit Links kopiert."))

    def _unique_path(self, stem: str, ext: str) -> Path:
        d = self.download_dir()
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{stem}{ext}"
        n = 2
        while p.exists():
            p = d / f"{stem} ({n}){ext}"
            n += 1
        return p

    def save_share_file(self):
        if not getattr(self, "_share_payload", None) or not self._share_payload["a"]:
            return
        p = self._unique_path(f"Addonliste_{datetime.now():%Y-%m-%d}", LIST_EXT)
        p.write_text(list_to_file_text(self._share_payload), encoding="utf-8")
        log.info("Download-Liste gespeichert: %s", p)
        self.notify(tr("Liste gespeichert: {0}", p), "ok", [(tr("Ordner öffnen"), lambda: open_in_explorer(p.parent))],
                    key="saved", timeout=20000)

    def export_share_pack(self):
        addons = self._share_addons()
        if not addons:
            self.info(tr("Es sind keine Addons installiert."))
            return
        self.export_pack_dialog(addons)

    def _import_modified(self, event=None):
        if not self.import_txt.edit_modified():
            return
        self.import_txt.edit_modified(False)
        if getattr(self, "_imp_job", None):
            self.after_cancel(self._imp_job)
        self._imp_job = self.after(300, self.preview_import)

    def paste_import(self):
        try:
            self.import_txt.insert("end", self.clipboard_get() + "\n")
        except tk.TclError:
            self.info(tr("Die Zwischenablage ist leer."))

    def preview_import(self):
        self._imp_job = None
        text = self.import_txt.get("1.0", "end").strip()
        self._import_data = None
        self.import_btn.state(["disabled"])
        if not text:
            self.import_preview.set("")
            self.import_btn.configure(text=tr("Installieren"))
            return
        try:
            data = parse_list_text(text)
        except ListError as e:
            self.import_preview.set(f"⚠ {e}")
            return
        have = self.sources()
        todo, lines = [], []
        for e in data["a"]:
            sid = CF_PREFIX + str(e["i"]) if e["t"] == "c" else e["r"]
            name = (e.get("n") or e.get("s") or sid) if e["t"] == "c" else e["r"]
            if sid in have:
                lines.append(tr("✓ {0} (schon da)", name))
            else:
                todo.append(e)
                lines.append(f"• {name}")
        head = tr("Liste mit {0} Addons ({1})", len(data['a']), data['fl'].strip('_') or '?')
        if data["fl"] and data["fl"] != self.flavor:
            head += tr(" – du installierst in {0}", self.flavor.strip('_'))
        if data["s"]:
            head += tr(" · {0} Set(s)", len(data['s']))
        self.import_preview.set(head + ":\n" + "\n".join(lines[:12]) + ("\n…" if len(lines) > 12 else ""))
        self._import_data = (todo, data["s"])
        self.import_btn.configure(text=tr("{0} Addon(s) installieren", len(todo)) if todo else tr("Alles schon installiert"))
        self.import_btn.state(["!disabled"] if todo else ["disabled"])

    def import_list_now(self):
        if not self._import_data or not self.ready():
            return
        todo, sets = self._import_data
        self.import_txt.delete("1.0", "end")
        self._run_list_import(todo, sets)

    def refresh_recv_files(self):
        self._recv_files = self.recent_files((LIST_EXT, PACK_EXT), 20)
        labels = [f"{p.name}   ·   {datetime.fromtimestamp(p.stat().st_mtime):%d.%m. %H:%M}" for p in self._recv_files]
        self.recv_cb["values"] = labels
        self.recv_file_var.set(labels[0] if labels else "")

    def open_recv_file(self):
        labels = list(self.recv_cb["values"])
        if self.recv_file_var.get() not in labels:
            self.info(tr("Im Download-Ordner liegt keine .lzlist- oder .lzpack-Datei."))
            return
        self._open_share_file(self._recv_files[labels.index(self.recv_file_var.get())])

    def open_other_share_file(self):
        f = filedialog.askopenfilename(title=tr("Liste oder Paket öffnen"),
                                       filetypes=[(tr("Leeroyzan-Liste/-Paket"), f"*{LIST_EXT} *{PACK_EXT}"),
                                                  (tr("Alle Dateien"), "*.*")])
        if f:
            self._open_share_file(Path(f))

    def _open_share_file(self, path: Path):
        if path.suffix.lower() == PACK_EXT:
            self.import_pack_dialog(str(path))
        else:
            self.import_list_dialog(str(path))

    def import_list_dialog(self, path=None):
        """Liste aus Datei (oder Drag & Drop) auf der Seite „Teilen“ anzeigen."""
        self.show_page("share")
        self.share_task("receive")
        if not path:
            self.import_txt.focus_set()
            return
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            self.error(tr("Datei konnte nicht gelesen werden: {0}", e))
            return
        self.import_txt.delete("1.0", "end")
        self.import_txt.insert("1.0", text)
        self.preview_import()

    # ----- Teilen ---------------------------------------------------------- #
    def export_pack_dialog(self, addons=None):
        if not self.ready(modifies=False):
            return
        sel = list(addons) if addons is not None else self.selected_addons()
        if not sel:
            self.info(tr("Bitte zuerst die Addons auswählen, die du teilen willst (Strg+Klick oder „Alle auswählen“)."))
            return
        by_name = {a.name.lower(): a for a in self.addons}
        chosen = {a.name.lower() for a in sel}
        missing = sorted({d for a in sel for d in a.deps
                          if d.lower() in by_name and d.lower() not in chosen}, key=str.lower)
        if missing and self.ask(tr("Diese Addons werden von deiner Auswahl benötigt:") + "\n\n"
                          + "\n".join(missing) + "\n\n" + tr("Mit ins Paket nehmen?")):
            sel += [by_name[d.lower()] for d in missing]

        dest = self._unique_path(f"Addons_{datetime.now():%Y-%m-%d}", PACK_EXT)
        sources, flavor = dict(self.sources()), self.flavor

        n_cf = sum(1 for a in sel if any(a.name in v.get("folders", []) and v.get("type") == "curseforge"
                                         for v in sources.values()))

        def done(path):
            size = path.stat().st_size / 1024 / 1024
            log.info("Paket exportiert: %s (%d Addons)", path, len(sel))
            self.set_status(tr("{0} Addons exportiert ({1:.1f} MB): {2}", len(sel), size, path))
            extra = (tr(" {0} CurseForge-Addon(s) sind nur als Verweis enthalten – dein Freund lädt sie mit seinem eigenen API-Key.", n_cf) if n_cf else "")
            self.notify(tr("Paket mit {0} Addons gespeichert ({1:.1f} MB): {2}.{3}", len(sel), size, path, extra), "ok",
                        [(tr("Ordner öffnen"), lambda: open_in_explorer(path.parent))], key="saved", timeout=25000)

        self.run_bg(tr("Exportiere Paket"), lambda: export_pack(sel, sources, flavor, Path(dest)), done)

    def _run_list_import(self, todo: list[dict], sets: dict, what: str | None = None):
        what = what or tr("aus der Liste")
        root, flavor = self.root_path, self.flavor
        gv = self.game[0] if self.game else ""
        token, key = self.cfg.get("github_token", ""), self.cf_key()
        if any(e["t"] == "c" for e in todo) and not key:
            self.need_cf_key()
            todo = [e for e in todo if e["t"] != "c"]
            if not todo:
                return

        def job():
            ok, manual, errors = [], [], []
            for e in todo:
                label = (e.get("n") or e.get("s") or str(e["i"])) if e["t"] == "c" else e["r"]
                info = None
                try:
                    if e["t"] == "c":
                        info = cf_pack_item({"mod_id": e["i"], "file_id": e.get("f")}, key, flavor, gv)
                        got = cf_install_asset(info["best"], info, root, flavor, key)
                        ok.append((None, info, info["best"], got))
                    else:
                        info = github_latest(e["r"], token)
                        asset = choose_asset(info, flavor, e.get("k", ""))
                        if not asset:
                            raise ValueError(tr("Das Release enthält keine Dateien."))
                        ok.append((e["r"], info, asset, github_install_asset(asset, root, flavor, token)))
                except ManualDownload as m:
                    manual.append((info, info["best"], m))
                except Exception as ex:  # noqa
                    log.error("Liste: %s: %s", label, ex)
                    errors.append(f"{label}: {ex}")
            return ok, manual, errors

        def done(out):
            ok, manual, errors = out
            installed = []
            for repo, info, asset, got in ok:
                if repo is None:
                    self.remember_cf_source(info, asset, got)
                else:
                    self.remember_source(repo, info, asset, got)
                self.remember_bundle(got)
                installed += got
            for name, members in sets.items():
                if name in (SET_ALL_OFF, SET_ALL_ON):
                    continue
                target = name
                if target in self.sets() and sorted(self.sets()[target]) != sorted(members):
                    target = tr("{0} (importiert)", name)
                self.sets()[target] = members
            save_config(self.cfg)
            log.info("Download-Liste importiert: %s", ", ".join(installed))
            self.refresh()
            self.reload_sets()
            self.refresh_sets_overview()
            msg = tr("{0} Addon(s) {1} installiert.", len(ok), what)
            if sets:
                msg += tr("  {0} Set(s) übernommen.", len(sets))
            self.set_status(msg)
            if ok:
                self.notify(msg, "ok", timeout=10000)
            if getattr(self, "cf_tree", None):
                self.cf_show_rows()
            if errors:
                self.warn(tr("Nicht installiert:") + "\n" + "\n".join(errors))
            if manual:
                self.run_download_queue([cf_queue_item(i, a) for i, a, _ in manual],
                                        tr("Im Browser laden (der Autor sperrt Programm-Downloads):"))
            self.install_dependencies([a for repo, _, a, _ in ok if repo is None])

        self.run_bg(tr("Lade Addons {0}", what), job, done)

    def import_pack_dialog(self, path=None):
        if not self.ready():
            return
        if not path:
            self.show_page("share")
            self.share_task("receive")
            return
        try:
            manifest = read_pack(Path(path))
        except ValueError as e:
            self.error(str(e))
            return

        entries = manifest["addons"]
        present = {a.name.lower(): a for a in self.addons}
        lines = []
        for e in entries:
            old = present.get(e["folder"].lower())
            ver = e.get("version") or "?"
            note = tr("ersetzt deine Version {0}", old.version or '?') if old else tr("neu")
            if (e.get("source") or {}).get("type") == "curseforge":
                note += tr(", wird von CurseForge geladen")
            lines.append(f"• {e.get('title') or e['folder']}  ({ver}) – {note}")
        text = (tr("Paket vom {0} ({1}), {2} Addons:", manifest.get('created', '?')[:10], manifest.get('flavor', '?'), len(entries)) + "\n"
                + "\n".join(lines[:10]) + ("\n…" if len(lines) > 10 else ""))
        if manifest.get("flavor") and manifest["flavor"] != self.flavor:
            text += (tr("\n\nHinweis: Das Paket wurde für {0} erstellt, du installierst es in {1}.", manifest['flavor'], self.flavor))
        if not self.ask(text, yes=tr("Installieren"), no=tr("Abbrechen")):
            return

        root, flavor = self.root_path, self.flavor
        gv = self.game[0] if self.game else ""
        cf_entries = [e for e in entries if (e.get("source") or {}).get("type") == "curseforge"]
        folders = [e["folder"] for e in entries if e not in cf_entries]
        cf_todo, seen = [], set()
        for e in cf_entries:
            src = e["source"]
            if isinstance(src.get("mod_id"), int) and src["mod_id"] not in seen:
                seen.add(src["mod_id"])
                cf_todo.append(src)
        cf_key = self.cf_key()
        if cf_todo and not cf_key:
            self.need_cf_key()
            cf_todo = []

        def job():
            installed = import_pack(Path(path), root, flavor, folders) if folders else []
            cf_ok, manual, errors = [], [], []
            for src in cf_todo:
                label = src.get("name") or src.get("slug") or str(src["mod_id"])
                try:
                    info = cf_pack_item(src, cf_key, flavor, gv)
                    got = cf_install_asset(info["best"], info, root, flavor, cf_key)
                    cf_ok.append((info, info["best"], got))
                except ManualDownload as m:
                    manual.append((info, info["best"], m))
                except Exception as e:  # noqa
                    errors.append(f"{label}: {e}")
            return installed, cf_ok, manual, errors

        def done(out):
            installed, cf_ok, manual, errors = out
            for e in entries:
                src = e.get("source")
                if src and src.get("type") == "github" and e["folder"] in installed:
                    try:
                        repo = parse_repo(src.get("repo", ""))
                    except ValueError:
                        continue
                    entry = self.sources().setdefault(
                        repo, {"type": "github", "tag": src.get("tag", ""),
                               "asset": "", "asset_key": "", "folders": []})
                    if e["folder"] not in entry["folders"]:
                        entry["folders"].append(e["folder"])
            for info, asset, got in cf_ok:
                self.remember_cf_source(info, asset, got)
                installed += got
            save_config(self.cfg)
            log.info("Paket importiert: %s -> %s", path, ", ".join(installed))
            self.refresh()
            self.set_status(tr("{0} Addons aus Paket installiert.", len(installed)))
            if errors:
                self.warn(tr("Nicht installiert:") + "\n\n" + "\n".join(errors))
            if manual:
                self.run_download_queue([cf_queue_item(i, a) for i, a, _ in manual],
                                        tr("Im Browser laden (der Autor sperrt Programm-Downloads):"))

        self.run_bg(tr("Importiere Paket"), job, done)
