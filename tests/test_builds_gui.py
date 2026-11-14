"""The Builds page in the real window: load a build from a Wowhead link, click talents, save builds, save a guide
and open its build in the planner. Needs a display (Linux: xvfb-run); Wowhead is replaced by the fixtures."""
import json
import logging
import os
import sys
import tempfile
import time
import traceback
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("APPDATA", str(Path(tempfile.mkdtemp(prefix="lz-buildsgui-")) / "appdata"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

try:
    import tkinter
    tkinter.Tk().destroy()
    HAS_DISPLAY = True
except Exception:  # noqa: BLE001 - no tkinter, no display
    HAS_DISPLAY = False

if HAS_DISPLAY:
    import guide_fixture
    import talent_fixture as tf
    import leeroy.api as lz
    from leeroy import guides, images, talents
    from test_builds import GUIDE_URL, JPEG, tid

LINK = "https://www.wowhead.com/forever/de/talent-calc/shaman/"


@unittest.skipUnless(HAS_DISPLAY, "needs tkinter and a display")
class BuildsPageTests(unittest.TestCase):
    def setUp(self):
        cfg_dir = Path(os.environ["APPDATA"]) / "Leeroyzan"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        lz.CONFIG_FILE.write_text(json.dumps({"language": "de", "check_on_start": False, "self_update_mode": "off",
                                             "last_page": "builds"}), encoding="utf-8")
        for f in guides.guides_dir().glob("*.json") if guides.guides_dir().is_dir() else []:
            f.unlink()
        self.patched = [(talents, "wowhead_text", talents.wowhead_text), (guides, "wowhead_text", guides.wowhead_text),
                        (images, "wowhead_bytes", images.wowhead_bytes)]
        talents.wowhead_text = lambda url, timeout=20: tf.talents_js()
        guides.wowhead_text = lambda url, timeout=20: guide_fixture.guide_html()
        images.wowhead_bytes = lambda url, timeout=20: JPEG
        self.errors: list[str] = []
        lz.setup_logging()

        class Collect(logging.Handler):
            def emit(inner, record):  # noqa: N805
                if record.levelno >= logging.ERROR and record.exc_info:
                    self.errors.append(inner.format(record))
        self.handler = Collect()
        lz.log.addHandler(self.handler)
        self.app = lz.App()
        self.app.report_callback_exception = lambda e, v, tb: self.errors.append("".join(traceback.format_exception(e, v, tb)))

    def tearDown(self):
        for job in self.app.tk.splitlist(self.app.tk.call("after", "info")):
            self.app.after_cancel(job)
        self.app.destroy()
        lz.log.removeHandler(self.handler)
        for mod, name, orig in self.patched:
            setattr(mod, name, orig)

    def pump(self, until=lambda: False, seconds: float = 3.0):
        end = time.time() + seconds
        while time.time() < end and not until():
            self.app.update()
            time.sleep(0.01)
        self.app.update()

    def click(self, talent: str, add: bool = True, shift: bool = False):
        app = self.app
        app._bld_draw()
        x0, y0, x1, y1, _ = next(h for h in app.bld_hits if h[4] == tid(talent))
        app._bld_motion(SimpleNamespace(x=(x0 + x1) // 2, y=(y0 + y1) // 2))
        app._bld_click(SimpleNamespace(x=(x0 + x1) // 2, y=(y0 + y1) // 2, state=1 if shift else 0), add=add)
        app.update()

    def test_planner_and_guides(self):
        app = self.app
        self.pump(lambda: app.bld_build is not None)
        self.assertIsNotNone(app.bld_build, app.bld_status_var.get())
        self.assertEqual(app.current_page, "builds")
        self.assertEqual(app.bld_class_var.get(), "Krieger")          # first class, its trees are not in the fixture

        # a build from a Wowhead link, pasted into the field
        app.bld_link_var.set(LINK + tf.GUIDE_HASH + "/" + tf.GUIDE_ORDER)
        app.bld_paste()
        self.pump(lambda: app.bld_build.spent == 51)
        b = app.bld_build
        self.assertEqual((b.cls.slug, b.summary()), ("shaman", "18/25/8"))
        self.assertIn("18/25/8", app.bld_status_var.get())
        self.assertEqual(app.bld_link_var.get(), "")
        self.pump(lambda: any(app.bld_imgs.values()), 3)
        app._bld_draw()
        self.assertEqual(len(app.bld_hits), 50)
        if images.can_convert():
            self.assertTrue(any(app.bld_imgs.values()), "icons are shown")
        self.assertIn("Donnernde Stöße", app.bld_order_text.get("1.0", "end"))

        # clicking: right click takes points back, left click spends them, Shift takes all ranks
        self.click("Earthbound", add=False)
        self.assertEqual(app.bld_build.summary(), "17/25/8")
        self.click("Toughness")
        self.assertEqual(app.bld_build.summary(), "17/26/8")
        self.assertIn("Zähigkeit", app.bld_text.get("1.0", "end"))
        self.click("Toughness")                                     # no points left
        self.assertEqual(app.bld_build.spent, 51)
        app.bld_reset()
        self.click("Thundering Strikes", shift=True)
        self.assertEqual(app.bld_build.summary(), "0/5/0")
        self.assertEqual(app.cfg["builds_last"]["forever"], app.bld_build.link())

        # saving, loading and deleting builds
        app.ask_text = lambda *a, **kw: "Mein Build"
        app.ask = lambda *a, **kw: True
        app.bld_save()
        self.assertEqual([(r["name"], r["summary"]) for r in app.cfg["builds"]], [("Mein Build", "0/5/0")])
        app.bld_reset()
        app.bld_saved_var.set(app.bld_saved_labels[0])
        app._bld_saved_chosen()
        self.assertEqual(app.bld_build.summary(), "0/5/0")
        app.bld_copy()
        self.assertEqual(app.clipboard_get(), app.bld_build.url())
        app.bld_delete()
        self.assertEqual(app.cfg["builds"], [])

        # a guide: saved, shown, and its talent build opens in the planner
        app.bld_link_var.set(GUIDE_URL)
        app.bld_paste()
        self.pump(lambda: bool(app.gd_rows))
        self.assertEqual(app.bld_view, "guides")
        self.assertEqual([g["title"] for g in app.gd_rows], ["Enhancement Shaman Leveling Guide - WoW Forever"])
        text = app.gd_text.get("1.0", "end")
        self.assertIn("von Yebb", text)
        self.assertIn("Erdschock", text)
        start = app.gd_text.tag_ranges("build:0")[0]
        app.gd_text.see(start)
        app.update()
        x, y, w, h = app.gd_text.bbox(start)
        app._bld_link_click(app.gd_text, SimpleNamespace(x=x + 2, y=y + h // 2))
        self.pump(lambda: app.bld_view == "planner" and app.bld_build.spent == 51)
        self.assertEqual((app.bld_view, app.bld_build.summary(), app.bld_build.extras), ("planner", "18/25/8", ["t0", "r2"]))

        # other language, other editions, wrong input, removing the guide
        app.change_language("en")
        self.pump(lambda: app.bld_build is not None and app.bld_build.spent == 51)
        self.assertEqual(app.bld_class_var.get(), "Shaman")
        app.bld_link_var.set("https://example.org/nothing")
        app.bld_paste()
        app.bld_set_view("guides")
        app.update()
        app.gd_delete()
        self.assertEqual(app.gd_rows, [])
        self.assertIn("No guide saved yet", app.gd_text.get("1.0", "end"))
        self.assertEqual(self.errors, [], "\n".join(self.errors))

    def test_wowhead_unreachable(self):
        def offline(url, timeout=20):
            raise OSError("offline")
        talents.wowhead_text = guides.wowhead_text = images.wowhead_bytes = offline
        for f in (lz.config_dir() / "wowhead").glob("talents-*.json"):
            f.unlink()
        app = self.app
        app.bld_data = app.bld_build = None
        app.bld_loading = ""
        app.builds_open()
        self.pump(lambda: "offline" in app.bld_status_var.get())
        self.assertIn("offline", app.bld_status_var.get())
        app._bld_draw()
        app.bld_save()
        app.bld_copy()
        app.bld_reset()
        app.gd_add(GUIDE_URL)
        self.pump(seconds=0.5)
        self.assertEqual(app.gd_rows, [])
        self.assertEqual(self.errors, [], "\n".join(self.errors))


if __name__ == "__main__":
    unittest.main()
