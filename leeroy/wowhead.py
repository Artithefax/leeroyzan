"""Wowhead: Suche mit Vorschau."""
from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request

from .constants import APP_VERSION
from .i18n import cur_lang, tr
from .reports import QUALITY_COLORS, fmt_int, fmt_money


# --------------------------------------------------------------------------- #
# Wowhead: Suche mit Vorschau
# --------------------------------------------------------------------------- #
# Wowhead hat getrennte Datenbanken je Spielausgabe.
WOWHEAD_EDITIONS = [("forever", "WoW Forever"), ("classic", "Classic (Era / Anniversary)"), ("tbc", "Burning Crusade Classic"),
                    ("wotlk", "Wrath of the Lich King Classic"), ("cata", "Cataclysm Classic"),
                    ("mop-classic", "Mists of Pandaria Classic"), ("", "Retail (aktuelles WoW)")]
# Typnummern aus der Wowhead-Suche → Adressteil und Anzeigename
WOWHEAD_TYPES = {1: ("npc", "NPC"), 2: ("object", "Objekt"), 3: ("item", "Gegenstand"), 4: ("item-set", "Set"),
                 5: ("quest", "Quest"), 6: ("spell", "Zauber"), 7: ("zone", "Zone"), 8: ("faction", "Fraktion"),
                 10: ("achievement", "Erfolg"), 11: ("title", "Titel"), 12: ("event", "Ereignis"),
                 13: ("class", "Klasse"), 14: ("race", "Volk"), 15: ("skill", "Fertigkeit"), 17: ("currency", "Währung")}
WOWHEAD_TOOLTIP_TYPES = ("item", "npc", "quest", "spell", "object", "achievement", "currency", "item-set")
WOWHEAD_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Leeroyzan/" + APP_VERSION


def wowhead_base(edition: str, lang: str = "") -> str:
    """https://www.wowhead.com[/classic][/de] – deutsche Seiten, wenn Leeroyzan auf Deutsch läuft."""
    lang = lang or cur_lang()
    return "https://www.wowhead.com" + (f"/{edition}" if edition else "") + ("/de" if lang == "de" else "")


def wowhead_url(edition: str, kind: str, wid) -> str:
    return f"{wowhead_base(edition)}/{kind}={wid}"


def wowhead_search_url(edition: str, query: str) -> str:
    return f"{wowhead_base(edition)}/search?q={urllib.parse.quote(query)}"


def _wowhead_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": WOWHEAD_UA, "Accept": "application/json, text/javascript, */*"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def wowhead_text(url: str, timeout: int = 20) -> str:
    """Eine Seite oder Datendatei von Wowhead als Text (Guides, Talentdaten)."""
    req = urllib.request.Request(url, headers={"User-Agent": WOWHEAD_UA, "Accept": "text/html, application/javascript, */*",
                                               "Accept-Language": "de,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def wowhead_bytes(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": WOWHEAD_UA, "Accept": "image/*, */*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def wowhead_search(query: str, edition: str) -> list[dict]:
    """Die Vorschläge der Wowhead-Suche (wie im Suchfeld auf der Seite): Name, Art, ID, Qualität."""
    query = query.strip()
    if not query:
        return []
    data = _wowhead_json(f"{wowhead_base(edition)}/search/suggestions-template?q={urllib.parse.quote(query)}")
    out = []
    for r in (data.get("results") or []) if isinstance(data, dict) else []:
        if not isinstance(r, dict):
            continue
        t = WOWHEAD_TYPES.get(r.get("type"))
        name = r.get("name")
        if not t or not name or r.get("id") is None:
            continue
        q = r.get("quality")
        out.append({"kind": t[0], "kind_name": t[1], "id": r["id"], "name": html.unescape(str(name)), "edition": edition,
                    "quality": q if isinstance(q, int) and 0 <= q < len(QUALITY_COLORS) else None,
                    "url": wowhead_url(edition, t[0], r["id"])})
    return out


def tooltip_text(markup: str) -> str:
    """Wowhead-Tooltip (HTML) → lesbarer Text mit Zeilenumbrüchen."""
    t = re.sub(r"<!--.*?-->", "", markup or "", flags=re.S)
    t = re.sub(r"<(script|style)\b.*?</\1>", "", t, flags=re.S | re.I)
    t = re.sub(r"<br\s*/?>|<table\b[^>]*>|</(div|tr|table|p|li|h\d)>", "\n", t, flags=re.I)
    t = re.sub(r"</t[dh]>", "   ", t, flags=re.I)
    t = html.unescape(re.sub(r"<[^>]+>", "", t))
    lines = [re.sub(r"[ \t\u00a0]+", " ", ln).strip() for ln in t.splitlines()]
    out = []
    for ln in lines:
        if ln or (out and out[-1]):
            out.append(ln)
    return "\n".join(out).strip()


def wowhead_tooltip(kind: str, wid, edition: str) -> dict:
    """Kurzinfo zu einem Eintrag (der Tooltip, den Wowhead beim Überfahren eines Links zeigt)."""
    if kind not in WOWHEAD_TOOLTIP_TYPES:
        return {}
    env = (f"/{edition}" if edition else "") + ("/de" if cur_lang() == "de" else "")
    data = _wowhead_json(f"https://nether.wowhead.com{env}/tooltip/{kind}/{wid}")
    if not isinstance(data, dict):
        return {}
    q = data.get("quality")
    return {"name": html.unescape(str(data.get("name") or "")), "text": tooltip_text(str(data.get("tooltip") or "")),
            "icon": str(data.get("icon") or ""),
            "quality": q if isinstance(q, int) and 0 <= q < len(QUALITY_COLORS) else None}


# --------------------------------------------------------------------------- #
# Mehr aus der Wowhead-Seite: Schnellinfo und Listen (Gedroppt von, Verkauft von …)
# --------------------------------------------------------------------------- #
# Listen der Seite, die Leeroyzan zeigt – Reihenfolge = Anzeige. Andere (Kommentare, Bilder …) bleiben weg.
WOWHEAD_LISTS = {
    "dropped-by": "Gedroppt von", "drops": "Beute", "sold-by": "Verkauft von", "sells": "Verkauft",
    "reward-from-q": "Belohnung von", "starts": "Beginnt Quests", "ends": "Beendet Quests", "objective-of": "Ziel von Quests",
    "created-by-spell": "Hergestellt durch", "created-by": "Hergestellt durch", "reagent-for": "Reagenz für",
    "contained-in-item": "Enthalten in", "contained-in-object": "Enthalten in", "mined-from-object": "Abgebaut aus",
    "gathered-from-object": "Gesammelt aus", "herbed-from-object": "Gepflückt aus", "skinned-from": "Gekürschnert von",
    "fished-in": "Geangelt in", "pick-pocketed-from": "Gestohlen von", "pickpocketing": "Taschendiebstahl",
    "disenchanting": "Entzaubern ergibt", "disenchanted-from": "Entzaubert aus", "contains": "Enthält",
    "mining": "Abbau ergibt", "herbalism": "Kräuterkunde ergibt", "skinning": "Kürschnern ergibt", "fishing": "Angeln ergibt",
    "starts-quest": "Beginnt Quests", "quests": "Quests", "teaches": "Lehrt", "abilities": "Fähigkeiten", "criteria-of": "Teil von",
}
WOWHEAD_LIST_ROWS = 5             # so viele Zeilen je Liste in der Vorschau
LOOT_MIN_SAMPLES = 20             # Dropchancen aus weniger Beobachtungen sind Zufall – sie kommen ans Ende
NPC_RANKS = {1: "Elite", 2: "Seltene Elite", 3: "Boss", 4: "Selten"}
QUEST_SIDES = {1: "Allianz", 2: "Horde"}
QUEST_COLORS = {"q10": "rot", "r1": "orange", "r2": "gelb", "r3": "grün", "r4": "grau"}
REACTIONS = {"q10": "feindlich", "q2": "freundlich", "q": "neutral"}


def _js_end(text: str, i: int) -> int:
    """Index der schließenden Klammer zu text[i] ('[' oder '{'), Zeichenketten werden übersprungen."""
    depth, in_str = 0, False
    while i < len(text):
        c = text[i]
        if in_str:
            if c == "\\":
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c in "[{":
            depth += 1
        elif c in "]}":
            depth -= 1
            if not depth:
                return i
        i += 1
    return -1


def _js_to_json(text: str) -> str:
    """JavaScript-Objekte in JSON: Schlüssel ohne Anführungszeichen (modes:{…}) bekommen welche."""
    out, i, in_str = [], 0, False
    while i < len(text):
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < len(text):
                out.append(text[i + 1])
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
            out.append(c)
        else:
            m = re.match(r"([{,]\s*)([A-Za-z_$][\w$]*)(\s*:)", text[i:])
            if m:
                out.append(f'{m.group(1)}"{m.group(2)}"{m.group(3)}')
                i += m.end()
                continue
            out.append(c)
        i += 1
    return "".join(out)


def infobox_lines(markup: str) -> list[str]:
    """Die Schnellinfo („Stufe: 11“, „Anfang: …“) aus Wowheads Markup als Textzeilen."""
    t = markup or ""
    t = re.sub(r"\[span=invisible\].*?\[/span\]", "", t, flags=re.S)
    t = re.sub(r"\[tooltip[^\]]*\].*?\[/tooltip\]", "", t, flags=re.S)       # Erklärtext zum Wert daneben
    t = re.sub(r"\[small\].*?\[/small\]", " ", t, flags=re.S)

    def money(m):
        a, b = m.group(1), m.group(2)
        return fmt_money(int(a)) + (f" – {fmt_money(int(b))}" if b else "")
    t = re.sub(r"\[money=(\d+)(?:-(\d+))?[^\]]*\]", money, t)
    t = re.sub(r"\[br\]", ", ", t)
    lines = []
    for li in re.findall(r"\[li[^\]]*\](.*?)\[/li\]", t, flags=re.S):
        if "[icondb=" in li:                         # „Symbol: …“ – nur eine Nummer
            continue
        if "[color=r1]" in li:                       # Questfarben: ab welcher Stufe rot, orange, gelb, grün, grau
            steps = re.findall(r"\[color=(q10|r\d)\](\d+)\[/color\]", li)
            li = tr("Questfarbe nach Stufe: {0}", ", ".join(f"{tr(QUEST_COLORS.get(c, c))} {n}" for c, n in steps))
        elif re.search(r"\[color=q\d*\][AH]\[/color\]", li):        # Einstellung zur Allianz (A) und Horde (H)
            li = re.sub(r"\[color=(q\d*)\]([AH])\[/color\]",
                        lambda m: f"{tr(QUEST_SIDES[1 if m.group(2) == 'A' else 2])} {tr(REACTIONS.get(m.group(1), 'neutral'))}", li)
            li = re.sub(r"(?<=\w)\s+(?=(?:" + "|".join(re.escape(tr(x)) for x in QUEST_SIDES.values()) + "))", ", ", li)
        li = re.sub(r"\[/?[a-z][^\]]*\]", "", li)      # übrige Marken: [url=…], [color=…], [copy …], [acronym=…] …
        li = re.sub(r"\s+", " ", html.unescape(li).replace("\u00a0", " ")).strip(" ,")
        if li:
            lines.append(li)
    return lines


def parse_wowhead_page(page: str) -> dict:
    """{'facts': [Zeilen der Schnellinfo], 'lists': [{'id', 'template', 'total', 'rows'}]} aus einer Wowhead-Seite."""
    facts: list[str] = []
    m = re.search(r'WH\.markup\.printHtml\("((?:[^"\\]|\\.)*)",\s*"infobox-contents-0"', page or "")
    if m:
        try:
            facts = infobox_lines(json.loads(f'"{m.group(1)}"'))
        except ValueError:
            facts = []
    lists = []
    starts = [m.end() - 1 for m in re.finditer(r"new Listview\(\{", page or "")]
    for n, start in enumerate(starts):
        # nur bis zur nächsten Liste suchen: eine Liste ohne eigene Daten darf nie die der nächsten bekommen
        head = page[start:min(start + 4000, starts[n + 1] if n + 1 < len(starts) else len(page))]
        lid = re.search(r"\bid:\s*'([\w-]+)'", head)
        if not lid or lid.group(1) not in WOWHEAD_LISTS or any(x["id"] == lid.group(1) for x in lists):
            continue
        dm = re.search(r"\bdata:\s*\[", head)
        if not dm:
            continue
        a = start + dm.end() - 1
        b = _js_end(page, a)
        if b < 0:
            continue
        try:
            rows = json.loads(_js_to_json(page[a:b + 1]))
        except ValueError:
            continue
        rows = [r for r in rows if isinstance(r, dict) and (r.get("name") or r.get("displayName"))]
        if not rows:
            continue
        tpl = re.search(r"\btemplate:\s*'(\w+)'", head)
        found = re.search(r"found\w*_format,\s*(\d+)", page[start:a])          # „230 gefunden, 200 angezeigt“
        lists.append({"id": lid.group(1), "template": tpl.group(1) if tpl else "", "rows": rows,
                      "total": max(len(rows), int(found.group(1)) if found else 0)})
    order = list(WOWHEAD_LISTS)
    lists.sort(key=lambda x: order.index(x["id"]))
    return {"facts": facts, "lists": lists}


def fetch_wowhead_page(kind: str, wid, edition: str) -> dict:
    return parse_wowhead_page(wowhead_text(wowhead_url(edition, kind, wid)))


def _pct(count, outof) -> str:
    p = 100 * count / outof
    text = f"{p:.1f}" if p < 10 else f"{p:.0f}"
    return (text.replace(".", ",") if cur_lang() == "de" else text) + " %"


def _chance(r: dict) -> float:
    c, o = r.get("count"), r.get("outof")
    return c / o if isinstance(c, (int, float)) and isinstance(o, (int, float)) and o > 0 and c > 0 else -1.0


def wowhead_list_rows(lst: dict, zone_name=None, limit: int = WOWHEAD_LIST_ROWS) -> list[dict]:
    """Die wichtigsten Zeilen einer Liste, lesbar: {'name', 'quality', 'info', 'kind', 'id'}.
    Beutelisten nach Dropchance (aus genügend Beobachtungen), sonst in Wowheads Reihenfolge (Beliebtheit)."""
    rows = list(lst["rows"])
    if any(_chance(r) >= 0 for r in rows):
        rows.sort(key=lambda r: (_chance(r) >= 0 and (r.get("outof") or 0) >= LOOT_MIN_SAMPLES, _chance(r), r.get("count") or 0),
                  reverse=True)
    tpl = lst["template"]
    out = []
    for r in rows[:limit]:
        info = []
        if tpl == "npc":
            lo, hi = r.get("minlevel"), r.get("maxlevel")
            if lo:
                info.append(tr("Stufe {0}", lo if lo == hi or not hi else f"{lo}–{hi}"))
            if NPC_RANKS.get(r.get("classification")):
                info.append(tr(NPC_RANKS[r["classification"]]))
        elif tpl == "quest":
            if r.get("level"):
                info.append(tr("Stufe {0}", r["level"]))
            if QUEST_SIDES.get(r.get("side")):
                info.append(tr(QUEST_SIDES[r["side"]]))
        elif tpl == "spell":
            if r.get("rank"):
                info.append(str(r["rank"]))
            if r.get("learnedat"):
                info.append(tr("ab Fertigkeit {0}", r["learnedat"]))
        loc = [z for z in (r.get("location") or []) if isinstance(z, int) and z > 0]
        if loc and zone_name and tpl in ("npc", "object"):
            z = zone_name(loc[0])
            if z and not z.startswith("#"):
                info.append(z)
        if _chance(r) >= 0:
            info.append(_pct(r["count"], r["outof"]) + ("" if (r.get("outof") or 0) >= LOOT_MIN_SAMPLES else " (" + tr("wenig Daten") + ")"))
        cost = r.get("cost")
        if isinstance(cost, list) and cost and isinstance(cost[0], list) and cost[0] and isinstance(cost[0][0], int):
            info.append(fmt_money(cost[0][0]) + (f" ({tr('{0} Stück', r['stack'])})" if isinstance(r.get("stack"), int) and r["stack"] > 1 else ""))
        q = r.get("quality")
        out.append({"name": html.unescape(str(r.get("name") or r.get("displayName"))), "id": r.get("id"),
                    "quality": q if isinstance(q, int) and 0 <= q < len(QUALITY_COLORS) else None,
                    "kind": tpl, "info": " · ".join(str(x) for x in info)})
    return out


def wowhead_list_more(lst: dict, limit: int = WOWHEAD_LIST_ROWS) -> str:
    rest = lst["total"] - min(limit, len(lst["rows"]))
    return tr("… und {0} weitere auf Wowhead", fmt_int(rest)) if rest > 0 else ""
