"""Statistik aus Bausteinen: Kennzahlen (woher ein Wert kommt, wie er über Sitzungen zusammengefasst und angezeigt
wird), Vorlagen (geordnete Listen von Bausteinen mit Optionen) und Zeiträume (Spieltag ab 04:00, Woche Mo–So).

Dieselbe Vorlage füllt die Ansicht in Leeroyzan und die Discord-Nachrichten. Eine neue Kennzahl ist ein Eintrag in
METRICS – Bericht, Editor und Discord kennen sie dann von selbst.
"""
from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable

from .constants import APP_VERSION
from .i18n import tr
from .reports import (
    CLASS_COLORS,
    CLASS_NAMES,
    DISCORD_COLOR,
    MONEY_SOURCES,
    QUALITY_NAMES,
    _join_and,
    _short_list,
    _summary_sentence,
    _top,
    aggregate_sessions,
    death_stats,
    fmt_dist,
    fmt_dur,
    fmt_int,
    fmt_money,
    fmt_transfers,
    level_forecast,
    new_records,
    plural,
    session_title,
    zone_ranking,
)
from .sessions import _int, money_breakdown

# ----- Zeiträume ------------------------------------------------------------------------ #
DEFAULT_DAY_START = "04:00"          # bis hierhin zählt die Nacht noch zum Spieltag davor


def day_start_minutes(value: str | None) -> int:
    """„04:00“ → 240. Falsche Werte → 04:00."""
    try:
        h, m = (int(x) for x in str(value or DEFAULT_DAY_START).split(":", 1))
        if 0 <= h < 24 and 0 <= m < 60:
            return h * 60 + m
    except ValueError:
        pass
    return 240


def play_day(ts: float, start_min: int = 240) -> date:
    """Spieltag eines Zeitpunkts: Eine Sitzung um 1 Uhr nachts gehört noch zum Abend davor."""
    return (datetime.fromtimestamp(ts) - timedelta(minutes=start_min)).date()


def period_key(kind: str, ts: float, start_min: int = 240) -> str:
    """Schlüssel des Zeitraums, in dem ts liegt: Tag „2026-11-24“, Woche „2026-W48“ (ISO, Montag bis Sonntag)."""
    d = play_day(ts, start_min)
    if kind == "week":
        y, w, _ = d.isocalendar()
        return f"{y}-W{w:02d}"
    return d.isoformat()


def _first_day(kind: str, key: str) -> date:
    if kind == "week":
        y, w = key.split("-W")
        return date.fromisocalendar(int(y), int(w), 1)
    return date.fromisoformat(key)


def period_bounds(kind: str, key: str, start_min: int = 240) -> tuple[float, float]:
    """Anfang und Ende (Unix-Zeit) eines Zeitraums."""
    d = _first_day(kind, key)
    begin = datetime(d.year, d.month, d.day) + timedelta(minutes=start_min)
    end = begin + timedelta(days=7 if kind == "week" else 1)
    return begin.timestamp(), end.timestamp()


def shift_period(kind: str, key: str, n: int) -> str:
    """Den Zeitraum n Schritte weiter (n < 0: zurück)."""
    d = _first_day(kind, key) + timedelta(days=(7 if kind == "week" else 1) * n)
    if kind == "week":
        y, w, _ = d.isocalendar()
        return f"{y}-W{w:02d}"
    return d.isoformat()


def period_label(kind: str, key: str) -> str:
    """„Mo 24.11.2026“ oder „KW 48 · 23.11.–29.11.2026“."""
    d = _first_day(kind, key)
    if kind == "week":
        last = d + timedelta(days=6)
        return tr("KW {0} · {1}–{2}", d.isocalendar()[1], d.strftime("%d.%m."), last.strftime(tr("%d.%m.%Y")))
    return d.strftime(tr("%d.%m.%Y"))


def sessions_between(sessions: list[dict], begin: float, end: float) -> list[dict]:
    """Sitzungen, die in diesem Zeitraum begonnen haben."""
    return [s for s in sessions if begin <= s["start"] < end]


# Zeiträume der Sitzungsliste in Leeroyzan
NAMED_PERIODS = [("all", "Alle Zeiträume"), ("today", "Heute"), ("yesterday", "Gestern"), ("week", "Diese Woche"),
                 ("lastweek", "Letzte Woche"), ("month", "Letzte 30 Tage")]


def named_period(name: str, now: float, start_min: int = 240) -> tuple[float, float, float, float] | None:
    """(Anfang, Ende, Anfang davor, Ende davor) eines Zeitraums der Sitzungsliste – None für „alle“."""
    if name in ("today", "yesterday", "week", "lastweek"):
        kind = "day" if name in ("today", "yesterday") else "week"
        key = period_key(kind, now, start_min)
        if name in ("yesterday", "lastweek"):
            key = shift_period(kind, key, -1)
        b, e = period_bounds(kind, key, start_min)
        pb, pe = period_bounds(kind, shift_period(kind, key, -1), start_min)
        return b, e, pb, pe
    if name == "month":
        b = now - 30 * 86400
        return b, now + 1, b - 30 * 86400, b
    return None


# ----- Kennzahlen ---------------------------------------------------------------------- #
@dataclass
class Ctx:
    """Was eine Kennzahl zum Rechnen bekommt."""
    sessions: list[dict]
    prev: list[dict] | None = None            # Sitzungen des Zeitraums davor (für den Vergleich)
    history: list[dict] = field(default_factory=list)   # alle Sitzungen (Rekorde, Prognose)
    chars: dict = field(default_factory=dict)  # Charakterdaten aus Leeroylink (Kontostand)
    period: bool = False                       # ein Zeitraum statt einer einzelnen Sitzung
    _a: dict | None = None
    _pa: dict | None = None

    @property
    def a(self) -> dict:
        if self._a is None:
            self._a = aggregate_sessions(self.sessions)
        return self._a

    @property
    def pa(self) -> dict | None:
        if self.prev is None:
            return None
        if self._pa is None:
            self._pa = aggregate_sessions(self.prev)
        return self._pa

    @property
    def single(self) -> dict | None:
        return self.sessions[0] if len(self.sessions) == 1 and not self.period else None


@dataclass(frozen=True)
class Metric:
    id: str
    cat: str
    label: str                                   # Feldname (z. B. in Discord)
    text: Callable[[Ctx, dict], str]             # Anzeige; "" = nichts zu zeigen
    num: Callable[[dict], float] | None = None   # Zahl aus der Zusammenfassung (Vergleich, „nur wenn > 0“)
    title: str = ""                              # Name im Editor, wenn er vom Feldnamen abweicht
    desc: str = ""                               # Erklärung im Editor
    rate: bool = False                           # „pro Stunde“ möglich
    top: int = 0                                 # Liste: Standardlänge (0 = keine Liste)
    wide: bool = False                           # in Discord über die ganze Breite
    period_only: bool = False                    # nur bei Zeiträumen sinnvoll


CATEGORIES = [("time", "Zeit"), ("progress", "Fortschritt"), ("gold", "Gold"), ("quests", "Quests und Beute"),
              ("combat", "Kampf und Instanzen"), ("travel", "Unterwegs und Berufe"), ("hl", "Highlights")]


def _hours(a: dict) -> float:
    return a["played"] / 3600 if a["played"] >= 600 else 0


def _per_hour(v: float, a: dict, fmt) -> str:
    h = _hours(a)
    return tr(" ({0}/h)", fmt(v / h)) if h and v else ""


def _names(ctx: Ctx) -> dict[str, str]:
    return {s["char"]: s["name"] or s["char"] for s in ctx.sessions}


# --- Zeit
def _t_played(ctx, o):
    a = ctx.a
    if not a["n"]:
        return ""
    if a["n"] == 1:
        return fmt_dur(a["played"])
    return tr("{0} (Ø {1} pro Sitzung)", fmt_dur(a["played"]), fmt_dur(a["played"] / a["n"]))


def _t_sessions(ctx, o):
    a = ctx.a
    days = {play_day(s["start"]) for s in ctx.sessions}
    return " · ".join([plural(a["n"], "{0} Sitzung", "{0} Sitzungen"), plural(len(days), "{0} Spieltag", "{0} Spieltage")])


def _t_split(ctx, o):
    a = ctx.a
    if not a["played"]:
        return ""
    tot = {k: sum(s["time"].get(k, 0) for s in ctx.sessions) for k in ("combat", "afk", "rest", "dead", "taxi", "instance")}
    names = [("combat", "Kampf"), ("afk", "AFK"), ("rest", "erholt"), ("dead", "tot"), ("taxi", "Flugroute"), ("instance", "Instanz")]
    return " · ".join(f"{tr(n)} {fmt_dur(tot[k])} ({round(tot[k] * 100 / a['played'])} %)" for k, n in names if tot[k] >= 60)


def _t_longest_day(ctx, o):
    days: dict[date, int] = {}
    for s in ctx.sessions:
        d = play_day(s["start"])
        days[d] = days.get(d, 0) + s["played"]
    if not days:
        return ""
    d, sec = max(days.items(), key=lambda kv: kv[1])
    return f"{d.strftime(tr('%d.%m.%Y'))} · {fmt_dur(sec)}"


# --- Fortschritt
def _t_level(ctx, o):
    by: dict[str, list[int]] = {}
    for s in sorted(ctx.sessions, key=lambda s: s["start"]):
        lv = s["level"]
        e = by.setdefault(s["char"], [lv["from"] or lv["to"], lv["to"]])
        e[1] = max(e[1], lv["to"])
    names = _names(ctx)

    def one(f, t):
        return f"{f} → {t}" if t > f > 0 else str(t or "–")
    if len(by) == 1:
        f, t = next(iter(by.values()))
        return one(f, t)
    return "\n".join(f"{names[c]} {one(f, t)}" for c, (f, t) in sorted(by.items(), key=lambda kv: names[kv[0]].lower()))


def _t_xp(ctx, o):
    a = ctx.a
    return fmt_int(a["xp"]) + (_per_hour(a["xp"], a, fmt_int) if o.get("rate") else "")


def _t_xp_sources(ctx, o):
    x = {k: sum(s["xp"][k] for s in ctx.sessions) for k in ("kills", "quests", "explore", "other")}
    names = [("kills", "Kills"), ("quests", "Quests"), ("explore", "Entdecken"), ("other", "Sonstiges")]
    return " · ".join(f"{tr(n)} {fmt_int(x[k])}" for k, n in names if x[k])


def _t_forecast(ctx, o):
    chars = {s["char"] for s in ctx.sessions}
    out = []
    for f in level_forecast(ctx.history or ctx.sessions):
        if f["char"] in chars and f["targets"]:
            nxt = f["targets"][0]
            out.append(tr("{0}: Stufe {1} in ≈ {2}", f["name"], nxt["level"], fmt_dur(nxt["hours"] * 3600)))
    return "\n".join(out)


def _t_rep(ctx, o):
    rep: dict[str, float] = {}
    for s in ctx.sessions:
        for k, v in s["rep"].items():
            rep[k] = rep.get(k, 0) + v
    top = _top({k: v for k, v in rep.items() if v}, o.get("top") or 5, key=abs)
    return " · ".join(f"{k} {'+' if v > 0 else '−'}{fmt_int(abs(v))}" for k, v in top)


# --- Gold
def _t_farmed(ctx, o):
    a = ctx.a
    return fmt_money(a["farmed"], sign=True) + (_per_hour(a["farmed"], a, fmt_money) if o.get("rate") else "")


def _t_net(ctx, o):
    return fmt_money(ctx.a["net"], sign=True)


def _t_income(ctx, o):
    a = ctx.a
    if not a["income"]:
        return ""
    parts = ", ".join(f"{tr(MONEY_SOURCES.get(k, k))} {fmt_money(v)}" for k, v in _top(a["gain"], o.get("top") or 5))
    return f"{fmt_money(a['income'])} ({parts})"


def _t_spent(ctx, o):
    a = ctx.a
    if not a["spent"]:
        return fmt_money(0)
    parts = ", ".join(f"{tr(MONEY_SOURCES.get(k, k))} {fmt_money(v)}" for k, v in _top(a["spend"], o.get("top") or 5))
    return f"{fmt_money(a['spent'])} ({parts})"


def _t_transfers(ctx, o):
    a = ctx.a
    if not a["transfers"]:
        return ""
    return fmt_transfers({"transfers": {k: tuple(v) for k, v in a["transfers"].items()}})


def _balances(ctx) -> list[tuple[str, int]]:
    names = _names(ctx)
    out = []
    for key in names:
        c = ctx.chars.get(key)
        if c and c.get("money") is not None:
            out.append((names[key], _int(c["money"])))
    return sorted(out, key=lambda kv: kv[0].lower())


def _t_balance(ctx, o):
    bal = _balances(ctx)
    if not bal:
        return ""
    if len(bal) == 1:
        return fmt_money(bal[0][1])
    total = sum(v for _, v in bal)
    return " · ".join(f"{n} {fmt_money(v)}" for n, v in bal) + " · " + tr("gesamt {0}", fmt_money(total))


def _t_zones(ctx, o):
    zr = [z for z in zone_ranking(ctx.sessions) if z["money"]]
    best = sorted(zr, key=lambda z: z["money_h"], reverse=True)[:o.get("top") or 3]
    return ", ".join(f"{z['zone']} {tr('{0}/h', fmt_money(z['money_h']))}" for z in best)


def _t_loot_value(ctx, o):
    return fmt_money(ctx.a["value"]) if ctx.a["value"] else ""


# --- Quests und Beute
def _t_quests(ctx, o):
    return fmt_int(ctx.a["quests"])


def _t_quests_open(ctx, o):
    acc = sum(len(s["quests"]["accepted"]) for s in ctx.sessions)
    ab = sum(len(s["quests"]["abandoned"]) for s in ctx.sessions)
    return " · ".join(x for x in (tr("{0} angenommen", acc) if acc else "", tr("{0} abgebrochen", ab) if ab else "") if x)


def _t_quest_list(ctx, o):
    done = sorted((q for s in ctx.sessions for q in s["quests"]["done"]), key=lambda q: q["t"], reverse=True)
    return _short_list([q["title"] or f"#{q['id']}" for q in done], o.get("top") or 8)


def _t_quest_reward(ctx, o):
    xp = sum(s["xp"]["quests"] for s in ctx.sessions)
    gold = sum(money_breakdown(s)["gain"].get("quest", 0) for s in ctx.sessions)
    return " · ".join(x for x in (tr("{0} XP", fmt_int(xp)) if xp else "", fmt_money(gold) if gold else "") if x)


def _t_loot(ctx, o):
    a = ctx.a
    if not a["loot"]:
        return ""
    q: dict[int, int] = {}
    for s in ctx.sessions:
        for k, n in s["loot"]["q"].items():
            q[_int(k)] = q.get(_int(k), 0) + n
    good = [f"{fmt_int(n)} {tr(QUALITY_NAMES[min(k, 6)])}" for k, n in sorted(q.items(), reverse=True) if k >= 3 and n]
    return tr("{0} Gegenstände", fmt_int(a["loot"])) + (f" ({', '.join(good)})" if good else "")


def _t_best_loot(ctx, o):
    notable = [e for s in ctx.sessions for e in s["loot"]["notable"] if e["q"] >= 3]
    best = sorted(notable, key=lambda e: (e["q"], e["t"]), reverse=True)
    names = list(dict.fromkeys(f"[{e['name']}]" for e in best))
    return ", ".join(names[:o.get("top") or 3])


def _t_items(ctx, o):
    return ", ".join(f"{e['name']} ×{fmt_int(e['n'])}" for _, e in _top(ctx.a["items"], o.get("top") or 5, key=lambda e: e["n"]))


# --- Kampf und Instanzen
def _t_kills(ctx, o):
    a = ctx.a
    elite = f" ({tr('{0} Elite', a['elite'])})" if a["elite"] else ""
    return fmt_int(a["kills"]) + elite + (_per_hour(a["kills"], a, fmt_int) if o.get("rate") else "")


def _t_mobs(ctx, o):
    return ", ".join(f"{n} ×{fmt_int(c)}" for n, c in _top(ctx.a["mobs"], o.get("top") or 5))


def _t_deaths(ctx, o):
    return fmt_int(ctx.a["deaths"])


def _t_killers(ctx, o):
    ds = death_stats(ctx.sessions)
    return ", ".join(f"{k} ×{n}" for k, n in ds["killers"][:o.get("top") or 3])


def _t_output(ctx, o):
    a = ctx.a
    if not (a["dmg"] or a["heal"] or a["taken"]):
        return ""
    dps = f" ({fmt_int(a['dmg'] / a['combat'])} DPS)" if a["combat"] >= 60 and a["dmg"] else ""
    hps = f" ({fmt_int(a['heal'] / a['combat'])} HPS)" if a["combat"] >= 60 and a["heal"] else ""
    return " · ".join(x for x in (tr("Schaden {0}", fmt_int(a["dmg"])) + dps if a["dmg"] else "",
                                  tr("Heilung {0}", fmt_int(a["heal"])) + hps if a["heal"] else "",
                                  tr("erlitten {0}", fmt_int(a["taken"])) if a["taken"] else "") if x)


def _t_max(ctx, o):
    hit = max(ctx.sessions, key=lambda s: s["combat"]["maxHit"], default=None)
    heal = max(ctx.sessions, key=lambda s: s["combat"]["maxHeal"], default=None)
    out = []
    if hit and hit["combat"]["maxHit"]:
        out.append(f"{fmt_int(hit['combat']['maxHit'])} ({hit['combat']['maxHitSpell'] or '?'})")
    if heal and heal["combat"]["maxHeal"]:
        out.append(tr("Heilung {0}", f"{fmt_int(heal['combat']['maxHeal'])} ({heal['combat']['maxHealSpell'] or '?'})"))
    return " · ".join(out)


def _t_utility(ctx, o):
    i = sum(s["combat"]["interrupts"] for s in ctx.sessions)
    d = sum(s["combat"]["dispels"] for s in ctx.sessions)
    return " · ".join(x for x in (tr("{0} unterbrochen", fmt_int(i)) if i else "", tr("{0} gebannt", fmt_int(d)) if d else "") if x)


def _t_runs(ctx, o):
    runs = [r for s in ctx.sessions for r in s["runs"]]
    return _short_list([r["name"] for r in runs], o.get("top") or 8)


def _t_bosses(ctx, o):
    return _short_list([b["name"] for s in ctx.sessions for b in s["bosses"]], o.get("top") or 8)


# --- Unterwegs und Berufe
def _t_distance(ctx, o):
    a = ctx.a
    return fmt_dist(a["walked"] + a["mount"])


def _t_travel(ctx, o):
    a = ctx.a
    return " · ".join(x for x in (tr("{0} zu Fuß", fmt_dist(a["walked"])) if a["walked"] else "",
                                  tr("{0} beritten", fmt_dist(a["mount"])) if a["mount"] else "",
                                  tr("{0} geschwommen", fmt_dist(a["swim"])) if a["swim"] else "",
                                  tr("{0} Flugroute", fmt_dist(a["taxi"])) if a["taxi"] else "") if x)


def _t_steps(ctx, o):
    a = ctx.a
    return " · ".join(x for x in (tr("≈ {0} Schritte", fmt_int(a["steps"])) if a["steps"] else "",
                                  tr("{0} Sprünge", fmt_int(a["jumps"])) if a["jumps"] else "") if x)


def _t_found(ctx, o):
    return _short_list([e["name"] for s in ctx.sessions for e in s["explore"]["found"]], o.get("top") or 8)


def _t_zone_time(ctx, o):
    return ", ".join(f"{n} {fmt_dur(sec)}" for n, sec in _top(ctx.a["zones"], o.get("top") or 5))


def _t_skills(ctx, o):
    first: dict[str, int] = {}
    last: dict[str, int] = {}
    for s in sorted(ctx.sessions, key=lambda s: s["start"]):
        for name, e in s["prof"]["skills"].items():
            if e["b"] > e["a"]:
                first.setdefault(name, e["a"])
                last[name] = e["b"]
    return " · ".join(f"{n} {first[n]} → {last[n]}" for n in sorted(last))


def _t_crafted(ctx, o):
    items: dict[str, int] = {}
    for s in ctx.sessions:
        for e in s["prof"]["crafted"].values():
            items[e["name"]] = items.get(e["name"], 0) + e["n"]
    return ", ".join(f"{n} ×{c}" for n, c in _top(items, o.get("top") or 5))


def _t_gathered(ctx, o):
    items: dict[str, int] = {}
    for s in ctx.sessions:
        for g in s["prof"]["gathered"].values():
            for e in g.values():
                items[e["name"]] = items.get(e["name"], 0) + e["n"]
    return ", ".join(f"{n} ×{c}" for n, c in _top(items, o.get("top") or 5))


def _t_learned(ctx, o):
    return _short_list([n for s in ctx.sessions for n in s["prof"]["learned"] + s["spellsLearned"]], o.get("top") or 8)


# --- Highlights
def _t_summary(ctx, o):
    if ctx.single:
        return _summary_sentence(ctx.single)
    a = ctx.a
    if not a["n"]:
        return tr("Keine Sitzungen in diesem Zeitraum.")
    progress = []
    if a["xp"]:
        progress.append(tr("{0} Erfahrung gesammelt", fmt_int(a["xp"])))
    if a["farmed"] > 0:
        progress.append(tr("{0} erfarmt", fmt_money(a["farmed"])))
    if a["quests"]:
        progress.append(tr("{0} Quests abgeschlossen", a["quests"]) if a["quests"] != 1 else tr("1 Quest abgeschlossen"))
    if a["kills"]:
        progress.append(tr("{0} Gegner besiegt", fmt_int(a["kills"])))
    who = plural(len(a["chars"]), "{0} Charakter", "{0} Charaktere")
    lead = tr("{0} in {1} mit {2}.", fmt_dur(a["played"]), plural(a["n"], "{0} Sitzung", "{0} Sitzungen"), who)
    if progress:
        return lead + " " + tr("Dabei {0}.", _join_and(progress))
    return lead


def _t_records(ctx, o):
    if not ctx.history:
        return ""
    seen: dict[str, str] = {}
    for s in sorted(ctx.sessions, key=lambda s: s["start"]):
        for label, value in new_records(s, ctx.history):
            seen[label] = f"{s['name'] or s['char']}: {value}" if ctx.period and len(ctx.a["chars"]) > 1 else value
    return "\n".join(f"🏆 {tr(label)}: {value}" for label, value in seen.items())


def _t_chars(ctx, o):
    rows = sorted(ctx.a["chars"].values(), key=lambda c: c["played"], reverse=True)
    out = []
    for i, c in enumerate(rows[:o.get("top") or 10], 1):
        cls = tr(CLASS_NAMES.get(c["class"], c["class"].title())) if c["class"] else ""
        out.append(f"{i}. {c['name']}" + (f" ({cls} {c['level']})" if cls else "") + " · " + " · ".join(
            [fmt_dur(c["played"]), tr("{0} XP", fmt_int(c["xp"])), fmt_money(c["farmed"], sign=True)]))
    return "\n".join(out)


def _n(key: str) -> Callable[[dict], float]:
    return lambda a: a.get(key, 0)


METRICS: dict[str, Metric] = {m.id: m for m in [
    Metric("time.played", "time", "Spielzeit", _t_played, _n("played")),
    Metric("time.sessions", "time", "Sitzungen", _t_sessions, _n("n"), title="Sitzungen und Spieltage", period_only=True),
    Metric("time.split", "time", "Zeitaufteilung", _t_split, _n("combat"), desc="Kampf, AFK, erholt, tot, Flugroute, Instanz"),
    Metric("time.longestDay", "time", "Längster Spieltag", _t_longest_day, period_only=True),
    Metric("level.range", "progress", "Stufe", _t_level, _n("levels")),
    Metric("xp.total", "progress", "Erfahrung", _t_xp, _n("xp"), rate=True),
    Metric("xp.sources", "progress", "Erfahrung nach Quelle", _t_xp_sources, _n("xp"), desc="Kills, Quests, Entdecken"),
    Metric("level.forecast", "progress", "Nächste Stufe", _t_forecast, desc="Geschätzte Spielzeit bis zur nächsten Stufe"),
    Metric("rep.changes", "progress", "Ruf", _t_rep, top=5),
    Metric("gold.farmed", "gold", "Gold", _t_farmed, _n("farmed"), title="Gold erfarmt", rate=True,
           desc="Beute, Quests, Händlerverkäufe und AH-Erlöse – ohne Überweisungen"),
    Metric("gold.net", "gold", "Gold netto", _t_net, _n("net"), desc="Kontostand am Ende minus am Anfang"),
    Metric("gold.income", "gold", "Einnahmen", _t_income, _n("income"), top=5),
    Metric("gold.spent", "gold", "Ausgaben", _t_spent, _n("spent"), top=5),
    Metric("gold.transfers", "gold", "Transfers", _t_transfers, lambda a: a.get("tin", 0) + a.get("tout", 0),
           desc="Twinks, Post von und an Spieler, Handel"),
    Metric("gold.balance", "gold", "Kontostand", _t_balance, desc="Aktueller Kontostand der Charaktere"),
    Metric("gold.zones", "gold", "Beste Goldgebiete", _t_zones, top=3),
    Metric("loot.value", "gold", "Händlerwert der Beute", _t_loot_value, _n("value")),
    Metric("quests.count", "quests", "Quests", _t_quests, _n("quests"), title="Quests abgeschlossen"),
    Metric("quests.open", "quests", "Quests angenommen", _t_quests_open, title="Quests angenommen / abgebrochen"),
    Metric("quests.list", "quests", "Abgeschlossene Quests", _t_quest_list, _n("quests"), top=8, wide=True),
    Metric("quests.reward", "quests", "Questbelohnungen", _t_quest_reward, desc="Quest-XP und Questgold"),
    Metric("loot.count", "quests", "Beute", _t_loot, _n("loot")),
    Metric("loot.best", "quests", "Beste Beute", _t_best_loot, top=3, desc="Ab „selten“"),
    Metric("loot.items", "quests", "Häufigste Beute", _t_items, top=5),
    Metric("kills.total", "combat", "Gegner", _t_kills, _n("kills"), title="Besiegte Gegner", rate=True),
    Metric("kills.mobs", "combat", "Häufigste Gegner", _t_mobs, top=5),
    Metric("deaths.total", "combat", "Tode", _t_deaths, _n("deaths")),
    Metric("deaths.killers", "combat", "Gefährlichste Gegner", _t_killers, _n("deaths"), top=3),
    Metric("combat.output", "combat", "Schaden und Heilung", _t_output, _n("dmg"), desc="Mit DPS und HPS pro Kampfsekunde"),
    Metric("combat.max", "combat", "Größter Treffer", _t_max, desc="Größter Treffer und größte Heilung"),
    Metric("combat.utility", "combat", "Unterbrechen und Bannen", _t_utility),
    Metric("runs.list", "combat", "Instanzen", _t_runs, _n("runs"), top=8, wide=True, title="Dungeons und Schlachtzüge"),
    Metric("runs.bosses", "combat", "Bosse", _t_bosses, _n("boss"), top=8),
    Metric("move.distance", "travel", "Strecke", _t_distance, lambda a: a.get("walked", 0) + a.get("mount", 0)),
    Metric("move.detail", "travel", "Unterwegs", _t_travel, desc="Zu Fuß, beritten, geschwommen, Flugroute"),
    Metric("move.steps", "travel", "Schritte und Sprünge", _t_steps, _n("steps")),
    Metric("explore.found", "travel", "Entdeckt", _t_found, _n("found"), top=8, wide=True, title="Entdeckte Gebiete"),
    Metric("explore.zones", "travel", "Meiste Zeit in", _t_zone_time, top=5, title="Zonen nach Spielzeit"),
    Metric("prof.skillups", "travel", "Fertigkeiten", _t_skills, _n("skillups"), wide=True, title="Fertigkeitspunkte"),
    Metric("prof.crafted", "travel", "Hergestellt", _t_crafted, top=5),
    Metric("prof.gathered", "travel", "Gesammelt", _t_gathered, top=5),
    Metric("prof.learned", "travel", "Gelernt", _t_learned, top=8, wide=True, desc="Rezepte und Zauber"),
    Metric("hl.summary", "hl", "Zusammenfassung", _t_summary, wide=True, desc="Zwei, drei Sätze (in Discord als Text oben)"),
    Metric("hl.records", "hl", "Neue Rekorde", _t_records, wide=True),
    Metric("hl.chars", "hl", "Charaktere", _t_chars, top=10, wide=True, title="Rangliste der Charaktere", period_only=True),
]}

OPTION_NAMES = {"rate": "pro Stunde", "compare": "Vergleich mit dem Zeitraum davor", "nonzero": "nur zeigen, wenn > 0",
                "top": "Anzahl"}


def metric_title(m: Metric) -> str:
    return tr(m.title or m.label)


def _compare(m: Metric, ctx: Ctx) -> str:
    if not m.num or ctx.pa is None:
        return ""
    now, before = m.num(ctx.a), m.num(ctx.pa)
    if not before:
        return tr(" (neu)") if now else ""
    pct = round((now - before) * 100 / abs(before))
    if pct == 0:
        return " (=)"
    return f" ({'▲' if pct > 0 else '▼'} {abs(pct)} %)"


def render_block(block: dict, ctx: Ctx) -> tuple[str, str, bool] | None:
    """(Feldname, Wert, ganze Breite) eines Bausteins – None, wenn es nichts zu zeigen gibt."""
    m = METRICS.get(block.get("id", ""))
    if m is None or (m.period_only and not ctx.period):
        return None
    if block.get("nonzero") and m.num and not m.num(ctx.a):
        return None
    try:
        value = m.text(ctx, block)
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        value = ""
    if not value:
        return None
    if block.get("compare") and ctx.period:
        value += _compare(m, ctx)
    return tr(m.label), value, m.wide or "\n" in value


# ----- Vorlagen ------------------------------------------------------------------------ #
def _b(mid: str, **opts) -> dict:
    return {"id": mid, **opts}


BUILTIN_TEMPLATES: dict[str, dict] = {
    "kompakt": {"name": "Kompakt", "blocks": [
        _b("hl.summary"), _b("time.played"), _b("level.range"), _b("xp.total"), _b("gold.farmed"), _b("kills.total"),
        _b("quests.count"), _b("deaths.total"), _b("move.distance"), _b("runs.bosses", nonzero=True),
        _b("loot.best", top=1), _b("runs.list"), _b("explore.found"), _b("hl.records")]},
    "leveln": {"name": "Leveln", "blocks": [
        _b("hl.summary"), _b("time.played", compare=True), _b("level.range"), _b("xp.total", rate=True, compare=True),
        _b("xp.sources"), _b("level.forecast"), _b("quests.count", compare=True), _b("quests.reward"),
        _b("kills.total", rate=True), _b("deaths.total"), _b("explore.found"), _b("hl.records")]},
    "gold": {"name": "Gold", "blocks": [
        _b("time.played"), _b("gold.farmed", rate=True, compare=True), _b("gold.income", top=5),
        _b("gold.spent", top=5), _b("gold.transfers"), _b("gold.balance"), _b("gold.zones", top=3),
        _b("loot.value"), _b("loot.best", top=3)]},
    "dungeons": {"name": "Dungeons", "blocks": [
        _b("time.played"), _b("runs.list"), _b("runs.bosses"), _b("loot.best", top=5), _b("deaths.total"),
        _b("deaths.killers", top=3), _b("combat.output"), _b("combat.max"), _b("kills.total")]},
    "alles": {"name": "Alles", "blocks": [
        _b(mid, nonzero=True, **({"compare": True} if mid in ("time.played", "xp.total", "gold.farmed", "kills.total",
                                                              "quests.count") else {}),
           **({"rate": True} if mid in ("xp.total", "gold.farmed") else {}))
        for mid in ["hl.summary", *(m for m in METRICS if m != "hl.summary")]]},
}


def all_templates(cfg: dict) -> dict[str, dict]:
    """Mitgelieferte und eigene Vorlagen: {id: {"name", "blocks", "builtin"}} – eigene nach den mitgelieferten."""
    out = {k: dict(copy.deepcopy(v), builtin=True) for k, v in BUILTIN_TEMPLATES.items()}
    for k, v in (cfg.get("stat_templates") or {}).items():
        if isinstance(v, dict) and k not in BUILTIN_TEMPLATES and isinstance(v.get("blocks"), list):
            blocks = [b for b in v["blocks"] if isinstance(b, dict) and b.get("id") in METRICS]
            out[k] = {"name": str(v.get("name") or k), "blocks": blocks, "builtin": False}
    return out


def template_name(t: dict) -> str:
    return tr(t["name"]) if t.get("builtin") else t["name"]


def new_template_id(cfg: dict, name: str) -> str:
    base = "".join(ch for ch in name.lower() if ch.isalnum())[:20] or "vorlage"
    existing = set(all_templates(cfg))
    tid, i = f"u_{base}", 2
    while tid in existing:
        tid, i = f"u_{base}{i}", i + 1
    return tid


def render_template(blocks: list[dict], ctx: Ctx) -> list[tuple[str, str, bool]]:
    out = []
    for b in blocks:
        r = render_block(b, ctx)
        if r:
            out.append(r)
    return out


def template_report(t: dict, ctx: Ctx, title: str, subtitle: str = "") -> list[tuple[str, str]]:
    """Eine Vorlage als Text für Leeroyzan: [(Text, Tag)]."""
    parts: list[tuple[str, str]] = [(title + "\n", "title")]
    if subtitle:
        parts.append((subtitle + "\n", "dim"))
    rows = render_template(t["blocks"], ctx)
    if not rows:
        parts.append(("\n" + tr("Für diese Auswahl gibt es mit dieser Vorlage nichts zu zeigen.") + "\n", "dim"))
    for label, value, wide in rows:
        if wide:
            parts.append(("\n" + label + "\n", "head"))
            parts.append((value + "\n", ""))
        else:
            parts.append((label + ":  ", "hl"))
            parts.append((value + "\n", ""))
    parts.append(("\n" + tr("Vorlage „{0}“", template_name(t)) + "\n", "dim"))
    return parts


# ----- Discord ------------------------------------------------------------------------- #
EMBED_LIMIT = 5800                    # Discord: 6000 Zeichen pro Nachricht – etwas Luft lassen
EMBEDS_PER_MESSAGE = 10
FIELDS_PER_EMBED = 25


def _embed_size(e: dict) -> int:
    return (len(e.get("title", "")) + len(e.get("description", "")) + len(e.get("footer", {}).get("text", ""))
            + sum(len(f["name"]) + len(f["value"]) for f in e.get("fields", [])))


def make_embed(t: dict, ctx: Ctx, title: str, color: int, stamp: float) -> dict:
    """Ein Embed aus einer Vorlage. Die Zusammenfassung (falls in der Vorlage) steht als Text oben."""
    desc = ""
    fields = []
    for b in t["blocks"]:
        r = render_block(b, ctx)
        if not r:
            continue
        label, value, wide = r
        if b["id"] == "hl.summary":
            desc = value
            continue
        fields.append({"name": label[:256], "value": value[:1024], "inline": not wide})
    e = {"title": title[:256], "color": color, "fields": fields[:FIELDS_PER_EMBED],
         "footer": {"text": f"Leeroyzan {APP_VERSION} · Leeroylink"},
         "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stamp))}
    if desc:
        e["description"] = desc[:3500]
    while _embed_size(e) > EMBED_LIMIT and e["fields"]:
        e["fields"].pop()
    return e


def session_messages(t: dict, s: dict, history: list[dict] | None = None, chars: dict | None = None) -> list[dict]:
    """Eine Sitzung als Discord-Nachricht nach Vorlage (wie bisher: Titel mit Charakter, Klasse und Uhrzeit)."""
    lv = s["level"]
    cls = tr(CLASS_NAMES.get(s["class"], s["class"].title())) if s["class"] else ""
    title = f"{s['name'] or s['char']}{' · ' + cls if cls else ''} – {session_title(s)}"
    if lv["to"] > lv["from"] > 0:
        title = "⬆ " + title
    ctx = Ctx([s], history=history or [], chars=chars or {})
    return [{"username": "Leeroyzan", "embeds": [make_embed(t, ctx, title, CLASS_COLORS.get(s["class"], DISCORD_COLOR), s["stop"])]}]


def period_messages(t: dict, title: str, sessions: list[dict], prev: list[dict] | None, history: list[dict],
                    chars: dict | None = None, each: bool = False, stamp: float | None = None) -> list[dict]:
    """Ein Zeitraum als Discord-Nachricht(en). each = ein Embed je Charakter, davor eines für alle mit der Rangliste."""
    stamp = stamp or time.time()
    chars = chars or {}
    if not each:
        ctx = Ctx(sessions, prev=prev, history=history, chars=chars, period=True)
        embeds = [make_embed(t, ctx, title, DISCORD_COLOR, stamp)]
    else:
        overview = {"name": t["name"], "blocks": [_b("hl.summary"), _b("hl.chars")]}
        embeds = [make_embed(overview, Ctx(sessions, history=history, chars=chars, period=True), title, DISCORD_COLOR, stamp)]
        by: dict[str, list[dict]] = {}
        for s in sessions:
            by.setdefault(s["char"], []).append(s)
        for char, lst in sorted(by.items(), key=lambda kv: -sum(s["played"] for s in kv[1])):
            pv = [s for s in (prev or []) if s["char"] == char] if prev is not None else None
            blocks = [b for b in t["blocks"] if b["id"] not in ("hl.chars",)]
            first = lst[0]
            cls = tr(CLASS_NAMES.get(first["class"], first["class"].title())) if first["class"] else ""
            name = f"{first['name'] or char}{' · ' + cls if cls else ''}"
            embeds.append(make_embed({"name": t["name"], "blocks": blocks},
                                     Ctx(lst, prev=pv, history=history, chars=chars, period=True), name,
                                     CLASS_COLORS.get(first["class"], DISCORD_COLOR), stamp))
    return split_messages(embeds)


def split_messages(embeds: list[dict]) -> list[dict]:
    """Verteilt Embeds auf Nachrichten: höchstens 10 und rund 6000 Zeichen pro Nachricht."""
    out: list[dict] = []
    cur: list[dict] = []
    size = 0
    for e in embeds:
        n = _embed_size(e)
        if cur and (len(cur) >= EMBEDS_PER_MESSAGE or size + n > EMBED_LIMIT):
            out.append({"username": "Leeroyzan", "embeds": cur})
            cur, size = [], 0
        cur.append(e)
        size += n
    if cur:
        out.append({"username": "Leeroyzan", "embeds": cur})
    return out


def embed_preview_text(messages: list[dict]) -> str:
    """Discord-Nachrichten als lesbarer Text (Vorschau in Leeroyzan)."""
    lines = []
    for i, msg in enumerate(messages):
        if i:
            lines.append("─" * 30)
        for e in msg["embeds"]:
            lines.append("▌ " + e.get("title", ""))
            if e.get("description"):
                lines.append(e["description"])
            for f in e.get("fields", []):
                lines.append(f"{f['name']}: {f['value']}" if f["inline"] else f"{f['name']}:\n{f['value']}")
            lines.append("")
    return "\n".join(lines).strip() + "\n"
