"""Karte: Daten (Wege, Orte, Zonen, Quest-Ebene, Suche) und die Seite im Fenster.

    python3 -m unittest tests.test_worldmap          (Fenster-Teil unter Linux mit xvfb-run)

Die Sitzungsdaten kommen aus dem Leeroylink-Szenario (tests/scenario.lua, braucht lupa); die Quest-Ebene
wird mit einer kleinen nachgebauten QuestieDB geprüft.
"""
import json
import os
import shutil
import sys
import tempfile
import time
import traceback
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="lz-map-"))
os.environ["APPDATA"] = str(TMP / "appdata")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from leeroy import mapdata as M  # noqa: E402
from leeroy.sessions import normalize_session, sessions_in_db  # noqa: E402

try:
    import run_addon_test
except ImportError:                                    # lupa fehlt
    run_addon_test = None

_SV = {}


def scenario_sv() -> str:
    """SavedVariables nach dem Leeroylink-Szenario (einmal je Testlauf)."""
    if "text" not in _SV:
        _, text1, now = run_addon_test.run(ROOT / "Leeroylink", 1, None)
        f = TMP / "sv1.lua"
        f.write_text(text1, encoding="utf-8")
        _, text2, _ = run_addon_test.run(ROOT / "Leeroylink", 2, f, start_now=now + 15)
        _SV["text"] = text2
    return _SV["text"]


class FakeDB:
    """Genug QuestieDB für die Quest-Ebene: Quests, NPCs, Objekte, Gegenstände mit Fundorten."""

    def __init__(self):
        q = lambda **kw: {"lvl": 10, "req": 1, "side": "", "classes": 0, "pre": [], "pre_all": False,    # noqa: E731
                          "exclusive": [], "kill": [], "objs": [], "items": [], "start": {"npc": [], "obj": [], "item": []},
                          "end": {"npc": [], "obj": []}, "name": "?", **kw}
        self.quests = {
            176: q(name="Wanted: Hogger", lvl=11, items=[1931], start={"npc": [], "obj": [68], "item": []}, end={"npc": [240], "obj": []}),
            11: q(name="Riverpaw Gnoll Bounty", lvl=10, kill=[478], end={"npc": [963], "obj": []}),
            50: q(name="Explore the Lake", lvl=8, start={"npc": [240], "obj": [], "item": []}, end={"npc": [240], "obj": []}),
            51: q(name="Follow-up", lvl=9, pre=[50], start={"npc": [240], "obj": [], "item": []}),
            52: q(name="Horde only", lvl=9, side="H", start={"npc": [240], "obj": [], "item": []}),
            53: q(name="Mage only", lvl=9, classes=128, start={"npc": [240], "obj": [], "item": []}),
            54: q(name="Too high", lvl=30, req=25, start={"npc": [240], "obj": [], "item": []}),
            55: q(name="Grey one", lvl=2, start={"npc": [240], "obj": [], "item": []}),
            56: q(name="Elsewhere", lvl=10, start={"npc": [999], "obj": [], "item": []}),
        }
        self.npcs = {240: ("Marshal Dughan", {12: [[42.1, 65.9]]}), 448: ("Hogger", {12: [[25.0, 92.9]]}),
                     478: ("Riverpaw Outrunner", {12: [[26.0, 86.0], [27.0, 87.5]], 40: [[50, 50]]}),
                     963: ("Deputy Rainer", {12: [[24.2, 74.4]]}), 999: ("Somebody", {14: [[50, 50]]})}
        self.objects = {68: ("Wanted Poster", {12: [[42.0, 65.5]]}), 1731: ("Copper Vein", {12: [[30, 30], [31, 31]], 40: [[10, 10]]})}
        self.items = {1931: {2: [448]}}
        self.triggers = {50: ["Explore the lake", {12: [[60.0, 50.0]]}]}

    def row(self, kind, eid, fields):
        if kind == "Npc" and eid in self.npcs:
            return {1: self.npcs[eid][0], 7: self.npcs[eid][1]}
        if kind == "Object" and eid in self.objects:
            return {1: self.objects[eid][0], 4: self.objects[eid][1]}
        if kind == "Item":
            return self.items.get(eid)
        if kind == "Quest" and eid in self.triggers:
            return {9: self.triggers[eid]}
        return None

    def npc(self, nid, locale):
        return {"id": nid, "name": self.npcs[nid][0], "sub": ""} if nid in self.npcs else None

    def obj_name(self, oid, locale):
        return self.objects.get(oid, (f"#{oid}",))[0]

    def item_name(self, iid, locale):
        return {1931: "Huge Gnoll Claw"}.get(iid, f"#{iid}")

    def quest_name(self, qid, locale):
        return self.quests[qid]["name"]

    def localized(self, kind, eid, column, locale):
        return None

    def all_ids(self, kind):
        return sorted(self.npcs if kind == "Npc" else self.objects)

    def search(self, text, locale, side="", lmin=0, lmax=0, limit=300):
        return [qid for qid, q in self.quests.items() if text.lower() in q["name"].lower()][:limit]


class RouteTests(unittest.TestCase):
    def test_parse_route(self):
        pts = M.parse_route("3035,5000,0;3140,5000,3;bad;3245,5010,4", 1000)
        self.assertEqual(pts, [(30.35, 50.0, 1000), (31.4, 50.0, 1003), (32.45, 50.1, 1007)])
        self.assertEqual(M.parse_route("", 5), [])

    def test_filter_and_layers(self):
        now = time.time()
        mk = lambda sid, char, start, segs=(), pins=(): {"id": sid, "char": char, "start": start, "stop": start + 60,  # noqa: E731
                                                       "map": {"segs": list(segs), "pins": list(pins)}}
        a = mk("a", "A-R", now - 100, [{"m": 1429, "k": "", "t": now - 100, "d": "1000,1000,0;2000,2000,5"},
                                       {"m": 1436, "k": "t", "t": now - 50, "d": "5000,5000,0"}],
               [{"k": "death", "m": 1429, "t": now - 90, "x": 10.0, "y": 10.0}, {"k": "boss", "m": 1581, "t": now - 80}])
        b = mk("b", "B-R", now - 10 * 86400)
        c = mk("c", "A-R", now - 40 * 86400)
        self.assertEqual([s["id"] for s in M.filter_sessions([a, b, c], period="7d")], ["a"])
        self.assertEqual([s["id"] for s in M.filter_sessions([a, b, c], period="30d")], ["a", "b"])
        self.assertEqual([s["id"] for s in M.filter_sessions([a, b, c], char="A-R", period="all")], ["a", "c"])
        self.assertEqual([s["id"] for s in M.filter_sessions([c, a], period="last")], ["a"])
        routes = M.session_routes([a], 1429)
        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0]["pts"][-1], (20.0, 20.0, int(now - 100) + 5))
        self.assertEqual(M.session_routes([a], 1436)[0]["k"], "t")
        pins = M.session_pins([a], 1429)
        self.assertEqual([p["k"] for p in pins], ["death"])
        self.assertEqual(M.session_pins([a], 1581), [], "places without position stay off the map")
        act = M.map_activity([a])
        self.assertEqual((act[1429]["pts"], act[1429]["pins"], act[1436]["pts"]), (2, 1, 1))
        self.assertEqual(M.zone_for_char(None, [a]), 1436)
        self.assertEqual(M.zone_for_char({"pos": {"m": 1433}}, [a]), 1433)

    def test_titles_and_way(self):
        self.assertEqual(M.way_command(42.11, 65.96), "/way 42.1 66.0")
        self.assertIn("Hogger", M.pin_title({"k": "death", "by": "Hogger"}))
        self.assertIn("Kupfererz", M.pin_title({"k": "gather", "g": "mining", "name": "Kupfererz"}))
        self.assertIn("12", M.pin_title({"k": "level", "l": 12}))

    def test_screenshot_file(self):
        root = TMP / "wow-shots"
        d = root / "_forever_" / "Screenshots"
        d.mkdir(parents=True)
        t = int(time.time()) - 500
        f = d / ("WoWScrnShot_" + datetime.fromtimestamp(t + 2).strftime("%m%d%y_%H%M%S") + ".jpg")
        f.write_bytes(b"x")
        self.assertEqual(M.screenshot_for(str(root), "_forever_", t), f)
        self.assertIsNone(M.screenshot_for(str(root), "_forever_", t - 100))


class ZoneTests(unittest.TestCase):
    def write_questie(self) -> Path:
        q = TMP / "QuestieDB"
        z = q / "support" / "Forever" / "Zones"
        z.mkdir(parents=True, exist_ok=True)
        (z / "areaIdToUiMapId.lua").write_text('''local ZoneDB = QuestieLoader:ImportModule("ZoneDB")
ZoneDB.private.areaIdToUiMapIdOverride = [[return {
    [0] = 0, -- Existing fail-safe
    [10073] = 1414, -- Synthetic AreaID: Kalimdor continent map
    [12] = 1429, -- Elwynn Forest
}]]
ZoneDB.private.areaIdToUiMapId = [[return {
    [9] = 1429, -- Northshire Valley -> Elwynn Forest
    [12] = 9999, -- (overridden)
    [616] = 2482, -- Mount Hyjal
}]]
''', encoding="utf-8")
        (z / "uiMapIdToAreaId.lua").write_text('''ZoneDB.private.uiMapIdToAreaIdOverride = [[return {
    [1414] = 10073, -- Kalimdor
    [310] = 209, -- Referenced dungeon area
}]]
ZoneDB.private.uiMapIdToAreaId = [[return {
    [1429] = 12, -- Elwynn Forest
    [2482] = 616, -- Mount Hyjal
}]]
''', encoding="utf-8")
        return q

    def test_questie_tables(self):
        qz = M.read_questie_zone_maps(self.write_questie(), "Forever")
        self.assertEqual(qz["area_to_ui"][12], 1429, "the override wins")
        self.assertEqual(qz["area_to_ui"][9], 1429)
        self.assertNotIn(0, qz["area_to_ui"])
        self.assertEqual(qz["ui_to_area"][2482], 616)
        self.assertEqual(qz["names"][2482], "Mount Hyjal")
        self.assertNotIn(310, qz["names"], "no names from 'Referenced dungeon area'")
        self.assertEqual(M.read_questie_zone_maps(TMP / "nothing", "Forever")["area_to_ui"], {})

    def test_index_merges_sources(self):
        qz = M.read_questie_zone_maps(self.write_questie(), "Forever")
        link = {"maps": {1429: {"name": "Wald von Elwynn", "type": 3, "parent": 1415, "on": 1415, "rect": [0.4, 0.5, 0.7, 0.8]},
                         1415: {"name": "Östliche Königreiche", "type": 2, "parent": 947, "on": 947, "rect": None},
                         1453: {"name": "Sturmwind", "type": 3, "parent": 1429, "on": 1415, "rect": None}}}
        idx = M.ZoneIndex(link, qz, {10: "Dämmerwald"})
        self.assertEqual(idx.name(1429), "Wald von Elwynn", "names from the game")
        self.assertEqual(idx.name(1431), "Dämmerwald", "learned names (QuestGuide) for zones the game index lacks")
        self.assertEqual(idx.name(1436), "Westfall", "classic fallback")
        self.assertEqual(idx.ui_for_area(9), 1429)
        self.assertEqual(idx.area(1429), 12)
        self.assertEqual(idx.continent_of(1453), 1415)
        self.assertTrue(idx.is_continent(1415))
        self.assertTrue(idx.has_layout)
        names = [z["name"] for z in idx.zones_on(1415)]
        self.assertIn("Wald von Elwynn", names)
        self.assertIn("Sturmwind", names)
        self.assertEqual({c["id"] for c in idx.continents()}, {1414, 1415})
        self.assertTrue(M.ZoneIndex().zones_on(1414), "works without any data")

    def test_image_urls(self):
        urls = M.map_image_urls("_forever_", 12)
        self.assertTrue(urls[0].endswith("/forever/maps/enus/zoom/12.jpg"))
        self.assertTrue(any("/classic/maps/" in u for u in urls), "classic maps as fallback for Forever")
        self.assertTrue(M.map_image_urls("_retail_", 12)[0].startswith("https://wow.zamimg.com/images/wow/maps/"))

    def test_image_cache_and_misses(self):
        from leeroy import images
        import urllib.error
        calls = []

        def fake_download(url):
            calls.append(url)
            if "/forever/" in url:
                raise urllib.error.HTTPError(url, 404, "nope", {}, None)
            raw = images.raw_path(url)
            raw.parent.mkdir(parents=True, exist_ok=True)
            raw.write_bytes(b"jpeg")
            return raw

        def fake_convert(src, dst, size=None):
            Path(dst).write_bytes(b"png")
        old = images._download, images.convert_to_png, images.can_convert
        images._download, images.convert_to_png, images.can_convert = fake_download, fake_convert, lambda: True
        try:
            path, url = M.map_image("_forever_", 4242)
            self.assertTrue(path and path.is_file() and "/classic/" in url, url)
            n = len(calls)
            path2, _ = M.map_image("_forever_", 4242)
            self.assertEqual((path2, len(calls)), (path, n), "second time from the data folder")
            calls.clear()
            M.map_image("_forever_", 4243)
            self.assertFalse(any("/forever/maps/enus/zoom/4243" in c for c in calls[1:]), "404s are not asked twice")
            calls.clear()
            M.map_image("_forever_", 4243)
            self.assertNotIn("https://wow.zamimg.com/images/wow/forever/maps/enus/zoom/4243.jpg", calls,
                             "a missing image is remembered for a week")

            def offline(url):
                raise urllib.error.URLError("no network")
            images._download = offline
            self.assertEqual(M.map_image("_classic_era_", 999), (None, "offline"))
        finally:
            images._download, images.convert_to_png, images.can_convert = old


class QuestLayerTests(unittest.TestCase):
    def setUp(self):
        self.db, self.idx = FakeDB(), M.ZoneIndex()

    def char(self, **kw):
        c = {"level": 10, "faction": "Alliance", "class": "WARRIOR", "questsDone": [],
             "questLog": {"t": 1, "list": [
                 {"id": 176, "title": "Wanted", "lvl": 11, "done": False, "o": [{"text": "Huge Gnoll Claw: 0/1", "done": False}]},
                 {"id": 11, "title": "Bounty", "lvl": 10, "done": True, "o": []}]}}
        c.update(kw)
        return c

    def test_active_and_available(self):
        L = M.quest_layer(self.db, self.idx, 1429, self.char(), "enUS")
        by = {a["qid"]: a for a in L["active"]}
        self.assertEqual(by[176]["end"], [(42.1, 65.9, "Marshal Dughan")])
        self.assertEqual(by[176]["spots"], [(25.0, 92.9, "Huge Gnoll Claw – Hogger")], "item objective -> the mob that drops it")
        self.assertEqual(by[11]["spots"], [], "finished quests only show the turn-in")
        self.assertEqual(by[11]["end"][0][2], "Deputy Rainer")
        avail = {a["qid"]: a for a in L["available"]}
        self.assertEqual(sorted(avail), [50], "prerequisites, faction, class, level, grey and other zones filtered")
        self.assertEqual(avail[50]["color"], "yellow", "two levels below: still yellow")
        self.assertEqual(avail[50]["places"][0][2], "Marshal Dughan")

    def test_rules(self):
        L = M.quest_layer(self.db, self.idx, 1429, self.char(questsDone=[50], **{"class": "MAGE"}), "enUS", show_gray=True)
        self.assertEqual(sorted(a["qid"] for a in L["available"]), [51, 53, 55])
        L = M.quest_layer(self.db, self.idx, 1429, self.char(faction="Horde"), "enUS")
        self.assertIn(52, [a["qid"] for a in L["available"]])

    def test_done_objective_and_trigger(self):
        c = self.char()
        c["questLog"]["list"][0]["o"][0] = {"text": "Huge Gnoll Claw: 1/1", "done": True}
        c["questLog"]["list"].append({"id": 50, "title": "Lake", "lvl": 8, "done": False, "o": []})
        L = M.quest_layer(self.db, self.idx, 1429, c, "enUS")
        by = {a["qid"]: a for a in L["active"]}
        self.assertEqual(by[176]["spots"], [], "objectives that are done disappear")
        self.assertEqual(by[50]["spots"], [(60.0, 50.0, "Explore the lake")], "exploration objective")

    def test_without_game_data(self):
        L = M.quest_layer(self.db, self.idx, 1429, {"level": 10, "faction": "Alliance"}, "enUS")
        self.assertEqual((L["active"], L["available"]), ([], []))
        self.assertTrue(L["note"])
        self.assertEqual(M.quest_layer(None, self.idx, 1429, self.char(), "enUS")["active"], [])

    def test_colors(self):
        self.assertEqual([M.quest_color(q, 20) for q in (26, 23, 21, 16, 10)], ["red", "orange", "yellow", "green", "gray"])

    def test_search(self):
        hits = M.map_search("copper", self.idx, self.db, "enUS")
        self.assertEqual(hits[0]["kind"], "object")
        self.assertEqual(sorted({p[0] for p in hits[0]["places"]}), [1429, 1436])
        self.assertEqual(M.map_search("elwynn", self.idx)[0]["places"], [(1429, None, None)])
        q = M.map_search("bounty", self.idx, self.db, "enUS")
        self.assertEqual([h["kind"] for h in q], [])                  # no giver -> nothing to show
        q = M.map_search("explore", self.idx, self.db, "enUS")
        self.assertEqual(q[0]["kind"], "quest")
        self.assertEqual(M.map_search("x", self.idx, self.db, "enUS"), [], "too short")


@unittest.skipIf(run_addon_test is None, "needs lupa")
class ImportTests(unittest.TestCase):
    """Was Leeroylink 0.9 schreibt, kommt in Leeroyzan an."""

    def test_sessions_and_state(self):
        import leeroy.api as lz
        db = lz.parse_lua_savedvariables(scenario_sv())["LeeroylinkDB"]
        s = sessions_in_db(db, "_forever_", "1#1")[0]
        m = s["map"]
        self.assertGreaterEqual(len(m["segs"]), 4)
        self.assertEqual(m["segs"][0]["m"], 1433)
        pts = M.parse_route(m["segs"][0]["d"], m["segs"][0]["t"])
        self.assertGreater(len(pts), 15)
        self.assertTrue(all(0 <= x <= 100 and 0 <= y <= 100 for x, y, _ in pts))
        self.assertIn("t", [g["k"] for g in m["segs"]])
        kinds = {p["k"] for p in m["pins"]}
        self.assertTrue({"qa", "rare", "found", "level", "gather", "shot", "death", "boss"} <= kinds, kinds)
        death = next(p for p in m["pins"] if p["k"] == "death")
        self.assertEqual((death["by"], death["lvl"]), ("Edwin VanCleef", 22))
        json.dumps(s)                                   # bleibt JSON-tauglich
        st = lz.link_state_from_dbs([("1#1", db)])
        ch = next(iter(st["chars"].values()))
        self.assertEqual(ch["questsDone"], [7, 33, 176])
        self.assertEqual(ch["pos"]["m"], 1433)
        self.assertEqual(ch["questLog"]["list"][0]["o"][1]["done"], True)
        mi = st["mapIndex"]["maps"]
        self.assertEqual(mi[1433]["name"], "Rotkammgebirge")
        self.assertEqual(mi[1433]["rect"], [0.49, 0.57, 0.66, 0.72])
        self.assertEqual(mi[1415]["type"], 2)

    def test_broken_map_data(self):
        s = normalize_session({"char": "A-B", "start": 100, "map": {"segs": [{"m": 1, "t": 5, "d": "1,2"}, {"m": "x"},
                                                                            {"m": 2, "t": 5, "d": "1,2,3"}],
                                                                   "pins": [{"k": "death"}, {"k": "level", "m": 2, "t": 9, "x": 20000}]}})
        self.assertEqual([g["m"] for g in s["map"]["segs"]], [2])
        self.assertEqual(s["map"]["pins"], [{"k": "level", "m": 2, "t": 9}], "a place needs both coordinates")
        self.assertEqual(normalize_session({"char": "A-B", "start": 100})["map"]["segs"], [], "older sessions: empty")


try:
    import tkinter
    tkinter.Tk().destroy()
    HAS_DISPLAY = True
except Exception:  # noqa: BLE001
    HAS_DISPLAY = False


@unittest.skipUnless(HAS_DISPLAY and run_addon_test is not None, "needs tkinter, a display and lupa")
class MapPageTests(unittest.TestCase):
    def test_page(self):
        import leeroy.api as lz
        wow = TMP / "World of Warcraft"
        sv = wow / "_forever_" / "WTF" / "Account" / "1#1" / "SavedVariables"
        sv.mkdir(parents=True, exist_ok=True)
        (sv / "Leeroylink.lua").write_text(scenario_sv(), encoding="utf-8")
        (wow / "_forever_" / "Interface" / "AddOns").mkdir(parents=True, exist_ok=True)
        shutil.copytree(ROOT / "Leeroylink", wow / "_forever_" / "Interface" / "AddOns" / "Leeroylink", dirs_exist_ok=True)
        (wow / ".build.info").write_text("Branch!STRING:0|Version!STRING:0|Product!STRING:0\neu|1.60.1.1|wow_forever\n")
        lz.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)       # beim Import festgelegt (alle Tests zusammen)
        lz.CONFIG_FILE.write_text(json.dumps({"wow_root": str(wow), "flavor": "_forever_", "language": "de",
                                                     "check_on_start": False, "self_update_mode": "off", "map_period": "all"}),
                                  encoding="utf-8")
        import leeroy.ui.worldmap as W
        old_image = W.map_image
        W.map_image = lambda flavor, area: (None, "missing")          # kein Netz im Test
        errors = []
        app = lz.App()
        app.report_callback_exception = lambda e, v, tb: errors.append("".join(traceback.format_exception(e, v, tb)))

        def pump(sec=1.0, until=None):
            end = time.time() + sec
            while time.time() < end:
                app.update()
                if until and until():
                    return
                time.sleep(0.02)
        try:
            pump(0.5)
            app.show_page("map")
            pump(8, until=lambda: app.map_ui and app._map_layer["routes"])
            self.assertEqual(app.map_ui, 1433, "opens where the character was last")
            self.assertIn("Rotkammgebirge", app.map_crumb_var.get())
            self.assertTrue(app._map_layer["routes"] and app._map_layer["pins"])
            kinds = {h[0] for h in app._map_hit.values()}
            self.assertTrue({"route", "pin", "player"} <= kinds, kinds)
            pin = next(h for h in app._map_hit.values() if h[0] == "pin" and h[1]["k"] == "rare")
            app._map_select(pin)
            self.assertIn("Rohh", app.map_text.get("1.0", "end"))
            app._map_select(("coord", (42.0, 63.5)))
            self.assertIn("/way 42.0 63.5", app.map_text.get("1.0", "end"))
            z = app._map_view["z"]
            app.map_zoom_step(1)
            self.assertGreater(app._map_view["z"], z)
            app.map_fit()
            # Wiedergabe bis zum Ende
            app.map_replay_start(app._map_replay_sids[0])
            pump(25, until=lambda: not app._map_replay["playing"])
            self.assertEqual(app._map_replay["cur"], app._map_replay["t1"])
            app.map_replay_stop(keep=False)
            # Übersicht und zurück
            app.map_up()
            pump(0.3)
            self.assertTrue(app.map_idx.is_continent(app.map_ui))
            zones = [h for h in app._map_hit.values() if h[0] == "zone"]
            self.assertTrue(zones)
            # Suche nach einer Zone
            app.map_search_var.set("Rotkamm")
            app.map_search()
            pump(3, until=lambda: app.map_ui == 1433)
            self.assertEqual(app.map_ui, 1433)
            # Filter und Ebenen
            app.map_period_cb.current(0)
            app._map_filter_changed()
            app.map_layer_vars["route"].set(False)
            app._map_layers_changed()
            self.assertFalse(any(h[0] == "route" for h in app._map_hit.values()))
            app.change_language("en")
            pump(0.3)
            app.show_page("map")
            pump(5, until=lambda: app.map_ui)
            self.assertIn("Map", [b.cget("text") for b in app.nav_buttons.values()])
        finally:
            W.map_image = old_image
            for job in app.tk.splitlist(app.tk.call("after", "info")):
                app.after_cancel(job)
            app.destroy()
        self.assertEqual(errors, [], "\n".join(errors))


if __name__ == "__main__":
    unittest.main()
