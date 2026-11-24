"""AH-Preise teilen: Export mit Zeitstempel je Preis, Import, Zusammenführen (neuester Preis gewinnt), Gültigkeit,
Auktionshaus-Zeilen mit geteilten Preisen, Data.lua für das Spiel und der Tooltip in Leeroylink.

    python3 -m unittest tests.test_ahshare
"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="lz-ah-"))
os.environ.setdefault("APPDATA", str(TMP / "appdata"))
sys.path.insert(0, str(ROOT))

from leeroy import ahshare as ah  # noqa: E402
from leeroy import auction  # noqa: E402
from leeroy import reports  # noqa: E402
from leeroy.i18n import set_language  # noqa: E402

try:
    from lupa import lua51
except ImportError:
    lua51 = None


def day(ts: float) -> int:
    return ah.ts_day(ts)


NOW = time.time()
TODAY = day(NOW)


def auctionator(entries: dict, mtime: float = NOW) -> dict:
    return {"realms": {"Realm Allianz": entries}, "vendor": {}, "files": 1, "mtime": mtime, "errors": []}


class ExportImportTests(unittest.TestCase):
    def setUp(self):
        set_language("de")
        self.data = auctionator({
            "2589": {"m": 34, "l": {str(TODAY - 1): 40, str(TODAY): 34}, "h": {str(TODAY): 50}, "a": {str(TODAY): 12}},
            "g:6085:1": {"m": 25092, "h": {str(TODAY - 20): 25092}, "l": {}},
            "4306": {"m": 0, "h": {}, "l": {}},
        }, mtime=NOW - 600)

    def test_export_has_a_timestamp_per_price(self):
        d = ah.export_prices(self.data, "Realm Allianz", "Tom", "_forever_", now=NOW)
        self.assertEqual((d["n"], d["by"], d["realm"]), (2, "Tom", "Realm Allianz"))
        price, ts = d["p"]["2589"]
        self.assertEqual(price, 34)
        self.assertLessEqual(ts, int(NOW - 600))                    # nie später, als WoW gespeichert hat
        self.assertEqual(day(d["p"]["6085"][1]), TODAY - 20)         # alter Scan behält sein Datum
        back = ah.parse_prices(ah.prices_to_bytes(d))
        self.assertEqual(back["p"], d["p"])
        self.assertTrue(ah.price_file_name(d).endswith(".lzprices"))

    def test_parse_rejects_junk_and_future(self):
        for junk in (b"", b"[]", b'{"kind": "x", "p": {}}', json.dumps({"kind": ah.PRICE_KIND, "v": 1, "p": {"a": [1, 2]}}).encode()):
            with self.assertRaises(ah.PriceError):
                ah.parse_prices(junk)
        d = ah.parse_prices(json.dumps({"kind": ah.PRICE_KIND, "v": 1, "realm": "R", "p": {"1": [5, NOW + 99999]}}))
        self.assertLessEqual(d["p"]["1"][1], int(time.time()))      # falsche Uhr beim Freund
        with self.assertRaises(ah.PriceError):
            ah.parse_prices(json.dumps({"kind": ah.PRICE_KIND, "v": 99, "p": {"1": [5, 5]}}))

    def test_newest_price_wins_in_any_order(self):
        store = {"realms": {}, "imports": []}
        new = {"realm": "R", "by": "Anna", "at": NOW, "n": 2, "p": {"1": [100, int(NOW - 3600)], "2": [7, int(NOW - 10)]}}
        old = {"realm": "R", "by": "Tom", "at": NOW, "n": 2, "p": {"1": [999, int(NOW - 86400)], "3": [5, int(NOW - 9 * 86400)]}}
        self.assertEqual(ah.merge_prices(store, new), {"new": 2, "newer": 0, "older": 0})
        self.assertEqual(ah.merge_prices(store, old), {"new": 1, "newer": 0, "older": 1})
        self.assertEqual(store["realms"]["R"]["1"][:3], [100, int(NOW - 3600), "Anna"])   # die ältere Datei ändert nichts
        fresh = ah.fresh_prices(store, "R", 7)
        self.assertEqual(set(fresh), {1, 2})                       # 9 Tage alt: zählt nicht mehr
        self.assertEqual(set(ah.fresh_prices(store, "R", 10)), {1, 2, 3})
        self.assertEqual(ah.prune_shared(store, keep_days=5), 1)
        self.assertEqual(len(store["imports"]), 2)

    def test_store_on_disk(self):
        store = ah.load_shared("_forever_")
        ah.merge_prices(store, {"realm": "R", "by": "X", "at": NOW, "n": 1, "p": {"5": [3, int(NOW)]}})
        ah.save_shared("_forever_", store)
        self.assertEqual(ah.load_shared("_forever_")["realms"]["R"]["5"][0], 3)

    def test_discord_links_only(self):
        with self.assertRaises(ah.PriceError):
            ah.fetch_discord_file("https://example.com/x.lzprices")
        self.assertTrue(ah.DISCORD_CDN_RE.match("https://cdn.discordapp.com/attachments/1/2/AH-Preise.lzprices?ex=1&is=2"))


class AuctionRowTests(unittest.TestCase):
    def test_shared_prices_in_rows(self):
        own = {"2589": {"m": 40, "l": {str(TODAY - 3): 40}, "h": {str(TODAY - 3): 40}, "a": {str(TODAY - 3): 5}},
               "4306": {"m": 900, "l": {str(TODAY): 900}, "h": {str(TODAY): 900}, "a": {}}}
        store = {"realms": {"Realm Allianz": {
            "2589": [30, int(NOW - 60), "Anna"],                    # neuer als der eigene Scan → aktueller Preis
            "4306": [100, int(NOW - 2 * 86400), "Tom"],              # älter → nur Verlauf
            "118": [5, int(NOW - 120), "Tom"],                       # nur beim Freund
            "765": [9, int(NOW - 30 * 86400), "Tom"]}}}              # zu alt → zählt nicht
        data = auction.with_shared_prices(auctionator(own), store, 7)
        rows = {r["id"]: r for r in auction.auction_rows(data, None, None, {}, "deDE")["Realm Allianz"]}
        self.assertEqual((rows[2589]["price"], rows[2589]["last"]), (30, TODAY))
        self.assertTrue(rows[2589]["shared"]["current"])
        self.assertEqual(rows[4306]["price"], 900)
        self.assertFalse(rows[4306]["shared"]["current"])
        self.assertIn(TODAY - 2, [d for d, *_ in rows[4306]["hist"]])
        self.assertEqual(rows[118]["price"], 5)
        self.assertNotIn(765, rows)
        self.assertIsNone(auction.auction_rows(auctionator(own), None, None, {}, "deDE")["Realm Allianz"][0]["shared"])

    def test_game_payload(self):
        store = {"realms": {"R": {"1": [5, int(NOW), "Tom"], "2": [6, int(NOW), "Anna"], "3": [1, int(NOW - 99 * 86400), "Tom"]}}}
        g = ah.game_prices(store, 7)
        self.assertEqual(g["days"], 7)
        self.assertEqual(set(g["realms"]["R"]), {1, 2})
        p, ts, who = g["realms"]["R"][1].split(":")
        self.assertEqual((int(p), g["by"][int(who) - 1]), (5, "Tom"))
        self.assertEqual(ah.game_prices({"realms": {}}), {})


class DiscordFileTests(unittest.TestCase):
    def test_multipart_upload(self):
        sent = {}

        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b""

        def fake(req, timeout=0):
            sent["ctype"] = req.headers.get("Content-type")
            sent["body"] = req.data
            return Resp()
        orig = reports.urllib.request.urlopen
        reports.urllib.request.urlopen = fake
        try:
            reports.discord_send("https://discord.com/api/webhooks/1/abc", {"content": "hi"},
                                 file=("AH-Preise_R.lzprices", b'{"x":1}'))
        finally:
            reports.urllib.request.urlopen = orig
        self.assertTrue(sent["ctype"].startswith("multipart/form-data; boundary="))
        self.assertIn(b'name="payload_json"', sent["body"])
        self.assertIn(b'filename="AH-Preise_R.lzprices"', sent["body"])
        self.assertIn(b'{"x":1}', sent["body"])

    def test_message(self):
        from leeroy.discordshare import share_prices_message
        set_language("de")
        d = {"realm": "R", "n": 3, "p": {"1": [1, 100], "2": [1, 200]}}
        msg = share_prices_message(d, "WoW Forever", "", "Tom")
        self.assertIn("AH-Preise übernehmen", msg["content"])
        self.assertEqual(msg["embeds"][0]["author"]["name"], "geteilt von Tom")
        self.assertIn("<t:200:R>", [f["value"] for f in msg["embeds"][0]["fields"]])


@unittest.skipIf(lua51 is None, "lupa not installed")
class GameTooltipTests(unittest.TestCase):
    def test_shared_price_in_tooltip(self):
        """Leeroylink zeigt den Preis eines Freundes, wenn er neuer ist als der eigene – und nie, wenn er zu alt ist."""
        lua = lua51.LuaRuntime(unpack_returned_tuples=True)
        lua.globals().TESTS_DIR = str(ROOT / "tests")
        addon = (ROOT / "Leeroylink").as_posix()
        res = lua.execute(f'''
            dofile(TESTS_DIR .. "/wow_stub.lua")
            STUB.loadAddon("{addon}")
            LeeroylinkImport = {{ schema = 1, generated = 1, sharedPrices = {{ days = 7, by = {{ "Anna" }}, realms = {{
                ["Realm Horde"] = {{ [2589] = "1:" .. STUB.now .. ":1" }},
                ["Realm Alliance"] = {{ [2589] = "34:" .. (STUB.now - 60) .. ":1", [765] = "9:" .. (STUB.now - 8 * 86400) .. ":1" }},
            }} }} }}
            STUB.fire("ADDON_LOADED", "Leeroylink")
            STUB.fire("PLAYER_LOGIN")
            local P = _G.Leeroylink.modules.Prices
            local p, t, by = P:Shared(2589)
            local old = P:Shared(765)
            P:Record(2589, 50)                 -- eigener Preis, jetzt: neuer als der geteilte
            return p, by, old == nil
        ''')
        self.assertEqual(tuple(res), (34, "Anna", True))           # Allianz-Tabelle (eigene Fraktion), zu alt = nichts


if __name__ == "__main__":
    unittest.main()
