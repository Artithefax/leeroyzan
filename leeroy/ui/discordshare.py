"""An Discord teilen: ein gemeinsamer Dialog (Vorschau, eigener Kommentar) für Builds, Guides, Wowhead, Quests,
Charaktere und Addon-Listen. (Mixin, wird in App eingemischt)."""
from __future__ import annotations

from tkinter import ttk
import tkinter as tk

from ..config import log, save_config
from ..discordshare import (
    share_addons_messages,
    share_build_messages,
    share_char_messages,
    share_guide_messages,
    share_preview,
    share_send,
    share_text_messages,
    share_wowhead_messages,
)
from ..i18n import tr
from ..presence import game_title
from ..reports import DISCORD_WEBHOOK_RE, report_plain_text
from ..sessions import load_sessions
from ..sharing import build_list, list_to_code
from ..wowhead import wowhead_url
from .theme import THEME

DISCORD_BTN = "Discord ↗"
SHARE_CODE_PART = 1800          # passt mit Codeblock in eine Discord-Nachricht (2000 Zeichen)


class DiscordSharePage:
    """Teil des Hauptfensters (wird in App eingemischt)."""

    # --- Ziel ----------------------------------------------------------------------------- #
    def share_hook(self) -> str:
        """Eigener Kanal fürs Teilen – sonst derselbe wie für die Sitzungsberichte."""
        return ((self.cfg.get("discord_share_webhook") or "").strip()
                or (self.cfg.get("discord_webhook") or "").strip())

    def _share_author(self) -> str:
        return (self.cfg.get("discord_share_name") or "").strip()

    # --- Der Dialog ---------------------------------------------------------------------- #
    def discord_share(self, what: str, make, options: list[tuple[str, str, bool]] | None = None) -> bool:
        """Zeigt die Vorschau, fragt nach einem Kommentar und sendet.
        make(comment, author, opts) -> Nachrichten; options: (Schlüssel, Beschriftung, Vorgabe) als Häkchen.
        True, wenn gesendet wird."""
        url = self.share_hook()
        if not url:
            self.notify(tr("Trage zuerst eine Discord-Webhook-Adresse in den Einstellungen ein."), "info",
                        [(tr("Einstellungen"), lambda: self.show_page("settings"))], key="discord-share")
            return False
        comment = tk.StringVar(value="")
        flags = {k: tk.BooleanVar(value=v) for k, _, v in options or []}
        holder: dict = {}

        def opts() -> dict:
            return {k: bool(v.get()) for k, v in flags.items()}

        def refresh():
            txt = holder.get("txt")
            if txt is None:
                return
            try:
                text = share_preview(make(comment.get(), self._share_author(), opts()))
            except Exception as e:  # noqa – die Vorschau darf den Dialog nie verhindern
                log.warning("Discord-Vorschau: %s", e)
                text = str(e)
            txt.configure(state="normal")
            txt.delete("1.0", "end")
            txt.insert("end", text)
            txt.configure(state="disabled")

        def extra(body, bg):
            t = THEME
            frame, txt = self._text(body, height=10)
            frame.pack(fill="x", pady=(8, 0))
            holder["txt"] = txt
            for k, label, _ in options or []:
                tk.Checkbutton(body, text=label, variable=flags[k], command=refresh, bg=bg, fg=t["text"],
                               activebackground=bg, activeforeground=t["gold"], selectcolor=t["row_a"],
                               highlightthickness=0, font=self.fonts["base"]).pack(anchor="w", pady=(6, 0))
            row = tk.Frame(body, bg=bg)
            row.pack(fill="x", pady=(8, 0))
            tk.Label(row, text=tr("Dein Kommentar (optional):"), bg=bg, fg=t["text"],
                     font=self.fonts["base"]).pack(side="left", padx=(0, 8))
            e = ttk.Entry(row, textvariable=comment)
            e.pack(side="left", fill="x", expand=True)
            holder["entry"] = e
            comment.trace_add("write", lambda *a: refresh())
            refresh()
            self.after(50, lambda: e.winfo_exists() and e.focus_set())
        go = self._wait_inline(tr("{0} an Discord senden?", what), "ask",
                               [(tr("An Discord senden"), True), (tr("Abbrechen"), False)], extra=extra, default=False)
        if not go:
            return False
        msgs = make(comment.get(), self._share_author(), opts())

        def done(res, err):
            if err:
                log.warning("Discord teilen: %s", err)
                self.error(tr("Discord: {0}", err))
                return
            log.info("An Discord geteilt: %s (%d Nachrichten)", what, res)
            self.set_status(tr("An Discord gesendet: {0}", what))
        self.set_status(tr("Sende an Discord …"))
        self.run_quiet(lambda: share_send(url, msgs), done)
        return True

    # --- Was sich teilen lässt -------------------------------------------------------------- #
    def share_build_discord(self):
        b = getattr(self, "bld_build", None)
        if not b:
            return
        row = self._bld_saved_row()
        name = row.get("name", "") if row and row.get("link") == b.link() else ""
        self.discord_share(tr("Build {0}", name or f"{b.cls.name} {b.summary()}"),
                           lambda c, a, o: share_build_messages(b, name, c, a))

    def share_guide_discord(self):
        g = getattr(self, "gd_current", None)
        if g:
            self.discord_share(tr("Guide „{0}“", g.get("title", "")), lambda c, a, o: share_guide_messages(g, "", c, a))

    def share_wowhead_discord(self):
        r = self._wh_selected()
        if not r:
            return
        key = self._wh_key_of(r)
        tip, page = self.wh_tips.get(key), self.wh_pages.get(key)
        self.discord_share(f"{tr(r['kind_name'])} „{r['name']}“", lambda c, a, o: share_wowhead_messages(r, tip, c, a, page))

    def share_quest_discord(self):
        qid = getattr(self, "qdb_current", None)
        if qid is None or self.qdb is None:
            return
        name = self.qdb.quest_name(qid, self._qdb_locale())
        text = report_plain_text(self._qdb_parts(qid))
        url = wowhead_url(self.cfg.get("wowhead_edition", "classic"), "quest", qid)
        self.discord_share(tr("Quest „{0}“", name),
                           lambda c, a, o: share_text_messages(name, text, url, f"Quest · ID {qid}", comment=c, author=a))

    def _chars_selected(self) -> dict | None:
        sel = self.chars_tree.selection() if getattr(self, "chars_tree", None) else ()
        try:
            return self._chars_rows[int(sel[0][1:])] if sel else None
        except (ValueError, IndexError):
            return None

    def share_char_discord(self):
        c = self._chars_selected()
        if not c:
            return
        mine = [s for s in (self.sessions_all or load_sessions(self.flavor) if self.flavor else []) if s["char"] == c["key"]]
        played = sum(s["played"] for s in mine)
        self.discord_share(tr("Charakter {0}", c["name"]),
                           lambda cm, a, o: share_char_messages(c, played, len(mine), o.get("gold", False), cm, a),
                           options=[("gold", tr("Gold mit anzeigen"), False)])

    def share_addons_discord(self, addons: list | None = None):
        """addons=None: die Auswahl der Teilen-Seite; sonst genau diese Addons (Rechtsklick in der Liste)."""
        if addons is None:
            addons = self._share_addons()
            exact, with_sets = self.share_exact.get(), self.share_sets.get()
        else:
            exact, with_sets = True, False
        if not addons:
            return
        payload, unlinked = build_list(addons, self.sources(), self.flavor, self.sets(), exact, with_sets)
        parts = list_to_code(payload, SHARE_CODE_PART) if payload["a"] else []
        title = game_title(self.flavor)
        what = (tr("Addon „{0}“", addons[0].title or addons[0].name) if len(addons) == 1
                else tr("{0} Addons", len(addons)))
        self.discord_share(what, lambda c, a, o: share_addons_messages(payload, parts, unlinked, title, c, a))

    # --- Einstellungen ------------------------------------------------------------------------ #
    def _w_discord_share(self, box):
        ttk.Separator(box).pack(fill="x", pady=(12, 8))
        ttk.Label(box, text=tr("Teilen: Builds, Guides, Wowhead, Quests, Charaktere und Addons haben einen Knopf „Discord ↗“. "
                               "Für Geteiltes kannst du einen eigenen Kanal eintragen – leer bleibt es der Kanal oben."),
                  style="Panel.TLabel", wraplength=280, justify="left").pack(anchor="w")
        e = ttk.Entry(box, textvariable=self.discord_share_var)
        e.pack(fill="x", pady=(6, 0))
        e.bind("<FocusOut>", lambda ev: self._save_discord_share())
        e.bind("<Return>", lambda ev: self._save_discord_share())
        ttk.Label(box, text=tr("Dein Name unter geteilten Beiträgen (optional):"), style="Panel.TLabel").pack(anchor="w", pady=(8, 0))
        n = ttk.Entry(box, textvariable=self.discord_share_name_var)
        n.pack(fill="x", pady=(4, 0))
        n.bind("<FocusOut>", lambda ev: self._save_discord_share())
        n.bind("<Return>", lambda ev: self._save_discord_share())

    def _save_discord_share(self):
        url = self.discord_share_var.get().strip()
        if url and not DISCORD_WEBHOOK_RE.match(url):
            self.set_status(tr("Das ist keine Discord-Webhook-Adresse."))
            return
        self.cfg["discord_share_webhook"] = url
        self.cfg["discord_share_name"] = self.discord_share_name_var.get().strip()[:60]
        save_config(self.cfg)
