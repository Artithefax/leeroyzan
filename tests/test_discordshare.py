"""An Discord teilen (python3 tests/test_discordshare.py): die Nachrichten für Builds, Guides, Wowhead, Quests,
Charaktere und Addon-Listen, Discords Grenzen, Vorschau, Senden – und die Knöpfe im echten Fenster
(Linux: xvfb-run; ohne Anzeige laufen nur die Logik-Tests)."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("APPDATA", str(Path(tempfile.mkdtemp(prefix="lz-dshare-")) / "appdata"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import guide_fixture  # noqa: E402
import leeroy.api as lz  # noqa: E402
import talent_fixture as tf  # noqa: E402
from leeroy import discordshare as ds  # noqa: E402
from leeroy.guides import parse_guide_html  # noqa: E402
from leeroy.i18n import set_language  # noqa: E402
from test_builds import GUIDE_URL, data  # noqa: E402

HOOK = "https://discord.com/api/webhooks/123/abc-DEF"


def check_limits(test, msgs):
    for m in msgs:
        test.assertEqual(m["allowed_mentions"], {"parse": []})        # nie @everyone, @here, Rollen oder Personen
        test.assertEqual(m["username"], "Leeroyzan")
        test.assertLessEqual(len(m.get("content", "")), ds.CONTENT_MAX)
        test.assertTrue(m.get("content") or m.get("embeds"))
        for e in m.get("embeds", []):
            test.assertLessEqual(ds._embed_len(e), ds.EMBED_TOTAL_MAX)
            test.assertLessEqual(len(e["title"]), ds.TITLE_MAX)
            test.assertLessEqual(len(e.get("description", "")), ds.DESC_MAX)
            test.assertLessEqual(len(e.get("fields", [])), ds.FIELDS_MAX)
            for f in e.get("fields", []):
                test.assertTrue(f["value"])
                test.assertLessEqual(len(f["value"]), ds.FIELD_MAX)
        json.dumps(m)


class MessageTests(unittest.TestCase):
    def setUp(self):
        set_language("de")

    def shaman(self):
        return lz.Build(data(), "shaman", "forever").load(tf.GUIDE_HASH, tf.GUIDE_ORDER)

    def test_build(self):
        b = self.shaman()
        msgs = ds.share_build_messages(b, "Leveling Verstärker", "Für Tom", "Rosenbert")
        check_limits(self, msgs)
        (m,) = msgs
        e = m["embeds"][0]
        self.assertEqual((e["title"], e["url"], m["content"]), ("Leveling Verstärker", b.url(), "Für Tom"))
        self.assertEqual(e["author"]["name"], "geteilt von Rosenbert")
        self.assertEqual(e["color"], 0x0070DD)                          # Schamanenblau aus den Klassendaten
        self.assertTrue(e["thumbnail"]["url"].endswith("/class_shaman.jpg"))
        self.assertIn("18/25/8", e["description"])
        self.assertIn("51 Punkte", e["description"])
        names = [f["name"] for f in e["fields"]]
        self.assertEqual([n for n in names if n[-2:-1].isdigit()], ["Elementar (18)", "Verstärkung (25)", "Wiederherstellung (8)"])
        self.assertIn("Reihenfolge (Anfang)", names)
        enh = next(f for f in e["fields"] if f["name"].startswith("Verstärkung"))
        self.assertIn("Donnernde Stöße 5/5", enh["value"])
        # ohne Namen: Klasse und Punkte; ohne Punkte: keine Stufe, keine Felder
        b.reset()
        e = ds.share_build_messages(b)[0]["embeds"][0]
        self.assertEqual(e["title"], "Schamane-Build 0/0/0")
        self.assertNotIn("fields", e)
        self.assertNotIn("content", ds.share_build_messages(b)[0])
        set_language("en")
        self.assertIn("points", ds.share_build_messages(self.shaman())[0]["embeds"][0]["description"])

    def test_guide(self):
        g = parse_guide_html(guide_fixture.guide_html(), GUIDE_URL)
        g["edition"] = "forever"
        (m,) = ds.share_guide_messages(g)
        check_limits(self, [m])
        e = m["embeds"][0]
        self.assertEqual((e["title"], e["url"]), (g["title"], GUIDE_URL))
        self.assertTrue(e["description"])
        self.assertLessEqual(len(e["description"]), 600)
        builds = next(f for f in e["fields"] if f["name"] == "Talent-Builds im Guide")
        self.assertIn("](https://www.wowhead.com/forever/de/talent-calc/shaman/", builds["value"])
        self.assertIn("Yebb", next(f for f in e["fields"] if f["name"] == "Autor")["value"])

    def test_wowhead(self):
        row = {"kind": "item", "kind_name": "Gegenstand", "id": 19019, "name": "Donnerzorn", "quality": 5,
               "url": "https://www.wowhead.com/classic/de/item=19019"}
        tip = {"name": "Donnerzorn, Gesegnete Klinge des Windsuchers", "quality": 5, "icon": "INV_Sword_39",
               "text": "Donnerzorn, Gesegnete Klinge des Windsuchers\nBeim Aufheben gebunden\nEinhand\n@everyone"}
        (m,) = ds.share_wowhead_messages(row, tip, "<@123> guck")
        check_limits(self, [m])
        e = m["embeds"][0]
        self.assertEqual(e["title"], tip["name"])
        self.assertTrue(e["description"].startswith("Beim Aufheben gebunden"))   # der Name steht nicht doppelt
        self.assertEqual(e["color"], 0xFF8000)                                   # legendär
        self.assertTrue(e["thumbnail"]["url"].endswith("/large/inv_sword_39.jpg"))
        self.assertEqual(e["footer"]["text"].split(" · ")[:2], ["Gegenstand", "ID 19019"])
        # ohne Kurzinfo: Name aus der Suche, gewöhnliche Qualität in Gold
        e = ds.share_wowhead_messages(dict(row, quality=1), None)[0]["embeds"][0]
        self.assertEqual((e["title"], e["color"]), ("Donnerzorn", ds.DISCORD_COLOR))
        self.assertNotIn("thumbnail", e)

    def test_text_and_char(self):
        text = "Die Verteidigung von Westfall\nStufe 14 · Westfall\n\n\n\nBelohnung\n" + "x" * 3000
        (m,) = ds.share_text_messages("Die Verteidigung von Westfall", text, "https://www.wowhead.com/classic/de/quest=155",
                                      "Quest · ID 155")
        check_limits(self, [m])
        e = m["embeds"][0]
        self.assertTrue(e["description"].startswith("Stufe 14"))
        self.assertNotIn("\n\n\n", e["description"])
        self.assertLessEqual(len(e["description"]), ds.SHARE_DESC)
        c = {"name": "Rosenbert", "level": 22, "class": "WARRIOR", "race": "Mensch", "realm": "Realm", "guild": "Die Tapferen",
             "money": 123456, "skills": [{"name": "Bergbau", "rank": 120, "max": 150}, {"name": "Einhandschwerter", "rank": 80, "max": 110}]}
        e = ds.share_char_messages(c, 7200, 3)[0]["embeds"][0]
        self.assertEqual((e["title"], e["color"]), ("Rosenbert", 0xC69B6D))
        self.assertIn("Stufe 22 · Krieger", e["description"])
        self.assertIn("<Die Tapferen>", e["description"])
        values = {f["name"]: f["value"] for f in e["fields"]}
        self.assertEqual(values["Berufe"], "Bergbau 120/150")                 # Waffenfertigkeiten sind kein Beruf
        self.assertNotIn("Gold", values)                                      # Gold nur auf Wunsch
        self.assertIn("Gold", {f["name"] for f in ds.share_char_messages(c, with_gold=True)[0]["embeds"][0]["fields"]})

    def test_addons(self):
        addons = [SimpleNamespace(name=n) for n in ("Questie", "Bagnon", "Mein_Kram", "Leatrix_Plus")]
        sources = {"cf:1": {"type": "curseforge", "mod_id": 334372, "name": "Questie", "slug": "questie", "folders": ["Questie"]},
                   "Bagnon/Bagnon": {"type": "github", "folders": ["Bagnon"]},
                   "cf:2": {"type": "curseforge", "mod_id": 2, "name": "Leatrix *Plus*", "slug": "leatrix-plus", "folders": ["Leatrix_Plus"]}}
        payload, unlinked = lz.build_list(addons, sources, "_forever_", {})
        parts = lz.list_to_code(payload, 1800)
        msgs = ds.share_addons_messages(payload, parts, unlinked, "WoW Forever", "Meine Liste")
        check_limits(self, msgs)
        self.assertEqual(len(msgs), 1 + len(parts))
        e = msgs[0]["embeds"][0]
        self.assertEqual(e["title"], "3 Addons für WoW Forever")
        self.assertIn("• [Questie](https://www.curseforge.com/wow/addons/questie)", e["description"])
        self.assertIn("[Leatrix \\*Plus\\*]", e["description"])                     # Formatierung entschärft
        self.assertIn("(https://github.com/Bagnon/Bagnon) (GitHub)", e["description"])
        self.assertEqual(e["fields"][0]["value"], "Mein\\_Kram")
        self.assertIn("Teilen → Empfangen", msgs[0]["content"])
        # der Code aus Discord lässt sich in Leeroyzan wieder einlesen
        pasted = "\n".join(m["content"] for m in msgs[1:])
        self.assertEqual(lz.parse_list_text(pasted)["a"], payload["a"])
        # viele Addons: lange Liste gekürzt, Code auf mehrere Nachrichten verteilt
        many = [SimpleNamespace(name=f"Addon{i}") for i in range(150)]
        srcs = {f"cf:{i}": {"type": "curseforge", "mod_id": 1000 + i, "name": f"Ein ziemlich langer Addonname Nummer {i}",
                            "slug": f"addon-mit-langem-namen-{i}", "folders": [f"Addon{i}"]} for i in range(150)}
        payload, unlinked = lz.build_list(many, srcs, "_forever_", {})
        parts = lz.list_to_code(payload, 1800)
        self.assertGreater(len(parts), 1)
        msgs = ds.share_addons_messages(payload, parts, unlinked)
        check_limits(self, msgs)
        desc = msgs[0]["embeds"][0]["description"]
        shown = desc.count("\n• ") + 1
        self.assertLess(shown, ds.SHARE_LIST_MAX + 1)
        self.assertTrue(desc.endswith(f"… und {150 - shown} weitere"))           # die Anzahl stimmt
        self.assertTrue(msgs[2]["content"].startswith("Code, Teil 2 von"))
        self.assertEqual(len(lz.parse_list_text("\n".join(m["content"] for m in msgs[1:]))["a"]), 150)

    def test_limits_preview_send(self):
        e = ds.share_embed("T" * 400, description="D" * 9000, fields=[(f"F{i}", "v" * 2000) for i in range(30)])
        check_limits(self, [ds.share_message(e, "c" * 3000)])
        self.assertTrue(e["title"].endswith("…"))
        msgs = ds.share_addons_messages({"a": [{"t": "c", "i": 1, "n": "A", "s": "a"}]}, ["LZ1:1/1:ABC"], [], "", "Hallo", "Rosi")
        text = ds.share_preview(msgs)
        self.assertTrue(text.startswith("Hallo"))
        self.assertIn("geteilt von Rosi", text)
        self.assertIn("• A", text)                       # Links in der Vorschau als schlichter Text
        self.assertIn("LZ1:1/1:ABC", text)
        sent, waits = [], []
        orig = ds.discord_send
        ds.discord_send = lambda url, m, sleep=None: sent.append((url, m))
        try:
            self.assertEqual(ds.share_send(HOOK, msgs, sleep=waits.append), 2)
        finally:
            ds.discord_send = orig
        self.assertEqual(([u for u, _ in sent], waits), ([HOOK, HOOK], [ds.SHARE_GAP]))


try:
    import tkinter
    tkinter.Tk().destroy()
    HAS_DISPLAY = True
except Exception:  # noqa: BLE001 - no tkinter, no display
    HAS_DISPLAY = False

if HAS_DISPLAY:
    from test_builds_gui import LINK, BuildsPageTests

    @unittest.skipUnless(HAS_DISPLAY, "needs tkinter and a display")
    class ShareButtonsTests(BuildsPageTests):
        """Die Knöpfe „Discord ↗“ im echten Fenster – gesendet wird an eine Attrappe."""
        test_planner_and_guides = test_wowhead_unreachable = None

        def setUp(self):
            super().setUp()
            from leeroy.ui import discordshare as uds
            self.uds, self.sent, self.dialogs = uds, [], []
            self.real_send = uds.share_send
            uds.share_send = lambda url, msgs, sleep=None: (self.sent.append((url, msgs)), len(msgs))[1]
            self.answer, self.comment, self.tick = True, "", False
            app = self.app

            def fake_dialog(text, kind, buttons, extra=None, default=None):
                frame = tkinter.Frame(app)
                extra(frame, "#000000")
                app.update()
                widgets = []
                stack = [frame]
                while stack:
                    w = stack.pop()
                    widgets.append(w)
                    stack.extend(w.winfo_children())
                if self.tick:
                    next(w for w in widgets if isinstance(w, tkinter.Checkbutton)).invoke()
                entry = next(w for w in widgets if w.winfo_class() == "TEntry")
                entry.insert(0, self.comment)
                preview = next(w for w in widgets if isinstance(w, tkinter.Text)).get("1.0", "end")
                self.dialogs.append((text, preview))
                frame.destroy()
                return self.answer
            app._wait_inline = fake_dialog

        def tearDown(self):
            self.uds.share_send = self.real_send
            super().tearDown()
            lz.CONFIG_FILE.unlink(missing_ok=True)       # keine Webhooks für die folgenden Tests übrig lassen

        def last(self):
            self.pump(lambda: bool(self.sent), 2)
            return self.sent[-1]

        def test_share_buttons(self):
            app = self.app
            self.pump(lambda: app.bld_build is not None)

            # ohne Webhook: Hinweis, nichts gesendet
            app.bld_link_var.set(LINK + tf.GUIDE_HASH + "/" + tf.GUIDE_ORDER)
            app.bld_paste()
            self.pump(lambda: app.bld_build.spent == 51)
            app.share_build_discord()
            self.assertEqual((self.sent, self.dialogs), ([], []))

            # Build: Vorschau mit Kommentar, gesendet an den Sitzungs-Kanal
            app.cfg["discord_webhook"] = HOOK
            self.comment = "Mein Leveling-Build"
            app.share_build_discord()
            url, msgs = self.last()
            self.assertEqual(url, HOOK)
            self.assertEqual(msgs[0]["content"], "Mein Leveling-Build")
            self.assertEqual(msgs[0]["embeds"][0]["url"], app.bld_build.url())
            self.assertIn("Build Schamane 18/25/8 an Discord senden?", self.dialogs[-1][0])
            self.assertIn("18/25/8", self.dialogs[-1][1])
            self.assertIn("Mein Leveling-Build", self.dialogs[-1][1])          # die Vorschau folgt dem Kommentar

            # eigener Kanal und Name fürs Teilen; Abbrechen sendet nichts
            app.discord_share_var.set("https://discord.com/api/webhooks/9/teilen")
            app.discord_share_name_var.set("Rosi")
            app._save_discord_share()
            self.comment = ""
            app.share_build_discord()
            url, msgs = self.last()
            self.assertEqual((url, msgs[0]["embeds"][0]["author"]["name"]), ("https://discord.com/api/webhooks/9/teilen", "geteilt von Rosi"))
            self.answer = False
            n = len(self.sent)
            app.share_build_discord()
            self.pump(seconds=0.2)
            self.assertEqual(len(self.sent), n)
            self.answer = True

            # Guide
            app.bld_link_var.set(GUIDE_URL)
            app.bld_paste()
            self.pump(lambda: bool(app.gd_rows) and app.gd_current is not None)
            self.assertEqual(str(app.gd_discord_btn["state"]), "normal")
            app.share_guide_discord()
            self.assertEqual(self.last()[1][0]["embeds"][0]["url"], GUIDE_URL)

            # Wowhead-Treffer mit Kurzinfo
            row = {"kind": "item", "kind_name": "Gegenstand", "id": 19019, "name": "Donnerzorn", "quality": 5,
                   "edition": app._wh_edition_key(), "url": "https://www.wowhead.com/classic/de/item=19019"}
            app.wh_tips[(row["edition"], "item", 19019)] = {"name": "Donnerzorn", "text": "Einhand", "quality": 5, "icon": "inv_sword_39"}
            app._wh_fill([row])
            app.wh_tree.selection_set("0")
            app.update()
            self.assertEqual(str(app.wh_discord_btn["state"]), "normal")
            app.share_wowhead_discord()
            e = self.last()[1][0]["embeds"][0]
            self.assertEqual((e["title"], e["description"]), ("Donnerzorn", "Einhand"))

            # Charakter, mit Gold per Häkchen
            app.link_state["chars"] = {"Rosenbert-Realm": {
                "key": "Rosenbert-Realm", "name": "Rosenbert", "realm": "Realm", "class": "WARRIOR", "level": 22, "race": "",
                "guild": "", "money": 98765, "lastSeen": 1794300000, "skills": [], "recipes": {}, "bags": {}, "bank": {}, "bankSeen": False}}
            app.refresh_characters()
            self.assertEqual(str(app.chars_discord_btn["state"]), "normal")
            self.tick = True
            app.share_char_discord()
            fields = {f["name"]: f["value"] for f in self.last()[1][0]["embeds"][0].get("fields", [])}
            self.assertEqual(fields.get("Gold"), lz.fmt_money(98765))
            self.tick = False

            # Addons aus der Liste (Rechtsklick): ohne Quelle nur Namen, kein Code
            app.share_addons_discord([SimpleNamespace(name="Mein_Kram", title="Mein Kram")])
            msgs = self.last()[1]
            self.assertEqual(len(msgs), 1)
            self.assertIn("Mein\\_Kram", msgs[0]["embeds"][0]["fields"][0]["value"])
            self.assertIn("Addon „Mein Kram“ an Discord senden?", self.dialogs[-1][0])
            self.assertEqual(self.errors, [], "\n".join(self.errors))


if __name__ == "__main__":
    unittest.main(verbosity=2)
