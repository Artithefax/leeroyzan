"""Discord-Post-Aufträge: was (Vorlage), wann (nach jeder Sitzung, täglich, wöchentlich), für wen und wohin.

Leeroyzan hat keinen Server: Termine prüft es, solange es läuft, und holt verpasste beim nächsten Start nach.
Je Auftrag merkt es sich den zuletzt gesendeten Zeitraum (bzw. die gesendeten Sitzungen) – nichts geht doppelt raus.
Tages- und Wochenberichte fassen immer einen abgeschlossenen Zeitraum zusammen (Spieltag ab 04:00, Woche Mo–So).
"""
from __future__ import annotations

import copy
import time
from datetime import datetime, timedelta

from .i18n import tr
from .metrics import (
    BUILTIN_TEMPLATES,
    all_templates,
    day_start_minutes,
    period_bounds,
    period_key,
    period_label,
    period_messages,
    session_messages,
    sessions_between,
    shift_period,
)
from .reports import DISCORD_WEBHOOK_RE, discord_send

WHEN = {"session": "Nach jeder Sitzung", "daily": "Täglich", "weekly": "Wöchentlich"}
CHAR_MODES = {"all": "Alle zusammen", "each": "Je Charakter ein Eintrag"}
WEBHOOKS = {"session": "Sitzungs-Webhook", "share": "Teilen-Webhook", "own": "Eigene Adresse"}
SENT_KEEP = 300                 # so viele gesendete Sitzungen je Auftrag merken
SESSIONS_AT_ONCE = 5            # nach einer langen Pause höchstens so viele Sitzungen auf einmal senden
WAIT_FOR_LOGOUT = 86400         # so lange wartet ein fälliger Bericht höchstens, während WoW noch läuft
NO_CATCH_UP_GRACE = 2 * 3600    # ohne „Nachholen“: so spät darf ein Termin noch gesendet werden

JOB_DEFAULTS = {"name": "", "on": False, "when": "session", "earliest": "04:00", "template": "kompakt", "chars": "all",
                "only": [], "webhook": "session", "url": "", "min_played": 10, "show_balance": True,
                "skip_empty": True, "catch_up": True}


def default_jobs(cfg: dict) -> list[dict]:
    """Die mitgelieferten Aufträge – „Nach jeder Sitzung“ übernimmt das alte Häkchen „automatisch senden“."""
    return [
        dict(JOB_DEFAULTS, id="session", name="Nach jeder Sitzung", on=bool(cfg.get("discord_auto")), when="session"),
        dict(JOB_DEFAULTS, id="daily", name="Tagesbericht", when="daily", min_played=0),
        dict(JOB_DEFAULTS, id="weekly", name="Wochenbericht", when="weekly", template="alles", chars="each", min_played=0),
    ]


def load_jobs(cfg: dict) -> list[dict]:
    """Aufträge aus der Konfiguration, vollständig und geprüft (fehlende Felder mit Standardwerten)."""
    raw = cfg.get("discord_jobs")
    if not isinstance(raw, list):
        return default_jobs(cfg)
    out, seen = [], set()
    for j in raw:
        if not isinstance(j, dict) or not j.get("id") or j["id"] in seen:
            continue
        seen.add(j["id"])
        job = dict(JOB_DEFAULTS, **{k: v for k, v in j.items() if k in JOB_DEFAULTS or k == "id"})
        if job["when"] not in WHEN:
            job["when"] = "session"
        if job["chars"] not in CHAR_MODES:
            job["chars"] = "all"
        if job["webhook"] not in WEBHOOKS:
            job["webhook"] = "session"
        job["only"] = [str(c) for c in job["only"]] if isinstance(job["only"], list) else []
        try:
            job["min_played"] = max(0, int(job["min_played"]))
        except (TypeError, ValueError):
            job["min_played"] = 0
        out.append(job)
    return out


def save_jobs(cfg: dict, jobs: list[dict]) -> None:
    cfg["discord_jobs"] = [copy.deepcopy(j) for j in jobs]
    cfg["discord_auto"] = any(j["on"] and j["when"] == "session" for j in jobs)    # für ältere Versionen


def new_job_id(jobs: list[dict]) -> str:
    ids = {j["id"] for j in jobs}
    i = 1
    while f"job{i}" in ids:
        i += 1
    return f"job{i}"


def job_name(job: dict) -> str:
    """Mitgelieferte Namen übersetzt, eigene wie eingegeben."""
    return tr(job["name"]) if job["name"] in ("Nach jeder Sitzung", "Tagesbericht", "Wochenbericht") else job["name"]


def job_url(job: dict, cfg: dict) -> str:
    if job["webhook"] == "own":
        url = job.get("url") or ""
    elif job["webhook"] == "share":
        url = cfg.get("discord_share_webhook") or cfg.get("discord_webhook") or ""
    else:
        url = cfg.get("discord_webhook") or ""
    url = url.strip()
    return url if DISCORD_WEBHOOK_RE.match(url) else ""


def job_state(cfg: dict, job: dict) -> dict:
    states = cfg.setdefault("discord_jobs_state", {})
    st = states.get(job["id"])
    if not isinstance(st, dict):
        st = {}
        if job["when"] == "session" and isinstance(cfg.get("discord_sent"), list):
            st["sent"] = list(cfg["discord_sent"])[-SENT_KEEP:]     # was bis 2.5 schon gesendet wurde
        states[job["id"]] = st
    return st


def _kind(job: dict) -> str:
    return "week" if job["when"] == "weekly" else "day"


def _fits(kind: str, key) -> bool:
    """Passt der gemerkte Zeitraum noch zur Art des Auftrags (z. B. nach dem Umstellen von täglich auf wöchentlich)?"""
    return isinstance(key, str) and bool(key) and (("-W" in key) == (kind == "week"))


def send_time(job: dict, key: str, start_min: int) -> float:
    """Frühester Sendezeitpunkt für einen Zeitraum: sein Ende, oder später am selben Tag ab „frühestens um“."""
    end = period_bounds(_kind(job), key, start_min)[1]
    at = datetime.fromtimestamp(end)
    h, m = divmod(day_start_minutes(job.get("earliest") or "04:00"), 60)
    want = at.replace(hour=h, minute=m, second=0, microsecond=0)
    if want.timestamp() < end:
        want += timedelta(days=1)
    return want.timestamp()


def due_period(job: dict, cfg: dict, now: float, wow_running: bool = False) -> tuple[str, str] | None:
    """("send" | "skip", Zeitraum) – was für einen Tages-/Wochenauftrag jetzt zu tun ist, sonst None.
    Ein neu eingeschalteter Auftrag beginnt mit dem nächsten Zeitraum (sendet nicht rückwirkend)."""
    if not job["on"] or job["when"] == "session":
        return None
    start_min = day_start_minutes(cfg.get("day_start"))
    kind = _kind(job)
    target = shift_period(kind, period_key(kind, now, start_min), -1)       # der zuletzt abgeschlossene Zeitraum
    st = job_state(cfg, job)
    last = st.get("last")
    if not _fits(kind, last):
        st["last"] = target
        return None
    if last >= target:
        return None
    at = send_time(job, target, start_min)
    if now < at:
        return None
    if not job["catch_up"] and now - at > NO_CATCH_UP_GRACE:
        return ("skip", target)
    if wow_running and now - at < WAIT_FOR_LOGOUT:
        return None                     # die laufende Sitzung kann noch zum Zeitraum gehören – nach dem Ausloggen
    return ("send", target)


def next_run_text(job: dict, cfg: dict, now: float | None = None) -> str:
    """„nach dem Ausloggen“, „Mo 01.12. 04:00“ oder „aus“."""
    if not job["on"]:
        return tr("aus")
    if job["when"] == "session":
        return tr("nach dem Ausloggen")
    now = now or time.time()
    start_min = day_start_minutes(cfg.get("day_start"))
    kind = _kind(job)
    cur = period_key(kind, now, start_min)
    last = job_state(cfg, job).get("last")
    if not _fits(kind, last):
        last = shift_period(kind, cur, -1)
    target = max(shift_period(kind, last, 1), shift_period(kind, cur, -1))
    at = send_time(job, target, start_min)
    if at <= now:
        return tr("jetzt fällig")
    return datetime.fromtimestamp(at).strftime(tr("%d.%m. %H:%M"))


def _template(job: dict, cfg: dict) -> dict:
    t = all_templates(cfg).get(job["template"]) or dict(BUILTIN_TEMPLATES["kompakt"], builtin=True)
    t = copy.deepcopy(t)
    if not job["show_balance"]:
        t["blocks"] = [b for b in t["blocks"] if b["id"] != "gold.balance"]
    return t


def _filter(job: dict, sessions: list[dict]) -> list[dict]:
    return [s for s in sessions if not job["only"] or s["char"] in job["only"]]


def session_job_todo(job: dict, cfg: dict, pending: list[dict]) -> list[dict]:
    """Neu gespeicherte Sitzungen, die dieser Auftrag senden soll (älteste zuerst, jede nur einmal)."""
    if not job["on"] or job["when"] != "session":
        return []
    sent = set(job_state(cfg, job).get("sent") or [])
    todo = [s for s in sorted(pending, key=lambda s: s["start"]) if not s.get("legacy") and s["id"] not in sent
            and s["played"] >= job["min_played"] * 60]
    return _filter(job, todo)[-SESSIONS_AT_ONCE:]


def session_job_messages(job: dict, cfg: dict, s: dict, history: list[dict], chars: dict | None = None) -> list[dict]:
    return session_messages(_template(job, cfg), s, history, chars)


def period_job_messages(job: dict, cfg: dict, key: str, history: list[dict], chars: dict | None = None) -> list[dict]:
    """Nachrichten eines Tages- oder Wochenberichts. [] = nichts zu senden (keine Sitzung, zu kurz gespielt)."""
    start_min = day_start_minutes(cfg.get("day_start"))
    kind = _kind(job)
    begin, end = period_bounds(kind, key, start_min)
    sessions = _filter(job, sessions_between(history, begin, end))
    if job["skip_empty"] and not sessions:
        return []
    if sum(s["played"] for s in sessions) < job["min_played"] * 60:
        return []
    pb, pe = period_bounds(kind, shift_period(kind, key, -1), start_min)
    prev = _filter(job, sessions_between(history, pb, pe))
    title = f"{job_name(job)} · {period_label(kind, key)}"
    return period_messages(_template(job, cfg), title, sessions, prev, history, chars,
                           each=job["chars"] == "each", stamp=min(end, time.time()))


def preview_messages(job: dict, cfg: dict, history: list[dict], chars: dict | None = None,
                     now: float | None = None) -> list[dict]:
    """Vorschau / Test: die letzte Sitzung bzw. der zuletzt abgeschlossene Zeitraum (oder der laufende, falls leer)."""
    if job["when"] == "session":
        lst = _filter(job, sorted(history, key=lambda s: s["start"]))
        return session_job_messages(job, cfg, lst[-1], history, chars) if lst else []
    now = now or time.time()
    start_min = day_start_minutes(cfg.get("day_start"))
    kind = _kind(job)
    cur = period_key(kind, now, start_min)
    test = dict(job, skip_empty=True, min_played=0)
    out = (period_job_messages(test, cfg, shift_period(kind, cur, -1), history, chars)
           or period_job_messages(test, cfg, cur, history, chars))
    mine = _filter(job, history)
    if not out and mine:                      # lange nicht gespielt: der Zeitraum der letzten Sitzung
        newest = max(s["start"] for s in mine)
        out = period_job_messages(test, cfg, period_key(kind, newest, start_min), history, chars)
    return out


def send_messages(url: str, messages: list[dict], sleep=time.sleep) -> None:
    """Nachrichten der Reihe nach senden (Discord erlaubt nur wenige pro Sekunde)."""
    for i, msg in enumerate(messages):
        if i:
            sleep(1.0)
        discord_send(url, msg, sleep=sleep)


def mark_sent(cfg: dict, job: dict, session_ids: list[str] | None = None, period: str | None = None) -> None:
    st = job_state(cfg, job)
    if session_ids:
        st["sent"] = (list(st.get("sent") or []) + session_ids)[-SENT_KEEP:]
        if job["id"] == "session":
            cfg["discord_sent"] = st["sent"]
    if period:
        st["last"] = max(period, st.get("last") or "")
