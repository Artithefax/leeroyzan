"""Dinge aus Leeroyzan an Discord teilen: Addon-Listen, Talent-Builds, Guides, Wowhead-Einträge, Quests, Charaktere.

Jede Funktion share_*_messages() baut eine oder mehrere Webhook-Nachrichten (Discord-Embeds). Gesendet wird mit
share_send() über denselben Webhook wie die Sitzungsberichte (oder einen eigenen Kanal fürs Teilen).
"""
from __future__ import annotations

import re
import time

from .constants import APP_VERSION
from .i18n import tr
from .reports import (
    CLASS_COLORS,
    CLASS_NAMES,
    DISCORD_COLOR,
    QUALITY_COLORS,
    discord_send,
    fmt_int,
    fmt_money,
)

# Grenzen von Discord für eine Nachricht
CONTENT_MAX, TITLE_MAX, DESC_MAX, FIELD_NAME_MAX, FIELD_MAX, FIELDS_MAX, EMBED_TOTAL_MAX = 2000, 256, 4096, 256, 1024, 25, 6000
SHARE_DESC = 1500                 # Beschreibungen kürzer halten – ein Beitrag soll in Discord lesbar bleiben
SHARE_GAP = 1.0                   # Pause zwischen mehreren Nachrichten (Discord erlaubt nur wenige pro Sekunde)
SHARE_LIST_MAX = 40               # so viele Addons stehen mit Link in der Nachricht, der Rest nur als Anzahl


def cut(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def _md(text: str) -> str:
    """Zeichen, die Discord als Formatierung liest, in Namen entschärfen."""
    return re.sub(r"([\\*_`~|>\[\]])", r"\\\1", text or "")


def _hex(color: str) -> int:
    try:
        return int(str(color).lstrip("#"), 16)
    except ValueError:
        return DISCORD_COLOR


def share_embed(title: str, url: str = "", description: str = "", fields=(), color: int = DISCORD_COLOR,
                thumbnail: str = "", footer: str = "") -> dict:
    """Ein Embed innerhalb der Grenzen von Discord. fields: (Name, Wert) oder (Name, Wert, nebeneinander)."""
    e = {"title": cut(title, TITLE_MAX), "color": color,
         "footer": {"text": cut(" · ".join(x for x in (footer, f"Leeroyzan {APP_VERSION}") if x), 2048)}}
    if url:
        e["url"] = url
    if description:
        e["description"] = cut(description, DESC_MAX)
    if thumbnail:
        e["thumbnail"] = {"url": thumbnail}
    out = []
    for f in list(fields)[:FIELDS_MAX]:
        name, value, inline = (f + (True,))[:3] if len(f) == 2 else f
        if value:
            out.append({"name": cut(name, FIELD_NAME_MAX), "value": cut(value, FIELD_MAX), "inline": bool(inline)})
    if out:
        e["fields"] = out
    # Gesamtlänge: zuerst die Beschreibung kürzen, dann Felder weglassen
    while _embed_len(e) > EMBED_TOTAL_MAX:
        if len(e.get("description", "")) > 200:
            e["description"] = cut(e["description"], max(200, len(e["description"]) - (_embed_len(e) - EMBED_TOTAL_MAX) - 10))
        elif e.get("fields"):
            e["fields"].pop()
        else:
            break
    return e


def _embed_len(e: dict) -> int:
    return (len(e.get("title", "")) + len(e.get("description", "")) + len(e["footer"]["text"])
            + sum(len(f["name"]) + len(f["value"]) for f in e.get("fields", [])) + len((e.get("author") or {}).get("name", "")))


def share_message(embed: dict | None = None, comment: str = "", author: str = "", content: str = "") -> dict:
    """Eine Webhook-Nachricht. comment = eigener Text über dem Embed, author = „geteilt von …“.
    Erwähnungen (@everyone, @here, Rollen, Personen) werden nie ausgelöst."""
    msg: dict = {"username": "Leeroyzan", "allowed_mentions": {"parse": []}}
    text = "\n".join(x for x in ((comment or "").strip(), content) if x)
    if text:
        msg["content"] = cut(text, CONTENT_MAX)
    if embed:
        embed = dict(embed)
        if author:
            embed["author"] = {"name": cut(tr("geteilt von {0}", author.strip()), 256)}
        msg["embeds"] = [embed]
    return msg


# ----- Talent-Build ------------------------------------------------------------------ #
def share_build_messages(build, name: str = "", comment: str = "", author: str = "") -> list[dict]:
    """Ein Build aus dem Talentplaner: Punkte je Baum, Talente mit Rang, Link zum Wowhead-Talentrechner."""
    from .images import icon_url
    from .talents import TALENT_EDITIONS
    cls = build.cls
    summary = build.summary()
    trees = [(t["name"], build.tree_points(i)) for i, t in enumerate(cls.trees)]
    main = max(trees, key=lambda t: t[1])[0] if build.spent else ""
    desc = [f"**{_md(cls.name)}** · {summary}" + (f" · {_md(main)}" if main else "")]
    ed = TALENT_EDITIONS.get(build.edition, ("", 0))[0]
    meta = [x for x in (ed.split(" (")[0], tr("{0} Punkte", build.spent),
                        tr("ab Stufe {0}", build.required_level) if build.spent else "") if x]
    desc.append(" · ".join(meta))
    fields = []
    for ti, tree in enumerate(build.trees):
        pts = build.tree_points(ti)
        if not pts:
            continue
        talents = sorted((t for t in tree if build.rank(t["id"])), key=lambda t: (t["row"], t["col"]))
        lines = [f"{_md(t['name'])} {build.rank(t['id'])}/{t['max']}" for t in talents]
        fields.append((f"{cls.trees[ti]['name']} ({pts})", "\n".join(lines), True))
    steps = build.steps()
    if steps and len(steps) == build.spent and build.order:
        first = [f"{s['level']}: {s['name']}" for s in steps[:6]]
        fields.append((tr("Reihenfolge (Anfang)"), "\n".join(_md(x) for x in first) + ("\n…" if len(steps) > 6 else ""), False))
    emb = share_embed(name or tr("{0}-Build {1}", cls.name, summary), build.url(), "\n".join(desc), fields,
                      _hex(cls.color), icon_url(cls.icon), tr("Talentplaner"))
    return [share_message(emb, comment, author)]


# ----- Guide --------------------------------------------------------------------------- #
def share_guide_messages(guide: dict, intro: str = "", comment: str = "", author: str = "") -> list[dict]:
    """Ein gespeicherter Wowhead-Guide: Titel, Autor, Stand, Anfang des Textes und eingebettete Talent-Builds."""
    from .guides import guide_builds, render_guide
    from .wowhead import wowhead_base
    if not intro:
        text = "".join(t for t, _ in render_guide(guide, wowhead_base(guide.get("edition") or "")))
        intro = re.sub(r"\n{3,}", "\n\n", text).strip()
    fields = [(tr("Autor"), _md(guide.get("author") or ""), True), (tr("Stand"), guide.get("updated") or "", True)]
    builds = guide_builds(guide)
    if builds:
        base = wowhead_base(guide.get("edition") or "")
        lines = [f"[{tr('Build {0}', i)}]({base}/talent-calc/{p['link']})" for i, p in enumerate(builds[:8], 1)]
        fields.append((tr("Talent-Builds im Guide"), " · ".join(lines), False))
    emb = share_embed(guide.get("title") or tr("Guide"), guide.get("url") or "", cut(intro, 600), fields,
                      DISCORD_COLOR, "", tr("Wowhead-Guide"))
    return [share_message(emb, comment, author)]


# ----- Wowhead-Eintrag ------------------------------------------------------------------ #
def share_wowhead_messages(row: dict, tip: dict | None = None, comment: str = "", author: str = "") -> list[dict]:
    """Ein Treffer der Wowhead-Suche (Gegenstand, Zauber, NPC, Quest …) mit seiner Kurzinfo."""
    from .images import icon_url
    tip = tip or {}
    name = tip.get("name") or row.get("name") or "?"
    lines = (tip.get("text") or "").splitlines()
    if lines and lines[0].strip() == name.strip():
        lines = lines[1:]
    q = tip.get("quality")
    q = row.get("quality") if q is None else q
    color = _hex(QUALITY_COLORS[q]) if isinstance(q, int) and 0 <= q < len(QUALITY_COLORS) else DISCORD_COLOR
    if color == 0xF3F0E8:                       # „gewöhnlich“ ist fast weiß – dann lieber Gold
        color = DISCORD_COLOR
    icon = icon_url(tip["icon"], "large") if tip.get("icon") else ""
    emb = share_embed(name, row.get("url") or "", cut("\n".join(lines), SHARE_DESC), (), color, icon,
                      f"{tr(row.get('kind_name') or '')} · ID {row.get('id')}".strip(" ·"))
    return [share_message(emb, comment, author)]


# ----- Quest ------------------------------------------------------------------------------ #
def share_text_messages(title: str, text: str, url: str = "", footer: str = "", color: int = DISCORD_COLOR,
                        comment: str = "", author: str = "") -> list[dict]:
    """Etwas, das Leeroyzan als Text anzeigt (z. B. eine Quest aus QuestieDB), als Nachricht mit Link."""
    lines = (text or "").strip().splitlines()
    if lines and lines[0].strip() == (title or "").strip():
        lines = lines[1:]
    body = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    emb = share_embed(title, url, cut(body, SHARE_DESC), (), color, "", footer)
    return [share_message(emb, comment, author)]


# ----- Charakter --------------------------------------------------------------------------- #
def share_char_messages(c: dict, played: int = 0, sessions: int = 0, with_gold: bool = False,
                        comment: str = "", author: str = "") -> list[dict]:
    """Ein Charakter aus Leeroylink: Stufe, Klasse, Gilde, Berufe – Gold nur auf Wunsch."""
    from .reports import fmt_dur, skill_group_by_name
    cls = tr(CLASS_NAMES.get(c.get("class") or "", (c.get("class") or "").title())) if c.get("class") else ""
    head = " · ".join(x for x in (tr("Stufe {0}", c["level"]) if c.get("level") else "", cls, c.get("race") or "",
                                  c.get("realm") or "", f"<{c['guild']}>" if c.get("guild") else "") if x)
    fields = []
    profs = [sk for sk in c.get("skills") or [] if skill_group_by_name(sk["name"]) == "prof"]
    if profs:
        fields.append((tr("Berufe"), "\n".join(f"{_md(sk['name'])} {sk['rank']}/{sk['max']}" for sk in profs), True))
    if played:
        fields.append((tr("Gespielt (Leeroylink)"), tr("{0} in {1} Sitzungen", fmt_dur(played), fmt_int(sessions)), True))
    if with_gold and c.get("money"):
        fields.append((tr("Gold"), fmt_money(c["money"]), True))
    emb = share_embed(c.get("name") or "?", "", head, fields, CLASS_COLORS.get(c.get("class") or "", DISCORD_COLOR),
                      "", tr("Charakter"))
    return [share_message(emb, comment, author)]


# ----- Addon-Liste -------------------------------------------------------------------------- #
def share_addons_messages(payload: dict, code_parts: list[str], unlinked: list[str], flavor_name: str = "",
                          comment: str = "", author: str = "") -> list[dict]:
    """Addons mit Links zu CurseForge/GitHub – und der Code dazu, den Freunde in Leeroyzan einfügen (Teilen → Empfangen).
    Ein langer Code wird auf mehrere Nachrichten verteilt."""
    entries = payload.get("a") or []
    lines: list[str] = []
    room = DESC_MAX - 60
    for n, e in enumerate(entries):
        if e["t"] == "c":
            url = f"https://www.curseforge.com/wow/addons/{e['s']}" if e.get("s") else f"https://www.curseforge.com/projects/{e['i']}"
            line = f"• [{_md(e.get('n') or e.get('s') or str(e['i']))}]({url})"
        else:
            line = f"• [{_md(e['r'].split('/')[-1])}](https://github.com/{e['r']}) (GitHub)"
        if n >= SHARE_LIST_MAX or sum(len(x) + 1 for x in lines) + len(line) > room:
            lines.append(tr("… und {0} weitere", len(entries) - n))
            break
        lines.append(line)
    desc = "\n".join(lines)
    fields = []
    if unlinked:
        fields.append((tr("Ohne Download-Quelle (nicht im Code)"), cut(", ".join(_md(n) for n in unlinked), FIELD_MAX), False))
    if payload.get("s"):
        fields.append((tr("Addon-Sets"), ", ".join(_md(n) for n in payload["s"]), False))
    title = tr("{0} Addons für {1}", len(entries), flavor_name) if flavor_name else tr("{0} Addons", len(entries))
    emb = share_embed(title, "", desc, fields, DISCORD_COLOR, "", tr("Addon-Liste"))
    hint = tr("Zum Installieren: Code kopieren → Leeroyzan → Teilen → Empfangen.") if code_parts else ""
    msgs = [share_message(emb, comment, author, hint)]
    for i, part in enumerate(code_parts, 1):
        head = tr("Code, Teil {0} von {1}:", i, len(code_parts)) + "\n" if len(code_parts) > 1 else ""
        msgs.append(share_message(content=cut(f"{head}```\n{part}\n```", CONTENT_MAX)))
    return msgs


# ----- Vorschau und Senden ------------------------------------------------------------------ #
def share_preview(messages: list[dict]) -> str:
    """So ungefähr sieht es in Discord aus – als schlichter Text für die Vorschau in Leeroyzan."""
    def plain(text: str) -> str:
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)          # [Name](Link) -> Name
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)                  # **fett**
        return re.sub(r"\\(.)", r"\1", text)                          # entschärfte Zeichen

    out = []
    for m in messages:
        if m.get("content"):
            out.append(m["content"])
        for e in m.get("embeds", []):
            if e.get("author"):
                out.append(e["author"]["name"])
            out.append(e.get("title", ""))
            if e.get("url"):
                out.append(e["url"])
            if e.get("description"):
                out.append(plain(e["description"]))
            for f in e.get("fields", []):
                out.append(f"\n{f['name']}\n{plain(f['value'])}")
        out.append("")
    return "\n".join(out).strip()


def share_send(url: str, messages: list[dict], sleep=time.sleep) -> int:
    """Sendet die Nachrichten der Reihe nach. Gibt die Anzahl zurück; ein Fehler bricht ab (Ausnahme)."""
    for i, m in enumerate(messages):
        if i:
            sleep(SHARE_GAP)
        discord_send(url, m, sleep=sleep)
    return len(messages)
