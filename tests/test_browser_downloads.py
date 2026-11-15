"""Gesperrte CurseForge-Downloads (python3 tests/test_browser_downloads.py, Linux: xvfb-run): Leeroyzan öffnet die
Download-Seiten nacheinander – die nächste, sobald die vorige Datei im Download-Ordner liegt und installiert ist –,
und „Nächste Seite“, „Alle Seiten öffnen“ und „Nicht mehr warten“ halten die Kette am Laufen. Der Browser ist eine
Attrappe: Die „Downloads“ legt der Test selbst in den Download-Ordner."""
import json
import os
import sys
import tempfile
import time
import traceback
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="lz-browserdl-"))
os.environ.setdefault("APPDATA", str(TMP / "appdata"))
sys.path.insert(0, str(ROOT))

try:
    import tkinter
    tkinter.Tk().destroy()
    HAS_DISPLAY = True
except Exception:  # noqa: BLE001 - no tkinter, no display
    HAS_DISPLAY = False

if HAS_DISPLAY:
    import leeroy.api as lz


def item(n: int) -> dict:
    name = f"Addon{n}"
    info = {"mod_id": 1000 + n, "slug": f"addon-{n}", "repo": name, "author": "Test", "allow_dl": False,
            "page": f"https://www.curseforge.com/wow/addons/addon-{n}"}
    asset = {"name": f"{name} 1.{n}", "file_name": f"{name}-1.{n}.zip", "file_id": 5000 + n,
             "game_versions": ["1.60.1"], "release_type": 1}
    return {"name": name, "info": info, "asset": asset, "page": lz.cf_download_url(info, asset)}


@unittest.skipUnless(HAS_DISPLAY, "needs tkinter and a display")
class BrowserChainTests(unittest.TestCase):
    def setUp(self):
        self.wow = TMP / f"wow{time.time_ns()}"
        (self.wow / "_forever_" / "Interface" / "AddOns").mkdir(parents=True)
        (self.wow / "_forever_" / "WTF").mkdir(parents=True)
        (self.wow / ".build.info").write_text("Branch!STRING:0|Version!STRING:0|Product!STRING:0\neu|1.60.1.1|wow_forever\n")
        self.dl = TMP / f"downloads{time.time_ns()}"
        self.dl.mkdir()
        lz.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        lz.CONFIG_FILE.write_text(json.dumps({
            "wow_root": str(self.wow), "flavor": "_forever_", "language": "de", "check_on_start": False,
            "self_update_mode": "off", "download_dir": str(self.dl)}), encoding="utf-8")
        self.errors = []
        self.app = lz.App()
        self.app.report_callback_exception = lambda e, v, tb: self.errors.append("".join(traceback.format_exception(e, v, tb)))
        self.opened = []
        self.app.open_link = self.opened.append
        self.app.DL_POLL_MS = 50

    def tearDown(self):
        for job in self.app.tk.splitlist(self.app.tk.call("after", "info")):
            self.app.after_cancel(job)
        self.app.destroy()
        lz.CONFIG_FILE.unlink(missing_ok=True)

    def pump(self, until, seconds=5.0):
        end = time.time() + seconds
        while time.time() < end and not until():
            self.app.update()
            time.sleep(0.02)
        self.app.update()
        return until()

    def download(self, it: dict):
        """Der Browser legt die Datei ab (wie nach dem Klick auf „Download“)."""
        name = it["name"]
        with zipfile.ZipFile(self.dl / it["asset"]["file_name"], "w") as zf:
            zf.writestr(f"{name}/{name}.toc", "## Interface: 16001\n## Version: 1\n")

    def installed(self, it: dict) -> bool:
        src = self.app.sources().get(lz.CF_PREFIX + str(it["info"]["mod_id"]))
        return bool(src and src.get("file_id") == it["asset"]["file_id"])

    def banner(self) -> str:
        b = self.app.banners.get("browser")
        return b._wrap_label.cget("text") if b is not None else ""

    def test_chain(self):
        app = self.app
        self.pump(lambda: not app.busy, 2)
        items = [item(n) for n in (1, 2, 3)]
        app.run_download_queue(items, "Im Browser laden:")
        self.assertEqual(self.opened, [items[0]["page"]])                       # nur die erste Seite
        self.assertIn("Datei 1 von 3: Addon1", self.banner())
        self.assertIn("Noch offen: Addon1, Addon2, Addon3", self.banner())

        # Datei 1 kommt an: installiert, dann öffnet sich von selbst die nächste Seite
        self.download(items[0])
        self.assertTrue(self.pump(lambda: self.installed(items[0]) and len(self.opened) == 2), self.opened)
        self.assertEqual(self.opened[1], items[1]["page"])
        self.assertTrue(self.pump(lambda: "Datei 2 von 3: Addon2" in self.banner()), self.banner())

        # „Nächste Seite“: nicht auf Datei 2 warten; Datei 3 kommt zuerst, dann Datei 2
        app.chain_open_next(skip=True)
        self.assertEqual(self.opened[2], items[2]["page"])
        self.download(items[2])
        self.assertTrue(self.pump(lambda: self.installed(items[2])))
        self.assertEqual(len(self.opened), 3)                                   # alle Seiten sind schon offen
        self.download(items[1])
        self.assertTrue(self.pump(lambda: self.installed(items[1]) and "browser" not in app.banners), self.banner())
        self.assertEqual(app.dl_chain, [])
        self.assertEqual(len(self.opened), 3)

        # neue Runde: „Alle Seiten öffnen“, eine wird nicht mehr abgewartet
        self.opened.clear()
        more = [item(n) for n in (4, 5, 6)]
        app.run_download_queue(more, "Im Browser laden:")
        app.chain_open_all()
        self.assertEqual(self.opened, [it["page"] for it in more])
        self.assertIn("Alle 3 Download-Seiten sind offen", self.banner())
        sid5 = lz.CF_PREFIX + str(more[1]["info"]["mod_id"])
        app.dl_watch.pop(sid5, None)                                            # „Nicht mehr warten“
        app._chain_after(sid5)
        self.assertEqual(len(app.dl_chain), 2)
        for it in (more[0], more[2]):
            self.download(it)
        self.assertTrue(self.pump(lambda: self.installed(more[0]) and self.installed(more[2]) and not app.dl_chain))
        self.assertNotIn("browser", app.banners)
        self.assertEqual(self.errors, [], "\n".join(self.errors))


if __name__ == "__main__":
    unittest.main(verbosity=2)
