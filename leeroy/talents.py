"""Talentplaner: Talentbäume von Wowhead, Builds prüfen, Wowhead-Links lesen und schreiben.

Die Bäume kommen aus der Datendatei des Wowhead-Talentrechners (dieselbe, die wowhead.com/…/talent-calc lädt) –
damit stimmen sie auch für WoW Forever mit seinen geänderten Talenten. Ein Build ist mit Wowhead austauschbar:
der Link …/talent-calc/shaman/<Punkte>/<Reihenfolge> lässt sich einlesen und wieder erzeugen.
"""
from __future__ import annotations

import html
import json
import re
import time
from pathlib import Path

from .config import config_dir, log, write_text_atomic
from .i18n import cur_lang
from .wowhead import wowhead_base, wowhead_text

# Ausgaben mit klassischen Talentbäumen: Adressteil bei Wowhead -> (Anzeigename, Höchststufe)
TALENT_EDITIONS = {"forever": ("WoW Forever", 60), "classic": ("Classic (Era / Anniversary)", 60),
                   "tbc": ("Burning Crusade Classic", 70), "wotlk": ("Wrath of the Lich King Classic", 80)}
FIRST_TALENT_LEVEL = 10
TALENT_CACHE_DAYS = 7

# Klassen in der Reihenfolge des Wowhead-Talentrechners. Die Reihenfolge der Bäume bestimmt den Link.
# (Adressteil, Klassen-ID, Deutsch, Englisch, Farbe, Icon, [(Baum-ID, Deutsch, Englisch, Icon), …], nur in diesen Ausgaben)
CLASSES = [
    ("warrior", 1, "Krieger", "Warrior", "#c69b6d", "class_warrior",
     [(161, "Waffen", "Arms", "ability_warrior_savageblow"), (164, "Furor", "Fury", "ability_warrior_innerrage"),
      (163, "Schutz", "Protection", "inv_shield_06")], None),
    ("paladin", 2, "Paladin", "Paladin", "#f48cba", "class_paladin",
     [(382, "Heilig", "Holy", "spell_holy_holybolt"), (383, "Schutz", "Protection", "spell_holy_devotionaura"),
      (381, "Vergeltung", "Retribution", "spell_holy_auraoflight")], None),
    ("hunter", 3, "Jäger", "Hunter", "#aad372", "class_hunter",
     [(361, "Tierherrschaft", "Beast Mastery", "ability_hunter_beasttaming"),
      (363, "Treffsicherheit", "Marksmanship", "ability_marksmanship"),
      (362, "Überleben", "Survival", "ability_hunter_swiftstrike")], None),
    ("rogue", 4, "Schurke", "Rogue", "#fff468", "class_rogue",
     [(182, "Meucheln", "Assassination", "ability_rogue_eviscerate"), (181, "Kampf", "Combat", "ability_backstab"),
      (183, "Täuschung", "Subtlety", "ability_stealth")], None),
    ("priest", 5, "Priester", "Priest", "#ffffff", "class_priest",
     [(201, "Disziplin", "Discipline", "spell_holy_wordfortitude"), (202, "Heilig", "Holy", "spell_holy_guardianspirit"),
      (203, "Schatten", "Shadow", "spell_shadow_shadowwordpain")], None),
    ("death-knight", 6, "Todesritter", "Death Knight", "#c41e3a", "class_deathknight",
     [(398, "Blut", "Blood", "spell_deathknight_bloodpresence"), (399, "Frost", "Frost", "spell_deathknight_frostpresence"),
      (400, "Unheilig", "Unholy", "spell_deathknight_unholypresence")], ("wotlk",)),
    ("shaman", 7, "Schamane", "Shaman", "#0070dd", "class_shaman",
     [(261, "Elementar", "Elemental", "spell_nature_lightning"), (263, "Verstärkung", "Enhancement", "spell_nature_lightningshield"),
      (262, "Wiederherstellung", "Restoration", "spell_nature_magicimmunity")], None),
    ("mage", 8, "Magier", "Mage", "#3fc7eb", "class_mage",
     [(81, "Arkan", "Arcane", "spell_holy_magicalsentry"), (41, "Feuer", "Fire", "spell_fire_firebolt02"),
      (61, "Frost", "Frost", "spell_frost_frostbolt02")], None),
    ("warlock", 9, "Hexenmeister", "Warlock", "#8788ee", "class_warlock",
     [(302, "Gebrechen", "Affliction", "spell_shadow_deathcoil"), (303, "Dämonologie", "Demonology", "spell_shadow_metamorphosis"),
      (301, "Zerstörung", "Destruction", "spell_shadow_rainoffire")], None),
    ("druid", 11, "Druide", "Druid", "#ff7c0a", "class_druid",
     [(283, "Gleichgewicht", "Balance", "spell_nature_starfall"), (281, "Wilder Kampf", "Feral Combat", "ability_racial_bearform"),
      (282, "Wiederherstellung", "Restoration", "spell_nature_healingtouch")], None),
]
# Zeichen der Skill-Reihenfolge im Wowhead-Link: klein = ein Punkt, groß = alle Ränge des Talents
ORDER_MIN = "abcdefghjkmnpqrstvwzxyilou468-~!"
ORDER_MAX = "ABCDEFGHJKMNPQRSTVWZXYILOU579_^."


class TalentClass:
    """Eine Klasse mit ihren drei Bäumen (Namen in der Sprache der Oberfläche)."""

    def __init__(self, row):
        self.slug, self.id, de, en, self.color, self.icon, trees, self.editions = row
        self.name = de if cur_lang() == "de" else en
        self.trees = [{"tab": tab, "name": tde if cur_lang() == "de" else ten, "icon": icon} for tab, tde, ten, icon in trees]

    @property
    def tabs(self) -> list[int]:
        return [t["tab"] for t in self.trees]


def talent_classes(edition: str) -> list[TalentClass]:
    return [TalentClass(r) for r in CLASSES if r[7] is None or edition in r[7]]


def talent_class(slug: str) -> TalentClass | None:
    slug = (slug or "").lower().replace("deathknight", "death-knight")
    return next((TalentClass(r) for r in CLASSES if r[0] == slug), None)


def max_talent_points(edition: str) -> int:
    return TALENT_EDITIONS.get(edition, TALENT_EDITIONS["classic"])[1] - (FIRST_TALENT_LEVEL - 1)


# --------------------------------------------------------------------------- #
# Daten von Wowhead
# --------------------------------------------------------------------------- #
def talents_url(edition: str, lang: str = "") -> str:
    lang = lang or cur_lang()
    return f"https://nether.wowhead.com/{edition}/" + ("de/" if lang == "de" else "") + "data/talents-classic"


def _plain(text) -> str:
    """Beschreibung ohne HTML-Reste."""
    text = re.sub(r"<br\s*/?>", "\n", str(text or ""), flags=re.I)
    return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def parse_talent_js(text: str) -> dict:
    """Die Datendatei des Talentrechners (WH.setPageData("wow.talentCalcClassic.<env>.data", {...});) in die Form,
    mit der Leeroyzan arbeitet: je Baum die Talente in Link-Reihenfolge (Zeile, dann Spalte)."""
    m = re.search(r'WH\.setPageData\(\s*"wow\.talentCalcClassic\.([A-Za-z0-9_-]+)\.data"\s*,\s*', text)
    if not m:
        raise ValueError("Keine Talentdaten in der Antwort von Wowhead.")
    raw, _ = json.JSONDecoder().raw_decode(text, m.end())
    if not isinstance(raw, dict) or not isinstance(raw.get("talents"), dict):
        raise ValueError("Unerwartetes Format der Talentdaten.")
    trees: dict[str, list] = {}
    for tab, talents in raw["talents"].items():
        if not isinstance(talents, dict):
            continue
        rows = []
        for t in talents.values():
            ranks = [r for r in (t.get("ranks") or []) if r] or [0]
            desc = t.get("descriptions") or {}
            if isinstance(desc, list):
                desc = {str(i + 1): d for i, d in enumerate(desc)}
            row = int(t.get("row") or 0)
            req_points = t.get("requiredPoints")
            rows.append({"id": t.get("id"), "row": row, "col": int(t.get("col") or 0), "icon": str(t.get("icon") or ""),
                         "name": str(t.get("name") or t.get("nameEnus") or "?"), "name_en": str(t.get("nameEnus") or t.get("name") or ""),
                         "max": len(ranks), "spells": ranks,
                         "req": [[r.get("id"), int(r.get("qty") or 1)] for r in (t.get("requires") or []) if isinstance(r, dict)],
                         "req_points": int(req_points) if req_points is not None else 5 * row,
                         "desc": [_plain(desc.get(str(i + 1))) for i in range(len(ranks))]})
        rows.sort(key=lambda x: (x["row"], x["col"]))
        trees[str(tab)] = rows
    layouts = raw.get("hashLayouts") if isinstance(raw.get("hashLayouts"), dict) else {}
    return {"env": m.group(1), "hash_version": str(raw.get("hashVersion") or ""), "trees": trees, "layouts": layouts}


def _talent_cache(edition: str, lang: str) -> Path:
    return config_dir() / "wowhead" / f"talents-{edition}-{lang}.json"


def load_talents(edition: str, refresh: bool = False, lang: str = "") -> dict:
    """Talentdaten einer Ausgabe – aus dem Zwischenspeicher, sonst (oder wenn älter als eine Woche) von Wowhead.
    Ist Wowhead nicht erreichbar, gilt der alte Stand weiter."""
    lang = lang or cur_lang()
    path = _talent_cache(edition, lang)
    cached = None
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(cached.get("trees"), dict):
            cached = None
    except (OSError, ValueError, AttributeError):
        cached = None
    if cached and not refresh and time.time() - float(cached.get("fetched") or 0) < TALENT_CACHE_DAYS * 86400:
        return cached
    try:
        data = parse_talent_js(wowhead_text(talents_url(edition, lang)))
    except Exception as e:  # noqa – Netz, Format: mit dem alten Stand weiter
        if cached:
            log.warning("Talentdaten %s nicht aktualisiert: %s", edition, e)
            cached["stale"] = True
            return cached
        raise
    data.update(edition=edition, lang=lang, fetched=time.time())
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(path, json.dumps(data, ensure_ascii=False))
    except OSError as e:
        log.warning("Talentdaten nicht gespeichert: %s", e)
    return data


# --------------------------------------------------------------------------- #
# Wowhead-Link
# --------------------------------------------------------------------------- #
def parse_build_link(text: str) -> dict | None:
    """Liest einen Talentrechner-Link (oder das Kürzel aus einem Guide, „shaman/<Punkte>/<Reihenfolge>“).
    Ergebnis: {"edition", "cls", "hash", "order"} – edition ist leer, wenn sie nicht im Link steht."""
    text = (text or "").strip().strip("<>\"'")
    text = text.split("#", 1)[0].split("?", 1)[0]
    m = re.search(r"wowhead\.com/(.*?)talent-calc/([^\s]*)", text, re.I)
    edition = ""
    if m:
        parts = [p for p in m.group(1).split("/") if p]
        edition = next((p.lower() for p in parts if p.lower() in TALENT_EDITIONS), "")
        if not edition:
            edition = "classic" if parts and parts[0].lower() in ("classic", "era") else ""
        rest = m.group(2)
    elif re.match(r"^[a-z-]+(/[^\s]*)?$", text, re.I):
        rest = text
    else:
        return None
    seg = [s for s in rest.split("/")]
    cls = talent_class(seg[0])
    if not cls:
        return None
    return {"edition": edition, "cls": cls.slug, "hash": seg[1] if len(seg) > 1 else "", "order": seg[2] if len(seg) > 2 else ""}


class Build:
    """Verteilte Talentpunkte einer Klasse samt der Reihenfolge, in der sie gesetzt wurden."""

    def __init__(self, data: dict, cls: str, edition: str = ""):
        self.data = data
        self.edition = edition or data.get("edition") or "classic"
        self.cls = talent_class(cls)
        if not self.cls:
            raise ValueError(f"Unbekannte Klasse: {cls}")
        self.trees: list[list[dict]] = [data["trees"].get(str(tab), []) for tab in self.cls.tabs]
        self.by_id: dict = {t["id"]: (ti, i, t) for ti, tree in enumerate(self.trees) for i, t in enumerate(tree)}
        self.points: dict = {}                  # Talent-ID -> Rang
        self.order: list = []                   # Talent-IDs in Skill-Reihenfolge (je Punkt ein Eintrag)
        self.extras: list[str] = []             # Zusätze aus dem Link (_t0, _r2 …), unverändert weitergereicht
        self.notes: list[str] = []              # Hinweise vom Einlesen (umbenannte, entfernte Talente)

    # ----- Stand ------------------------------------------------------------- #
    def rank(self, tid) -> int:
        return self.points.get(tid, 0)

    def tree_points(self, ti: int, below_row: int | None = None, points: dict | None = None) -> int:
        points = self.points if points is None else points
        return sum(points.get(t["id"], 0) for t in self.trees[ti] if below_row is None or t["row"] < below_row)

    @property
    def spent(self) -> int:
        return sum(self.points.values())

    @property
    def max_points(self) -> int:
        return max_talent_points(self.edition)

    @property
    def talented(self) -> int:
        """Rang der Forever-Eigenschaft „Talented“: so viele Stufen früher gibt es den ersten Talentpunkt."""
        for x in self.extras:
            m = re.fullmatch(r"t([0-5])", x)
            if m and self.edition == "forever":
                return int(m.group(1))
        return 0

    def level_for(self, n_points: int) -> int:
        """Stufe, ab der so viele Punkte verfügbar sind."""
        return 0 if n_points <= 0 else max(1, n_points + FIRST_TALENT_LEVEL - 1 - self.talented)

    @property
    def required_level(self) -> int:
        return self.level_for(self.spent)

    def summary(self) -> str:
        return "/".join(str(self.tree_points(i)) for i in range(len(self.trees)))

    # ----- Regeln ------------------------------------------------------------ #
    def _legal(self, points: dict) -> bool:
        """Jedes Talent mit Punkten erfüllt seine Voraussetzungen (Punkte in den Zeilen darüber, Vorgänger-Talent)."""
        for ti, tree in enumerate(self.trees):
            for t in tree:
                if points.get(t["id"], 0) <= 0:
                    continue
                if self.tree_points(ti, t["row"], points) < t["req_points"]:
                    return False
                if any(points.get(rid, 0) < qty for rid, qty in t["req"]):
                    return False
        return True

    def why_not(self, tid) -> str:
        """Grund, warum hier gerade kein Punkt gesetzt werden kann: "max", "points", "tree", "requires" – oder ""."""
        if tid not in self.by_id:
            return "unknown"
        ti, _, t = self.by_id[tid]
        if self.rank(tid) >= t["max"]:
            return "max"
        if self.spent >= self.max_points:
            return "points"
        if self.tree_points(ti) < t["req_points"]:
            return "tree"
        if any(self.rank(rid) < qty for rid, qty in t["req"]):
            return "requires"
        return ""

    def can_add(self, tid) -> bool:
        return not self.why_not(tid)

    def add(self, tid, full: bool = False) -> int:
        """Setzt einen Punkt (full: so viele wie möglich). Rückgabe: gesetzte Punkte."""
        n = 0
        while self.can_add(tid):
            self.points[tid] = self.rank(tid) + 1
            self.order.append(tid)
            n += 1
            if not full:
                break
        return n

    def can_remove(self, tid) -> bool:
        if self.rank(tid) <= 0:
            return False
        points = dict(self.points)
        points[tid] -= 1
        return self._legal(points)

    def remove(self, tid, full: bool = False) -> int:
        n = 0
        while self.can_remove(tid):
            self.points[tid] -= 1
            if not self.points[tid]:
                del self.points[tid]
            for i in range(len(self.order) - 1, -1, -1):     # den zuletzt gesetzten Punkt dieses Talents
                if self.order[i] == tid:
                    del self.order[i]
                    break
            n += 1
            if not full:
                break
        if n and not self._order_legal(self.order):
            self.order = self._default_order()
        return n

    def reset(self, ti: int | None = None) -> None:
        keep = {} if ti is None else {tid: r for tid, r in self.points.items() if self.by_id[tid][0] != ti}
        self.points = keep
        self.order = [tid for tid in self.order if tid in keep]
        if not self._order_legal(self.order):
            self.order = self._default_order()

    # ----- Reihenfolge ------------------------------------------------------- #
    def _order_legal(self, order: list) -> bool:
        """Die Reihenfolge ergibt genau die verteilten Punkte, und jeder Schritt war zu seiner Zeit erlaubt."""
        have: dict = {}
        for tid in order:
            if tid not in self.by_id:
                return False
            ti, _, t = self.by_id[tid]
            if have.get(tid, 0) >= t["max"] or self.tree_points(ti, t["row"], have) < t["req_points"] \
                    or any(have.get(rid, 0) < qty for rid, qty in t["req"]):
                return False
            have[tid] = have.get(tid, 0) + 1
        return have == self.points

    def _default_order(self) -> list:
        """Ohne bekannte Reihenfolge: der Baum mit den meisten Punkten zuerst, darin von oben nach unten."""
        order, have = [], {}
        for ti in sorted(range(len(self.trees)), key=lambda i: -self.tree_points(i)):
            progress = True
            while progress:
                progress = False
                for t in self.trees[ti]:
                    tid = t["id"]
                    while have.get(tid, 0) < self.points.get(tid, 0) \
                            and self.tree_points(ti, t["row"], have) >= t["req_points"] \
                            and all(have.get(rid, 0) >= qty for rid, qty in t["req"]):
                        have[tid] = have.get(tid, 0) + 1
                        order.append(tid)
                        progress = True
        return order

    def steps(self) -> list[dict]:
        """Skill-Reihenfolge zum Nachlesen: je Punkt Stufe, Talent und Rang."""
        out, have = [], {}
        for n, tid in enumerate(self.order, 1):
            ti, _, t = self.by_id[tid]
            have[tid] = have.get(tid, 0) + 1
            out.append({"level": self.level_for(n), "id": tid, "tree": ti, "name": t["name"], "rank": have[tid], "max": t["max"]})
        return out

    # ----- Link schreiben ---------------------------------------------------- #
    def hash(self) -> str:
        parts = ["".join(str(self.rank(t["id"])) for t in tree).rstrip("0") for tree in self.trees]
        points = "-".join(parts).rstrip("-")
        if not points and not self.extras:
            return ""
        return (self.data.get("hash_version") or "") + points + "".join("_" + x for x in self.extras)

    def order_hash(self) -> str:
        out, last = "", None
        for tid in self.order:
            ti, idx, t = self.by_id[tid]
            if idx >= len(ORDER_MIN):
                return ""
            if ti != last:
                out += str(ti)
                last = ti
            ch = ORDER_MIN[idx]
            out += ch
            if t["max"] > 1 and out.endswith(ch * t["max"]):
                out = out[:-t["max"]] + ORDER_MAX[idx]
        return out

    def url(self, lang: str = "") -> str:
        url = f"{wowhead_base(self.edition, lang)}/talent-calc/{self.cls.slug}"
        h = self.hash()
        if h:
            url += "/" + h
            o = self.order_hash()
            if o:
                url += "/" + o
        return url

    def link(self) -> str:
        """Kurzform zum Speichern: Klasse/Punkte/Reihenfolge."""
        return "/".join(x for x in (self.cls.slug, self.hash(), self.order_hash() if self.hash() else "") if x)

    # ----- Link lesen -------------------------------------------------------- #
    def load(self, hash_: str, order: str = "") -> "Build":
        """Übernimmt Punkte (und Reihenfolge) aus einem Wowhead-Link. Passt etwas nicht mehr zu den aktuellen
        Bäumen, wird es weggelassen und in notes vermerkt – nie ein Fehler."""
        self.points, self.order, self.extras, self.notes = {}, [], [], []
        hash_ = (hash_ or "").strip()
        version = self.data.get("hash_version") or ""
        points_part, *extras = hash_.split("_")
        self.extras = [x for x in extras if re.fullmatch(r"[a-z]\d{1,3}", x)]
        legacy_key = ""
        if version and points_part.startswith(version):
            points_part = points_part[len(version):]
        elif points_part and not re.match(r"^[0-9-]", points_part):
            legacy_key = next((k for k in sorted(self.data.get("layouts") or {}, key=len, reverse=True)
                               if points_part.startswith(k) and re.match(r"^[0-9-]*$", points_part[len(k):])), "")
            if not legacy_key:
                self.notes.append("version")
                return self
            points_part = points_part[len(legacy_key):]
        digits = points_part.split("-")
        if legacy_key:
            self._load_legacy(legacy_key, digits)
            order = ""                           # die Reihenfolge bezog sich auf den alten Baum
        else:
            for ti, tree in enumerate(self.trees):
                for i, ch in enumerate(digits[ti] if ti < len(digits) else ""):
                    if not ch.isdigit():
                        self.notes.append("format")
                        break
                    if i < len(tree) and int(ch):
                        self.points[tree[i]["id"]] = min(int(ch), tree[i]["max"])
                    elif int(ch):
                        self.notes.append("extra")
        self._prune()
        picks = self._read_order(order)
        self.order = picks if picks and self._order_legal(picks) else self._default_order()
        return self

    def _load_legacy(self, key: str, digits: list[str]) -> None:
        """Link aus einer älteren Fassung der Bäume: Talente über ihren englischen Namen (sonst über Position und
        Zauber) in den heutigen Baum übertragen – so macht es auch der Wowhead-Rechner."""
        candidates = self.data["layouts"].get(key) or []
        for layout in candidates if isinstance(candidates, list) else [candidates]:
            picks, ok = [], isinstance(layout, dict)
            for ti, tab in enumerate(self.cls.tabs):
                entries = (layout.get(str(tab)) or []) if ok else []
                d = digits[ti] if ti < len(digits) else ""
                if len(d) > len(entries) or not d.isdigit() and d:
                    ok = False
                    break
                for i, ch in enumerate(d):
                    if int(ch) > entries[i][2]:
                        ok = False
                    elif int(ch):
                        picks.append((ti, entries[i], int(ch)))
            if not ok:
                continue
            for ti, entry, pts in picks:
                row, col, _, spell, name = entry[:5]
                tree = self.trees[ti]
                t = next((x for x in tree if x["name_en"] == name), None) or \
                    next((x for x in tree if x["row"] == row and x["col"] == col and x["spells"][0] == spell), None)
                if not t:
                    self.notes.append("removed:" + str(name))
                    continue
                self.points[t["id"]] = max(self.points.get(t["id"], 0), min(pts, t["max"]))
            self.notes.append("legacy")
            return
        self.notes.append("version")

    def _prune(self) -> None:
        """Nimmt Punkte heraus, die ihre Voraussetzungen nicht (mehr) erfüllen, und alles über dem Punktelimit."""
        changed = True
        while changed:
            changed = False
            for ti, tree in enumerate(self.trees):
                for t in tree:
                    if self.points.get(t["id"], 0) and (
                            self.tree_points(ti, t["row"]) < t["req_points"]
                            or any(self.points.get(rid, 0) < qty for rid, qty in t["req"])):
                        del self.points[t["id"]]
                        self.notes.append("unreachable:" + t["name"])
                        changed = True
        if self.spent > self.max_points:
            self.notes.append("over")
            for ti in range(len(self.trees) - 1, -1, -1):
                for t in reversed(self.trees[ti]):
                    while self.spent > self.max_points and self.can_remove(t["id"]):
                        self.points[t["id"]] -= 1
                        if not self.points[t["id"]]:
                            del self.points[t["id"]]

    def _read_order(self, order: str) -> list:
        picks, ti = [], None
        for ch in order or "":
            if ch.isdigit() and int(ch) < len(self.trees) and ch not in ORDER_MIN and ch not in ORDER_MAX:
                ti = int(ch)
                continue
            if ti is None:
                return []
            idx, full = ORDER_MIN.find(ch), False
            if idx < 0:
                idx, full = ORDER_MAX.find(ch), True
            if idx < 0 or idx >= len(self.trees[ti]):
                return []
            t = self.trees[ti][idx]
            picks.extend([t["id"]] * (t["max"] if full else 1))
        return picks


def build_from_link(data: dict, link: str, edition: str = "") -> Build | None:
    """Build aus einem Link oder Kürzel; None, wenn der Text kein Talentrechner-Link ist."""
    p = parse_build_link(link)
    if not p:
        return None
    return Build(data, p["cls"], edition or p["edition"] or data.get("edition") or "classic").load(p["hash"], p["order"])
