"""Builds finden: Wowhead-Guides einer Klasse suchen und nach Zweck ordnen (Leveling, Dungeons & Raids, PvP …).

Die Anfrage ist freier Text („Schamane“, „scharmane leveling“, „Verstärkung Dungeon“, „Druide Tank“). Klasse,
Spezialisierung, Zweck und Rolle erkennt Leeroyzan selbst – auf Deutsch und Englisch, mit kleinen Tippfehlern.

Wowhead hat keine offene Schnittstelle für Guides. Leeroyzan liest sie deshalb aus mehreren Quellen und nimmt,
was es findet: die Guide-Übersicht der Klasse, die Wowhead-Suche, die Suchvorschläge und – wenn das wenig ist –
die Navigation in den gefundenen Guides selbst. Jede Quelle darf fehlen oder ihren Aufbau ändern; erkannt wird
ein Guide an seiner Adresse (…/guide/classes/<klasse>/…). Ergebnisse bleiben einen Tag im Datenordner.
"""
from __future__ import annotations

import difflib
import html
import json
import re
import threading
import time
import urllib.error
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from .config import config_dir, log, write_text_atomic
from .i18n import cur_lang, tr
from .talents import CLASSES, parse_build_link
from .wowhead import _js_end, _js_to_json, wowhead_base, wowhead_text

CACHE_HOURS = 24
FETCH_TIMEOUT = 15
CRAWL_PAGES = 3              # so viele Guides werden höchstens nach weiteren Guides durchsucht

# Zwecke in der Reihenfolge der Anzeige
CATEGORIES = [("leveling", "Leveling"), ("pve", "Dungeons & Raids"), ("pvp", "PvP"), ("talents", "Talente & Builds"),
              ("gear", "Ausrüstung"), ("play", "Spielweise"), ("overview", "Überblick"), ("other", "Sonstiges")]
CATEGORY_NAMES = dict(CATEGORIES)
ROLES = {"tank": "Tank", "healer": "Heiler", "dps": "DPS"}

# Wörter der Anfrage -> Zweck / Rolle (kleingeschrieben, ohne Umlaute verglichen)
_CAT_WORDS = {
    "leveling": "leveling", "levelling": "leveling", "leveln": "leveling", "level": "leveling", "aufleveln": "leveling",
    "questen": "leveling", "stufen": "leveling", "lvl": "leveling",
    "dungeon": "pve", "dungeons": "pve", "dungen": "pve", "instanz": "pve", "instanzen": "pve", "raid": "pve",
    "raids": "pve", "schlachtzug": "pve", "pve": "pve", "endgame": "pve",
    "pvp": "pvp", "schlachtfeld": "pvp", "duell": "pvp", "arena": "pvp",
    "talent": "talents", "talente": "talents", "build": "talents", "builds": "talents", "skillung": "talents",
    "bis": "gear", "gear": "gear", "ausruestung": "gear", "ausrustung": "gear", "items": "gear", "equipment": "gear",
    "rotation": "play", "makros": "play", "macros": "play", "addons": "play", "stats": "play", "werte": "play",
    "uberblick": "overview", "ueberblick": "overview", "overview": "overview", "anfanger": "overview", "einsteiger": "overview",
}
_ROLE_WORDS = {"tank": "tank", "tanken": "tank", "heiler": "healer", "heilen": "healer", "heal": "healer", "healer": "healer",
               "heilung": "healer", "dps": "dps", "schaden": "dps", "damage": "dps"}
_EXTRA_CLASS_WORDS = {"schami": "shaman", "sham": "shaman", "hexer": "warlock", "lock": "warlock", "dk": "death-knight",
                      "pala": "paladin", "pally": "paladin", "hunter": "hunter", "jaeger": "hunter", "jager": "hunter",
                      "dudu": "druid", "mage": "mage", "magier": "mage", "warri": "warrior", "krieger": "warrior"}
_SPEC_SLUG_FIX = {"feral-combat": "feral"}
_STOP = {"guide", "guides", "fur", "fuer", "for", "the", "der", "die", "das", "und", "and", "wow", "forever", "classic", "beste",
         "best", "tipps", "tips", "tricks", "zum", "zur", "im", "in"}

_GUIDE_RX = re.compile(r"^(?:https?://(?:[a-z0-9-]+\.)?wowhead\.com)?/?(?:(?P<ed>[a-z0-9-]+)/)?(?:(?P<lang>[a-z]{2})/)?"
                       r"guide/(?P<rest>[A-Za-z0-9/_-]+?)/?$", re.I)
_LANGS = {"de", "en", "es", "fr", "it", "pt", "ru", "ko", "cn", "mx", "tw"}


def _fold(text: str) -> str:
    t = (text or "").lower()
    for a, b in (("ä", "a"), ("ö", "o"), ("ü", "u"), ("ß", "ss")):
        t = t.replace(a, b)
    return t


def _words(text: str) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9]+", _fold(text)) if w]


# --------------------------------------------------------------------------- #
# Anfrage verstehen
# --------------------------------------------------------------------------- #
def _class_words() -> dict[str, str]:
    out = dict(_EXTRA_CLASS_WORDS)
    for slug, _cid, de, en, *_ in CLASSES:
        out[_fold(de).replace(" ", "")] = slug
        out[_fold(en).replace(" ", "")] = slug
        out[slug.replace("-", "")] = slug
    return out


def spec_slug(name_en: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name_en.lower()).strip("-")
    return _SPEC_SLUG_FIX.get(s, s)


def _spec_words() -> dict[str, list[tuple[str, str]]]:
    """Wort -> [(Klasse, Spec-Adressteil)] – „Wiederherstellung“ gibt es bei Schamane und Druide."""
    out: dict[str, list[tuple[str, str]]] = {}
    for slug, _cid, _de, _en, _col, _icon, trees, _eds in CLASSES:
        for _tid, de, en, _ic in trees:
            for w in {_fold(de).replace(" ", ""), _fold(en).replace(" ", ""), spec_slug(en).replace("-", "")}:
                out.setdefault(w, []).append((slug, spec_slug(en)))
    for w, specs in (("resto", [("shaman", "restoration"), ("druid", "restoration")]), ("enh", [("shaman", "enhancement")]),
                     ("ele", [("shaman", "elemental")]), ("bm", [("hunter", "beast-mastery")]), ("mm", [("hunter", "marksmanship")]),
                     ("feral", [("druid", "feral")]), ("eule", [("druid", "balance")]), ("moonkin", [("druid", "balance")]),
                     ("katze", [("druid", "feral")]), ("baer", [("druid", "feral")]), ("bar", [("druid", "feral")]),
                     ("disc", [("priest", "discipline")]), ("ret", [("paladin", "retribution")]), ("prot", [("warrior", "protection"), ("paladin", "protection")]),
                     ("affli", [("warlock", "affliction")]), ("demo", [("warlock", "demonology")]), ("destro", [("warlock", "destruction")]),
                     ("sub", [("rogue", "subtlety")]), ("assa", [("rogue", "assassination")])):
        out.setdefault(w, []).extend(specs)
    return out


def _close(word: str, choices) -> str | None:
    """Gleiches Wort, Anfang (ab 4 Buchstaben) oder kleiner Tippfehler („scharmane“ -> „schamane“)."""
    if word in choices:
        return word
    if len(word) >= 4:
        starts = [c for c in choices if c.startswith(word)]
        if len(starts) == 1:
            return starts[0]
    if len(word) >= 5:
        hit = difflib.get_close_matches(word, list(choices), n=1, cutoff=0.8)
        if hit:
            return hit[0]
    return None


def parse_query(text: str) -> dict:
    """{"cls": Klasse oder "", "spec": Spec oder "", "cat": Zweck oder "", "role": Rolle oder "", "rest": übrige Wörter}."""
    classes, specs = _class_words(), _spec_words()
    out = {"cls": "", "spec": "", "cat": "", "role": "", "rest": [], "sod": False}
    spec_hits: list[list[tuple[str, str]]] = []
    for w in _words(text):
        if w in ("sod", "season", "discovery"):
            out["sod"] = True
            continue
        if w in _STOP:
            continue
        c = _close(w, classes)
        if c and not out["cls"]:
            out["cls"] = classes[c]
            continue
        if w in _CAT_WORDS or (len(w) >= 5 and _close(w, _CAT_WORDS)):
            out["cat"] = out["cat"] or _CAT_WORDS[_close(w, _CAT_WORDS)]
            continue
        if w in _ROLE_WORDS or (len(w) >= 5 and _close(w, _ROLE_WORDS)):
            out["role"] = out["role"] or _ROLE_WORDS[_close(w, _ROLE_WORDS)]
            continue
        s = specs.get(w) or (specs[_close(w, specs)] if len(w) >= 5 and _close(w, specs) else None)
        if s:
            spec_hits.append(s)
            continue
        out["rest"].append(w)
    for hit in spec_hits:
        pick = [s for s in hit if not out["cls"] or s[0] == out["cls"]]
        if pick:
            out["cls"] = out["cls"] or pick[0][0]
            out["spec"] = pick[0][1]
            break
    if out["spec"] == "protection" and not out["role"]:
        out["role"] = "tank"
    out["rest"] = " ".join(out["rest"])
    return out


def describe_query(q: dict) -> str:
    """Kurztext, was erkannt wurde („Schamane · Verstärkung · Leveling“)."""
    from .talents import talent_class
    bits = []
    cls = talent_class(q["cls"]) if q.get("cls") else None
    if cls:
        bits.append(cls.name)
        if q.get("spec"):
            bits.append(spec_name(q["cls"], q["spec"]))
    if q.get("role"):
        bits.append(tr(ROLES[q["role"]]))
    if q.get("cat"):
        bits.append(tr(CATEGORY_NAMES[q["cat"]]))
    return " · ".join(bits)


def spec_name(cls: str, spec: str) -> str:
    for slug, _cid, _de, _en, _col, _icon, trees, _eds in CLASSES:
        if slug == cls:
            for _tid, de, en, _ic in trees:
                if spec_slug(en) == spec:
                    return de if cur_lang() == "de" else en
    return spec.replace("-", " ").title()


# --------------------------------------------------------------------------- #
# Guide-Adressen erkennen und einordnen
# --------------------------------------------------------------------------- #
def guide_path(url: str, edition: str) -> str:
    """„classes/shaman/enhancement/dps-leveling-tips“ – oder "", wenn die Adresse kein Guide dieser Ausgabe ist."""
    url = html.unescape((url or "").strip()).replace("\\/", "/").split("#", 1)[0].split("?", 1)[0]
    m = _GUIDE_RX.match(url)
    if not m:
        return ""
    ed, lang = (m.group("ed") or "").lower(), (m.group("lang") or "").lower()
    if ed in _LANGS and not lang:                         # /de/guide/… (Retail auf Deutsch)
        ed, lang = "", ed
    if ed and ed != edition:
        return ""
    if not ed and url.lower().startswith(("http", "/")) and edition:
        return ""                                         # absolute Adresse ohne Ausgabe: Retail
    return m.group("rest").strip("/").lower()


def classify(path: str, title: str = "") -> dict:
    """Klasse, Spec, Zweck und Rolle aus der Guide-Adresse (und dem Titel)."""
    parts = path.split("/")
    variant = ""
    cls = spec = ""
    topic = parts[-1]
    if "classes" in parts:
        i = parts.index("classes")
        variant = "/".join(parts[:i])
        cls = parts[i + 1] if len(parts) > i + 1 else ""
        rest = parts[i + 2:]
        if len(rest) >= 2:
            spec = rest[0]
        topic = rest[-1] if rest else ""
    words = set(re.split(r"[^a-z0-9]+", f"{topic} {_fold(title)}"))
    t = topic.lower()
    if "leveling" in t or "levelling" in t or "leveling" in words:
        cat = "leveling"
    elif "pvp" in t or "pvp" in words:
        cat = "pvp"
    elif re.search(r"\bbis\b|best-in-slot|gear|equipment|enchant|consumable|-bis-|bis-", t):
        cat = "gear"
    elif re.search(r"talent|builds?\b|runes?\b", t):
        cat = "talents"
    elif re.search(r"rotation|cooldown|macro|addon|stat|abilit|playstyle|weakaura|opener", t):
        cat = "play"
    elif re.search(r"pve|dungeon|raid|tank|healer|heal|dps", t):
        cat = "pve"
    elif re.search(r"overview|changes|beginner|starter|basics|class-guide|intro", t) or not topic:
        cat = "overview"
    else:
        cat = "other"
    role = ""
    for key, rx in (("tank", r"\btank"), ("healer", r"\bheal"), ("dps", r"\bdps\b|\bdamage\b")):
        if re.search(rx, t.replace("-", " ")):
            role = key
            break
    return {"cls": cls, "spec": spec, "cat": cat, "role": role, "variant": variant, "topic": topic}


def nice_title(path: str) -> str:
    """Lesbarer Titel aus der Adresse, wenn die Quelle keinen hat („Enhancement – Dps Leveling Tips“)."""
    parts = path.split("/")
    if "classes" in parts:
        parts = parts[parts.index("classes") + 1:]
    bits = [p.replace("-", " ").strip() for p in parts if p]
    if len(bits) >= 2:
        bits = bits[1:]                                   # die Klasse steht schon daneben
    fixed = {"dps": "DPS", "pve": "PvE", "pvp": "PvP", "bis": "BiS", "and": "and", "of": "of", "the": "the", "in": "in"}
    return " – ".join(" ".join(fixed.get(w, w[:1].upper() + w[1:]) for w in bit.split()) for bit in bits)


def _clean_title(text: str) -> str:
    t = re.sub(r"\s+[-–|]\s+(Wowhead|WoW Forever|Classic|World of Warcraft)\b.*$", "", text or "", flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"\[/?[a-z][^\]]*\]", " ", t)
    t = re.sub(r"\s+", " ", html.unescape(t)).strip(" -–|·")
    return t if len(t) >= 3 and not re.fullmatch(r"(?i)(guide|guides|mehr|more|hier|here|read more|weiterlesen)", t) else ""


# --------------------------------------------------------------------------- #
# Guides aus Wowhead-Seiten lesen (mehrere Formen, alle optional)
# --------------------------------------------------------------------------- #
def _listview_rows(page: str):
    for m in re.finditer(r"new Listview\(\{", page):
        start = m.end() - 1
        head = page[start:start + 6000]
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
        for r in rows if isinstance(rows, list) else []:
            if isinstance(r, dict):
                yield r


def extract_guides(page: str, edition: str) -> list[dict]:
    """Alle Guides, auf die eine Seite verweist: [{"path", "title", "author", "updated", "rating"}]."""
    page = page or ""
    flat = page.replace("\\/", "/")
    found: dict[str, dict] = {}
    rank: dict[str, int] = {}

    def add(url, title="", trust=2, **extra):
        """trust: wie sicher der Titel zum Link gehört (3 = gleiche Zeile/Marke, 1 = nur in der Nähe)."""
        path = guide_path(url, edition)
        if not path:
            return
        e = found.setdefault(path, {"path": path, "title": "", "author": "", "updated": "", "rating": 0.0})
        t = _clean_title(title)
        if t and (trust > rank.get(path, 0) or (trust == rank.get(path, 0) and len(t) > len(e["title"]))):
            e["title"], rank[path] = t, trust
        for k, v in extra.items():
            if v and not e.get(k):
                e[k] = v

    # 1. Listen der Seite (Wowhead-Übersichten und -Suche): Zeilen mit Guide-Adresse
    for r in _listview_rows(page):
        url = r.get("url") or r.get("link") or r.get("href") or ""
        if not isinstance(url, str) or "guide" not in url:
            continue
        title = r.get("name") or r.get("title") or r.get("displayName") or ""
        author = r.get("author") or r.get("authorName") or ""
        rating = r.get("rating")
        add(url, str(title), 3, author=str(author) if isinstance(author, str) else "",
            updated=str(r.get("lastEdit") or r.get("date") or "")[:10],
            rating=float(rating) if isinstance(rating, (int, float)) else 0.0)
    # 2. JSON-Objekte irgendwo in der Seite: "url":"/forever/guide/…" mit "name"/"title" in der Nähe
    for m in re.finditer(r'"(?:url|link|href)"\s*:\s*"([^"]*guide/[^"]+)"', flat):
        near = flat[max(0, m.start() - 400):m.end() + 400]
        tm = re.search(r'"(?:name|title)"\s*:\s*"((?:[^"\\]|\\.){3,200})"', near)
        title = ""
        if tm:
            try:
                title = json.loads(f'"{tm.group(1)}"')
            except ValueError:
                title = tm.group(1)
        add(m.group(1), title, 1)
    # 3. Links im HTML
    for m in re.finditer(r'<a\b[^>]*?href="([^"]*guide/[^"]+)"[^>]*>(.*?)</a>', flat, re.S | re.I):
        add(m.group(1), m.group(2), 2)
    # 4. Wowhead-Markup (Navigation und Links in Guides): [nav-item=guide/…]Titel[/nav-item], [url=…]Titel[/url]
    for m in re.finditer(r"\[(nav-item|url)=(?:\"|&quot;)?([^\s\]\"&]*guide/[^\s\]\"&]+)[^\]]*\](.*?)\[/\1\]", flat, re.S | re.I):
        add(m.group(2), m.group(3), 3)
    return list(found.values())


def suggestion_guides(data, edition: str) -> list[dict]:
    """Guides aus den Wowhead-Suchvorschlägen (JSON), falls Wowhead dort welche liefert."""
    out = []
    for r in (data.get("results") or []) if isinstance(data, dict) else []:
        if not isinstance(r, dict):
            continue
        url = r.get("url") or r.get("link") or ""
        if isinstance(url, str) and "guide/" in url:
            path = guide_path(url, edition)
            if path:
                out.append({"path": path, "title": _clean_title(str(r.get("name") or "")), "author": "", "updated": "", "rating": 0.0})
    return out


# --------------------------------------------------------------------------- #
# Suchen
# --------------------------------------------------------------------------- #
_CACHE_LOCK = threading.Lock()


def _cache_file(edition: str, lang: str):
    return config_dir() / "wowhead" / f"guide-index-{edition or 'retail'}-{lang or 'en'}.json"


def _cache_get(edition: str, lang: str, key: str, max_age: float | None):
    try:
        data = json.loads(_cache_file(edition, lang).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    e = data.get(key) if isinstance(data, dict) else None
    if not isinstance(e, dict) or not isinstance(e.get("guides"), list):
        return None
    if max_age is not None and time.time() - float(e.get("at") or 0) > max_age:
        return None
    return e


def _cache_put(edition: str, lang: str, key: str, guides: list[dict]) -> None:
    with _CACHE_LOCK:
        f = _cache_file(edition, lang)
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except (OSError, ValueError):
            data = {}
        data[key] = {"at": time.time(), "guides": guides}
        f.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(f, json.dumps(data, ensure_ascii=False))


def source_urls(q: dict, text: str, edition: str, lang: str) -> list[str]:
    """Die Wowhead-Seiten, die nach Guides durchsucht werden (in dieser Reihenfolge)."""
    base = wowhead_base(edition, lang)
    urls = []
    if q.get("cls"):
        en = next((row[3] for row in CLASSES if row[0] == q["cls"]), q["cls"])
        urls.append(f"{base}/guides/classes/{q['cls']}")
        urls.append(f"{base}/search?q={urllib.parse.quote(en)}")
        urls.append(f"{base}/search/suggestions-template?q={urllib.parse.quote(en)}")
    elif text.strip():
        urls.append(f"{base}/search?q={urllib.parse.quote(text.strip())}")
        urls.append(f"{base}/search/suggestions-template?q={urllib.parse.quote(text.strip())}")
    return urls


def _seed_paths(q: dict) -> list[str]:
    """Bekannte Guide-Adressen von Wowhead, falls die Übersichten nichts liefern – ihre Navigation führt zu den anderen."""
    cls = q.get("cls")
    if not cls:
        return []
    out = [f"classes/{cls}/leveling-tips", f"classes/{cls}/overview"]
    row = next((r for r in CLASSES if r[0] == cls), None)
    for _tid, _de, en, _ic in (row[6] if row else []):
        out.append(f"classes/{cls}/{spec_slug(en)}/dps-leveling-tips")
    return out


def find_guides(text: str, edition: str, lang: str = "", fetch=None, refresh: bool = False) -> dict:
    """Guides zu einer Anfrage. Ergebnis: {"query", "guides": [...], "offline": bool, "sources": int}.

    Jeder Guide: {"path", "url", "title", "cls", "spec", "cat", "role", "variant", "author", "updated", "rating"}."""
    fetch = fetch or (lambda url: wowhead_text(url, timeout=FETCH_TIMEOUT))
    lang = lang or cur_lang()
    q = parse_query(text)
    key = q["cls"] or "q:" + " ".join(_words(text))
    cached = None if refresh else _cache_get(edition, lang, key, CACHE_HOURS * 3600)
    offline = False
    if cached:
        raw = cached["guides"]
        n_sources = -1
    else:
        raw, n_sources, errors = [], 0, []
        urls = source_urls(q, text, edition, lang)

        def get(url):
            try:
                return url, fetch(url), None
            except (urllib.error.URLError, OSError, TimeoutError, ValueError) as e:
                return url, None, e
        with ThreadPoolExecutor(max_workers=4) as pool:
            pages = list(pool.map(get, urls))
        for url, page, err in pages:
            if err is not None:
                log.info("Build-Suche: %s -> %s", url, err)
                if not (isinstance(err, urllib.error.HTTPError) and err.code in (404, 410)):
                    errors.append(err)
                continue
            n_sources += 1
            before = len(raw)
            if "suggestions-template" in url:
                try:
                    raw += suggestion_guides(json.loads(page), edition)
                except ValueError:
                    pass
            else:
                raw += extract_guides(page, edition)
            log.info("Build-Suche: %s -> %d Zeichen, %d Guides", url, len(page or ""), len(raw) - before)
        if q["cls"]:
            raw = [g for g in raw if classify(g["path"])["cls"] == q["cls"]] or raw
        # wenig gefunden: Guides selbst (ihre Navigation) nach weiteren durchsuchen
        known = {g["path"] for g in raw}
        crawl = [g["path"] for g in raw if classify(g["path"])["cls"] == q["cls"]] if q["cls"] else []
        if len(known) < 6:
            crawl = crawl[:CRAWL_PAGES] + [p for p in _seed_paths(q) if p not in crawl][:max(0, CRAWL_PAGES + 2 - len(crawl))]
            base = wowhead_base(edition, lang)
            with ThreadPoolExecutor(max_workers=4) as pool:
                pages = list(pool.map(get, [f"{base}/guide/{p}" for p in crawl]))
            for url, page, err in pages:
                if err is not None:
                    log.info("Build-Suche: %s -> %s", url, err)
                    if not (isinstance(err, urllib.error.HTTPError) and err.code in (404, 410)):
                        errors.append(err)
                    continue
                n_sources += 1
                log.info("Build-Suche: %s -> %d Zeichen", url, len(page or ""))
                path = guide_path(url, edition)
                own = re.search(r'<meta\s+property="og:title"\s+content="([^"]*)"', page or "")
                if path:
                    raw.append({"path": path, "title": _clean_title(own.group(1)) if own else "", "author": "", "updated": "",
                                "rating": 0.0})
                raw += extract_guides(page, edition)
        if n_sources == 0 and errors:
            stale = _cache_get(edition, lang, key, None)
            if stale:
                raw, offline = stale["guides"], True
            else:
                raise errors[0]
    # zusammenführen, einordnen, filtern
    merged: dict[str, dict] = {}
    for g in raw:
        e = merged.setdefault(g["path"], dict(g))
        if len(g.get("title") or "") > len(e.get("title") or ""):
            e["title"] = g["title"]
        for k in ("author", "updated", "rating"):
            if g.get(k) and not e.get(k):
                e[k] = g[k]
    guides = []
    for g in merged.values():
        c = classify(g["path"], g.get("title", ""))
        if q["cls"] and c["cls"] != q["cls"]:
            continue
        if c["variant"] and "season-of-discovery" in c["variant"] and not q["sod"]:
            continue
        guides.append({**g, **c, "title": g.get("title") or nice_title(g["path"]),
                       "url": f"{wowhead_base(edition, lang)}/guide/{g['path']}"})
    if not cached and not offline and guides and q["cls"]:
        _cache_put(edition, lang, key, [{k: g[k] for k in ("path", "title", "author", "updated", "rating")} for g in guides])
    if not q["cls"] and q["rest"]:
        words = q["rest"].split()
        guides = [g for g in guides if all(w in _fold(g["title"] + " " + g["path"]) for w in words)] or guides
    order = [k for k, _ in CATEGORIES]
    guides.sort(key=lambda g: (order.index(g["cat"]), g["spec"] or "", -float(g.get("rating") or 0), g["title"].lower()))
    return {"query": q, "guides": guides, "offline": offline, "sources": n_sources}


def filter_guides(guides: list[dict], q: dict) -> list[dict]:
    """Was zur Anfrage passt: Spec, Zweck und Rolle, wenn sie genannt sind (Guides ohne Spec gelten für alle)."""
    out = guides
    if q.get("spec"):
        out = [g for g in out if not g["spec"] or g["spec"] == q["spec"]]
    if q.get("cat"):
        out = [g for g in out if g["cat"] == q["cat"] or (q["cat"] == "talents" and g["cat"] in ("leveling", "pve", "pvp"))]
    if q.get("role"):
        out = [g for g in out if not g["role"] or g["role"] == q["role"]]
    return out


# --------------------------------------------------------------------------- #
# Builds im Guide mit ihrer Überschrift
# --------------------------------------------------------------------------- #
_HEAD_RX = re.compile(r"\[(h2|h3|h4)([^\]]*)\](.*?)\[/\1\]|\[tab\s+name=\"([^\"]+)\"", re.S | re.I)


def titled_builds(guide: dict) -> list[dict]:
    """Talent-Builds eines Guides, jeder mit der letzten Überschrift oder dem Reiter davor („Level 10–20“)."""
    markup = guide.get("markup") or ""
    heads = []
    for m in _HEAD_RX.finditer(markup):
        text = m.group(4) or m.group(3) or ""
        text = re.sub(r"\[/?[a-z][^\]]*\]", "", text)
        text = re.sub(r"\s+", " ", html.unescape(text)).strip()
        if text:
            heads.append((m.start(), text, "tab" if m.group(4) else m.group(1).lower()))
    out, seen = [], set()
    for m in re.finditer(r"\[talent=([^\s\]]+)", markup):
        link = m.group(1)
        p = parse_build_link(link)
        if not p or link in seen:
            continue
        seen.add(link)
        before = [h for h in heads if h[0] < m.start()]
        label = ""
        if before:
            last = before[-1]
            label = last[1]
            if last[2] == "tab":                            # Reiter unter einer Überschrift: „Überschrift – Reiter“
                head = next((h for h in reversed(before) if h[2] != "tab"), None)
                if head and head[1] != last[1]:
                    label = f"{head[1]} – {last[1]}"
        p["edition"] = p["edition"] or guide.get("edition") or ""
        p.update(link=link, label=label)
        out.append(p)
    return out


def log_result(text: str, res: dict) -> None:
    log.info("Build-Suche „%s“: %d Guides (%s Quellen%s)", text, len(res["guides"]), res["sources"],
             ", offline" if res["offline"] else "")
