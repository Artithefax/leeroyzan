"""Karte: Zonen und Kontinente, Kartenbilder, Wege und Orte aus Leeroylink, Quest-Ebene aus QuestieDB.

Koordinaten sind überall Prozent der Zonenkarte (0–100), so wie das Spiel, Questie und Wowhead sie angeben.
Das Spiel kennt Karten unter „UiMapIDs“ (z. B. 1429 = Wald von Elwynn), Questie und Wowhead unter
Gebiets-IDs (12 = Wald von Elwynn). Die Zuordnung kommt aus QuestieDB (für WoW Forever mit eigenen Tabellen),
sonst aus einer kleinen Tabelle der klassischen Zonen hier.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
from datetime import datetime
from pathlib import Path

from .config import config_dir, log
from .i18n import tr

# --------------------------------------------------------------------------- #
# Zonen
# --------------------------------------------------------------------------- #
KALIMDOR, EASTERN_KINGDOMS = 1414, 1415
WORLD_TYPE, CONTINENT_TYPE, ZONE_TYPE, DUNGEON_TYPE = 1, 2, 3, 4
# UiMapID -> (Gebiets-ID, Kontinent, englischer Name) der klassischen Zonen – nur Ersatz, wenn QuestieDB und
# das Kartenverzeichnis von Leeroylink fehlen.
CLASSIC_ZONES = {
    1411: (14, KALIMDOR, "Durotar"), 1412: (215, KALIMDOR, "Mulgore"), 1413: (17, KALIMDOR, "The Barrens"),
    1438: (141, KALIMDOR, "Teldrassil"), 1439: (148, KALIMDOR, "Darkshore"), 1440: (331, KALIMDOR, "Ashenvale"),
    1441: (400, KALIMDOR, "Thousand Needles"), 1442: (406, KALIMDOR, "Stonetalon Mountains"),
    1443: (405, KALIMDOR, "Desolace"), 1444: (357, KALIMDOR, "Feralas"), 1445: (15, KALIMDOR, "Dustwallow Marsh"),
    1446: (440, KALIMDOR, "Tanaris"), 1447: (16, KALIMDOR, "Azshara"), 1448: (361, KALIMDOR, "Felwood"),
    1449: (490, KALIMDOR, "Un'Goro Crater"), 1450: (493, KALIMDOR, "Moonglade"), 1451: (1377, KALIMDOR, "Silithus"),
    1452: (618, KALIMDOR, "Winterspring"), 1454: (1637, KALIMDOR, "Orgrimmar"), 1456: (1638, KALIMDOR, "Thunder Bluff"),
    1457: (1657, KALIMDOR, "Darnassus"),
    1416: (36, EASTERN_KINGDOMS, "Alterac Mountains"), 1417: (45, EASTERN_KINGDOMS, "Arathi Highlands"),
    1418: (3, EASTERN_KINGDOMS, "Badlands"), 1419: (4, EASTERN_KINGDOMS, "Blasted Lands"),
    1420: (85, EASTERN_KINGDOMS, "Tirisfal Glades"), 1421: (130, EASTERN_KINGDOMS, "Silverpine Forest"),
    1422: (28, EASTERN_KINGDOMS, "Western Plaguelands"), 1423: (139, EASTERN_KINGDOMS, "Eastern Plaguelands"),
    1424: (267, EASTERN_KINGDOMS, "Hillsbrad Foothills"), 1425: (47, EASTERN_KINGDOMS, "The Hinterlands"),
    1426: (1, EASTERN_KINGDOMS, "Dun Morogh"), 1427: (51, EASTERN_KINGDOMS, "Searing Gorge"),
    1428: (46, EASTERN_KINGDOMS, "Burning Steppes"), 1429: (12, EASTERN_KINGDOMS, "Elwynn Forest"),
    1430: (41, EASTERN_KINGDOMS, "Deadwind Pass"), 1431: (10, EASTERN_KINGDOMS, "Duskwood"),
    1432: (38, EASTERN_KINGDOMS, "Loch Modan"), 1433: (44, EASTERN_KINGDOMS, "Redridge Mountains"),
    1434: (33, EASTERN_KINGDOMS, "Stranglethorn Vale"), 1435: (8, EASTERN_KINGDOMS, "Swamp of Sorrows"),
    1436: (40, EASTERN_KINGDOMS, "Westfall"), 1437: (11, EASTERN_KINGDOMS, "Wetlands"),
    1453: (1519, EASTERN_KINGDOMS, "Stormwind City"), 1455: (1537, EASTERN_KINGDOMS, "Ironforge"),
    1458: (1497, EASTERN_KINGDOMS, "Undercity"),
}
CONTINENT_NAMES = {KALIMDOR: "Kalimdor", EASTERN_KINGDOMS: "Östliche Königreiche"}
_ZONE_ROW = re.compile(r"^\s*\[(\d+)\]\s*=\s*(\d+)\s*,\s*(?:--\s*(.*?))?\s*$", re.M)


def _lua_block(text: str, name: str) -> str:
    """Inhalt von „ZoneDB.private.<name> = [[return { … }]]“ – ohne die gleichnamigen …Override-Blöcke."""
    m = re.search(r"\b" + re.escape(name) + r"\s*=\s*\[\[return\s*\{(.*?)\}\]\]", text, re.S)
    return m.group(1) if m else ""


def read_questie_zone_maps(folder: Path, flavor_name: str = "") -> dict:
    """Zuordnung Gebiets-ID <-> UiMapID aus den QuestieDB-Supportdateien (für Forever die eigenen).

    Ergebnis: {"area_to_ui": {area: ui}, "ui_to_area": {ui: area}, "names": {ui: englischer Name}}"""
    out = {"area_to_ui": {}, "ui_to_area": {}, "names": {}}
    base = Path(folder) / "support"
    dirs = ([base / flavor_name / "Zones"] if flavor_name else []) + [base / "Zones"]
    zdir = next((d for d in dirs if (d / "areaIdToUiMapId.lua").is_file()), None)
    if zdir is None:
        return out
    try:
        a2u = (zdir / "areaIdToUiMapId.lua").read_text(encoding="utf-8", errors="replace")
        u2a = (zdir / "uiMapIdToAreaId.lua").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for block in (_lua_block(a2u, "areaIdToUiMapId"), _lua_block(a2u, "areaIdToUiMapIdOverride")):   # Override gewinnt
        for m in _ZONE_ROW.finditer(block):
            area, ui = int(m.group(1)), int(m.group(2))
            if ui:
                out["area_to_ui"][area] = ui
    for block in (_lua_block(u2a, "uiMapIdToAreaIdOverride"), _lua_block(u2a, "uiMapIdToAreaId")):    # direkte Zonen gewinnen
        for m in _ZONE_ROW.finditer(block):
            ui, area = int(m.group(1)), int(m.group(2))
            out["ui_to_area"][ui] = area
            name = (m.group(3) or "").strip()
            if name and "Referenced" not in name and "Synthetic" not in name:
                out["names"][ui] = name
    return out


class ZoneIndex:
    """Alle bekannten Karten: Name, Art, Kontinent, Lage auf dem Kontinent, Gebiets-ID."""

    def __init__(self, link_index: dict | None = None, questie: dict | None = None, learned: dict | None = None):
        link_maps = (link_index or {}).get("maps") or {}
        questie = questie or {"area_to_ui": {}, "ui_to_area": {}, "names": {}}
        learned = learned or {}
        self.area_to_ui: dict[int, int] = {a: ui for ui, (a, _, _) in CLASSIC_ZONES.items()}
        self.area_to_ui.update(questie["area_to_ui"])
        self.ui_to_area: dict[int, int] = {ui: a for ui, (a, _, _) in CLASSIC_ZONES.items()}
        self.ui_to_area.update(questie["ui_to_area"])
        self.maps: dict[int, dict] = {}
        for ui, (area, cont, name) in CLASSIC_ZONES.items():
            self.maps[ui] = {"id": ui, "name": name, "type": ZONE_TYPE, "parent": cont, "on": cont, "rect": None}
        for cid, name in CONTINENT_NAMES.items():
            self.maps[cid] = {"id": cid, "name": tr(name), "type": CONTINENT_TYPE, "parent": 947, "on": 947, "rect": None}
        for ui, name in questie["names"].items():
            if ui in self.maps:
                self.maps[ui]["name"] = name
            elif ui not in (947,) and ui not in CONTINENT_NAMES:
                self.maps[ui] = {"id": ui, "name": name, "type": ZONE_TYPE, "parent": 0, "on": 0, "rect": None}
        for ui, e in link_maps.items():                   # Namen in der Sprache des Spiels, echte Lage
            self.maps[ui] = {"id": ui, **e}
        for ui, e in self.maps.items():
            area = self.ui_to_area.get(ui)
            if ui not in link_maps and area and learned.get(area):
                e["name"] = learned[area]
        self.has_layout = any(e.get("rect") for e in self.maps.values() if e.get("type") == ZONE_TYPE)

    def get(self, ui: int) -> dict | None:
        return self.maps.get(ui)

    def name(self, ui: int) -> str:
        e = self.maps.get(ui)
        return e["name"] if e else tr("Karte {0}", ui)

    def area(self, ui: int) -> int:
        return self.ui_to_area.get(ui, 0)

    def ui_for_area(self, area: int) -> int:
        return self.area_to_ui.get(area, 0)

    def continent_of(self, ui: int) -> int:
        e, guard = self.maps.get(ui), 0
        while e and e.get("type") != CONTINENT_TYPE and guard < 6:
            nxt = e.get("on") or e.get("parent")
            e, guard = self.maps.get(nxt), guard + 1
        return e["id"] if e and e.get("type") == CONTINENT_TYPE else 0

    def continents(self) -> list[dict]:
        out = [e for e in self.maps.values() if e.get("type") == CONTINENT_TYPE and self.zones_on(e["id"])]
        return sorted(out, key=lambda e: (e["id"] not in CONTINENT_NAMES, e["name"].lower()))

    def zones_on(self, continent: int) -> list[dict]:
        out = [e for e in self.maps.values() if e.get("type") == ZONE_TYPE and self.continent_of(e["id"]) == continent]
        return sorted(out, key=lambda e: e["name"].lower())

    def is_continent(self, ui: int) -> bool:
        e = self.maps.get(ui)
        return bool(e and e.get("type") == CONTINENT_TYPE)


# --------------------------------------------------------------------------- #
# Kartenbilder (von Wowhead, einmal geladen und im Datenordner)
# --------------------------------------------------------------------------- #
# Ausgaben, deren Karten wir bei Wowhead probieren – der Reihe nach. Forever hat geänderte Karten (Mulgore,
# Östliche Pestländer, Rotkammgebirge, Sturmwind); fehlen eigene, passen die klassischen für alle übrigen Zonen.
MAP_EDITIONS = {"_forever_": ("forever", "classic"), "_classic_era_": ("classic",), "_anniversary_": ("classic",),
                "_classic_era_ptr_": ("classic",), "_classic_": ("classic",), "_retail_": ("",)}
MAP_IMAGE_BASE = "https://wow.zamimg.com/images/wow/"
MAP_SIZES = ("zoom", "original")
MAP_MISS_DAYS = 7
DEFAULT_MAP_SIZE = (1002, 668)          # Seitenverhältnis der Zonenkarten im Spiel
_MISS_LOCK = threading.Lock()


def map_image_urls(flavor: str, area: int) -> list[str]:
    out = []
    for ed in MAP_EDITIONS.get(flavor, ("classic",)):
        for size in MAP_SIZES:
            out.append(f"{MAP_IMAGE_BASE}{ed + '/' if ed else ''}maps/enus/{size}/{int(area)}.jpg")
    return out


def _miss_file() -> Path:
    return config_dir() / "wowhead" / "maps-missing.json"


def _misses() -> dict:
    try:
        return json.loads(_miss_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _note_miss(url: str) -> None:
    with _MISS_LOCK:
        data = _misses()
        data[url] = int(time.time())
        f = _miss_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(data, indent=0), encoding="utf-8")


def map_image(flavor: str, area: int, fetch: bool = True) -> tuple[Path | None, str]:
    """PNG der Zonenkarte und die Adresse, von der sie stammt. (None, Grund), wenn es keine gibt.

    Grund: "" (gefunden), "offline", "missing" (Wowhead hat keine), "noconvert" (kein Bildwandler)."""
    from . import images
    if not area:
        return None, "missing"
    urls = map_image_urls(flavor, area)
    for url in urls:                                  # schon da?
        p = images.image_path(url)
        if p.is_file() and p.stat().st_size > 0:
            return p, url
    if not fetch:
        return None, "missing"
    if not images.can_convert():
        return None, "noconvert"
    misses, now = _misses(), time.time()
    reason = "missing"
    for url in urls:
        if now - misses.get(url, 0) < MAP_MISS_DAYS * 86400:
            continue
        try:
            raw = images._download(url)
        except urllib.error.HTTPError as e:
            if e.code in (403, 404, 410):
                _note_miss(url)
                continue
            reason = "offline"
            continue
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            log.info("Kartenbild %s: %s", url, e)
            reason = "offline"
            continue
        try:
            dst = images.image_path(url)
            dst.parent.mkdir(parents=True, exist_ok=True)
            images.convert_to_png(raw, dst)
            return dst, url
        except Exception as e:  # noqa – kaputte Datei: weglegen und weiter
            log.info("Kartenbild %s nicht lesbar: %s", url, e)
            try:
                raw.unlink()
            except OSError:
                pass
            _note_miss(url)
    return None, reason


def scaled_map_image(url: str, size: tuple[int, int]) -> Path | None:
    """Dieselbe Karte in einer anderen Größe (hochwertig umgerechnet, im Datenordner gemerkt)."""
    from . import images
    dst = images.image_path(url, size)
    if dst.is_file() and dst.stat().st_size > 0:
        return dst
    raw = images.raw_path(url)
    if not raw.is_file() or not images.can_convert():
        return None
    try:
        images.convert_to_png(raw, dst, size)
        return dst
    except Exception as e:  # noqa
        log.info("Kartenbild %s in %s: %s", url, size, e)
        return None


# --------------------------------------------------------------------------- #
# Wege und Orte aus den Sitzungen
# --------------------------------------------------------------------------- #
PIN_KINDS = {
    "death": "Tod", "level": "Stufenaufstieg", "boss": "Boss", "rare": "Seltener Gegner", "loot": "Seltene Beute",
    "gather": "Sammelpunkt", "found": "Entdeckt", "qa": "Quest angenommen", "qd": "Quest abgegeben", "shot": "Screenshot",
}
GATHER_NAMES = {"herb": "Kräuterkunde", "mining": "Bergbau", "skinning": "Kürschnerei", "fishing": "Angeln"}


def parse_route(d: str, t0: int) -> list[tuple[float, float, int]]:
    """„x,y,s;…“ (0–10000, Sekunden seit dem Punkt davor) -> [(x %, y %, Zeitpunkt)]."""
    out, t = [], int(t0)
    for part in (d or "").split(";"):
        bits = part.split(",")
        if len(bits) != 3:
            continue
        try:
            x, y, dt = int(bits[0]), int(bits[1]), int(bits[2])
        except ValueError:
            continue
        t += max(0, dt)
        out.append((x / 100.0, y / 100.0, t))
    return out


PERIODS = {"last": "Letzte Sitzung", "today": "Heute", "7d": "Letzte 7 Tage", "30d": "Letzte 30 Tage", "all": "Alles"}


def filter_sessions(sessions: list[dict], char: str = "", period: str = "7d", now: float | None = None) -> list[dict]:
    """Sitzungen eines Charakters (oder aller) in einem Zeitraum; neueste zuerst."""
    now = now or time.time()
    out = [s for s in sessions if not char or s.get("char") == char]
    out.sort(key=lambda s: s.get("start", 0), reverse=True)
    if period == "last":
        return out[:1]
    if period == "today":
        start = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        return [s for s in out if s.get("stop", s.get("start", 0)) >= start]
    days = {"7d": 7, "30d": 30}.get(period)
    if days:
        return [s for s in out if s.get("stop", s.get("start", 0)) >= now - days * 86400]
    return out


def session_routes(sessions: list[dict], ui: int) -> list[dict]:
    """Wegstücke auf einer Karte: [{"sid", "char", "start", "k", "pts": [(x, y, t)]}], ältestes zuerst."""
    out = []
    for s in sessions:
        for sg in (s.get("map") or {}).get("segs") or []:
            if sg.get("m") != ui:
                continue
            pts = parse_route(sg.get("d", ""), sg.get("t", 0))
            if pts:
                out.append({"sid": s.get("id", ""), "char": s.get("char", ""), "start": s.get("start", 0),
                            "k": sg.get("k", ""), "pts": pts})
    out.sort(key=lambda r: r["pts"][0][2])
    return out


def session_pins(sessions: list[dict], ui: int) -> list[dict]:
    """Orte auf einer Karte (nur mit Position), mit Sitzung und Charakter."""
    out = []
    for s in sessions:
        for p in (s.get("map") or {}).get("pins") or []:
            if p.get("m") == ui and p.get("x") is not None:
                out.append({**p, "sid": s.get("id", ""), "char": s.get("char", ""), "name_char": s.get("name", "")})
    out.sort(key=lambda p: p["t"])
    return out


def map_activity(sessions: list[dict]) -> dict[int, dict]:
    """Je Karte: Anzahl Wegpunkte, Orte und letzte Zeit – für die Kontinentübersicht und die Zonenliste."""
    out: dict[int, dict] = {}
    for s in sessions:
        M = s.get("map") or {}
        for sg in M.get("segs") or []:
            e = out.setdefault(sg["m"], {"pts": 0, "pins": 0, "last": 0})
            e["pts"] += sg.get("d", "").count(";") + 1
            e["last"] = max(e["last"], sg.get("t", 0))
        for p in M.get("pins") or []:
            e = out.setdefault(p["m"], {"pts": 0, "pins": 0, "last": 0})
            e["pins"] += 1
            e["last"] = max(e["last"], p.get("t", 0))
    return out


def pin_title(p: dict) -> str:
    """Kurzer Text zu einem Ort (für Hover und Liste)."""
    k = p.get("k")
    if k == "death":
        return tr("Tod durch {0}", p["by"]) if p.get("by") else tr("Tod")
    if k == "level":
        return tr("Stufe {0} erreicht", p.get("l", "?"))
    if k == "boss":
        return tr("Boss besiegt: {0}", p.get("name", "?"))
    if k == "rare":
        return tr("Seltener Gegner: {0}", p.get("name", "?"))
    if k == "loot":
        return tr("Seltene Beute: {0}", p.get("name", "?"))
    if k == "gather":
        return f"{tr(GATHER_NAMES.get(p.get('g', ''), 'Sammelpunkt'))}: {p.get('name', '?')}"
    if k == "found":
        return tr("Entdeckt: {0}", p.get("name", "?"))
    if k == "qa":
        return tr("Quest angenommen: {0}", p.get("name") or f"#{p.get('id', '?')}")
    if k == "qd":
        return tr("Quest abgegeben: {0}", p.get("name") or f"#{p.get('id', '?')}")
    if k == "shot":
        return tr("Screenshot")
    return tr(PIN_KINDS.get(k, k or "?"))


def screenshot_for(root: str, flavor: str, t: int, slack: int = 4) -> Path | None:
    """Die Bilddatei zu einem Screenshot-Ort: WoW nennt sie WoWScrnShot_MMTTJJ_HHMMSS (Ortszeit)."""
    d = Path(root or "") / flavor / "Screenshots"
    if not root or not d.is_dir():
        return None
    for dt in sorted(range(-slack, slack + 1), key=abs):
        stamp = datetime.fromtimestamp(t + dt).strftime("%m%d%y_%H%M%S")
        for ext in ("jpg", "png", "tga"):
            p = d / f"WoWScrnShot_{stamp}.{ext}"
            if p.is_file():
                return p
    return None


def way_command(x: float, y: float) -> str:
    """/way-Befehl (TomTom und andere Wegpunkt-Addons) für Koordinaten in Prozent."""
    return f"/way {x:.1f} {y:.1f}"


# --------------------------------------------------------------------------- #
# Quest-Ebene (QuestieDB)
# --------------------------------------------------------------------------- #
CLASS_BITS = {"WARRIOR": 1, "PALADIN": 2, "HUNTER": 4, "ROGUE": 8, "PRIEST": 16, "SHAMAN": 64, "MAGE": 128,
              "WARLOCK": 256, "DRUID": 1024}
MAX_OBJECTIVE_SPOTS = 160          # je Quest – sonst wird die Karte bei Tieren mit 300 Fundorten unlesbar


def _spawns(raw) -> dict[int, list[tuple[float, float]]]:
    out: dict[int, list[tuple[float, float]]] = {}
    if not isinstance(raw, dict):
        return out
    for area, pts in raw.items():
        if not isinstance(area, int):
            continue
        for pt in pts if isinstance(pts, list) else []:
            if isinstance(pt, list) and len(pt) >= 2 and isinstance(pt[0], (int, float)) and isinstance(pt[1], (int, float)) \
                    and pt[0] >= 0 and pt[1] >= 0:
                out.setdefault(area, []).append((float(pt[0]), float(pt[1])))
    return out


def npc_spawns(db, nid: int) -> dict[int, list[tuple[float, float]]]:
    return _spawns((db.row("Npc", nid, 20) or {}).get(7))


def object_spawns(db, oid: int) -> dict[int, list[tuple[float, float]]]:
    return _spawns((db.row("Object", oid, 10) or {}).get(4))


def _id_list(v) -> list[int]:
    if isinstance(v, dict):
        v = [v[k] for k in sorted(v) if isinstance(k, int)]
    return [int(x) for x in (v or []) if isinstance(x, (int, float)) and x]


def item_sources(db, iid: int) -> tuple[list[int], list[int]]:
    """NPCs und Objekte, bei denen ein Gegenstand zu finden ist."""
    r = db.row("Item", iid, 16) or {}
    return _id_list(r.get(2)), _id_list(r.get(3))


def _on_map(spawns: dict, idx: ZoneIndex, ui: int) -> list[tuple[float, float]]:
    out = []
    for area, pts in spawns.items():
        if idx.ui_for_area(area) == ui:
            out.extend(pts)
    return out


def quest_color(qlvl: int, level: int) -> str:
    """Schwierigkeitsfarbe wie im Questlog: grau, grün, gelb, orange, rot."""
    if not level or not qlvl:
        return "yellow"
    d = qlvl - level
    if d >= 5:
        return "red"
    if d >= 3:
        return "orange"
    if d >= -2:
        return "yellow"
    gray_at = 5 + level // 10 if level < 60 else 9
    return "green" if -d <= gray_at else "gray"


def _giver_places(db, who: dict, idx: ZoneIndex, ui: int, locale: str) -> list[tuple[float, float, str]]:
    """Wo Questgeber oder -abgabe (NPCs, Objekte) auf dieser Karte stehen."""
    out = []
    for nid in who["npc"][:4]:
        pts = _on_map(npc_spawns(db, nid), idx, ui)[:6]
        if pts:
            n = db.npc(nid, locale)
            out += [(x, y, n["name"] if n else f"NPC {nid}") for x, y in pts]
    for oid in who["obj"][:4]:
        pts = _on_map(object_spawns(db, oid), idx, ui)[:6]
        if pts:
            name = db.obj_name(oid, locale)
            out += [(x, y, name) for x, y in pts]
    return out


def _start_places(db, q: dict, idx: ZoneIndex, ui: int, locale: str) -> list[tuple[float, float, str]]:
    return _giver_places(db, q["start"], idx, ui, locale)


def _end_places(db, q: dict, idx: ZoneIndex, ui: int, locale: str) -> list[tuple[float, float, str]]:
    return _giver_places(db, q["end"], idx, ui, locale)


def _objective_places(db, qid: int, q: dict, idx: ZoneIndex, ui: int, locale: str,
                      done_texts: list[str]) -> list[tuple[float, float, str]]:
    """Wo die Ziele einer Quest zu erledigen sind (Gegner, Objekte, Beute, Orte) – ohne erledigte Ziele."""
    def finished(name: str) -> bool:
        low = name.lower()
        return any(low and low in t for t in done_texts)
    out: list[tuple[float, float, str]] = []
    for nid in q["kill"]:
        n = db.npc(nid, locale)
        name = n["name"] if n else f"NPC {nid}"
        if not finished(name):
            out += [(x, y, name) for x, y in _on_map(npc_spawns(db, nid), idx, ui)]
    for oid in q["objs"]:
        name = db.obj_name(oid, locale)
        if not finished(name):
            out += [(x, y, name) for x, y in _on_map(object_spawns(db, oid), idx, ui)]
    for iid in q["items"]:
        iname = db.item_name(iid, locale)
        if finished(iname):
            continue
        npcs, objs = item_sources(db, iid)
        for nid in npcs[:12]:
            n = db.npc(nid, locale)
            label = f"{iname} – {n['name']}" if n else iname
            out += [(x, y, label) for x, y in _on_map(npc_spawns(db, nid), idx, ui)]
        for oid in objs[:12]:
            label = f"{iname} – {db.obj_name(oid, locale)}"
            out += [(x, y, label) for x, y in _on_map(object_spawns(db, oid), idx, ui)]
    trig = (db.row("Quest", qid, 36) or {}).get(9)
    if isinstance(trig, list) and len(trig) >= 2:
        text = trig[0] if isinstance(trig[0], str) else tr("Ort erkunden")
        out += [(x, y, text) for x, y in _on_map(_spawns(trig[1]), idx, ui)]
    if len(out) > MAX_OBJECTIVE_SPOTS:            # gleichmäßig ausdünnen
        step = len(out) / MAX_OBJECTIVE_SPOTS
        out = [out[int(i * step)] for i in range(MAX_OBJECTIVE_SPOTS)]
    return out


def quest_layer(db, idx: ZoneIndex, ui: int, char: dict | None, locale: str, available: bool = True,
                show_gray: bool = False) -> dict:
    """Marken der Quest-Ebene für eine Karte und einen Charakter.

    {"active": [{"qid", "title", "lvl", "done", "objectives": [texte], "end": [(x, y, name)], "spots": [(x, y, name)]}],
     "available": [{"qid", "title", "lvl", "color", "places": [(x, y, name)]}], "note": Hinweis}"""
    out = {"active": [], "available": [], "note": ""}
    if db is None or not char:
        return out
    log_ = char.get("questLog")
    if log_ is None:
        out["note"] = tr("Die Questliste kommt von Leeroylink 0.9 – einmal einloggen und wieder ausloggen.")
    in_log = set()
    for e in (log_ or {}).get("list", []):
        qid = e["id"]
        in_log.add(qid)
        q = db.quests.get(qid)
        if not q:
            continue
        done_texts = [o["text"].lower() for o in e.get("o", []) if o.get("done")]
        entry = {"qid": qid, "title": db.quest_name(qid, locale) or e.get("title", ""), "lvl": q["lvl"] or e.get("lvl", 0),
                 "done": e.get("done", False), "objectives": [(o["text"], o["done"]) for o in e.get("o", [])],
                 "end": _end_places(db, q, idx, ui, locale),
                 "spots": [] if e.get("done") else _objective_places(db, qid, q, idx, ui, locale, done_texts)}
        if entry["end"] or entry["spots"]:
            out["active"].append(entry)
    if not available:
        return out
    done = char.get("questsDone")
    if done is None:
        if not out["note"]:
            out["note"] = tr("Welche Quests schon erledigt sind, meldet Leeroylink 0.9 beim nächsten Ausloggen.")
        return out
    done_set, level = set(done), int(char.get("level") or 0)
    side = {"Alliance": "A", "Horde": "H"}.get(char.get("faction", ""), "")
    cbit = CLASS_BITS.get(char.get("class", ""), 0)
    for qid, places in quest_starts_on(db, idx, ui, locale).items():
        q = db.quests.get(qid)
        if not q or qid in done_set or qid in in_log:
            continue
        if side and q["side"] and q["side"] != side:
            continue
        if q["classes"] and cbit and not q["classes"] & cbit:
            continue
        if q["req"] and level and q["req"] > level:
            continue
        if q["pre"]:
            have = [p in done_set for p in q["pre"]]
            if (q["pre_all"] and not all(have)) or (not q["pre_all"] and not any(have)):
                continue
        if any(x in done_set for x in q["exclusive"]):
            continue
        color = quest_color(q["lvl"], level)
        if color == "gray" and not show_gray:
            continue
        out["available"].append({"qid": qid, "title": db.quest_name(qid, locale), "lvl": q["lvl"], "color": color,
                                 "places": places})
    out["available"].sort(key=lambda a: (a["lvl"], a["title"]))
    return out


_STARTS_LOCK = threading.Lock()


def quest_starts_on(db, idx: ZoneIndex, ui: int, locale: str) -> dict[int, list[tuple[float, float, str]]]:
    """Alle Quests, deren Geber (NPC oder Objekt) auf dieser Karte steht – einmal je Datenbank berechnet."""
    with _STARTS_LOCK:
        cache = getattr(db, "_lz_starts", None)
        if cache is None or cache.get("_idx") is not idx or cache.get("_loc") != locale:
            cache = {"_idx": idx, "_loc": locale}
            try:
                db._lz_starts = cache
            except AttributeError:
                pass
        if ui in cache:
            return cache[ui]
        out: dict[int, list[tuple[float, float, str]]] = {}
        for qid, q in db.quests.items():
            places = _start_places(db, q, idx, ui, locale)
            if places:
                out[qid] = places
        cache[ui] = out
        return out


# --------------------------------------------------------------------------- #
# Suche
# --------------------------------------------------------------------------- #
_NAMES_LOCK = threading.Lock()


def _name_index(db, locale: str) -> list[tuple[str, int, str]]:
    """(Art, ID, Name klein) aller NPCs und Objekte – einmal je Datenbank und Sprache."""
    with _NAMES_LOCK:
        cache = getattr(db, "_lz_names", None) or {}
        if locale in cache:
            return cache[locale]
        out = []
        for nid in db.all_ids("Npc"):
            r = db.row("Npc", nid, 20) or {}
            if not r.get(7):
                continue
            name = db.localized("Npc", nid, 1, locale) or r.get(1)
            if isinstance(name, str):
                out.append(("npc", nid, name.lower()))
        for oid in db.all_ids("Object"):
            r = db.row("Object", oid, 10) or {}
            if not r.get(4):
                continue
            name = db.localized("Object", oid, 1, locale) or r.get(1)
            if isinstance(name, str):
                out.append(("object", oid, name.lower()))
        cache[locale] = out
        try:
            db._lz_names = cache
        except AttributeError:
            pass
        return out


def map_search(text: str, idx: ZoneIndex, db=None, locale: str = "enUS", limit: int = 40) -> list[dict]:
    """Zonen, NPCs, Objekte und Quests nach Namen. Treffer: {"kind", "id", "name", "sub", "places": [(ui, x, y)]}."""
    text = (text or "").strip().lower()
    if len(text) < 2:
        return []
    out: list[dict] = []
    for e in idx.maps.values():
        if e.get("type") in (ZONE_TYPE, CONTINENT_TYPE) and text in e["name"].lower():
            out.append({"kind": "zone", "id": e["id"], "name": e["name"], "sub": tr("Zone") if e["type"] == ZONE_TYPE
                        else tr("Kontinent"), "places": [(e["id"], None, None)]})
    out.sort(key=lambda r: (not r["name"].lower().startswith(text), r["name"].lower()))
    if db is None:
        return out[:limit]
    hits = [(k, i, n) for k, i, n in _name_index(db, locale) if text in n]
    hits.sort(key=lambda h: (not h[2].startswith(text), len(h[2]), h[2]))
    for kind, eid, _ in hits[:limit * 2]:
        spawns = npc_spawns(db, eid) if kind == "npc" else object_spawns(db, eid)
        places = [(idx.ui_for_area(area), x, y) for area, pts in spawns.items() for x, y in pts if idx.ui_for_area(area)]
        if not places:
            continue
        if kind == "npc":
            n = db.npc(eid, locale) or {}
            name, sub = n.get("name", f"NPC {eid}"), n.get("sub") or tr("NPC")
        else:
            name, sub = db.obj_name(eid, locale), tr("Objekt")
        same = next((r for r in out if r["kind"] == kind and r["name"] == name), None)
        if same:                                   # gleicher Name, andere ID (z. B. Kupfervorkommen): zusammenfassen
            same["places"] = (same["places"] + places)[:400]
            same["ids"].append(eid)
        else:
            out.append({"kind": kind, "id": eid, "ids": [eid], "name": name, "sub": sub, "places": places[:400]})
        if len(out) >= limit:
            break
    for r in out:
        if r["kind"] in ("npc", "object"):
            zones = sorted({idx.name(p[0]) for p in r["places"]})
            r["sub"] = f"{r['sub']} · {', '.join(zones[:2])}" + (" …" if len(zones) > 2 else "")
    if len(out) < limit and not text.isdigit():
        for qid in db.search(text, locale, limit=limit):
            q = db.quests.get(qid)
            if not q:
                continue
            places = []
            for nid in q["start"]["npc"][:3]:
                places += [(idx.ui_for_area(a), x, y) for a, pts in npc_spawns(db, nid).items() for x, y in pts[:3]
                           if idx.ui_for_area(a)]
            if places:
                out.append({"kind": "quest", "id": qid, "name": db.quest_name(qid, locale),
                            "sub": tr("Quest · Stufe {0}", q["lvl"]), "places": places})
            if len(out) >= limit:
                break
    return out[:limit]


def zone_for_char(char: dict | None, sessions: list[dict]) -> int:
    """Die Karte, auf der ein Charakter zuletzt war (Position beim Ausloggen oder letzter Wegpunkt)."""
    if char and (char.get("pos") or {}).get("m"):
        return char["pos"]["m"]
    for s in sorted(sessions, key=lambda s: s.get("start", 0), reverse=True):
        segs = (s.get("map") or {}).get("segs") or []
        if segs:
            return segs[-1]["m"]
    return 0


def clear_image_misses() -> None:
    """„Kartenbilder neu laden“: die Liste fehlender Bilder vergessen."""
    try:
        os.remove(_miss_file())
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# Wachposten: wo finde ich …? (Lehrer, Händler, Dienste – auf jeder Karte)
# --------------------------------------------------------------------------- #
F_VENDOR, F_FLIGHT, F_TRAINER, F_INN, F_BANK, F_GUILD, F_TABARD = 4, 8, 16, 128, 256, 512, 1024
F_BATTLE, F_AUCTION, F_STABLE, F_REPAIR, F_BARBER = 2048, 4096, 8192, 16384, 33554432
_CLASSES = [("WARRIOR", "Krieger", "Warrior"), ("PALADIN", "Paladin", "Paladin"), ("HUNTER", "Jäger", "Hunter|Pet"),
            ("ROGUE", "Schurke", "Rogue"), ("PRIEST", "Priester", "Priest"), ("SHAMAN", "Schamane", "Shaman"),
            ("MAGE", "Magier", "Mage|Portal"), ("WARLOCK", "Hexenmeister", "Warlock|Demon"), ("DRUID", "Druide", "Druid")]
_PROFESSIONS = [("alchemy", "Alchemie", "Alchem"), ("blacksmithing", "Schmiedekunst", "Blacksmith|Armorsmith|Weaponsmith"),
                ("enchanting", "Verzauberkunst", "Enchant"), ("engineering", "Ingenieurskunst", "Engineer"),
                ("herbalism", "Kräuterkunde", "Herbalis"),
                ("leatherworking", "Lederverarbeitung", "Leatherwork"), ("mining", "Bergbau", r"Mining|\bMiner"),
                ("skinning", "Kürschnerei", "Skinn"), ("tailoring", "Schneiderei", "Tailor"),
                ("cooking", "Kochkunst", r"Cook|\bChef"), ("firstaid", "Erste Hilfe", "First Aid|Physician|Surgeon|Medic"),
                ("fishing", "Angeln", "Fish")]
_VENDORS = [("repair", "Reparatur", F_REPAIR, ""),
            ("general", "Gemischtwaren", F_VENDOR, r"General (Goods|Supplies|Trade)|Trade (Goods|Supplies|Supplier)|Tradesman"),
            ("reagents", "Reagenzien", F_VENDOR, "Reagent"),
            ("food", "Essen und Trinken", F_VENDOR, r"Food|Drink|Baker|Butcher|Bartender|Barmaid|Fruit|Meat|Waitress|Innkeeper|Cheese|Mushroom"),
            ("supplies", "Handwerksbedarf", F_VENDOR, r"(Alchemy|Tailoring|Leatherworking|Blacksmithing|Engineering|Enchanting|"
                                                      r"Fishing|Cooking|Herbalism|Mining|Jewelcrafting) Suppl|Recipes|Patterns|Plans"),
            ("weapons", "Waffen", F_VENDOR, r"Weapon|Blade|Axe|Bow|Gun|Staff|Sword|Mace|Dagger|Fletcher"),
            ("armor", "Rüstung", F_VENDOR, r"Armor|Shield|Clothier|Cloth\b|Mail\b|Leather Goods"),
            ("bags", "Taschen", F_VENDOR, r"\bBag"),
            ("poisons", "Gifte", F_VENDOR, "Poison|Shady Dealer")]
_SERVICES = [("inn", "Gasthaus", F_INN, ""), ("bank", "Bank", F_BANK, ""), ("auction", "Auktionshaus", F_AUCTION, ""),
             ("flight", "Flugmeister", F_FLIGHT, ""), ("stable", "Stallmeister", F_STABLE, ""),
             ("mailbox", "Briefkasten", 0, ""), ("transmog", "Transmogrifizierer", 0, "Transmog"),
             ("barber", "Barbier", F_BARBER, "Barber"), ("guild", "Gildenmeister", F_GUILD, ""),
             ("tabard", "Wappenröcke", F_TABARD, "Tabard"), ("battle", "Kampfmeister", F_BATTLE, ""),
             ("weaponmaster", "Waffenmeister", 0, "Weapon Master")]
# Gruppen fürs Menü: (Name, [(Schlüssel, Name)])
GUIDE_GROUPS = [
    ("Klassenlehrer", [(f"class:{k}", n) for k, n, _ in _CLASSES]),
    ("Berufslehrer", [(f"prof:{k}", n) for k, n, _ in _PROFESSIONS]),
    ("Händler", [(f"vendor:{k}", n) for k, n, _, _ in _VENDORS]),
    ("Dienste", [(f"service:{k}", n) for k, n, _, _ in _SERVICES]),
]
GUIDE_NAMES = {key: name for _, items in GUIDE_GROUPS for key, name in items}
_GUIDE_LOCK = threading.Lock()


def guide_index(db) -> dict[str, list[tuple[str, int]]]:
    """Schlüssel der Wachposten-Liste -> [("npc"|"object", ID)] – einmal je Datenbank aus Art (Händler, Lehrer …)
    und englischem Titel der NPCs bestimmt."""
    with _GUIDE_LOCK:
        cached = getattr(db, "_lz_guide", None)
        if cached is not None:
            return cached
        out: dict[str, list[tuple[str, int]]] = {key: [] for key in GUIDE_NAMES}
        cls = [(f"class:{k}", re.compile(rf"\b({rx}) Trainer")) for k, _, rx in _CLASSES]
        prof = [(f"prof:{k}", re.compile(rx)) for k, _, rx in _PROFESSIONS]
        vend = [(f"vendor:{k}", flag, re.compile(rx) if rx else None) for k, _, flag, rx in _VENDORS]
        serv = [(f"service:{k}", flag, re.compile(rx) if rx else None) for k, _, flag, rx in _SERVICES]
        for nid in db.all_ids("Npc"):
            r = db.row("Npc", nid, 20) or {}
            if not r.get(7):
                continue
            flags = r.get(15) if isinstance(r.get(15), int) else 0
            sub = r.get(14) if isinstance(r.get(14), str) else ""
            if not flags and not sub:
                continue
            ref = ("npc", nid)
            if flags & F_TRAINER:
                hit = next((key for key, rx in cls if rx.search(sub)), None)
                if hit:
                    out[hit].append(ref)
                elif "Weapon Master" not in sub:
                    hit = next((key for key, rx in prof if rx.search(sub)), None)
                    if hit:
                        out[hit].append(ref)
            for key, flag, rx in vend:
                if flags & flag and (rx is None or rx.search(sub)):
                    out[key].append(ref)
            for key, flag, rx in serv:
                if (flag and flags & flag) or (rx is not None and rx.search(sub)):
                    out[key].append(ref)
        for oid in db.all_ids("Object"):
            r = db.row("Object", oid, 10) or {}
            if r.get(4) and r.get(1) == "Mailbox":
                out["service:mailbox"].append(("object", oid))
        try:
            db._lz_guide = out
        except AttributeError:
            pass
        return out


def guide_places(db, idx: ZoneIndex, key: str, side: str = "", locale: str = "enUS") -> list[dict]:
    """Alle Fundorte einer Wachposten-Kategorie: [{"kind", "id", "name", "sub", "ui", "x", "y"}].
    side "A"/"H": nur NPCs, die dieser Fraktion freundlich sind."""
    out = []
    for kind, eid in guide_index(db).get(key, []):
        if kind == "npc":
            r = db.row("Npc", eid, 20) or {}
            friendly = r.get(13) if isinstance(r.get(13), str) else ""
            if side and friendly and side not in friendly:
                continue
            n = db.npc(eid, locale) or {}
            name, sub, spawns = n.get("name") or f"NPC {eid}", n.get("sub") or "", npc_spawns(db, eid)
        else:
            name = tr("Briefkasten") if key == "service:mailbox" else db.obj_name(eid, locale)
            sub, spawns = "", object_spawns(db, eid)
        for area, pts in spawns.items():
            ui = idx.ui_for_area(area)
            if not ui:
                continue
            for x, y in pts[:3] if kind == "npc" else pts:      # NPCs mit Laufweg haben mehrere Punkte: der erste reicht fast immer
                out.append({"kind": kind, "id": eid, "name": name, "sub": sub, "ui": ui, "x": x, "y": y})
                if kind == "npc":
                    break
    return out


def nearest_first(places: list[dict], x: float | None, y: float | None) -> list[dict]:
    """Nach Entfernung zu einem Punkt der Karte sortiert (Kartenbreite : -höhe = 3 : 2); ohne Punkt nach Namen."""
    if x is None or y is None:
        return sorted(places, key=lambda p: (p["name"].lower(), p["x"]))
    return sorted(places, key=lambda p: ((p["x"] - x) * 1.5) ** 2 + (p["y"] - y) ** 2)
