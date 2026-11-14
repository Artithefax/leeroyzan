"""Talent planner and guides: Wowhead data file, build rules, links in both directions, guide pages, images.

No network: the Wowhead answers come from tests/talent_fixture.py and tests/guide_fixture.py.
"""
import base64
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("APPDATA", tempfile.mkdtemp(prefix="lz-builds-"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import guide_fixture  # noqa: E402
import talent_fixture as tf  # noqa: E402
from leeroy import guides, images, talents  # noqa: E402
from leeroy.i18n import set_language  # noqa: E402

GUIDE_URL = "https://www.wowhead.com/forever/de/guide/classes/shaman/enhancement/dps-leveling-tips"
JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAA0JCgsKCA0LCgsODg0PEyAVExISEyccHhcgLikxMC4pLSwzOko+MzZGNywtQFdBRkxOUlNSMj5aYVpQYEpRUk//"
    "2wBDAQ4ODhMREyYVFSZPNS01T09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT0//wAARCAAMABADASIAAhEBAxEB/8QA"
    "HwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkK"
    "FhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXG"
    "x8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAEC"
    "AxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOE"
    "hYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDMooorxj6o"
    "/9k=")       # 16x12 pixels


def data(**kw) -> dict:
    d = talents.parse_talent_js(tf.talents_js(**kw))
    d["edition"] = "forever"
    return d


def tid(name: str) -> int:
    return next(r[0] for rows in tf.SHAMAN.values() for r in rows if r[6] == name)


class TalentDataTests(unittest.TestCase):
    def setUp(self):
        set_language("de")

    def test_parse_data_file(self):
        d = data()
        self.assertEqual((d["env"], d["hash_version"]), ("classicplus", "vkndmh"))
        self.assertEqual({k: len(v) for k, v in d["trees"].items()}, {"261": 16, "262": 16, "263": 18})
        enh = d["trees"]["263"]
        self.assertEqual([t["name_en"] for t in enh[:3]], ["Earth's Grasp", "Thundering Strikes", "Ancestral Knowledge"])
        flurry = next(t for t in enh if t["name_en"] == "Flurry")
        self.assertEqual((flurry["max"], flurry["req_points"], flurry["req"]), (5, 15, [[tid("Mental Dexterity"), 3]]))
        self.assertEqual(flurry["desc"][1], "Schlaghagel: Rang 2.")
        with self.assertRaises(ValueError):
            talents.parse_talent_js("<html>blocked</html>")

    def test_classes_and_points(self):
        self.assertEqual(talents.max_talent_points("forever"), 51)
        self.assertEqual(talents.max_talent_points("wotlk"), 71)
        self.assertNotIn("death-knight", [c.slug for c in talents.talent_classes("forever")])
        self.assertIn("death-knight", [c.slug for c in talents.talent_classes("wotlk")])
        self.assertEqual(talents.talent_class("shaman").tabs, [261, 263, 262])
        set_language("en")
        self.assertEqual(talents.talent_class("shaman").trees[1]["name"], "Enhancement")

    def test_cache_and_offline(self):
        calls = []
        orig = talents.wowhead_text
        talents.wowhead_text = lambda url, timeout=20: (calls.append(url), tf.talents_js())[1]
        try:
            d = talents.load_talents("forever", lang="de")
            self.assertEqual(calls, ["https://nether.wowhead.com/forever/de/data/talents-classic"])
            self.assertEqual(talents.load_talents("forever", lang="de")["trees"], d["trees"])
            self.assertEqual(len(calls), 1, "second call must come from the cache")

            def offline(url, timeout=20):
                raise OSError("offline")
            talents.wowhead_text = offline
            self.assertTrue(talents.load_talents("forever", refresh=True, lang="de").get("stale"))
            with self.assertRaises(OSError):
                talents.load_talents("tbc", lang="de")
        finally:
            talents.wowhead_text = orig


class BuildTests(unittest.TestCase):
    def setUp(self):
        set_language("de")
        self.data = data()

    def test_guide_build_round_trip(self):
        b = talents.Build(self.data, "shaman").load(tf.GUIDE_HASH, tf.GUIDE_ORDER)
        self.assertEqual((b.summary(), b.spent, b.required_level, b.notes), ("18/25/8", 51, 60, []))
        self.assertEqual(b.rank(tid("Flurry")), 2)
        self.assertEqual(b.hash(), tf.GUIDE_HASH)
        self.assertEqual(b.order_hash(), tf.GUIDE_ORDER)
        self.assertEqual(b.url("de"), f"https://www.wowhead.com/forever/de/talent-calc/shaman/{tf.GUIDE_HASH}/{tf.GUIDE_ORDER}")
        steps = b.steps()
        self.assertEqual((steps[0]["level"], steps[0]["name"], steps[-1]["level"]), (10, "Donnernde Stöße", 60))

    def test_links(self):
        p = talents.parse_build_link(f"https://www.wowhead.com/forever/de/talent-calc/shaman/{tf.GUIDE_HASH}_r2/{tf.GUIDE_ORDER}?x=1#top")
        self.assertEqual((p["edition"], p["cls"], p["order"]), ("forever", "shaman", tf.GUIDE_ORDER))
        self.assertEqual(talents.parse_build_link("https://www.wowhead.com/classic/talent-calc/mage")["edition"], "classic")
        self.assertEqual(talents.parse_build_link("shaman/abc/def")["hash"], "abc")
        self.assertIsNone(talents.parse_build_link("https://www.wowhead.com/forever/talent-calc/bard/123"))
        self.assertIsNone(talents.parse_build_link("hello world"))
        b = talents.build_from_link(self.data, f"shaman/{tf.GUIDE_HASH}_r2/{tf.GUIDE_ORDER}")
        self.assertEqual((b.summary(), b.extras), ("18/25/8", ["t0", "r2"]))
        self.assertTrue(b.hash().endswith("_t0_r2"))

    def test_rules(self):
        b = talents.Build(self.data, "shaman")
        flurry, dex, strikes = tid("Flurry"), tid("Mental Dexterity"), tid("Thundering Strikes")
        self.assertEqual(b.why_not(flurry), "tree")
        self.assertEqual(b.add(strikes, full=True), 5)
        self.assertEqual(b.add(dex, full=True), 3)
        self.assertEqual(b.add(tid("Ancestral Knowledge"), full=True), 5)
        self.assertEqual(b.add(tid("Elemental Weapons")), 1)
        self.assertEqual(b.add(tid("Improved Lightning Shield")), 1)
        self.assertEqual(b.tree_points(1), 15)
        self.assertTrue(b.can_add(flurry))
        b.add(flurry)
        self.assertFalse(b.can_remove(dex), "Flurry needs 3 points in Mental Dexterity")
        self.assertFalse(b.can_remove(strikes), "Flurry needs 15 points above it")
        self.assertEqual(b.remove(flurry), 1)
        self.assertTrue(b.can_remove(dex))
        b.add(tid("Guardian Totems"))
        b.remove(dex)
        self.assertEqual(b.why_not(flurry), "requires")
        self.assertEqual(b.required_level, 10 + b.spent - 1)
        b.reset(1)
        self.assertEqual((b.spent, b.order, b.hash()), (0, [], ""))

    def test_point_limit_and_order(self):
        b = talents.Build(self.data, "shaman").load(tf.GUIDE_HASH, "")       # no order in the link
        self.assertEqual(len(b.order), 51)
        self.assertTrue(b._order_legal(b.order))
        self.assertEqual(b.why_not(tid("Toughness")), "points")
        self.assertEqual(b.add(tid("Toughness")), 0)
        b.remove(tid("Earthbound"))
        self.assertEqual(b.summary(), "17/25/8")
        self.assertTrue(b._order_legal(b.order))
        again = talents.Build(self.data, "shaman").load(b.hash(), b.order_hash())
        self.assertEqual((again.points, again.order), (b.points, b.order))

    def test_talented_perk_shifts_levels(self):
        b = talents.Build(self.data, "shaman").load("vkndmh-05_t3")
        self.assertEqual((b.talented, b.level_for(1), b.required_level), (3, 7, 11))

    def test_broken_and_old_links(self):
        b = talents.Build(self.data, "shaman").load("vkndmh-0000000000000002")      # Improved Stormstrike without anything else
        self.assertEqual(b.spent, 0)
        self.assertTrue(any(n.startswith("unreachable:") for n in b.notes))
        b = talents.Build(self.data, "shaman").load("zzz999")
        self.assertEqual((b.spent, b.notes), (0, ["version"]))
        b = talents.Build(self.data, "shaman").load("vkndmh05330310201-0520303110212122-053", "1!!!")
        self.assertEqual(b.summary(), "18/25/8", "a bad order must not lose the points")
        old = talents.Build(self.data, "shaman").load("v2-45")         # old layout: second talent was the first then
        self.assertEqual(old.rank(tid("Thundering Strikes")), 4)
        self.assertEqual(old.rank(tid("Ancestral Knowledge")), 5)
        self.assertIn("legacy", old.notes)
        self.assertTrue(old.hash().startswith("vkndmh"))

    def test_edition_without_hash_version(self):
        d = data(hash_version="", old_layout=False)
        d["edition"] = "classic"
        b = talents.Build(d, "shaman").load("05330310201-0520303110212122-053", tf.GUIDE_ORDER)
        self.assertEqual((b.summary(), b.talented), ("18/25/8", 0))
        self.assertEqual(b.url("en"), f"https://www.wowhead.com/classic/talent-calc/shaman/05330310201-0520303110212122-053/{tf.GUIDE_ORDER}")


class GuideTests(unittest.TestCase):
    def setUp(self):
        set_language("de")
        self.guide = guides.parse_guide_html(guide_fixture.guide_html(), GUIDE_URL)

    def test_parse_page(self):
        g = self.guide
        self.assertEqual((g["title"], g["author"], g["updated"], g["edition"]),
                         ("Enhancement Shaman Leveling Guide - WoW Forever", "Yebb", "06.11.2026", "forever"))
        self.assertTrue(g["markup"].startswith("Welcome to the Wowhead"))
        self.assertEqual(g["names"]["spell"]["2645"], {"n": "Geisterwolf"})
        self.assertEqual(g["names"]["item"]["249398"], {"n": "Ikone aus poliertem Treibholz", "q": 3})
        with self.assertRaises(ValueError):
            guides.parse_guide_html("<html><body>Just a moment...</body></html>", GUIDE_URL)

    def test_urls(self):
        self.assertTrue(guides.is_guide_url(GUIDE_URL))
        self.assertFalse(guides.is_guide_url("https://example.org/guide/x"))
        self.assertFalse(guides.is_guide_url("https://www.wowhead.com/forever/de/talent-calc/shaman"))
        self.assertEqual(guides.guide_edition("https://www.wowhead.com/guide/retail-thing"), "")
        self.assertEqual(guides.guide_id(GUIDE_URL + "?x=1#toc"), "forever-de-guide-classes-shaman-enhancement-dps-leveling-tips")

    def test_builds_in_guide(self):
        builds = guides.guide_builds(self.guide)
        self.assertEqual(len(builds), 1)
        self.assertEqual((builds[0]["cls"], builds[0]["edition"], builds[0]["order"]), ("shaman", "forever", tf.GUIDE_ORDER))
        b = talents.build_from_link(data(), builds[0]["link"], builds[0]["edition"])
        self.assertEqual(b.summary(), "18/25/8")

    def test_render(self):
        parts = guides.render_guide(self.guide, "https://www.wowhead.com/forever/de")
        text = "".join(t for t, _ in parts)
        self.assertIn("covers tips & tricks.", text)
        self.assertIn("flexible levelers [1]. Use Geisterwolf and Ikone aus poliertem Treibholz early", text)
        self.assertIn("Erdschock   ·   7", text)
        self.assertIn(" 1. Keep Geisterwolf up\n 2. Use Ruf des Feuers", text)
        self.assertNotIn("evil()", text)
        self.assertNotIn("[", text.replace("[1]", ""))
        self.assertNotIn("\n\n\n", text)
        tags = {t: tg for t, tg in parts}
        self.assertEqual(tags["Leveling as an Enhancement Shaman"], ("h2",))
        self.assertEqual(tags["always"], ("b",))
        self.assertIn("url:https://www.wowhead.com/forever/de/item=249398", tags["Ikone aus poliertem Treibholz"])
        self.assertIn("q3", tags["Ikone aus poliertem Treibholz"])
        self.assertIn("url:https://www.wowhead.com/forever/de/guide/classes/shaman/enhancement/rotation", tags["Rotation"])
        self.assertIn("url:https://example.org/x", tags["this page"])
        self.assertTrue(any("build:0" in tg for tg in tags.values()))

    def test_store(self):
        gid = guides.save_guide(self.guide)
        rows = guides.list_guides()
        self.assertEqual([(r["id"], r["builds"]) for r in rows if r["id"] == gid], [(gid, 1)])
        self.assertEqual(guides.load_guide(gid)["title"], self.guide["title"])
        guides.delete_guide(gid)
        self.assertIsNone(guides.load_guide(gid))

    def test_fetch_checks_address(self):
        with self.assertRaises(ValueError):
            guides.fetch_guide("https://example.org/forever/guide/x")
        orig = guides.wowhead_text
        guides.wowhead_text = lambda url, timeout=20: guide_fixture.guide_html()
        try:
            self.assertEqual(guides.fetch_guide(GUIDE_URL + "#best-builds")["url"], GUIDE_URL)
        finally:
            guides.wowhead_text = orig


class ImageTests(unittest.TestCase):
    def test_addresses(self):
        self.assertEqual(images.icon_url("Spell_Nature_Lightning"), "https://wow.zamimg.com/images/wow/icons/large/spell_nature_lightning.jpg")
        self.assertEqual(images.background_url("classicplus", 263), "https://wow.zamimg.com/images/wow/talents/backgrounds/classicplus/263.jpg")
        self.assertEqual(images.image_path(images.icon_url("a_b"), (40, 40)).name, "images_wow_icons_large_a_b@40x40.png")

    @unittest.skipUnless(images.can_convert(), "needs Windows (GDI+) or Pillow")
    def test_convert_and_cache(self):
        calls = []
        orig = images.wowhead_bytes
        images.wowhead_bytes = lambda url, timeout=20: (calls.append(url), JPEG)[1]
        try:
            url = images.icon_url("test_icon_convert")
            wanted = [(url, (40, 40)), (url, None), (url, (40, 40))]
            self.assertEqual(images.fetch_images(wanted), 2)
            for size, expect in (((40, 40), (40, 40)), (None, (16, 12))):
                raw = images.cached_image(url, size, fetch=False).read_bytes()
                self.assertEqual(raw[:8], b"\x89PNG\r\n\x1a\n")
                self.assertEqual(struct.unpack(">II", raw[16:24]), expect)
            self.assertEqual(len(calls), 1, "the download is kept, other sizes need no network")
            self.assertEqual(images.fetch_images(wanted), 2)
            self.assertEqual(len(calls), 1)

            def broken(url, timeout=20):
                raise OSError("offline")
            images.wowhead_bytes = broken
            self.assertIsNone(images.cached_image(images.icon_url("missing_icon"), (40, 40)))
        finally:
            images.wowhead_bytes = orig


if __name__ == "__main__":
    unittest.main()
