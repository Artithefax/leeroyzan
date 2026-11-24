"""AH-Preise teilen und übernehmen (Seite „Teilen“, Aufgaben 3 und 4). (Mixin, wird in App eingemischt)."""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from tkinter import filedialog, ttk
import tkinter as tk

from ..ahshare import (
    DEFAULT_MAX_DAYS,
    PRICE_EXT,
    PriceError,
    export_prices,
    fetch_discord_file,
    fresh_prices,
    load_shared,
    merge_prices,
    parse_prices,
    price_file_name,
    prices_to_bytes,
    prune_shared,
    save_shared,
)
from ..auction import auctionator_savedvariables, load_auctionator
from ..config import log, save_config
from ..discordshare import share_prices_message
from ..i18n import tr
from ..presence import game_title
from ..reports import discord_send, fmt_int
from .theme import THEME


class AhShareMixin:
    """Teil des Hauptfensters (wird in App eingemischt)."""

    def ah_shared_days(self) -> int:
        try:
            return max(1, min(60, int(self.cfg.get("ah_shared_days", DEFAULT_MAX_DAYS))))
        except (TypeError, ValueError):
            return DEFAULT_MAX_DAYS

    # ----- Panels ------------------------------------------------------------------------ #
    def _ah_share_panels(self, host):
        t = THEME
        # 3: schicken
        box = self._card_box(host, pady=(0, 0), fill="both", expand=True)
        self.share_panels["ahsend"] = box.master
        self._share_step(box, 1, tr("Im Spiel scannen"))
        ttk.Label(box, style="Panel.TLabel", foreground=t["text_faint2"], wraplength=900, justify="left",
                  text=tr("Mit Auctionator das Auktionshaus scannen und danach ausloggen oder /reload – erst dann schreibt WoW "
                          "die Preise in die Datei, die Leeroyzan liest.")).pack(anchor="w", pady=(4, 0))
        self.ahs_status = tk.StringVar()
        srow = ttk.Frame(box, style="Panel.TFrame")
        srow.pack(fill="x", pady=(8, 0))
        ttk.Label(srow, textvariable=self.ahs_status, style="Panel.TLabel").pack(side="left")
        self.ahs_realm_var = tk.StringVar()
        self.ahs_realm_cb = ttk.Combobox(srow, textvariable=self.ahs_realm_var, state="readonly", width=26)
        self.ahs_realm_cb.bind("<<ComboboxSelected>>", lambda e: self._ahs_show_status())
        ttk.Button(srow, text=tr("Neu einlesen"), command=lambda: self.ah_share_refresh(force=True)).pack(side="right")
        self._share_step(box, 2, tr("Schicken"), pady=(16, 0))
        self._share_action(box, tr("In Discord posten"),
                           tr("Postet die Preise als Datei in euren Kanal – mit dem Zeitpunkt, wann jeder Preis gesehen wurde."),
                           self.ah_share_discord, True)
        self._share_action(box, tr("Als Datei speichern"), tr("Eine .lzprices-Datei im Download-Ordner, die du selbst verschickst."),
                           self.ah_share_save)
        ttk.Label(box, style="Panel.TLabel", foreground=t["text_faint2"], wraplength=900, justify="left",
                  text=tr("Geschickt werden nur deine eigenen Scans. Deine Freunde übernehmen die Datei bei „AH-Preise "
                          "übernehmen“ – ältere Preise überschreiben bei ihnen nie neuere.")).pack(anchor="w", pady=(14, 0))

        # 4: übernehmen
        rbox = self._card_box(host, pady=(0, 0), fill="both", expand=True)
        self.share_panels["ahreceive"] = rbox.master
        cols = ttk.Frame(rbox, style="Panel.TFrame")
        cols.pack(fill="both", expand=True)
        left = ttk.Frame(cols, style="Panel.TFrame")
        left.pack(side="left", fill="both", expand=True)
        right = ttk.Frame(cols, style="Panel.TFrame", width=430)
        right.pack(side="left", fill="y", padx=(20, 0))
        right.pack_propagate(False)
        self._share_step(left, 1, tr("Preisdatei holen"))
        ttk.Label(left, style="Panel.TLabel", foreground=t["text_faint2"], wraplength=560, justify="left",
                  text=tr("In Discord die Datei herunterladen und hier öffnen (oder ins Fenster ziehen). Schneller: Rechtsklick "
                          "auf die Datei → „Link kopieren“ und hier einfügen.")).pack(anchor="w", pady=(4, 0))
        lrow = ttk.Frame(left, style="Panel.TFrame")
        lrow.pack(fill="x", pady=(8, 0))
        self.ahr_link_var = tk.StringVar()
        le = ttk.Entry(lrow, textvariable=self.ahr_link_var)
        le.pack(side="left", fill="x", expand=True)
        le.bind("<Return>", lambda e: self.ah_import_link())
        ttk.Button(lrow, text=tr("Link laden"), style="Primary.TButton", command=self.ah_import_link).pack(side="left", padx=(8, 0))
        ttk.Button(lrow, text=tr("Einfügen"), command=self._ahr_paste_link).pack(side="left", padx=(8, 0))
        ttk.Label(left, text=tr("… oder eine Datei aus deinem Download-Ordner:"), style="Panel.TLabel").pack(anchor="w", pady=(12, 0))
        frow = ttk.Frame(left, style="Panel.TFrame")
        frow.pack(fill="x", pady=(6, 0))
        self.ahr_file_var = tk.StringVar()
        self.ahr_cb = ttk.Combobox(frow, textvariable=self.ahr_file_var, state="readonly")
        self.ahr_cb.pack(side="left", fill="x", expand=True)
        ttk.Button(frow, text=tr("Öffnen"), command=self._ahr_open_recent).pack(side="left", padx=(8, 0))
        ttk.Button(frow, text=tr("Andere …"), command=self._ahr_open_other).pack(side="left", padx=(8, 0))
        self.ahr_result = tk.StringVar()
        ttk.Label(left, textvariable=self.ahr_result, style="Panel.TLabel", foreground=t["ok"], wraplength=560,
                  justify="left").pack(anchor="w", pady=(12, 0))
        self._share_step(right, 2, tr("So zählen geteilte Preise"))
        drow = ttk.Frame(right, style="Panel.TFrame")
        drow.pack(fill="x", pady=(6, 0))
        ttk.Label(drow, text=tr("Gültig bis"), style="Panel.TLabel").pack(side="left")
        self.ahr_days_var = tk.StringVar(value=str(self.ah_shared_days()))
        sp = ttk.Spinbox(drow, from_=1, to=60, width=4, textvariable=self.ahr_days_var, command=self._ahr_save_days)
        sp.pack(side="left", padx=(6, 6))
        sp.bind("<FocusOut>", lambda e: self._ahr_save_days())
        sp.bind("<Return>", lambda e: self._ahr_save_days())
        ttk.Label(drow, text=tr("Tage nach dem Scan"), style="Panel.TLabel").pack(side="left")
        ttk.Label(right, style="Panel.TLabel", foreground=t["text_faint2"], wraplength=410, justify="left",
                  text=tr("Je Gegenstand gilt der neueste Preis – deiner oder der eines Freundes. Ältere Preise gehen nur in den "
                          "Verlauf ein. Was älter ist als die Grenze, zählt nirgends mehr: nicht als aktueller Preis, nicht "
                          "für Schnäppchen und nicht im Tooltip im Spiel.")).pack(anchor="w", pady=(6, 0))
        self.ahr_summary = tk.StringVar()
        ttk.Label(right, textvariable=self.ahr_summary, style="Panel.TLabel", wraplength=410, justify="left").pack(anchor="w", pady=(10, 0))
        brow = ttk.Frame(right, style="Panel.TFrame")
        brow.pack(fill="x", pady=(10, 0))
        ttk.Button(brow, text=tr("Zum Auktionshaus"), command=lambda: self.show_page("auction")).pack(side="left")
        ttk.Button(brow, text=tr("Geteilte Preise löschen"), style="Danger.TButton", command=self.ah_clear_shared).pack(side="right")

    # ----- Schicken ---------------------------------------------------------------------- #
    def ah_share_refresh(self, force: bool = False):
        """Status beider AH-Aufgaben neu füllen (eigene Auctionator-Daten, geteilte Preise, Downloads)."""
        if getattr(self, "ahs_status", None) is None:
            return
        self._ahr_refresh()
        if not self.root_path or not self.flavor:
            self.ahs_status.set(tr("Wähle zuerst den WoW-Ordner."))
            return
        files = auctionator_savedvariables(self.root_path, self.flavor)
        sig = (self.root_path, self.flavor, tuple((str(f), f.stat().st_mtime) for f in files))
        if not force and getattr(self, "_ahs_sig", None) == sig and getattr(self, "_ahs_data", None) is not None:
            self._ahs_show_status()
            return
        self._ahs_sig = sig
        self.ahs_status.set(tr("Lese Auctionator …"))
        root, flavor = self.root_path, self.flavor

        def done(data, err):
            if err:
                self.ahs_status.set(tr("Auctionator konnte nicht gelesen werden: {0}", str(err)[:160]))
                return
            self._ahs_data = data
            realms = sorted(data["realms"], key=lambda r: -len(data["realms"][r]))
            self.ahs_realm_cb.configure(values=realms)
            if self.ahs_realm_var.get() not in realms:
                self.ahs_realm_var.set(realms[0] if realms else "")
            if len(realms) > 1:
                self.ahs_realm_cb.pack(side="left", padx=(10, 0))
            else:
                self.ahs_realm_cb.pack_forget()
            self._ahs_show_status()
        self.run_quiet(lambda: load_auctionator(root, flavor), done)

    def _ahs_export(self) -> dict | None:
        data = getattr(self, "_ahs_data", None)
        realm = self.ahs_realm_var.get()
        if not data or not realm:
            return None
        d = export_prices(data, realm, self._share_author(), self.flavor)
        return d if d["n"] else None

    def _ahs_show_status(self):
        d = self._ahs_export()
        if not d:
            self.ahs_status.set(tr("Noch keine eigenen Preise – scanne im Spiel mit Auctionator, dann ausloggen oder /reload."))
            return
        newest = max(v[1] for v in d["p"].values())
        self.ahs_status.set(tr("Deine Preise: {0} Gegenstände · Stand {1}", fmt_int(d["n"]),
                               datetime.fromtimestamp(newest).strftime(tr("%d.%m.%Y %H:%M"))))

    def ah_share_discord(self):
        d = self._ahs_export()
        if not d:
            self.info(tr("Noch keine eigenen Preise – scanne im Spiel mit Auctionator, dann ausloggen oder /reload."))
            return
        url = self.share_hook()
        if not url:
            self.notify(tr("Trage zuerst eine Discord-Webhook-Adresse ein (oben auf dieser Seite)."), "info", key="discord-share")
            return
        msg = share_prices_message(d, game_title(self.flavor), "", self._share_author())
        name, content = price_file_name(d), prices_to_bytes(d)

        def done(_res, err):
            if err:
                log.warning("AH-Preise an Discord: %s", err)
                self.error(tr("Discord: {0}", err))
                return
            log.info("AH-Preise an Discord gesendet: %s, %d Gegenstände", d["realm"], d["n"])
            self.notify(tr("{0} AH-Preise an Discord gesendet.", fmt_int(d["n"])), "ok", timeout=8000)
        self.run_quiet(lambda: discord_send(url, msg, file=(name, content)), done)

    def ah_share_save(self):
        d = self._ahs_export()
        if not d:
            self.info(tr("Noch keine eigenen Preise – scanne im Spiel mit Auctionator, dann ausloggen oder /reload."))
            return
        p = self._unique_path(Path(price_file_name(d)).stem, PRICE_EXT)
        p.write_bytes(prices_to_bytes(d))
        log.info("AH-Preise gespeichert: %s", p)
        from ..files import open_in_explorer
        self.notify(tr("Preise gespeichert: {0}", p), "ok", [(tr("Ordner öffnen"), lambda: open_in_explorer(p.parent))],
                    key="saved", timeout=20000)

    # ----- Übernehmen --------------------------------------------------------------------- #
    def _ahr_refresh(self):
        self._ahr_files = self.recent_files((PRICE_EXT,), 20)
        labels = [f"{p.name}   ·   {datetime.fromtimestamp(p.stat().st_mtime):%d.%m. %H:%M}" for p in self._ahr_files]
        self.ahr_cb["values"] = labels
        self.ahr_file_var.set(labels[0] if labels else "")
        self._ahr_show_summary()

    def _ahr_show_summary(self):
        if not self.flavor:
            return
        store = load_shared(self.flavor)
        days = self.ah_shared_days()
        lines = []
        for realm in sorted(store["realms"]):
            n_all = len(store["realms"][realm])
            n_fresh = len(fresh_prices(store, realm, days))
            lines.append(tr("{0}: {1} geteilte Preise, davon {2} gültig", realm, fmt_int(n_all), fmt_int(n_fresh)))
        recent = store.get("imports", [])[-4:]
        if recent:
            lines.append("")
            lines.append(tr("Zuletzt übernommen:"))
            for imp in reversed(recent):
                lines.append("• " + tr("{0} von {1} · {2} Preise", datetime.fromtimestamp(imp["at"]).strftime(tr("%d.%m. %H:%M")),
                                       imp.get("by") or tr("unbekannt"), fmt_int(imp.get("n", 0))))
        self.ahr_summary.set("\n".join(lines) if lines else tr("Noch keine Preise von Freunden übernommen."))

    def _ahr_save_days(self):
        try:
            days = max(1, min(60, int(self.ahr_days_var.get())))
        except ValueError:
            days = self.ah_shared_days()
        self.ahr_days_var.set(str(days))
        if days != self.ah_shared_days():
            self.cfg["ah_shared_days"] = days
            save_config(self.cfg)
            self.ah_sig = None                      # Auktionshaus-Seite beim nächsten Öffnen neu aufbauen
            self.schedule_link_write()
            self._ahr_show_summary()

    def _ahr_paste_link(self):
        try:
            self.ahr_link_var.set(self.clipboard_get().strip())
        except tk.TclError:
            self.info(tr("Die Zwischenablage ist leer."))
            return
        self.ah_import_link()

    def _ahr_open_recent(self):
        labels = list(self.ahr_cb["values"])
        if self.ahr_file_var.get() not in labels:
            self.info(tr("Im Download-Ordner liegt keine .lzprices-Datei."))
            return
        self.ah_import_file(self._ahr_files[labels.index(self.ahr_file_var.get())])

    def _ahr_open_other(self):
        f = filedialog.askopenfilename(title=tr("AH-Preise öffnen"),
                                       filetypes=[(tr("AH-Preise"), f"*{PRICE_EXT}"), (tr("Alle Dateien"), "*.*")])
        if f:
            self.ah_import_file(Path(f))

    def ah_import_file(self, path: Path):
        """Datei öffnen (auch per Drag & Drop)."""
        self.show_page("share")
        self.share_task("ahreceive")
        try:
            raw = Path(path).read_bytes()
        except OSError as e:
            self.error(tr("Datei konnte nicht gelesen werden: {0}", e))
            return
        self._ah_import_bytes(raw)

    def ah_import_link(self):
        url = self.ahr_link_var.get().strip()
        if not url:
            self.set_status(tr("Bitte den Link zur Datei einfügen."))
            return
        self.ahr_result.set(tr("Lade …"))

        def done(raw, err):
            if err:
                self.ahr_result.set("")
                self.error(str(err) if isinstance(err, PriceError) else tr("Konnte nicht geladen werden: {0}", err))
                return
            self.ahr_link_var.set("")
            self._ah_import_bytes(raw)
        self.run_quiet(lambda: fetch_discord_file(url), done)

    def _ah_import_bytes(self, raw: bytes):
        if not self.flavor:
            return
        try:
            d = parse_prices(raw)
        except PriceError as e:
            self.ahr_result.set("")
            self.error(str(e))
            return
        if d["flavor"] and d["flavor"] != self.flavor:
            if not self.ask(tr("Diese Preise stammen aus {0}, du bist gerade in {1}. Trotzdem übernehmen?",
                               d["flavor"].strip("_"), self.flavor.strip("_")), yes=tr("Übernehmen"), no=tr("Abbrechen")):
                return
        store = load_shared(self.flavor)
        res = merge_prices(store, d)
        prune_shared(store)
        save_shared(self.flavor, store)
        days = self.ah_shared_days()
        stale = sum(1 for v in d["p"].values() if v[1] < time.time() - days * 86400)
        who = d["by"] or tr("einem Freund")
        text = tr("{0} Preise von {1} für {2} übernommen: {3} neu, {4} aktueller als bisher, {5} älter (ignoriert).",
                  fmt_int(d["n"]), who, d["realm"], fmt_int(res["new"]), fmt_int(res["newer"]), fmt_int(res["older"]))
        if stale:
            text += " " + tr("{0} davon sind älter als {1} Tage und zählen nicht mehr.", fmt_int(stale), days)
        self.ahr_result.set(text)
        log.info("AH-Preise übernommen: %s von %s (%s)", d["realm"], who, res)
        self.ah_sig = None
        self.schedule_link_write()
        self._ahr_show_summary()

    def ah_clear_shared(self):
        if not self.flavor or not self.ask(tr("Alle übernommenen Preise von Freunden löschen? Deine eigenen Scans bleiben."),
                                           yes=tr("Löschen"), no=tr("Abbrechen")):
            return
        save_shared(self.flavor, {"realms": {}, "imports": []})
        self.ahr_result.set("")
        self.ah_sig = None
        self.schedule_link_write()
        self._ahr_show_summary()
