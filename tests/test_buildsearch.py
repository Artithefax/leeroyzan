"""Builds finden: Anfrage verstehen, Guides aus Wowhead-Seiten lesen, einordnen, filtern, Cache und offline.

No network: Wowhead is replaced by small pages in the forms Wowhead uses (Listview data, links, guide markup).
"""
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("APPDATA", tempfile.mkdtemp(prefix="lz-buildsearch-"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import guide_fixture  # noqa: E402
from leeroy import buildsearch as B  # noqa: E402
from leeroy.guides import parse_guide_html  # noqa: E402
from leeroy.i18n import set_language  # noqa: E402

BASE = "https://www.wowhead.com/forever/de"


def hub_page() -> str:
    """Guide-Übersicht der Klasse: eine Listview mit Guide-Zeilen (Schlüssel ohne Anführungszeichen wie bei Wowhead)."""
    rows = [
        {"id": 1, "name": "Enhancement Shaman DPS Leveling Tips - WoW Forever", "url": "/forever/guide/classes/shaman/enhancement/dps-leveling-tips",
         "author": "Woah", "rating": 4.5, "lastEdit": "2026-11-10 12:00:00"},
        {"id": 2, "name": "Restoration Shaman Healer PvE Overview", "url": "/forever/guide/classes/shaman/restoration/overview-pve-healer"},
        {"id": 3, "name": "Shaman PvP Guide", "url": "/forever/guide/classes/shaman/enhancement/dps-pvp-guide"},
        {"id": 4, "name": "Warrior Leveling", "url": "/forever/guide/classes/warrior/leveling-tips"},
        {"id": 5, "name": "Retail Shaman", "url": "/guide/classes/shaman/overview"},
    ]
    data = json.dumps(rows).replace('"id":', "id:").replace('"name":', "name:")
    return ("<html><head><title>Schamanen-Guides</title></head><body><script>"
            f"new Listview({{template: 'guide', id: 'guides', name: 'Guides', data: {data}}});</script>"
            '<a href="/forever/de/guide/classes/shaman/elemental/dps-bis-gear-pve">Elementar BiS</a>'
            '<a href="/forever/de/guides/classes/shaman">alle</a></body></html>')


def search_page() -> str:
    """Wowhead-Suche: nur Links und JSON in einem Skript (anderer Aufbau als die Übersicht)."""
    return ('<div><a class="q" href="https://www.wowhead.com/forever/de/guide/classes/shaman/enhancement/talent-builds-pve-dps">'
            "<span>Enhancement Talent Builds</span></a></div>"
            '<script>var g = {"url":"\\/forever\\/guide\\/classes\\/shaman\\/elemental\\/dps-leveling-tips","name":"Elemental Leveling"};</script>')


class FakeWowhead:
    def __init__(self, pages: dict, fail: bool = False):
        self.pages, self.fail, self.asked = pages, fail, []

    def __call__(self, url):
        self.asked.append(url)
        if self.fail:
            raise urllib.error.URLError("offline")
        for key, page in self.pages.items():
            if key in url:
                return page
        raise urllib.error.HTTPError(url, 404, "not found", {}, None)


class QueryTests(unittest.TestCase):
    def setUp(self):
        set_language("de")

    def test_words(self):
        cases = {"Schamane": ("shaman", "", "", ""), "scharmane": ("shaman", "", "", ""),
                 "scharmane leveling": ("shaman", "", "leveling", ""), "Verstärkung Dungeon": ("shaman", "enhancement", "pve", ""),
                 "druide tank": ("druid", "", "", "tank"), "Druide Wiederherstellung": ("druid", "restoration", "", ""),
                 "Krieger PvP": ("warrior", "", "pvp", ""), "hexer bis": ("warlock", "", "gear", ""),
                 "Jäger Tierherrschaft": ("hunter", "beast-mastery", "", ""), "Paladin Heiler": ("paladin", "", "", "healer"),
                 "warrior prot": ("warrior", "protection", "", "tank"), "Shaman leveling guide": ("shaman", "", "leveling", "")}
        for text, want in cases.items():
            q = B.parse_query(text)
            self.assertEqual((q["cls"], q["spec"], q["cat"], q["role"]), want, text)
        self.assertEqual(B.parse_query("hogger")["rest"], "hogger")
        self.assertEqual(B.describe_query(B.parse_query("scharmane leveling")), "Schamane · Leveling")

    def test_addresses(self):
        self.assertEqual(B.guide_path("/forever/de/guide/classes/shaman/rotation", "forever"), "classes/shaman/rotation")
        self.assertEqual(B.guide_path("guide/classes/shaman/x", "forever"), "classes/shaman/x", "relative markup links")
        for other in ("/classic/guide/classes/shaman/z", "/guide/classes/shaman/a", "/de/guide/classes/shaman/a",
                      "https://www.wowhead.com/forever/guides/classes/shaman", "https://example.org/forever/guide/x"):
            self.assertEqual(B.guide_path(other, "forever"), "", other)

    def test_classify(self):
        def c(path):
            r = B.classify(path)
            return r["cls"], r["spec"], r["cat"], r["role"]
        self.assertEqual(c("classes/shaman/enhancement/dps-leveling-tips"), ("shaman", "enhancement", "leveling", "dps"))
        self.assertEqual(c("classes/shaman/restoration/overview-pve-healer"), ("shaman", "restoration", "pve", "healer"))
        self.assertEqual(c("classes/warrior/protection/tank-bis-gear-pve"), ("warrior", "protection", "gear", "tank"))
        self.assertEqual(c("classes/druid/feral/tank-talent-builds-pve"), ("druid", "feral", "talents", "tank"))
        self.assertEqual(c("classes/priest/holy/healer-rotation-cooldowns-pve")[2], "play")
        self.assertEqual(c("classes/shaman/overview"), ("shaman", "", "overview", ""))
        self.assertEqual(B.classify("season-of-discovery/classes/shaman/x")["variant"], "season-of-discovery")
        self.assertEqual(B.nice_title("classes/shaman/enhancement/dps-leveling-tips"), "Enhancement – DPS Leveling Tips")


class ExtractTests(unittest.TestCase):
    def test_listview_links_and_json(self):
        found = {g["path"]: g for g in B.extract_guides(hub_page(), "forever")}
        self.assertIn("classes/shaman/enhancement/dps-leveling-tips", found)
        self.assertEqual(found["classes/shaman/enhancement/dps-leveling-tips"]["title"], "Enhancement Shaman DPS Leveling Tips")
        self.assertEqual(found["classes/shaman/enhancement/dps-leveling-tips"]["author"], "Woah")
        self.assertEqual(found["classes/shaman/elemental/dps-bis-gear-pve"]["title"], "Elementar BiS")
        self.assertNotIn("classes/shaman/overview", found, "retail guides stay out")
        s = {g["path"]: g["title"] for g in B.extract_guides(search_page(), "forever")}
        self.assertEqual(s, {"classes/shaman/enhancement/talent-builds-pve-dps": "Enhancement Talent Builds",
                             "classes/shaman/elemental/dps-leveling-tips": "Elemental Leveling"})

    def test_markup_navigation(self):
        found = {g["path"]: g["title"] for g in B.extract_guides(guide_fixture.guide_html(), "forever")}
        self.assertEqual(found.get("classes/shaman/enhancement/rotation"), "Rotation")
        self.assertEqual(found.get("classes/shaman/enhancement/overview-pve-dps"), "Spec Overview")

    def test_suggestions(self):
        data = {"results": [{"type": 100, "name": "Shaman Leveling", "url": "/forever/guide/classes/shaman/leveling-tips"},
                            {"type": 1, "name": "Hogger", "id": 448}]}
        self.assertEqual([g["path"] for g in B.suggestion_guides(data, "forever")], ["classes/shaman/leveling-tips"])


class FindTests(unittest.TestCase):
    def setUp(self):
        set_language("de")
        f = B._cache_file("forever", "de")
        if f.exists():
            f.unlink()

    def test_find_sort_filter_cache(self):
        web = FakeWowhead({"/guides/classes/shaman": hub_page(), "/search?q=Shaman": search_page()})
        res = B.find_guides("scharmane", "forever", "de", fetch=web)
        paths = [g["path"] for g in res["guides"]]
        self.assertEqual([g["cat"] for g in res["guides"][:2]], ["leveling", "leveling"], "leveling first")
        self.assertEqual(paths[:2], ["classes/shaman/elemental/dps-leveling-tips", "classes/shaman/enhancement/dps-leveling-tips"],
                         "then by spec")
        self.assertNotIn("classes/warrior/leveling-tips", paths)
        self.assertEqual({g["cat"] for g in res["guides"]}, {"leveling", "pve", "pvp", "talents", "gear"})
        g = res["guides"][1]
        self.assertEqual(g["url"], f"{BASE}/guide/classes/shaman/enhancement/dps-leveling-tips")
        self.assertTrue(any("/guides/classes/shaman" in u for u in web.asked))
        self.assertEqual([u for u in web.asked if "/guide/classes/" in u], [], "enough found: no guide pages fetched")
        # Filter
        q = B.parse_query("schamane leveling")
        self.assertEqual({g["cat"] for g in B.filter_guides(res["guides"], q)}, {"leveling"})
        q = B.parse_query("resto")
        self.assertEqual([g["spec"] for g in B.filter_guides(res["guides"], q)], ["restoration"])
        q = B.parse_query("schamane builds")
        self.assertEqual({g["cat"] for g in B.filter_guides(res["guides"], q)}, {"leveling", "pve", "pvp", "talents"})
        # zweites Mal aus dem Cache, ohne Netz
        web2 = FakeWowhead({}, fail=True)
        again = B.find_guides("Schamane PvP", "forever", "de", fetch=web2)
        self.assertEqual(web2.asked, [])
        self.assertEqual(len(again["guides"]), len(res["guides"]))
        # neu laden ohne Netz: alter Stand, als offline markiert
        stale = B.find_guides("Schamane", "forever", "de", fetch=web2, refresh=True)
        self.assertTrue(stale["offline"])
        self.assertEqual(len(stale["guides"]), len(res["guides"]))

    def test_nothing_and_offline(self):
        with self.assertRaises(urllib.error.URLError):
            B.find_guides("Druide", "forever", "de", fetch=FakeWowhead({}, fail=True))
        res = B.find_guides("Druide", "forever", "de", fetch=FakeWowhead({}))
        self.assertEqual(res["guides"], [])
        self.assertEqual(B.find_guides("Hogger", "forever", "de", fetch=FakeWowhead({}))["guides"], [])

    def test_seed_pages(self):
        """Übersicht und Suche liefern nichts: bekannte Guide-Adressen und ihre Navigation."""
        web = FakeWowhead({"/guide/classes/shaman/enhancement/dps-leveling-tips": guide_fixture.guide_html()})
        res = B.find_guides("Schamane", "forever", "de", fetch=web)
        self.assertEqual(sorted(g["path"] for g in res["guides"]),
                         ["classes/shaman/enhancement/dps-leveling-tips", "classes/shaman/enhancement/overview-pve-dps",
                          "classes/shaman/enhancement/rotation"])

    def test_season_of_discovery(self):
        page = ('<a href="/classic/guide/season-of-discovery/classes/shaman/enhancement/dps-leveling-tips">SoD</a>'
                '<a href="/classic/guide/classes/shaman/leveling-tips">Era</a>')
        web = FakeWowhead({"/guides/classes/shaman": page})
        self.assertEqual([g["title"] for g in B.find_guides("Schamane", "classic", "en", fetch=web)["guides"]], ["Era"])
        f = B._cache_file("classic", "en")
        f.unlink()
        self.assertEqual(len(B.find_guides("Schamane sod", "classic", "en", fetch=web)["guides"]), 2)


class TitledBuildsTests(unittest.TestCase):
    def test_labels(self):
        g = parse_guide_html(guide_fixture.guide_html(), "https://www.wowhead.com/forever/de/guide/classes/shaman/enhancement/dps-leveling-tips")
        builds = B.titled_builds(g)
        self.assertTrue(builds)
        self.assertEqual(builds[0]["label"], "Best Talent Builds")
        self.assertEqual(builds[0]["cls"], "shaman")
        g2 = {"edition": "forever", "markup": "[h2]Leveling[/h2][tabs][tab name=\"Level 10-20\"][talent=shaman/abc][/tab]"
                                              "[tab name=\"Level 60\"][talent=shaman/abcd][/tab][/tabs][h3]Raid[/h3][talent=shaman/x1]"}
        self.assertEqual([b["label"] for b in B.titled_builds(g2)], ["Leveling – Level 10-20", "Leveling – Level 60", "Raid"])


if __name__ == "__main__":
    unittest.main()
