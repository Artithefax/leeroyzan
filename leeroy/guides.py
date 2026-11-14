"""Wowhead-Guides speichern und offline lesen.

Ein Guide steht bei Wowhead als Markup ([h2]…[/h2], [spell=123], [talent=shaman/…]) in der Seite. Leeroyzan
speichert dieses Markup samt den Namen der verlinkten Zauber, Gegenstände und Quests im Datenordner und stellt
es als Text dar; Talent-Builds aus dem Guide lassen sich im Talentplaner öffnen.
"""
from __future__ import annotations

import html
import json
import re
import time
from pathlib import Path

from .config import config_dir, write_text_atomic
from .i18n import tr
from .talents import TALENT_EDITIONS, parse_build_link, talent_class
from .wowhead import wowhead_text

# Typnummern in WH.Gatherer.addData(typ, …) -> Adressteil bei Wowhead
GATHERER_KINDS = {1: "npc", 2: "object", 3: "item", 4: "item-set", 5: "quest", 6: "spell", 7: "zone", 8: "faction",
                  10: "achievement", 13: "class", 14: "race", 15: "skill", 17: "currency"}
ENTITY_TAGS = set(GATHERER_KINDS.values()) | {"itemset", "pet", "title", "event", "statistic", "transmog-set", "mount", "building"}
INLINE_TAGS = {"b": "b", "i": "i", "u": "u", "s": "", "small": "", "sup": "", "sub": "", "color": "", "span": "", "tooltip": "",
               "icon": "", "class": "", "race": "", "money": "", "abbr": "", "acronym": "", "font": "", "size": ""}
BLOCK_TAGS = {"center", "wrapper", "quote", "box-highlight", "div", "grid", "section", "minibox", "tabs", "nav", "table", "tr",
              "ul", "ol", "p", "pad", "br", "hr", "toc", "code", "pre", "h1", "h2", "h3", "h4", "h5", "li", "td", "th", "tab",
              "nav-item", "cta-button", "url", "talent", "img", "screenshot", "video", "youtube", "map", "model", "pin",
              "copy", "ad", "feedback", "menu", "widget", "db", "wowheadresponsivevideo", "guide", "html", "script", "style"}
SKIP_CONTENT = {"script", "style", "video", "youtube", "map", "model", "copy", "html", "menu", "widget", "pin"}
_TAG_RX = re.compile(r"\[(/?)([A-Za-z][A-Za-z0-9-]*)((?:=(?:\"[^\"]*\"|[^\]\s]*))?(?:\s+[^\]]*)?)\]")


def is_guide_url(url: str) -> bool:
    return bool(re.match(r"^https?://([a-z0-9-]+\.)?wowhead\.com/.*guide", (url or "").strip(), re.I))


def guide_edition(url: str) -> str:
    """Wowhead-Ausgabe aus der Adresse (forever, classic, tbc …; leer = Retail)."""
    m = re.match(r"^https?://[^/]+/([a-z0-9-]+)/", url or "", re.I)
    first = m.group(1).lower() if m else ""
    return first if first in TALENT_EDITIONS or first in ("cata", "mop-classic") else ""


def _js_string_after(text: str, pos: int):
    """Die JSON-Zeichenkette, die ab pos (nach Leerraum) beginnt – oder None."""
    m = re.compile(r"\s*").match(text, pos)
    start = m.end()
    if start >= len(text) or text[start] != '"':
        return None, start
    try:
        value, end = json.JSONDecoder(strict=False).raw_decode(text, start)
    except ValueError:
        return None, start
    return (value, end) if isinstance(value, str) else (None, start)


def parse_guide_html(page: str, url: str = "") -> dict:
    """Titel, Autor, Markup und Namen aus einer Wowhead-Guide-Seite. ValueError, wenn kein Guide darin steckt."""
    markup = None
    for m in re.finditer(r"WH\.markup\.printHtml\(", page):
        value, end = _js_string_after(page, m.end())
        if value is None:
            continue
        if re.match(r'\s*,\s*"guide-body"', page[end:end + 40]) or markup is None and len(value) > 400:
            markup = value
            if re.match(r'\s*,\s*"guide-body"', page[end:end + 40]):
                break
    if not markup:
        raise ValueError("Auf dieser Seite wurde kein Guide gefunden.")
    names: dict[str, dict] = {}
    for m in re.finditer(r"WH\.Gatherer\.addData\(\s*(\d+)\s*,\s*\d+\s*,\s*", page):
        kind = GATHERER_KINDS.get(int(m.group(1)))
        if not kind:
            continue
        try:
            data, _ = json.JSONDecoder(strict=False).raw_decode(page, m.end())
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        for eid, e in data.items():
            if not isinstance(e, dict):
                continue
            name = next((e[k] for k in e if k.startswith("name_") and isinstance(e[k], str) and e[k]), None) or e.get("name")
            if name:
                entry = {"n": html.unescape(str(name))}
                if isinstance(e.get("quality"), int):
                    entry["q"] = e["quality"]
                names.setdefault(kind, {})[str(eid)] = entry

    def meta(prop: str) -> str:
        mm = re.search(r'<meta\s+property="og:%s"\s+content="([^"]*)"' % re.escape(prop), page)
        return html.unescape(mm.group(1)).strip() if mm else ""
    title = meta("title")
    if not title:
        mm = re.search(r"<title>([^<]*)</title>", page)
        title = re.sub(r"\s*-\s*Wowhead\s*$", "", html.unescape(mm.group(1)).strip()) if mm else url
    author = re.search(r'href="[^"]*/author/([^"/?]+)"', page)
    updated = re.search(r'class="date-tip"[^>]*>\s*([^<]+?)\s*<', page)
    canonical = re.search(r'<link\s+rel="canonical"\s+href="([^"]+)"', page)
    return {"url": url or (canonical.group(1) if canonical else ""), "title": title, "summary": meta("description"),
            "author": html.unescape(author.group(1)) if author else "", "updated": updated.group(1) if updated else "",
            "edition": guide_edition(url or (canonical.group(1) if canonical else "")), "markup": markup, "names": names,
            "saved": time.time()}


def fetch_guide(url: str) -> dict:
    url = url.strip().split("#", 1)[0]
    if not is_guide_url(url):
        raise ValueError("Das ist keine Adresse eines Wowhead-Guides.")
    return parse_guide_html(wowhead_text(url, timeout=30), url)


# --------------------------------------------------------------------------- #
# Ablage
# --------------------------------------------------------------------------- #
def guides_dir() -> Path:
    return config_dir() / "guides"


def guide_id(url: str) -> str:
    path = re.sub(r"^https?://[^/]+/", "", url.split("?", 1)[0].split("#", 1)[0]).strip("/")
    return re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-")[:120] or "guide"


def save_guide(guide: dict) -> str:
    gid = guide_id(guide["url"])
    guides_dir().mkdir(parents=True, exist_ok=True)
    write_text_atomic(guides_dir() / f"{gid}.json", json.dumps(guide, ensure_ascii=False))
    return gid


def load_guide(gid: str) -> dict | None:
    try:
        g = json.loads((guides_dir() / f"{gid}.json").read_text(encoding="utf-8"))
        return g if isinstance(g, dict) and isinstance(g.get("markup"), str) else None
    except (OSError, ValueError):
        return None


def delete_guide(gid: str) -> None:
    try:
        (guides_dir() / f"{gid}.json").unlink()
    except OSError:
        pass


def list_guides() -> list[dict]:
    """Gespeicherte Guides (ohne Inhalt), neueste zuerst."""
    out = []
    for f in guides_dir().glob("*.json") if guides_dir().is_dir() else []:
        g = load_guide(f.stem)
        if g:
            out.append({"id": f.stem, "title": g.get("title") or f.stem, "url": g.get("url", ""), "edition": g.get("edition", ""),
                        "author": g.get("author", ""), "updated": g.get("updated", ""), "saved": g.get("saved", 0),
                        "builds": len(guide_builds(g))})
    return sorted(out, key=lambda g: -float(g["saved"] or 0))


def guide_builds(guide: dict) -> list[dict]:
    """Talent-Builds, die im Guide eingebettet sind ([talent=shaman/<Punkte>/<Reihenfolge>])."""
    out, seen = [], set()
    for m in re.finditer(r"\[talent=([^\s\]]+)", guide.get("markup") or ""):
        p = parse_build_link(m.group(1))
        if p and m.group(1) not in seen:
            seen.add(m.group(1))
            p["edition"] = p["edition"] or guide.get("edition") or ""
            p["link"] = m.group(1)
            out.append(p)
    return out


# --------------------------------------------------------------------------- #
# Darstellung
# --------------------------------------------------------------------------- #
def _attr(attrs: str, name: str = "") -> str:
    """Wert des Tags selbst ([url=…]) oder eines Attributs ([h2 toc="…"])."""
    if not name:
        m = re.match(r'=(?:"([^"]*)"|([^\]\s]*))', attrs)
    else:
        m = re.search(r'(?:^|\s)%s=(?:"([^"]*)"|([^\]\s]*))' % re.escape(name), attrs)
    return (m.group(1) if m.group(1) is not None else m.group(2)) if m else ""


def render_guide(guide: dict, base: str) -> list[tuple[str, tuple]]:
    """Markup -> Textstücke mit Stil-Marken für das Textfeld.

    Marken: h2, h3, b, i, dim, mono, q0…q7 (Gegenstandsqualität), link (anklickbar) – ein Link trägt zusätzlich
    eine Marke "url:<Adresse>" oder "build:<Nummer>". base ist die Wowhead-Startadresse der Ausgabe."""
    markup = (guide.get("markup") or "").replace("\r\n", "\n").replace("\r", "\n")
    names = guide.get("names") or {}
    builds = [b["link"] for b in guide_builds(guide)]
    out: list[tuple[str, tuple]] = []
    styles: list[str] = []          # offene Stil-Marken
    lists: list[list] = []          # offene Listen: [geordnet?, Zähler]
    state = {"nl": 2, "skip": "", "cell": 0, "link": "", "table": 0}

    def emit(text: str, *extra: str) -> None:
        if not text or state["skip"]:
            return
        tags = [s for s in styles if s] + [x for x in extra if x]
        if state["link"]:
            tags += ([] if extra else ["ent"]) + [state["link"], "link"]
        tags = tuple(dict.fromkeys(tags))
        out.append((text, tags))
        tail = len(text) - len(text.rstrip("\n"))
        state["nl"] = state["nl"] + tail if not text.strip("\n") else tail

    def newline(n: int = 1) -> None:
        if state["skip"]:
            return
        while state["nl"] < n:
            out.append(("\n", ()))
            state["nl"] += 1

    def text_piece(t: str) -> None:
        if (state["table"] or lists) and not t.strip():
            return                                     # Zeilenumbrüche zwischen Tabellenzeilen und Listenpunkten
        t = html.unescape(t)
        t = re.sub(r"[ \t]+", " ", t)
        t = re.sub(r" ?\n ?", "\n", t)
        t = re.sub(r"\n{3,}", "\n\n", t)
        if state["nl"]:
            t = t.lstrip("\n ") if state["nl"] >= 2 else re.sub(r"^ +", "", re.sub(r"^\n{2,}", "\n", t))
        if t:
            emit(t)

    def absolute(target: str) -> str:
        if re.match(r"^https?://", target, re.I):
            return target
        if target.startswith("//"):
            return "https:" + target
        return base.rstrip("/") + "/" + target.lstrip("/")

    pos = 0
    for m in _TAG_RX.finditer(markup):
        closing, name, attrs = m.group(1) == "/", m.group(2).lower(), m.group(3) or ""
        known = name in ENTITY_TAGS or name in INLINE_TAGS or name in BLOCK_TAGS
        if not known and not (closing or "=" in attrs):
            continue                                   # eckige Klammern im Text, kein Tag
        text_piece(markup[pos:m.start()])
        pos = m.end()
        if state["skip"]:
            if closing and name == state["skip"]:
                state["skip"] = ""
            continue
        if name in SKIP_CONTENT:
            if not closing and re.search(r"\[/%s\]" % re.escape(name), markup[pos:], re.I):
                state["skip"] = name
            continue
        if name in ENTITY_TAGS and name not in ("class", "race") and not closing:
            eid = _attr(attrs)
            kind = {"itemset": "item-set"}.get(name, name)
            entry = (names.get(kind) or {}).get(re.sub(r"\D.*$", "", eid)) or {}
            label = entry.get("n") or f"{kind} {eid}"
            quality = f"q{entry['q']}" if isinstance(entry.get("q"), int) and 0 <= entry["q"] <= 7 else ""
            saved, state["link"] = state["link"], state["link"] or f"url:{base.rstrip('/')}/{kind}={re.sub(r'[^0-9]', '', eid)}"
            emit(label, quality or "ent")
            state["link"] = saved
        elif name in ("h1", "h2", "h3", "h4", "h5"):
            style = "h2" if name in ("h1", "h2") else "h3"
            if closing:
                if style in styles:
                    styles.remove(style)
                newline(1)
            else:
                newline(2)
                styles.append(style)
        elif name in INLINE_TAGS:
            style = INLINE_TAGS[name]
            if closing:
                if style in styles:
                    styles.remove(style)
            elif style:
                styles.append(style)
        elif name in ("url", "nav-item", "cta-button"):
            if closing:
                state["link"] = ""
            else:
                target = _attr(attrs) or _attr(attrs, "url") or _attr(attrs, "href")
                if name == "nav-item":
                    newline(1)
                    emit("› ", "dim")
                state["link"] = "url:" + absolute(target) if target else ""
        elif name == "talent" and not closing:
            link = _attr(attrs)
            newline(1)
            if link in builds:
                cls = talent_class(parse_build_link(link)["cls"])
                saved, state["link"] = state["link"], f"build:{builds.index(link)}"
                emit(tr("▶ Talent-Build im Planer öffnen ({0})", cls.name), "build")
                state["link"] = saved
            newline(1)
        elif name in ("ul", "ol"):
            if closing:
                if lists:
                    lists.pop()
                newline(1 if lists else 2)
            else:
                lists.append([name == "ol", 0])
                newline(1)
        elif name == "li":
            if not closing:
                newline(1)
                indent = "   " * max(0, len(lists) - 1)
                if lists and lists[-1][0]:
                    lists[-1][1] += 1
                    emit(f"{indent} {lists[-1][1]}. ", "dim")
                else:
                    emit(f"{indent} • ", "dim")
                state["nl"] = 2                          # führenden Leerraum des Listenpunkts schlucken
        elif name == "tr":
            state["cell"] = 0
            newline(1)
        elif name in ("td", "th"):
            if not closing:
                if state["cell"]:
                    emit("   ·   ", "dim")
                state["cell"] += 1
                state["nl"] = 2                          # Leerraum am Zellenanfang schlucken
        elif name == "tab" and not closing:
            newline(2)
            emit("▸ " + html.unescape(_attr(attrs, "name") or ""), "h3")
            newline(1)
        elif name in ("code", "pre"):
            if closing:
                if "mono" in styles:
                    styles.remove("mono")
            else:
                styles.append("mono")
        elif name in ("pad", "br"):
            newline(1)
        elif name == "hr":
            newline(2)
        elif name in ("img", "screenshot", "toc", "ad", "feedback", "db", "guide", "wowheadresponsivevideo"):
            pass
        elif name == "table":
            state["table"] = max(0, state["table"] + (-1 if closing else 1))
            newline(2)
        else:                                            # Blöcke ohne eigene Darstellung: nur ein Absatz
            newline(2 if name in ("table", "tabs", "quote", "box-highlight", "nav") else 1)
    text_piece(markup[pos:])
    while out and not out[-1][0].strip():
        out.pop()
    return out
