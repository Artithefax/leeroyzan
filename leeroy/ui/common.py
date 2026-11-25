"""Gemeinsame Helfer des Hauptfensters: Hintergrund-Vorgänge, Spielstart, Pfade und Versionen. (Mixin, wird in App eingemischt)."""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from tkinter import filedialog
import tkinter as tk

from ..i18n import tr
from ..config import log, save_config
from ..gameupdate import check_update, local_build, open_battlenet as open_battlenet_app, quiet_for
from ..wow import Addon, FLAVOR_RE, find_wow_exe, flavor_label, list_flavors, read_game_version, running_wow
from ..curseforge import cf_download_url, default_download_dir
from ..selfupdate import NoReleaseYet, clean_child_env
from ..wowhead import wowhead_base


class CommonMixin:
    """Teil des Hauptfensters (wird in App eingemischt)."""

    # ----- Hilfen ---------------------------------------------------------- #
    @property
    def root_path(self) -> str:
        return self.root_var.get().strip()

    @property
    def flavor(self) -> str:
        # Auswahlfeld zeigt evtl. "_classic_beta_  (Forever)" – nur den Ordnernamen nehmen
        parts = self.flavor_var.get().split()
        return parts[0] if parts else ""

    def sources(self) -> dict:
        return self.cfg["sources"].setdefault(self.flavor, {})

    def sets(self) -> dict:
        return self.cfg["sets"].setdefault(self.flavor, {})

    def source_label(self, sid: str, src: dict) -> str:
        if src.get("type") == "curseforge":
            return f"CurseForge: {src.get('name') or sid}"
        return f"GitHub: {sid}"

    def source_name(self, sid: str) -> str:
        src = self.sources().get(sid, {})
        return src.get("name") or sid

    def source_page(self, sid: str, src: dict) -> str:
        if src.get("type") == "curseforge":
            return src.get("page") or f"https://www.curseforge.com/wow/addons/{src.get('slug', '')}"
        return f"https://github.com/{sid}/releases"

    def cf_key(self) -> str:
        return (self.cfg.get("curseforge_key") or "").strip()

    def download_dir(self) -> Path:
        d = (self.cfg.get("download_dir") or "").strip()
        return Path(d) if d else default_download_dir()

    def folder_source(self, folder: str) -> tuple[str, dict] | tuple[None, None]:
        for sid, s in self.sources().items():
            if folder in s.get("folders", []):
                return sid, s
        return None, None

    def start_wow(self, check: bool = True):
        """„Spielen“: erst (kurz) prüfen, ob WoW ein Update braucht – dann WoW oder die Battle.net-App starten."""
        if not self.root_path or not self.flavor:
            self.notify(tr("Bitte zuerst den WoW-Ordner wählen."), "warn", [(tr("WoW-Ordner wählen"), self.browse_root), (tr("Einstellungen"), lambda: self.show_page("settings"))], key="noroot")
            return
        exe = find_wow_exe(self.root_path, self.flavor)
        if not exe:
            self.error(tr("In {0} wurde keine WoW-.exe gefunden.\n\nIst diese Version vollständig installiert?", Path(self.root_path) / self.flavor))
            return
        running = running_wow(self.root_path, self.flavor)
        if running:
            self.info(tr("WoW läuft bereits ({0}).", ', '.join(running)))
            return
        if self.busy:
            self.info(tr("Bitte warten, bis „{0}“ fertig ist – sonst ändert Leeroyzan Addons, während WoW sie lädt.",
                         self.busy_label))
            return
        if check and self.cfg.get("wow_update_check", True):
            self._check_wow_then_start(exe)
            return
        self._launch_wow(exe)

    def _check_wow_then_start(self, exe: Path):
        """Fragt Blizzards Versionsserver (höchstens ein paar Sekunden). Geht das nicht, startet WoW wie bisher."""
        root, flavor = self.root_path, self.flavor
        self.set_status(tr("Prüfe, ob WoW ein Update braucht …"))
        try:
            self.play_btn.state(["disabled"])
        except (AttributeError, tk.TclError):
            pass

        def done(res, err):
            try:
                self.play_btn.state(["!disabled"])
            except (AttributeError, tk.TclError):
                pass
            if err or not res or res.get("state") != "update":
                if err or (res or {}).get("error"):
                    log.info("WoW-Update-Prüfung übersprungen: %s", err or res.get("error"))
                self._launch_wow(exe)
                return
            self.wow_needs_update(res)
        self.run_quiet(lambda: check_update(root, flavor), done)

    def wow_needs_update(self, res: dict):
        """WoW braucht ein Update: Battle.net-App öffnen und warten, bis der neue Build da ist."""
        log.info("WoW braucht ein Update: %s -> %s (%s)", res.get("local"), res.get("remote"), res.get("product"))
        self.dismiss("wowupdate-avail")
        self.open_battlenet(for_update=True)
        auto = bool(self.cfg.get("wow_update_autostart", True))
        gen = getattr(self, "_wow_wait_gen", 0) + 1          # nur ein Beobachter, auch wenn „Spielen“ öfter gedrückt wird
        self._wow_wait_gen = gen
        self._wow_update_wait = {"target": res.get("target", ""), "version": res.get("remote", ""), "start": auto,
                                 "until": time.time() + self.WOW_UPDATE_WAIT, "root": self.root_path, "flavor": self.flavor,
                                 "gen": gen}
        text = tr("WoW braucht ein Update ({0} → {1}). Die Battle.net-App ist offen und lädt es.",
                  res.get("local") or "?", res.get("remote") or "?")
        text += " " + (tr("Leeroyzan startet WoW, sobald es fertig ist.") if auto else
                       tr("Leeroyzan meldet sich, sobald es fertig ist."))
        self.notify(text, "update", [(tr("Trotzdem starten"), lambda: self.start_wow(check=False)),
                                     (tr("Nicht warten"), self.cancel_wow_update_wait)], key="wowupdate")
        self.set_status(tr("Warte auf das WoW-Update …"))
        self.after(self.WOW_UPDATE_POLL_MS, lambda: self._watch_wow_update(gen))

    WOW_UPDATE_WAIT = 3 * 3600          # so lange wartet Leeroyzan höchstens auf das Ende des Updates
    WOW_UPDATE_POLL_MS = 15000
    WOW_UPDATE_QUIET = 30               # Sekunden ohne Schreiben in den Spieldateien = die App ist fertig

    def cancel_wow_update_wait(self):
        self._wow_update_wait = None
        self.dismiss("wowupdate")
        self.set_status(tr("Warten auf das WoW-Update beendet."))

    def _watch_wow_update(self, gen: int = 0):
        """Alle 15 s: Ist der neue Build installiert? Dann WoW starten (oder Bescheid geben)."""
        w = getattr(self, "_wow_update_wait", None)
        if not w or w.get("gen", 0) != gen:
            return
        if w["root"] != self.root_path or w["flavor"] != self.flavor or time.time() > w["until"]:
            self._wow_update_wait = None
            self.dismiss("wowupdate")
            return
        if running_wow(w["root"], w["flavor"]):          # über die Battle.net-App gestartet – nichts mehr zu tun
            self._wow_update_wait = None
            self.dismiss("wowupdate")
            return
        now = local_build(w["root"], w["flavor"])       # während die App schreibt, fehlt die Datei kurz
        done = bool(now) and ((w["target"] and now["build"] == w["target"]) or
                              (not w["target"] and w["version"] and now["version"] == w["version"]))
        if not done or quiet_for(w["root"]) < self.WOW_UPDATE_QUIET:       # Build da, aber die App schreibt noch
            self.after(self.WOW_UPDATE_POLL_MS, lambda: self._watch_wow_update(gen))
            return
        self._wow_update_wait = None
        self.dismiss("wowupdate")
        self.dismiss("wowupdate-avail")
        self.wow_version_state = {"state": "current", "local": now["version"], "remote": now["version"]}
        self._show_wow_version()
        log.info("WoW-Update fertig (%s, %s)", now["version"], now["build"])
        if w["start"]:
            self.notify(tr("WoW ist aktualisiert – Leeroyzan startet es."), "ok", timeout=8000)
            self.after(3000, lambda: self._autostart_wow(time.time() + 600))
        else:
            self.notify(tr("WoW ist aktualisiert."), "update", [(tr("Spielen"), lambda: self.start_wow(check=False))],
                        key="wowupdate-done")

    def _autostart_wow(self, until: float):
        """Start nach dem Update – wartet, falls Leeroyzan gerade Addons aktualisiert (höchstens zehn Minuten)."""
        if not self.root_path or not self.flavor or running_wow(self.root_path, self.flavor):
            return
        if self.busy and time.time() < until:
            self.after(5000, lambda: self._autostart_wow(until))
            return
        self.start_wow(check=False)

    def check_wow_version(self, silent: bool = True):
        """Ohne zu starten: Ist ein WoW-Update da? (beim Start von Leeroyzan, alle paar Stunden, „Jetzt prüfen“)"""
        if not self.root_path or not self.flavor:
            return
        root, flavor = self.root_path, self.flavor

        def done(res, err):
            res = res or {"state": "unknown", "error": str(err)}
            self.wow_version_state = res
            self._show_wow_version()
            waiting = getattr(self, "_wow_update_wait", None)          # „Spielen“ wartet schon – kein zweiter Hinweis
            if res.get("state") == "update" and not waiting and not running_wow(root, flavor):
                seen = getattr(self, "_wow_update_seen", set())
                if not silent or res.get("target") not in seen:
                    seen.add(res.get("target"))
                    self._wow_update_seen = seen
                    self.notify(tr("WoW-Update verfügbar ({0} → {1}). Die Battle.net-App lädt es, sobald sie läuft.",
                                   res.get("local") or "?", res.get("remote") or "?"), "update",
                                [(tr("Battle.net öffnen"), lambda: self.open_battlenet(for_update=True))],
                                key="wowupdate-avail")
            elif res.get("state") == "current":
                self.dismiss("wowupdate-avail")
            if not silent and res.get("state") != "update":
                self.set_status(tr("WoW ist aktuell ({0}).", res.get("local")) if res.get("state") == "current" else
                                tr("Ob WoW ein Update braucht, ließ sich gerade nicht prüfen."))
        self.run_quiet(lambda: check_update(root, flavor), done)

    def _show_wow_version(self):
        var = getattr(self, "wow_version_var", None)
        res = getattr(self, "wow_version_state", None)
        if var is None:
            return
        if not res:
            var.set(tr("Noch nicht geprüft."))
        elif res.get("state") == "current":
            var.set(tr("Installiert: {0} – aktuell.", res.get("local") or "?"))
        elif res.get("state") == "update":
            var.set(tr("Installiert: {0} – Update auf {1} verfügbar.", res.get("local") or "?", res.get("remote") or "?"))
        else:
            var.set(tr("Ließ sich nicht prüfen (offline oder Spielversion unbekannt)."))

    def _watch_wow_version(self):
        """Alle paar Stunden, solange Leeroyzan läuft."""
        try:
            if self.cfg.get("wow_update_check", True):
                self.check_wow_version(silent=True)
        finally:
            self.after(self.WOW_VERSION_POLL_MS, self._watch_wow_version)

    WOW_VERSION_POLL_MS = 2 * 3600 * 1000

    def _launch_wow(self, exe: Path):
        self.auto_update_link(quiet=True)          # WoW soll gleich das aktuelle Leeroylink laden
        try:
            flags = 0x00000008 | 0x00000200 if sys.platform.startswith("win") else 0  # losgelöst
            proc = subprocess.Popen([str(exe)], cwd=str(exe.parent), close_fds=True, creationflags=flags,
                                    env=clean_child_env())
        except OSError as e:
            self.error(tr("WoW konnte nicht gestartet werden:\n{0}", e))
            return
        log.info("WoW gestartet: %s", exe)
        self._watch_game_start(proc, time.time())
        self.set_status(tr("{0} gestartet. Falls WoW nach dem Login fragt: Battle.net-App öffnen.", exe.name))
        btn = self.play_btn
        btn.state(["disabled"])

        def enable():
            try:
                btn.state(["!disabled"])
            except tk.TclError:
                pass          # Ansicht inzwischen gewechselt
        self.after(15000, enable)   # Doppelstarts vermeiden

    GAME_EARLY_EXIT = 25            # Sekunden: endet WoW früher, ist meist die Battle.net-App im Weg

    def _watch_game_start(self, proc, started: float):
        """Endet WoW gleich nach dem Start wieder, steckt fast immer die Battle.net-App dahinter: Sie aktualisiert
        oder repariert gerade das Spiel und hält dessen Daten gesperrt („container locked“)."""
        code = proc.poll()
        if code is None:
            if time.time() - started < self.GAME_EARLY_EXIT:
                self.after(1000, lambda: self._watch_game_start(proc, started))
            return
        log.warning("WoW nach %.0f s beendet (Code %s)", time.time() - started, code)
        acts = [(tr("Battle.net öffnen"), self.open_battlenet)] if sys.platform.startswith("win") else []
        self.notify(tr("WoW hat sich gleich nach dem Start wieder beendet. Meist aktualisiert oder repariert die "
                       "Battle.net-App gerade das Spiel und hält seine Dateien gesperrt („container locked“). Warte, "
                       "bis sie fertig ist, oder starte WoW einmal über die Battle.net-App."), "warn", acts, key="gamestart")

    def open_battlenet(self, for_update: bool = False):
        """Öffnet die Battle.net-App – wenn möglich gleich auf der Seite der gewählten Spielversion."""
        try:
            if self.root_path and self.flavor:
                how = open_battlenet_app(self.root_path, self.flavor)
                log.info("Battle.net-App geöffnet (%s)%s", how, " für ein WoW-Update" if for_update else "")
            else:
                os.startfile("battlenet://")          # öffnet die Battle.net-App, wenn sie installiert ist
        except (AttributeError, OSError) as e:
            self.warn(tr("Die Battle.net-App ließ sich nicht öffnen: {0}", e))

    def open_header_link(self, url: str):
        self.open_link(wowhead_base(self.cfg.get("wowhead_edition", "classic")) if url == "wowhead" else url)

    def open_link(self, url: str):
        try:
            webbrowser.open(url, new=2)
            self.set_status(tr("Geöffnet: {0}", url))
        except Exception as e:  # noqa
            self.error(tr("Link konnte nicht geöffnet werden:\n{0}\n\n{1}", url, e))

    def set_status(self, text: str):
        self.status_var.set(text)

    def save_options(self):
        self.cfg["auto_backup"] = bool(self.auto_backup_var.get())
        self.cfg["check_on_start"] = bool(self.check_start_var.get())
        if getattr(self, "wow_check_var", None) is not None:
            self.cfg["wow_update_check"] = bool(self.wow_check_var.get())
            self.cfg["wow_update_autostart"] = bool(self.wow_autostart_var.get())
        label = self.self_update_var.get()
        mode = next((k for k, v in self.UPDATE_MODES.items() if tr(v) == label), "auto")
        changed = mode != self.cfg.get("self_update_mode")
        self.cfg["self_update_mode"] = mode
        self.cfg["self_update_check"] = mode != "off"
        save_config(self.cfg)
        if changed and mode == "auto":
            self.after(300, lambda: self.check_manager_update(silent=True))

    def ready(self, modifies: bool = True, quiet: bool = False) -> bool:
        """Prüft, ob eine Aktion starten darf. modifies=True warnt zusätzlich, wenn WoW läuft."""
        if self.asking:
            if not quiet:
                self.set_status(tr("Bitte zuerst die Frage oben beantworten."))
            return False
        if self.busy:
            if not quiet:
                self.info(tr("Bitte warten, ein Vorgang läuft noch."))
            return False
        if not self.root_path or not self.flavor:
            if not quiet:
                self.notify(tr("Bitte zuerst den WoW-Ordner wählen."), "warn", [(tr("WoW-Ordner wählen"), self.browse_root), (tr("Einstellungen"), lambda: self.show_page("settings"))], key="noroot")
            return False
        if modifies:
            running = running_wow(self.root_path, self.flavor)
            if running and not self.ask(
                    tr("WoW läuft gerade ({0}). Änderungen an Addons wirken erst nach /reload, und beim Ausloggen kann WoW Einstellungen überschreiben. Trotzdem fortfahren?", ', '.join(running)),
                    yes=tr("Fortfahren"), no=tr("Abbrechen")):
                return False
        return True

    @property
    def busy(self) -> bool:
        """Läuft ein Vorgang, der Addons oder WTF ändert? Reine Abfragen (Update-Prüfung, Suche) zählen nicht."""
        return any(j["kind"] == "write" for j in self.running_jobs.values())

    @property
    def busy_label(self) -> str:
        writes = [j["label"] for j in self.running_jobs.values() if j["kind"] == "write"]
        return writes[0] if writes else tr("ein Vorgang")

    def run_bg(self, label: str, func, on_done=None, on_error=None, kind: str = "write"):
        """Führt func im Hintergrund aus; on_done(result) läuft im GUI-Thread.

        kind="write": ändert Addons oder WTF – andere schreibende Aktionen warten, bis er fertig ist.
        kind="read": nur Abfragen (Updates prüfen, suchen) – sperrt nichts, auch nicht den Spielstart."""
        if kind == "read" and any(j["label"] == label for j in self.running_jobs.values()):
            return                                   # dieselbe Abfrage läuft schon
        job = self._next_job = getattr(self, "_next_job", 0) + 1
        self.running_jobs[job] = {"label": label, "kind": kind, "started": time.time()}
        self.set_status(label + " …")
        self._show_activity()

        def worker():
            try:
                res = func()
                self.jobs.put((job, on_done, on_error, res, None))
            except Exception as e:  # noqa
                self.jobs.put((job, on_done, on_error, None, e))

        threading.Thread(target=worker, daemon=True, name=f"job-{job}").start()

    def run_quiet(self, func, on_done):
        """Wie run_bg, aber unsichtbar: kein Status, kein Sanduhr-Cursor, blockiert nichts.
        on_done(result, error) läuft im GUI-Thread."""
        def worker():
            try:
                self.quiet_jobs.put((on_done, func(), None))
            except Exception as e:  # noqa
                self.quiet_jobs.put((on_done, None, e))

        threading.Thread(target=worker, daemon=True).start()

    def _show_activity(self):
        """Sanduhr und Liste laufender Vorgänge unten rechts."""
        jobs = list(self.running_jobs.values())
        try:
            self.config(cursor="watch" if any(j["kind"] == "write" for j in jobs) else "")
            if getattr(self, "activity_var", None) is not None:
                self.activity_var.set(("⟳ " + " · ".join(j["label"] for j in jobs)) if jobs else "")
        except tk.TclError:
            pass

    def _run_callback(self, cb, *args):
        """Ein Fehler in einer Rückmeldung darf die Verarbeitung weiterer Vorgänge nie anhalten."""
        try:
            cb(*args)
        except Exception as e:  # noqa
            log.exception("Fehler nach einem Hintergrund-Vorgang: %s", e)
            try:
                self.set_status(tr("Fehler: {0}", e))
            except tk.TclError:
                pass

    def _poll_jobs(self):
        try:
            while True:
                try:
                    cb, res, err = self.quiet_jobs.get_nowait()
                except queue.Empty:
                    break
                self._run_callback(cb, res, err)
            while True:
                try:
                    job, cb, err_cb, res, err = self.jobs.get_nowait()
                except queue.Empty:
                    break
                self.running_jobs.pop(job, None)
                self._show_activity()
                if err:
                    if not isinstance(err, NoReleaseYet):
                        log.error("%s", err)
                    if err_cb:
                        self._run_callback(err_cb, err)
                    else:
                        self.set_status(tr("Fehler: {0}", err))
                        self._run_callback(self.error, str(err))
                elif cb:
                    self._run_callback(cb, res)
        finally:
            self.after(100, self._poll_jobs)

    def selected_addons(self) -> list[Addon]:
        """Ausgewählte Addons; eine ausgewählte Gruppe zählt mit allen ihren Ordnern."""
        if self.tree is None or not self.tree.winfo_exists():
            return []
        names = set()
        for iid in self.tree.selection():
            if iid.startswith("grp:"):
                names.update(self.tree.get_children(iid))
                names.update(self.group_members.get(iid, []))
            else:
                names.add(iid)
        return [a for a in self.addons if a.name in names]

    def _remember_open(self, is_open: bool):
        iid = self.tree.focus()
        if iid.startswith("grp:"):
            (self.open_groups.add if is_open else self.open_groups.discard)(iid)

    def _toggle_grouping(self):
        self.cfg["group_addons"] = bool(self.group_var.get())
        save_config(self.cfg)
        self.render()

    def _column_at(self, col_id: str) -> str:
        """Spaltenname zur Treeview-Spalten-ID (#1, #2 …) der aktuellen Ansicht."""
        if not col_id or col_id == "#0":
            return ""
        shown = tuple(self.tree["displaycolumns"])
        if not shown or shown[0] == "#all":
            shown = self.COLUMNS
        i = int(col_id[1:]) - 1
        return shown[i] if 0 <= i < len(shown) else ""

    def _pending_cf(self, addons) -> str:
        """Quellen-ID eines offenen CurseForge-Updates dieser Addons ("" wenn keins)."""
        for a in addons:
            sid, src = self.folder_source(a.name)
            if not src or src.get("type") != "curseforge":
                continue
            if self.has_update(sid) and (self.update_info.get(sid) or {}).get("best"):
                return sid
        return ""

    def cf_update_link(self, addons) -> tuple[str, str]:
        """(Name, Download-Adresse) eines verfügbaren CurseForge-Updates dieser Addons – sonst ("", "")."""
        sid = self._pending_cf(addons)
        if not sid:
            return "", ""
        info = self.update_info[sid]
        return self.sources()[sid].get("name") or sid, cf_download_url(info, info["best"])

    def open_cf_update(self, addons=None, sid: str = ""):
        """CurseForge-Download im Browser öffnen – die geladene ZIP wird danach automatisch installiert."""
        if not sid:
            sid = self._pending_cf(list(addons) if addons is not None else self.selected_addons())
        info = self.update_info.get(sid) or {}
        if not sid or not info.get("best"):
            return
        self.open_link(cf_download_url(info, info["best"]))
        self.watch_download(sid, manual=True)
        self.refresh_browser_list()
        self.set_status(tr("CurseForge-Download für {0} geöffnet – sobald die Datei in {1} liegt, installiert Leeroyzan sie automatisch.", self.source_name(sid), self.download_dir()))

    # ----- Pfade / Versionen ----------------------------------------------- #
    def browse_root(self):
        d = filedialog.askdirectory(title=tr("World of Warcraft-Ordner wählen"),
                                    initialdir=self.root_path or None)
        if d:
            self.root_var.set(d)
            self._load_flavors()

    def _load_flavors(self):
        # Wurde direkt ein Versionsordner (z. B. ..\_classic_beta_) oder ein Unterordner
        # davon (Interface, AddOns) gewählt? Dann auf den WoW-Hauptordner korrigieren.
        preselect = ""
        p = Path(self.root_path) if self.root_path else None
        if p is not None:
            for cand in (p, *p.parents):
                if FLAVOR_RE.match(cand.name):
                    preselect = cand.name
                    self.root_var.set(str(cand.parent))
                    break
        if preselect:
            self.flavor_var.set(preselect)
        flavors = list_flavors(self.root_path)
        self.flavor_cb["values"] = [flavor_label(f) for f in flavors]
        current = self.flavor if self.flavor in flavors else (flavors[0] if flavors else "")
        self.flavor_var.set(flavor_label(current) if current else "")
        if self.root_path and not flavors:
            self.set_status(tr("Keine Spielversion gefunden – stimmt der WoW-Ordner?"))
        self.on_flavor_change()

    def on_flavor_change(self):
        self.cfg["wow_root"] = self.root_path
        self.cfg["flavor"] = self.flavor
        save_config(self.cfg)
        self.updates.clear()
        self.update_info.clear()
        self.game = read_game_version(self.root_path, self.flavor) if self.flavor else None
        self.update_game_info()
        self.reload_sets()
        self.refresh(background=True)
        self._sessions_flavor_changed()
