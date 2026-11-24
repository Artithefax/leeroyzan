"""Statistik-Vorlagen (Editor, Auswahl auf der Leeroylink-Seite) und Discord-Post-Aufträge (Liste, Editor,
Vorschau, Zeitplan). (Mixin, wird in App eingemischt)."""
from __future__ import annotations

import copy
import time

from tkinter import ttk
import tkinter as tk

from ..autopost import (
    CHAR_MODES,
    WEBHOOKS,
    WHEN,
    due_period,
    job_name,
    job_url,
    load_jobs,
    mark_sent,
    new_job_id,
    next_run_text,
    period_job_messages,
    preview_messages,
    save_jobs,
    send_messages,
    session_job_messages,
    session_job_todo,
)
from ..config import log, save_config
from ..i18n import tr
from ..metrics import (
    CATEGORIES,
    METRICS,
    OPTION_NAMES,
    Ctx,
    all_templates,
    day_start_minutes,
    embed_preview_text,
    metric_title,
    new_template_id,
    template_name,
    template_report,
)
from ..sessions import load_sessions
from ..wow import running_wow
from .theme import THEME


class StatisticsMixin:
    """Vorlagen und Post-Aufträge (Teil des Hauptfensters)."""

    AUTOPOST_POLL_MS = 60000
    AUTOPOST_RETRY = 15 * 60          # nach einem Fehler so lange warten, bevor ein Auftrag es noch einmal versucht

    # ----- Hilfen ---------------------------------------------------------------------- #
    def _stat_window(self, title: str, size: str) -> tuple[tk.Toplevel, ttk.Frame]:
        t = THEME
        win = tk.Toplevel(self)
        win.fonts = self.fonts
        win.title(title)
        win.configure(bg=t["panel"])
        win.transient(self)
        w, h = (int(x) for x in size.split("x"))
        w, h = min(w, self.winfo_screenwidth()), min(h, self.winfo_screenheight() - 60)
        x = self.winfo_rootx() + (self.winfo_width() - w) // 2
        y = self.winfo_rooty() + (self.winfo_height() - h) // 3
        x = max(0, min(x, self.winfo_screenwidth() - w))
        y = max(0, min(y, self.winfo_screenheight() - h - 40))
        win.geometry(f"{w}x{h}+{x}+{y}")
        win.keep = []                       # Tk-Variablen leben so lange wie das Fenster
        frame = ttk.Frame(win, style="Panel.TFrame", padding=(18, 14))
        frame.pack(fill="both", expand=True)
        return win, frame

    def _stat_listbox(self, parent, height=10, select="browse") -> tk.Listbox:
        t = THEME
        frame = self._framed(parent)
        lb = tk.Listbox(frame, height=height, selectmode=select, exportselection=False, bg=t["row_a"], fg=t["text"],
                        selectbackground=t["btn_primary"], selectforeground=t["btn_text"], highlightthickness=0,
                        borderwidth=0, activestyle="none", font=self.fonts["base"])
        sb = ttk.Scrollbar(frame, orient="vertical", command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        lb.pack(side="left", fill="both", expand=True, padx=(1, 0), pady=1)
        sb.pack(side="right", fill="y", padx=(0, 1), pady=1)
        lb.frame = frame
        return lb

    def _stat_ctx_for_view(self) -> Ctx:
        """Die Sitzungen, die auf der Leeroylink-Seite gerade gewählt sind (für Vorschau und Vorlagen)."""
        shown = list(getattr(self, "sessions_shown", []) or [])
        prev = getattr(self, "sessions_prev", None)
        chars = (getattr(self, "link_state", {}) or {}).get("chars", {})
        return Ctx(shown, prev=prev, history=list(getattr(self, "sessions_all", []) or []), chars=chars, period=True)

    # ----- Vorlage auf der Leeroylink-Seite ---------------------------------------------- #
    def _sess_template_widgets(self, head, buttons):
        """Auswahl „Standardansicht / Vorlage“ im Seitenkopf und der Knopf zum Editor bei den Ansichten."""
        ttk.Button(buttons, text=tr("Vorlagen …"), command=self.open_template_editor).pack(side="right", padx=(0, 6))
        self.sess_tpl_cb = ttk.Combobox(head, textvariable=self.sess_tpl_var, state="readonly", width=16)
        self.sess_tpl_cb.pack(side="right", padx=(0, 8))
        self.sess_tpl_cb.bind("<<ComboboxSelected>>", lambda e: self._sess_template_changed())
        self._sess_template_values()

    def _sess_template_values(self):
        cb = getattr(self, "sess_tpl_cb", None)
        if cb is None:
            return
        tpl = all_templates(self.cfg)
        self._sess_tpl_ids = [""] + list(tpl)
        labels = [tr("Standardansicht")] + [template_name(tpl[k]) for k in tpl]
        try:
            cb["values"] = labels
            cur = self.cfg.get("sess_template", "")
            self.sess_tpl_var.set(labels[self._sess_tpl_ids.index(cur)] if cur in self._sess_tpl_ids else labels[0])
        except tk.TclError:
            pass

    def _sess_template_changed(self):
        labels = list(self.sess_tpl_cb["values"])
        try:
            self.cfg["sess_template"] = self._sess_tpl_ids[labels.index(self.sess_tpl_var.get())]
        except (ValueError, IndexError):
            self.cfg["sess_template"] = ""
        save_config(self.cfg)
        self._sess_show()

    def sess_template(self) -> dict | None:
        tid = self.cfg.get("sess_template", "")
        return all_templates(self.cfg).get(tid) if tid else None

    def template_parts(self, t: dict, s: dict | None, label: str):
        """Bericht nach Vorlage: eine Sitzung (s) oder alle gezeigten."""
        chars = (self.link_state or {}).get("chars", {})
        if s is not None:
            from ..reports import session_title
            ctx = Ctx([s], history=self.sessions_all, chars=chars)
            return template_report(t, ctx, f"{s['name'] or s['char']} – {session_title(s)}")
        ctx = self._stat_ctx_for_view()
        return template_report(t, ctx, tr("Gesamt – {0}", label))

    # ----- Vorlagen-Editor -------------------------------------------------------------- #
    def open_template_editor(self, select: str = ""):
        old = getattr(self, "_tpl_win", None)
        if old is not None and old.winfo_exists():
            old.lift()
            return
        t = THEME
        win, frame = self._stat_window(tr("Statistik-Vorlagen"), "980x640")
        self._tpl_win = win
        ed = {"id": select or self.cfg.get("sess_template") or "kompakt", "sel": None}

        top = ttk.Frame(frame, style="Panel.TFrame")
        top.pack(fill="x")
        ttk.Label(top, text=tr("Vorlage"), style="Panel.TLabel").pack(side="left", padx=(0, 8))
        tpl_var = tk.StringVar()
        win.keep.append(tpl_var)
        tpl_cb = ttk.Combobox(top, textvariable=tpl_var, state="readonly", width=24)
        tpl_cb.pack(side="left")
        btns = ttk.Frame(top, style="Panel.TFrame")
        btns.pack(side="left", padx=(12, 0))
        hint = tk.StringVar()
        ttk.Label(frame, textvariable=hint, style="Panel.TLabel", foreground=t["text_faint2"], wraplength=900,
                  justify="left").pack(anchor="w", pady=(8, 6))

        body = ttk.Frame(frame, style="Panel.TFrame")
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body, style="Panel.TFrame", width=270)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        ttk.Label(left, text=tr("Bausteine"), style="CardKicker.TLabel").pack(anchor="w", pady=(0, 4))
        tf = self._framed(left)
        tf.pack(fill="both", expand=True)
        tree = ttk.Treeview(tf, show="tree", selectmode="browse")
        sb = ttk.Scrollbar(tf, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True, padx=(1, 0), pady=1)
        sb.pack(side="right", fill="y", padx=(0, 1), pady=1)
        for cat, label in CATEGORIES:
            tree.insert("", "end", iid=f"cat:{cat}", text=tr(label), open=True)
        for m in METRICS.values():
            tree.insert(f"cat:{m.cat}", "end", iid=m.id, text=metric_title(m))
        add_btn = ttk.Button(left, text=tr("Hinzufügen →"))
        add_btn.pack(fill="x", pady=(6, 0))

        mid = ttk.Frame(body, style="Panel.TFrame", width=260)
        mid.pack(side="left", fill="y", padx=(14, 0))
        mid.pack_propagate(False)
        ttk.Label(mid, text=tr("In der Vorlage"), style="CardKicker.TLabel").pack(anchor="w", pady=(0, 4))
        lb = self._stat_listbox(mid, height=14)
        lb.frame.pack(fill="both", expand=True)
        mrow = ttk.Frame(mid, style="Panel.TFrame")
        mrow.pack(fill="x", pady=(6, 0))
        up_btn = ttk.Button(mrow, text="↑", width=3)
        up_btn.pack(side="left")
        down_btn = ttk.Button(mrow, text="↓", width=3)
        down_btn.pack(side="left", padx=(4, 0))
        rm_btn = ttk.Button(mrow, text=tr("Entfernen"))
        rm_btn.pack(side="right")
        opt = ttk.Frame(mid, style="Panel.TFrame")
        opt.pack(fill="x", pady=(10, 0))
        desc_var = tk.StringVar()
        ttk.Label(opt, textvariable=desc_var, style="Panel.TLabel", foreground=t["text_faint2"], wraplength=250,
                  justify="left").pack(anchor="w")
        opt_vars = {k: tk.BooleanVar() for k in ("rate", "compare", "nonzero")}
        opt_checks = {k: ttk.Checkbutton(opt, text=tr(OPTION_NAMES[k]), variable=v, style="Wrap.TCheckbutton")
                      for k, v in opt_vars.items()}
        for c in opt_checks.values():
            c.pack(anchor="w", pady=(4, 0))
        top_row = ttk.Frame(opt, style="Panel.TFrame")
        top_row.pack(anchor="w", pady=(6, 0))
        ttk.Label(top_row, text=tr("Anzahl"), style="Panel.TLabel").pack(side="left", padx=(0, 6))
        top_var = tk.StringVar()
        top_spin = ttk.Spinbox(top_row, from_=1, to=25, width=4, textvariable=top_var)
        top_spin.pack(side="left")

        right = ttk.Frame(body, style="Panel.TFrame")
        right.pack(side="left", fill="both", expand=True, padx=(14, 0))
        ttk.Label(right, text=tr("Vorschau (die auf der Leeroylink-Seite gewählten Sitzungen)"),
                  style="CardKicker.TLabel").pack(anchor="w", pady=(0, 4))
        pf, ptxt = self._text(right)
        pf.pack(fill="both", expand=True)
        self._tag_text(ptxt)
        ttk.Button(frame, text=tr("Schließen"), command=win.destroy).pack(anchor="e", pady=(10, 0))

        def own() -> dict:
            return self.cfg.setdefault("stat_templates", {})

        def current() -> dict:
            return all_templates(self.cfg).get(ed["id"]) or all_templates(self.cfg)["kompakt"]

        def editable() -> bool:
            return not current().get("builtin")

        def save():
            save_config(self.cfg)
            self._sess_template_values()
            if getattr(self, "current_page", "") == "sessions":
                self._sess_show()

        def fill_templates():
            tpl = all_templates(self.cfg)
            ids = list(tpl)
            if ed["id"] not in tpl:
                ed["id"] = ids[0]
            ed["ids"] = ids
            tpl_cb["values"] = [template_name(tpl[k]) + ("" if tpl[k]["builtin"] else " ✎") for k in ids]
            tpl_cb.current(ids.index(ed["id"]))

        def fill_blocks(keep: int | None = None):
            tp = current()
            lb.delete(0, "end")
            for b in tp["blocks"]:
                m = METRICS[b["id"]]
                flags = [x for x, on in (("/h", b.get("rate")), ("±", b.get("compare")), (f"{b.get('top')}", b.get("top")))
                         if on]
                lb.insert("end", metric_title(m) + (f"  ({', '.join(flags)})" if flags else ""))
            if keep is not None and tp["blocks"]:
                keep = max(0, min(keep, len(tp["blocks"]) - 1))
                lb.selection_set(keep)
                lb.see(keep)
            hint.set(tr("Mitgelieferte Vorlage – zum Ändern mit „Kopieren“ eine eigene anlegen.") if not editable() else
                     tr("Eigene Vorlage – Änderungen werden sofort gespeichert und gelten auch für Discord."))
            state = "normal" if editable() else "disabled"
            for w in (add_btn, up_btn, down_btn, rm_btn, top_spin, *opt_checks.values()):
                w.configure(state=state)
            for w in btn_edit:
                w.configure(state=state)
            show_options()
            preview()

        def preview():
            ctx = self._stat_ctx_for_view()
            parts = template_report(current(), ctx, tr("Vorschau"), tr("{0} Sitzungen", len(ctx.sessions)))
            self._set_text(ptxt, parts=parts)

        def sel_index() -> int | None:
            s = lb.curselection()
            return s[0] if s else None

        def show_options(*_):
            i = sel_index()
            tp = current()
            if i is None or i >= len(tp["blocks"]):
                desc_var.set(tr("Einen Baustein in der Vorlage wählen, um seine Optionen zu sehen."))
                for c in opt_checks.values():
                    c.pack_forget()
                top_row.pack_forget()
                return
            b = tp["blocks"][i]
            m = METRICS[b["id"]]
            desc_var.set(tr(m.desc) if m.desc else metric_title(m))
            for k, c in opt_checks.items():
                c.pack_forget()
                if k == "rate" and not m.rate:
                    continue
                if k in ("compare", "nonzero") and not m.num:
                    continue
                opt_vars[k].set(bool(b.get(k)))
                c.pack(anchor="w", pady=(4, 0))
            top_row.pack_forget()
            if m.top:
                top_var.set(str(b.get("top") or m.top))
                top_row.pack(anchor="w", pady=(6, 0))

        def set_option(*_):
            i = sel_index()
            if i is None or not editable():
                return
            b = own()[ed["id"]]["blocks"][i]
            for k, v in opt_vars.items():
                if v.get():
                    b[k] = True
                else:
                    b.pop(k, None)
            m = METRICS[b["id"]]
            if m.top:
                try:
                    b["top"] = max(1, min(25, int(top_var.get())))
                except ValueError:
                    pass
            save()
            fill_blocks(keep=i)

        def add_block(*_):
            mid_ = tree.focus() or (tree.selection() or [""])[0]
            if mid_ not in METRICS or not editable():
                return
            blocks = own()[ed["id"]]["blocks"]
            i = sel_index()
            pos = len(blocks) if i is None else i + 1
            blocks.insert(pos, {"id": mid_})
            save()
            fill_blocks(keep=pos)

        def move(delta: int):
            i = sel_index()
            if i is None or not editable():
                return
            blocks = own()[ed["id"]]["blocks"]
            j = i + delta
            if 0 <= j < len(blocks):
                blocks[i], blocks[j] = blocks[j], blocks[i]
                save()
                fill_blocks(keep=j)

        def remove():
            i = sel_index()
            if i is None or not editable():
                return
            del own()[ed["id"]]["blocks"][i]
            save()
            fill_blocks(keep=i)

        def ask_name(title: str, initial: str) -> str | None:
            dlg, f = self._stat_window(title, "380x150")
            var = tk.StringVar(value=initial)
            dlg.keep.append(var)
            ttk.Label(f, text=tr("Name der Vorlage"), style="Panel.TLabel").pack(anchor="w")
            e = ttk.Entry(f, textvariable=var)
            e.pack(fill="x", pady=(6, 0))
            e.focus_set()
            e.select_range(0, "end")
            res = {"v": None}

            def ok(*_):
                res["v"] = var.get().strip() or None
                dlg.destroy()
            row = ttk.Frame(f, style="Panel.TFrame")
            row.pack(fill="x", pady=(12, 0))
            ttk.Button(row, text=tr("Übernehmen"), style="Primary.TButton", command=ok).pack(side="left")
            ttk.Button(row, text=tr("Abbrechen"), command=dlg.destroy).pack(side="right")
            e.bind("<Return>", ok)
            dlg.grab_set()
            self.wait_window(dlg)
            return res["v"]

        def new(copy_from: dict | None = None):
            name = ask_name(tr("Neue Vorlage"), tr("Kopie von {0}", template_name(copy_from)) if copy_from else tr("Meine Vorlage"))
            if not name:
                return
            tid = new_template_id(self.cfg, name)
            own()[tid] = {"name": name, "blocks": copy.deepcopy(copy_from["blocks"]) if copy_from else []}
            ed["id"] = tid
            save()
            fill_templates()
            fill_blocks()

        def rename():
            if not editable():
                return
            name = ask_name(tr("Vorlage umbenennen"), current()["name"])
            if name:
                own()[ed["id"]]["name"] = name
                save()
                fill_templates()

        def delete():
            if not editable() or not self.ask(tr("Vorlage „{0}“ löschen?", current()["name"]), yes=tr("Löschen"),
                                              no=tr("Abbrechen")):
                return
            del own()[ed["id"]]
            if self.cfg.get("sess_template") == ed["id"]:
                self.cfg["sess_template"] = ""
            ed["id"] = "kompakt"
            save()
            fill_templates()
            fill_blocks()

        def pick(*_):
            i = tpl_cb.current()
            if 0 <= i < len(ed["ids"]):
                ed["id"] = ed["ids"][i]
                fill_blocks()

        ttk.Button(btns, text=tr("Neu"), command=lambda: new()).pack(side="left")
        ttk.Button(btns, text=tr("Kopieren"), command=lambda: new(current())).pack(side="left", padx=(6, 0))
        btn_edit = [ttk.Button(btns, text=tr("Umbenennen"), command=rename),
                    ttk.Button(btns, text=tr("Löschen"), style="Danger.TButton", command=delete)]
        for b in btn_edit:
            b.pack(side="left", padx=(6, 0))
        tpl_cb.bind("<<ComboboxSelected>>", pick)
        lb.bind("<<ListboxSelect>>", show_options)
        tree.bind("<Double-1>", add_block)
        add_btn.configure(command=add_block)
        up_btn.configure(command=lambda: move(-1))
        down_btn.configure(command=lambda: move(1))
        rm_btn.configure(command=remove)
        for c in opt_checks.values():
            c.configure(command=set_option)
        top_spin.configure(command=set_option)
        top_spin.bind("<Return>", set_option)
        top_spin.bind("<FocusOut>", set_option)
        fill_templates()
        fill_blocks()

    # ----- Post-Aufträge in den Einstellungen ------------------------------------------- #
    def _w_autopost(self, parent):
        t = THEME
        box = ttk.Frame(parent, style="Panel.TFrame")
        ttk.Label(box, text=tr("Automatisch posten"), style="Panel.TLabel", font=self.fonts["bold"]).pack(anchor="w")
        ttk.Label(box, text=tr("Was Leeroyzan wann in Discord postet. Es postet, solange es läuft; verpasste Termine "
                               "holt es beim nächsten Start nach."), style="Panel.TLabel", foreground=t["text_faint2"],
                  wraplength=300, justify="left").pack(anchor="w", pady=(2, 6))
        frame, tv = self._list(box, (("name", tr("Auftrag")), ("next", tr("Nächster Post"))), (150, 120),
                               stretch=("name",), height=4)
        frame.pack(fill="x")
        tv.tag_configure("off", foreground=t["text_faint"])
        tv.bind("<Double-1>", lambda e: self.edit_selected_job())
        self.job_tree = tv
        row = ttk.Frame(box, style="Panel.TFrame")
        row.pack(fill="x", pady=(6, 0))
        ttk.Button(row, text=tr("Bearbeiten"), command=self.edit_selected_job).pack(side="left")
        ttk.Button(row, text=tr("An/Aus"), command=self.toggle_selected_job).pack(side="left", padx=(6, 0))
        ttk.Button(row, text=tr("Neu"), command=lambda: self.open_job_editor(None)).pack(side="left", padx=(6, 0))
        row2 = ttk.Frame(box, style="Panel.TFrame")
        row2.pack(fill="x", pady=(6, 0))
        ttk.Button(row2, text=tr("Vorschau"), command=lambda: self.preview_job(self._selected_job())).pack(side="left")
        ttk.Button(row2, text=tr("Jetzt senden (Test)"), command=lambda: self.test_job(self._selected_job())).pack(
            side="left", padx=(6, 0))
        ttk.Button(row2, text=tr("Löschen"), style="Danger.TButton", command=self.delete_selected_job).pack(side="right")
        drow = ttk.Frame(box, style="Panel.TFrame")
        drow.pack(fill="x", pady=(10, 0))
        ttk.Label(drow, text=tr("Spieltag beginnt um"), style="Panel.TLabel").pack(side="left", padx=(0, 8))
        self.day_start_var = tk.StringVar(value=self.cfg.get("day_start") or "04:00")
        e = ttk.Entry(drow, textvariable=self.day_start_var, width=6)
        e.pack(side="left")
        e.bind("<FocusOut>", lambda ev: self._save_day_start())
        e.bind("<Return>", lambda ev: self._save_day_start())
        ttk.Label(box, text=tr("Was davor gespielt wird, zählt noch zum Vortag. Die Woche geht von Montag bis Sonntag."),
                  style="Panel.TLabel", foreground=t["text_faint2"], wraplength=300, justify="left").pack(anchor="w", pady=(4, 0))
        ttk.Button(box, text=tr("Statistik-Vorlagen bearbeiten …"), command=self.open_template_editor).pack(anchor="w", pady=(8, 0))
        self.refresh_jobs()
        return box

    def _save_day_start(self):
        raw = self.day_start_var.get().strip()
        mins = day_start_minutes(raw)
        value = f"{mins // 60:02d}:{mins % 60:02d}"
        if raw != value:
            self.day_start_var.set(value)
            if raw:
                self.set_status(tr("Uhrzeit bitte als HH:MM, z. B. 04:00."))
        if self.cfg.get("day_start", "04:00") != value:
            self.cfg["day_start"] = value
            save_config(self.cfg)
            self.refresh_jobs()

    def refresh_jobs(self):
        tv = getattr(self, "job_tree", None)
        if tv is None:
            return
        try:
            if not tv.winfo_exists():
                return
            sel = tv.selection()
            tv.delete(*tv.get_children())
            for j in load_jobs(self.cfg):
                tv.insert("", "end", iid=j["id"], tags=() if j["on"] else ("off",),
                          values=(("✓ " if j["on"] else "✗ ") + job_name(j), next_run_text(j, self.cfg)))
            if sel and tv.exists(sel[0]):
                tv.selection_set(sel[0])
        except tk.TclError:
            pass

    def _selected_job(self) -> dict | None:
        tv = getattr(self, "job_tree", None)
        sel = tv.selection() if tv is not None else ()
        jobs = load_jobs(self.cfg)
        if not sel:
            if len(jobs) == 1:
                return jobs[0]
            self.set_status(tr("Bitte einen Auftrag auswählen."))
            return None
        return next((j for j in jobs if j["id"] == sel[0]), None)

    def edit_selected_job(self):
        job = self._selected_job()
        if job:
            self.open_job_editor(job)

    def toggle_selected_job(self):
        job = self._selected_job()
        if not job:
            return
        jobs = load_jobs(self.cfg)
        for j in jobs:
            if j["id"] == job["id"]:
                j["on"] = not j["on"]
                if j["on"] and not job_url(j, self.cfg):
                    self.notify(tr("Für „{0}“ fehlt noch die Webhook-Adresse.", job_name(j)), "info")
        save_jobs(self.cfg, jobs)
        save_config(self.cfg)
        self.refresh_jobs()

    def delete_selected_job(self):
        job = self._selected_job()
        if not job or not self.ask(tr("Auftrag „{0}“ löschen?", job_name(job)), yes=tr("Löschen"), no=tr("Abbrechen")):
            return
        save_jobs(self.cfg, [j for j in load_jobs(self.cfg) if j["id"] != job["id"]])
        self.cfg.get("discord_jobs_state", {}).pop(job["id"], None)
        save_config(self.cfg)
        self.refresh_jobs()

    def open_job_editor(self, job: dict | None):
        t = THEME
        jobs = load_jobs(self.cfg)
        is_new = job is None
        job = copy.deepcopy(job) if job else dict(load_jobs({"discord_jobs": [{"id": new_job_id(jobs)}]})[0],
                                                   name=tr("Neuer Auftrag"), on=True, when="weekly", template="kompakt")
        win, outer = self._stat_window(tr("Post-Auftrag"), "580x720")
        btns = ttk.Frame(outer, style="Panel.TFrame")
        btns.pack(side="bottom", fill="x", pady=(12, 0))
        f = ttk.Frame(outer, style="Panel.TFrame")
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)
        r = 0

        def label(text):
            nonlocal r
            ttk.Label(f, text=text, style="Panel.TLabel").grid(row=r, column=0, sticky="nw", padx=(0, 12), pady=5)

        def combo(var, values: dict, current: str):
            cb = ttk.Combobox(f, textvariable=var, state="readonly", values=[tr(v) for v in values.values()])
            var.set(tr(values.get(current, next(iter(values.values())))))
            return cb

        def key_of(var, values: dict) -> str:
            return next((k for k, v in values.items() if tr(v) == var.get()), next(iter(values)))

        v = {"name": tk.StringVar(value=job_name(job)), "on": tk.BooleanVar(value=job["on"]),
             "when": tk.StringVar(), "earliest": tk.StringVar(value=job["earliest"]), "template": tk.StringVar(),
             "chars": tk.StringVar(), "webhook": tk.StringVar(), "url": tk.StringVar(value=job.get("url", "")),
             "min": tk.StringVar(value=str(job["min_played"])), "balance": tk.BooleanVar(value=job["show_balance"]),
             "skip": tk.BooleanVar(value=job["skip_empty"]), "catch": tk.BooleanVar(value=job["catch_up"])}
        label(tr("Name"))
        ttk.Entry(f, textvariable=v["name"]).grid(row=r, column=1, sticky="ew", pady=5)
        r += 1
        ttk.Checkbutton(f, text=tr("Aktiv"), variable=v["on"], style="Wrap.TCheckbutton").grid(row=r, column=1, sticky="w")
        r += 1
        label(tr("Wann"))
        when_cb = combo(v["when"], WHEN, job["when"])
        when_cb.grid(row=r, column=1, sticky="ew", pady=5)
        r += 1
        label(tr("Frühestens um"))
        early = ttk.Entry(f, textvariable=v["earliest"], width=8)
        early.grid(row=r, column=1, sticky="w", pady=5)
        r += 1
        when_hint = tk.StringVar()
        ttk.Label(f, textvariable=when_hint, style="Panel.TLabel", foreground=t["text_faint2"], wraplength=380,
                  justify="left").grid(row=r, column=1, sticky="w")
        r += 1
        label(tr("Vorlage"))
        tpl = all_templates(self.cfg)
        tpl_names = {k: template_name(x) for k, x in tpl.items()}
        tpl_cb = ttk.Combobox(f, textvariable=v["template"], state="readonly", values=list(tpl_names.values()))
        v["template"].set(tpl_names.get(job["template"], tpl_names["kompakt"]))
        tpl_cb.grid(row=r, column=1, sticky="ew", pady=5)
        r += 1
        label(tr("Charaktere"))
        chars_cb = combo(v["chars"], CHAR_MODES, job["chars"])
        chars_cb.grid(row=r, column=1, sticky="ew", pady=5)
        r += 1
        label(tr("Nur diese"))
        known = sorted({s["char"] for s in self._job_history()} | set(job["only"]), key=str.lower)
        lb = self._stat_listbox(f, height=3, select="multiple")
        lb.frame.grid(row=r, column=1, sticky="ew", pady=5)
        for i, c in enumerate(known):
            lb.insert("end", c.replace("-", " – ", 1))
            if c in job["only"]:
                lb.selection_set(i)
        r += 1
        ttk.Label(f, text=tr("Keine Auswahl = alle Charaktere."), style="Panel.TLabel", foreground=t["text_faint2"]).grid(
            row=r, column=1, sticky="w")
        r += 1
        label(tr("Kanal"))
        hook_cb = combo(v["webhook"], WEBHOOKS, job["webhook"])
        hook_cb.grid(row=r, column=1, sticky="ew", pady=5)
        r += 1
        label(tr("Adresse"))
        url_e = ttk.Entry(f, textvariable=v["url"])
        url_e.grid(row=r, column=1, sticky="ew", pady=5)
        r += 1
        label(tr("Mindestens gespielt"))
        mrow = ttk.Frame(f, style="Panel.TFrame")
        mrow.grid(row=r, column=1, sticky="w", pady=5)
        ttk.Spinbox(mrow, from_=0, to=600, width=5, textvariable=v["min"]).pack(side="left")
        ttk.Label(mrow, text=tr("Minuten"), style="Panel.TLabel").pack(side="left", padx=(6, 0))
        r += 1
        for key, text in (("balance", tr("Kontostand zeigen")), ("skip", tr("Nichts senden, wenn nicht gespielt wurde")),
                          ("catch", tr("Verpasste Termine beim nächsten Start nachholen"))):
            ttk.Checkbutton(f, text=text, variable=v[key], style="Wrap.TCheckbutton").grid(row=r, column=1, sticky="w", pady=2)
            r += 1

        def sync(*_):
            when = key_of(v["when"], WHEN)
            early.configure(state="disabled" if when == "session" else "normal")
            url_e.configure(state="normal" if key_of(v["webhook"], WEBHOOKS) == "own" else "disabled")
            when_hint.set({"session": tr("Nach dem Ausloggen, sobald Leeroyzan die Sitzung übernommen hat."),
                           "daily": tr("Der abgeschlossene Spieltag – ab der Spieltag-Grenze, frühestens zur genannten Uhrzeit."),
                           "weekly": tr("Die abgeschlossene Woche (Mo–So) – am Montag ab der Spieltag-Grenze, frühestens zur "
                                        "genannten Uhrzeit.")}[when])
        for cb in (when_cb, hook_cb):
            cb.bind("<<ComboboxSelected>>", sync)
        sync()

        def collect() -> dict:
            out = dict(job)
            name = v["name"].get().strip() or tr("Auftrag")
            if name != job_name(job):
                out["name"] = name
            out["on"] = bool(v["on"].get())
            out["when"] = key_of(v["when"], WHEN)
            mins = day_start_minutes(v["earliest"].get())
            out["earliest"] = f"{mins // 60:02d}:{mins % 60:02d}"
            out["template"] = next((k for k, n in tpl_names.items() if n == v["template"].get()), "kompakt")
            out["chars"] = key_of(v["chars"], CHAR_MODES)
            out["only"] = [known[i] for i in lb.curselection()]
            out["webhook"] = key_of(v["webhook"], WEBHOOKS)
            out["url"] = v["url"].get().strip()
            try:
                out["min_played"] = max(0, int(v["min"].get()))
            except ValueError:
                out["min_played"] = job["min_played"]
            out["show_balance"] = bool(v["balance"].get())
            out["skip_empty"] = bool(v["skip"].get())
            out["catch_up"] = bool(v["catch"].get())
            return out

        def save():
            new = collect()
            if new["on"] and not job_url(new, self.cfg):
                self.notify(tr("Für „{0}“ fehlt noch die Webhook-Adresse.", job_name(new)), "info")
            lst = load_jobs(self.cfg)
            if is_new:
                lst.append(new)
            else:
                lst = [new if j["id"] == new["id"] else j for j in lst]
                old = next((j for j in jobs if j["id"] == new["id"]), None)
                if old and old["when"] != new["when"]:
                    self.cfg.get("discord_jobs_state", {}).get(new["id"], {}).pop("last", None)
            save_jobs(self.cfg, lst)
            save_config(self.cfg)
            self.refresh_jobs()
            win.destroy()

        ttk.Button(btns, text=tr("Speichern"), style="Primary.TButton", command=save).pack(side="left")
        ttk.Button(btns, text=tr("Vorschau"), command=lambda: self.preview_job(collect())).pack(side="left", padx=(6, 0))
        ttk.Button(btns, text=tr("Abbrechen"), command=win.destroy).pack(side="right")

    def _job_history(self) -> list[dict]:
        return self.sessions_all or (load_sessions(self.flavor) if self.flavor else [])

    def preview_job(self, job: dict | None):
        if not job:
            return
        msgs = preview_messages(job, self.cfg, self._job_history(), (self.link_state or {}).get("chars", {}))
        win, f = self._stat_window(tr("Vorschau: {0}", job_name(job)), "620x560")
        ttk.Label(f, text=tr("So sähe der Post mit der letzten Sitzung bzw. dem zuletzt abgeschlossenen Zeitraum aus."),
                  style="Panel.TLabel", foreground=THEME["text_faint2"], wraplength=560, justify="left").pack(anchor="w")
        tf, txt = self._text(f)
        tf.pack(fill="both", expand=True, pady=(8, 0))
        self._set_text(txt, embed_preview_text(msgs) if msgs else tr("Noch keine passenden Sitzungen."))
        ttk.Button(f, text=tr("Schließen"), command=win.destroy).pack(anchor="e", pady=(10, 0))

    def test_job(self, job: dict | None):
        """Sendet die Vorschau wirklich – ohne den Merker zu setzen (der echte Termin kommt trotzdem)."""
        if not job:
            return
        url = job_url(job, self.cfg)
        if not url:
            self.notify(tr("Trage zuerst eine Discord-Webhook-Adresse in den Einstellungen ein."), "info")
            return
        msgs = preview_messages(job, self.cfg, self._job_history(), (self.link_state or {}).get("chars", {}))
        if not msgs:
            self.info(tr("Noch keine passenden Sitzungen."))
            return

        def done(_res, err):
            if err:
                log.warning("Discord (Test %s): %s", job["id"], err)
                self.error(tr("Discord: {0}", err))
            else:
                self.set_status(tr("„{0}“ an Discord gesendet (Test).", job_name(job)))
        self.run_quiet(lambda: send_messages(url, msgs), done)

    # ----- Zeitplan --------------------------------------------------------------------- #
    def _watch_autopost(self):
        """Jede Minute: Ist ein Tages- oder Wochenbericht fällig?"""
        try:
            self._autopost_tick()
        except (tk.TclError, OSError, ValueError) as e:
            log.warning("Post-Aufträge: %s", e)
        finally:
            self.after(self.AUTOPOST_POLL_MS, self._watch_autopost)

    def _autopost_tick(self):
        if getattr(self, "_autopost_busy", False) or not self.flavor:
            return
        now = time.time()
        retry = getattr(self, "_autopost_retry", {})
        jobs = [j for j in load_jobs(self.cfg) if j["on"] and j["when"] != "session" and retry.get(j["id"], 0) <= now]
        if not jobs:
            return
        root, flavor = self.root_path, self.flavor
        self._autopost_busy = True

        def check():
            return bool(root and running_wow(root, flavor))

        def checked(running, err):
            self._autopost_busy = False
            if err:
                log.warning("Post-Aufträge: %s", err)
                return
            todo, changed = [], False
            for j in jobs:
                before = copy.deepcopy(self.cfg.get("discord_jobs_state", {}).get(j["id"]))
                act = due_period(j, self.cfg, now, bool(running))
                changed = changed or before != self.cfg.get("discord_jobs_state", {}).get(j["id"])
                if act and act[0] == "skip":
                    mark_sent(self.cfg, j, period=act[1])
                    log.info("Post-Auftrag %s: %s ausgelassen (nicht nachholen)", j["id"], act[1])
                    changed = True
                elif act:
                    todo.append((j, act[1]))
            if changed:
                save_config(self.cfg)
                self.refresh_jobs()
            if todo:
                self._autopost_send_periods(todo)

        self.run_quiet(check, checked)

    def _autopost_send_periods(self, todo: list[tuple[dict, str]]):
        snap = copy.deepcopy({k: self.cfg.get(k) for k in ("stat_templates", "day_start")})
        chars = copy.deepcopy((self.link_state or {}).get("chars", {}))
        urls = {j["id"]: job_url(j, self.cfg) for j, _ in todo}
        flavor = self.flavor
        self._autopost_busy = True

        def work():
            history = load_sessions(flavor)
            results = []
            for j, key in todo:
                try:
                    msgs = period_job_messages(j, snap, key, history, chars)
                    if msgs and not urls[j["id"]]:
                        results.append((j, key, "nourl"))
                        continue
                    if msgs:
                        send_messages(urls[j["id"]], msgs)
                    results.append((j, key, "sent" if msgs else "empty"))
                except (OSError, ValueError, RuntimeError) as e:
                    results.append((j, key, e))
            return results

        def done(results, err):
            self._autopost_busy = False
            if err:
                log.warning("Post-Aufträge: %s", err)
                return
            for j, key, res in results:
                if res in ("sent", "empty"):
                    mark_sent(self.cfg, j, period=key)
                    if res == "sent":
                        log.info("Post-Auftrag %s: %s an Discord gesendet", j["id"], key)
                        self.set_status(tr("„{0}“ an Discord gesendet.", job_name(j)))
                elif res == "nourl":
                    self._autopost_retry_later(j)
                    self.notify(tr("„{0}“ ist fällig, aber es fehlt die Webhook-Adresse.", job_name(j)), "info",
                                [(tr("Einstellungen"), lambda: self.show_page("settings"))], key=f"autopost-{j['id']}")
                else:
                    self._autopost_retry_later(j)
                    log.warning("Post-Auftrag %s: %s", j["id"], res)
                    self.set_status(tr("Discord: {0}", res))
            save_config(self.cfg)
            self.refresh_jobs()

        self.run_quiet(work, done)

    def _autopost_retry_later(self, job: dict):
        self._autopost_retry = getattr(self, "_autopost_retry", {})
        self._autopost_retry[job["id"]] = time.time() + self.AUTOPOST_RETRY

    def autopost_sessions(self, pending: list[dict]):
        """Nach dem Ausloggen: neu gespeicherte Sitzungen an alle Aufträge „Nach jeder Sitzung“."""
        plans = []
        for j in load_jobs(self.cfg):
            todo = session_job_todo(j, self.cfg, pending)
            url = job_url(j, self.cfg)
            if todo and url:
                plans.append((j, url, todo))
        if not plans:
            return
        snap = copy.deepcopy({k: self.cfg.get(k) for k in ("stat_templates", "day_start")})
        chars = copy.deepcopy((self.link_state or {}).get("chars", {}))
        flavor = self.flavor

        def work():
            history = load_sessions(flavor)
            out = []
            for j, url, todo in plans:
                sent: list[str] = []
                err = None
                for s in todo:
                    try:
                        if sent:
                            time.sleep(1.0)
                        send_messages(url, session_job_messages(j, snap, s, history, chars))
                    except (OSError, ValueError, RuntimeError) as e:
                        err = e
                        break
                    sent.append(s["id"])
                out.append((j, sent, err))
            return out

        def done(results, err):
            if err:
                log.warning("Discord: %s", err)
                return
            n = 0
            for j, sent, e in results:
                if sent:
                    mark_sent(self.cfg, j, session_ids=sent)
                    n += len(sent)
                    log.info("Sitzungen an Discord gesendet (%s): %s", j["id"], ", ".join(sent))
                if e:
                    log.warning("Discord: %s", e)
                    self.set_status(tr("Discord: {0}", e))
            save_config(self.cfg)
            if n and not any(e for _, _, e in results):
                self.set_status(tr("Sitzung an Discord gesendet.") if n == 1 else tr("{0} Sitzungen an Discord gesendet.", n))

        self.run_quiet(work, done)
