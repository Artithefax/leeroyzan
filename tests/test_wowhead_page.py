"""Mehr Infos in der Wowhead-Vorschau (python3 tests/test_wowhead_page.py): Schnellinfo und Listen aus echten
Seitenausschnitten (tests/wowhead_page_fixture.py) – und die Vorschau im Fenster (Linux: xvfb-run), wo Einträge
der Listen anklickbar sind. Wowhead selbst wird nicht aufgerufen."""
import json
import os
import sys
import tempfile
import time
import traceback
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("APPDATA", str(Path(tempfile.mkdtemp(prefix="lz-whpage-")) / "appdata"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import leeroy.api as lz  # noqa: E402
import wowhead_page_fixture as F  # noqa: E402
from leeroy.i18n import set_language  # noqa: E402

ZONES = {12: "Wald von Elwynn"}


def zone(z):
    return ZONES.get(z, f"#{z}")          # wie QuestieDB: unbekannte Zonen als #Nummer – die bleiben weg


class PageTests(unittest.TestCase):
    def setUp(self):
        set_language("de")

    def lists(self, page):
        return {x["id"]: x for x in lz.parse_wowhead_page(page)["lists"]}

    def test_item_sources(self):
        d = lz.parse_wowhead_page(F.ITEM_2589)
        self.assertEqual(d["facts"], ["Handwerksmaterial", "Seite: Keins", "Hinzugefügt in Patch 1.60.1", "Englische: Linen Cloth"])
        # Reihenfolge wie in WOWHEAD_LISTS, „Siehe auch“ und Kommentare bleiben weg
        self.assertEqual([x["id"] for x in d["lists"]], ["dropped-by", "objective-of", "reagent-for", "contained-in-object"])
        rows = lz.wowhead_list_rows(d["lists"][0], zone)
        # nach Dropchance; 3 von 3 ist Zufall und kommt ans Ende
        self.assertEqual([r["name"] for r in rows], ["Schmuggler der Defias", "Taschendieb der Defias", "Morgaine die Verschlagene",
                                                     "Koboldhilfsarbeiter", "Seltener Kobold"])
        self.assertEqual(rows[0]["info"], "Stufe 11–12 · 33 %")                         # Zone 40 unbekannt: weggelassen
        self.assertEqual(rows[2]["info"], "Stufe 10 · Selten · Wald von Elwynn · 30 %")
        self.assertEqual(rows[4]["info"], "Stufe 5 · Wald von Elwynn · 100 % (wenig Daten)")
        self.assertEqual((rows[0]["kind"], rows[0]["id"]), ("npc", 95))
        self.assertEqual([r["info"] for r in lz.wowhead_list_rows(d["lists"][3])], ["4,1 %", "17 % (wenig Daten)"])
        self.assertEqual(lz.wowhead_list_rows(d["lists"][1])[1]["info"], "Stufe 15 · Horde")
        self.assertEqual(lz.wowhead_list_rows(d["lists"][2])[0]["info"], "ab Fertigkeit 25")
        self.assertEqual(len(lz.wowhead_list_rows(d["lists"][0], limit=2)), 2)
        self.assertEqual(lz.wowhead_list_more(d["lists"][0], 2), "… und 3 weitere auf Wowhead")
        self.assertEqual(lz.wowhead_list_more(d["lists"][0]), "")

    def test_vendor_and_rewards(self):
        d = lz.parse_wowhead_page(F.ITEM_159)
        self.assertEqual(d["facts"][0], "Preis: 23k – 27k")
        self.assertIn("Verbrauchbar", d["facts"])                                       # der Erklärtext dazu fällt weg
        lists = self.lists(F.ITEM_159)
        sold = lists["sold-by"]
        self.assertEqual(sold["total"], 230)                                            # „230 gefunden, 200 angezeigt“
        self.assertEqual(lz.wowhead_list_rows(sold, zone)[0]["info"], "Stufe 10 · Wald von Elwynn · 26k (5 Stück)")
        self.assertEqual(lz.wowhead_list_more(sold), "… und 228 weitere auf Wowhead")
        self.assertEqual([r["name"] for r in lz.wowhead_list_rows(lists["reward-from-q"])], ["Ein Schurkenhandel", "Der Scharlachrote Kreuzzug"])

    def test_npc_and_quest(self):
        d = lz.parse_wowhead_page(F.NPC_448)
        self.assertEqual(d["facts"][:5], ["Stufe: 11", "Einstufung: Elite", "Einstellung: Allianz feindlich, Horde feindlich",
                                          "Art: Humanoid", "Wert: 27k"])
        lists = self.lists(F.NPC_448)
        drops = lz.wowhead_list_rows(lists["drops"])                                    # einzeilige Listen, data:[
        self.assertEqual([(r["name"], r["quality"], r["info"]) for r in drops][:2],
                         [("Zähes Stockfleisch", 1, "4,8 %"), ("Hoggers Halskette", 3, "1,3 %")])
        self.assertEqual(lists["drops"]["total"], 3)                                    # _totalCount zählt Beobachtungen, nicht Einträge
        spells = lz.wowhead_list_rows(lists["abilities"])                               # Schlüssel ohne Anführungszeichen
        self.assertEqual([(r["name"], r["info"]) for r in spells], [("Rüstung durchstechen", ""), ("Sturmattacke", "Rang 1"), ("Kopfnuss", "")])
        q = lz.parse_wowhead_page(F.QUEST_176)
        self.assertEqual(q["lists"], [])
        self.assertIn("Anfang: Steckbrief, Steckbrief", q["facts"])                     # die unsichtbare Wiederholung fällt weg
        self.assertIn("Ende: Marshal Dughan", q["facts"])
        self.assertIn("Questfarbe nach Stufe: rot 5, orange 7, gelb 9, grün 14, grau 17", q["facts"])
        self.assertIn('Englische: GESUCHT: "Hogger"', q["facts"])
        set_language("en")
        self.assertEqual(lz.parse_wowhead_page(F.ITEM_159)["facts"][0], "Preis: 23c – 27c")
        self.assertEqual(lz.wowhead_list_rows(lists["drops"])[0]["info"], "4.8 %")
        self.assertIn("quest colour by level: red 5, orange 7, yellow 9, green 14, grey 17",
                      [f.lower() for f in lz.parse_wowhead_page(F.QUEST_176)["facts"]])

    def test_broken_input(self):
        self.assertEqual(lz.parse_wowhead_page(""), {"facts": [], "lists": []})
        self.assertEqual(lz.parse_wowhead_page("<html>blocked</html>"), {"facts": [], "lists": []})
        cut = F.ITEM_2589[:F.ITEM_2589.index('"outof":7884')]                          # abgebrochene Übertragung
        self.assertEqual([x["id"] for x in lz.parse_wowhead_page(cut)["lists"]], [])
        self.assertEqual(lz.parse_wowhead_page(cut)["facts"][0], "Handwerksmaterial")
        # eine Liste ohne eigene Daten (data: variable) bekommt nicht die der nächsten Liste
        odd = "new Listview({template: 'npc', id: 'sold-by', data: lv_vendors});\n" + F.NPC_448
        self.assertNotIn("sold-by", self.lists(odd))
        self.assertEqual(len(self.lists(odd)["drops"]["rows"]), 3)
        # Zeichenketten bleiben, wie sie sind – auch mit „,wort:“ darin
        self.assertEqual(json.loads(lz.module_of("parse_wowhead_page")._js_to_json('[{a:1,"t":"x,b: y {c:2}",d:{e:[1]}}]')),
                         [{"a": 1, "t": "x,b: y {c:2}", "d": {"e": [1]}}])

    def test_discord(self):
        row = {"kind": "item", "kind_name": "Gegenstand", "id": 159, "name": "Erfrischendes Quellwasser", "quality": 1,
               "url": "https://www.wowhead.com/forever/de/item=159"}
        e = lz.share_wowhead_messages(row, None, page=lz.parse_wowhead_page(F.ITEM_159))[0]["embeds"][0]
        fields = {f["name"]: f["value"] for f in e["fields"]}
        self.assertTrue(fields["Schnellinfo"].startswith("Preis: 23k – 27k"))
        self.assertEqual(fields["Verkauft von"].splitlines(), ["Brog Hamfist – Stufe 10 · 26k (5 Stück)",
                                                               "Bruder Danil – Stufe 5 · 26k (5 Stück)", "… und 228 weitere auf Wowhead"])
        self.assertNotIn("fields", lz.share_wowhead_messages(row, None)[0]["embeds"][0])


try:
    import tkinter
    tkinter.Tk().destroy()
    HAS_DISPLAY = True
except Exception:  # noqa: BLE001 - no tkinter, no display
    HAS_DISPLAY = False


@unittest.skipUnless(HAS_DISPLAY, "needs tkinter and a display")
class PreviewTests(unittest.TestCase):
    def setUp(self):
        lz.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        lz.CONFIG_FILE.write_text(json.dumps({"language": "de", "check_on_start": False, "self_update_mode": "off",
                                             "last_page": "wowhead", "wowhead_edition": "forever"}), encoding="utf-8")
        from leeroy.ui import wowhead as ui
        self.ui, self.calls = ui, []
        self.real = (ui.wowhead_tooltip, ui.fetch_wowhead_page)
        pages = {("item", 2589): F.ITEM_2589, ("npc", 95): F.NPC_448}

        def page(kind, wid, edition):
            self.calls.append((kind, wid, edition))
            if (kind, wid) not in pages:
                raise OSError("offline")
            return lz.parse_wowhead_page(pages[(kind, wid)])
        ui.wowhead_tooltip = lambda kind, wid, edition: {"name": "Leinenstoff", "text": "Leinenstoff\nHandwerkswaren", "quality": 1}
        ui.fetch_wowhead_page = page
        self.errors = []
        self.app = lz.App()
        self.app.report_callback_exception = lambda e, v, tb: self.errors.append("".join(traceback.format_exception(e, v, tb)))

    def tearDown(self):
        self.ui.wowhead_tooltip, self.ui.fetch_wowhead_page = self.real
        for job in self.app.tk.splitlist(self.app.tk.call("after", "info")):
            self.app.after_cancel(job)
        self.app.destroy()
        lz.CONFIG_FILE.unlink(missing_ok=True)

    def pump(self, until, seconds=3.0):
        end = time.time() + seconds
        while time.time() < end and not until():
            self.app.update()
            time.sleep(0.01)
        self.app.update()

    def text(self):
        return self.app.wh_text.get("1.0", "end")

    def test_preview(self):
        app = self.app
        app.show_page("wowhead")
        app.update()
        app.wh_open_entry({"kind": "item", "kind_name": "Gegenstand", "id": 2589, "name": "Leinenstoff", "quality": 1,
                           "edition": "forever", "url": "https://www.wowhead.com/forever/de/item=2589"})
        self.pump(lambda: "Gedroppt von" in self.text())
        text = self.text()
        self.assertIn("Handwerkswaren", text)                       # Kurzinfo
        self.assertIn("Schnellinfo", text)
        self.assertIn("Hinzugefügt in Patch 1.60.1", text)
        self.assertIn("Gedroppt von (5)", text)
        self.assertIn("Schmuggler der Defias  Stufe 11–12 · 33 %", text)
        self.assertIn("Reagenz für (3)", text)
        self.assertNotIn("Lade weitere Infos", text)
        self.assertEqual(self.calls, [("item", 2589, "forever")])
        app.wh_tree.selection_set("0")                                # noch einmal: aus dem Zwischenspeicher
        app._wh_show()
        app.update()
        self.assertEqual(len(self.calls), 1)

        # ein NPC aus „Gedroppt von“ anklicken: er wird oben in die Liste gesetzt und angezeigt
        start = app.wh_text.tag_ranges("whlink:0")[0]
        app.wh_text.see(start)
        app.update()
        x, y, w, h = app.wh_text.bbox(start)
        from types import SimpleNamespace
        app._wh_link_click(SimpleNamespace(x=x + 2, y=y + h // 2))
        self.pump(lambda: "Beute" in self.text())
        self.assertEqual(app.wh_rows[0]["name"], "Schmuggler der Defias")
        self.assertEqual([r["id"] for r in app.wh_rows], [95, 2589])
        self.assertIn("Fähigkeiten (3)", self.text())

        # Seite nicht erreichbar: Kurzinfo bleibt, kein Fehler
        app.wh_open_entry({"kind": "spell", "kind_name": "Zauber", "id": 1, "name": "Etwas", "quality": None,
                           "edition": "forever", "url": "https://www.wowhead.com/forever/de/spell=1"})
        self.pump(lambda: self.text().startswith("Etwas") and "Lade weitere Infos" not in self.text()
                  and "Lade Kurzinfo" not in self.text())
        self.assertIn("Handwerkswaren", self.text())
        self.assertIn("spell=1", self.text())
        self.assertEqual(self.errors, [], "\n".join(self.errors))


if __name__ == "__main__":
    unittest.main(verbosity=2)
