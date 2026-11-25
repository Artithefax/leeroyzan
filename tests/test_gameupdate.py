"""WoW-Update vor „Spielen“: .build.info/.flavor.info lesen, Blizzards Versionsserver fragen, vergleichen,
die Battle.net-App öffnen – und der Ablauf im Fenster (warten, bis das Update fertig ist, dann WoW starten).

    python3 -m unittest tests.test_gameupdate
"""
import io
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="lz-gu-"))
os.environ.setdefault("APPDATA", str(TMP / "appdata"))
sys.path.insert(0, str(ROOT))

from leeroy import gameupdate as gu  # noqa: E402

BUILD_HEAD = ("Branch!STRING:0|Active!DEC:1|Build Key!HEX:16|CDN Key!HEX:16|Install Key!HEX:16|IM Size!DEC:4|"
              "CDN Path!STRING:0|CDN Hosts!STRING:0|CDN Servers!STRING:0|Tags!STRING:0|Armadillo!STRING:0|"
              "Last Activated!STRING:0|Version!STRING:0|KeyRing!HEX:16|Product!STRING:0")
TAGS = "Windows x86_64 EU? acct-DEU? geoip-DE? deDE speech?:Windows x86_64 EU? acct-DEU? geoip-DE? deDE text?"
VERSIONS = """Region!STRING:0|BuildConfig!HEX:16|CDNConfig!HEX:16|KeyRing!HEX:16|BuildId!DEC:4|VersionsName!String:0|ProductConfig!HEX:16
## seqn = 3021597
us|AAAA1111|c1|k1|60200|1.60.2.60200|p1
eu|BBBB2222|c2|k2|60200|1.60.2.60200|p2
"""


def build_row(branch="eu", active="1", key="bbbb2222", version="1.60.2.60200", product="wow_forever", tags=TAGS):
    return f"{branch}|{active}|{key}|cdn|inst|0|tpr/wow|hosts|servers|{tags}||2026-11-25|{version}|kr|{product}"


def make_root(name: str, rows: list[str], flavor="_forever_", flavor_info: str | None = None) -> Path:
    root = TMP / name
    (root / flavor).mkdir(parents=True, exist_ok=True)
    (root / ".build.info").write_text("\n".join([BUILD_HEAD, *rows]) + "\n", encoding="utf-8")
    if flavor_info is not None:
        (root / flavor / ".flavor.info").write_text(flavor_info, encoding="utf-8")
    return root


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def opener_for(*answers):
    """Fake für urlopen: je Aufruf die nächste Antwort (Text oder Ausnahme); merkt sich URLs und Kopfzeilen."""
    calls = []

    def opener(req, timeout=None):
        calls.append((req.full_url, dict(req.header_items()), timeout))
        a = answers[min(len(calls), len(answers)) - 1]
        if isinstance(a, Exception):
            raise a
        return FakeResponse(a.encode("utf-8"))
    opener.calls = calls
    return opener


class ParseTests(unittest.TestCase):
    def test_build_info_table(self):
        rows = gu.parse_table("\n".join([BUILD_HEAD, build_row(), build_row("us", "0", "old", "1.60.1.1")]))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["build key"], "bbbb2222")
        self.assertEqual(rows[0]["product"], "wow_forever")
        self.assertEqual(rows[1]["version"], "1.60.1.1")

    def test_versions_table_skips_comments(self):
        rows = gu.parse_table(VERSIONS)
        self.assertEqual([r["region"] for r in rows], ["us", "eu"])
        self.assertEqual(rows[1]["buildconfig"], "BBBB2222")
        self.assertEqual(rows[1]["versionsname"], "1.60.2.60200")

    def test_garbage_gives_no_rows(self):
        self.assertEqual(gu.parse_table(""), [])
        self.assertEqual(gu.parse_table("<html>nope</html>"), [])

    def test_product_code_from_flavor_info(self):
        root = make_root("pc1", [], "_classic_era_", "Product Flavor!STRING:0\nwow_classic_era\n")
        self.assertEqual(gu.product_code(str(root), "_classic_era_"), "wow_classic_era")

    def test_product_code_without_flavor_info(self):
        root = make_root("pc2", [])
        self.assertEqual(gu.product_code(str(root), "_forever_"), "wow_forever")
        self.assertEqual(gu.product_code(str(root), "_retail_"), "wow")

    def test_local_build_prefers_active_row_of_this_product(self):
        root = make_root("lb1", [build_row("us", "0", "dead0000", "1.50.0.1"), build_row("eu", "1", "BBBB2222"),
                                 build_row("eu", "1", "ffff0000", "4.4.1.1", "wow_classic")])
        b = gu.local_build(str(root), "_forever_")
        self.assertEqual(b, {"product": "wow_forever", "region": "eu", "build": "bbbb2222",
                             "version": "1.60.2.60200", "locale": "deDE"})

    def test_local_build_missing(self):
        self.assertIsNone(gu.local_build(str(TMP / "nowhere"), "_forever_"))
        root = make_root("lb2", [build_row(product="wow_classic")])
        self.assertIsNone(gu.local_build(str(root), "_forever_"))


class CompareTests(unittest.TestCase):
    LOCAL = {"product": "wow_forever", "region": "eu", "build": "bbbb2222", "version": "1.60.2.60200", "locale": "deDE"}

    def test_same_build_is_current(self):
        res = gu.compare(self.LOCAL, gu.parse_table(VERSIONS))
        self.assertEqual(res["state"], "current")

    def test_other_build_needs_update_and_uses_own_region(self):
        local = dict(self.LOCAL, build="aaaa1111", version="1.60.1.1")    # = Build der US-Zeile, aber Region eu
        res = gu.compare(local, gu.parse_table(VERSIONS))
        self.assertEqual((res["state"], res["target"], res["remote"], res["local"]),
                         ("update", "bbbb2222", "1.60.2.60200", "1.60.1.1"))

    def test_unknown_region_falls_back_to_first_row(self):
        res = gu.compare(dict(self.LOCAL, region="cn", build="aaaa1111"), gu.parse_table(VERSIONS))
        self.assertEqual(res["state"], "current")

    def test_without_build_keys_compares_versions(self):
        rows = [{"region": "eu", "buildconfig": "", "versionsname": "1.60.2.60200"}]
        self.assertEqual(gu.compare(dict(self.LOCAL, build=""), rows)["state"], "current")
        self.assertEqual(gu.compare(dict(self.LOCAL, build="", version="1.60.1.1"), rows)["state"], "update")

    def test_no_rows_is_unknown(self):
        self.assertEqual(gu.compare(self.LOCAL, [])["state"], "unknown")


class FetchTests(unittest.TestCase):
    def test_https_first_with_user_agent(self):
        op = opener_for(VERSIONS)
        rows = gu.fetch_versions("wow_forever", "eu", opener=op)
        self.assertEqual(len(rows), 2)
        url, headers, timeout = op.calls[0]
        self.assertEqual(url, "https://eu.version.battle.net/v2/products/wow_forever/versions")
        self.assertIn("User-agent", headers)
        self.assertEqual(timeout, gu.TIMEOUT)

    def test_falls_back_to_port_1119(self):
        op = opener_for(OSError("blocked"), VERSIONS)
        self.assertEqual(len(gu.fetch_versions("wow_forever", "eu", opener=op)), 2)
        self.assertEqual(op.calls[1][0], "http://eu.patch.battle.net:1119/wow_forever/versions")

    def test_unknown_region_asks_us(self):
        op = opener_for(VERSIONS)
        gu.fetch_versions("wow", "xx", opener=op)
        self.assertTrue(op.calls[0][0].startswith("https://us.version.battle.net/"))

    def test_both_fail_raises(self):
        with self.assertRaises(OSError):
            gu.fetch_versions("wow_forever", "eu", opener=opener_for(OSError("a"), OSError("b")))

    def test_check_update(self):
        root = make_root("cu1", [build_row(key="0123abcd", version="1.60.1.1")])
        res = gu.check_update(str(root), "_forever_", opener=opener_for(VERSIONS))
        self.assertEqual((res["state"], res["target"], res["product"]), ("update", "bbbb2222", "wow_forever"))
        res = gu.check_update(str(make_root("cu2", [build_row()])), "_forever_", opener=opener_for(VERSIONS))
        self.assertEqual(res["state"], "current")

    def test_check_update_offline_or_without_build_info(self):
        root = make_root("cu3", [build_row()])
        res = gu.check_update(str(root), "_forever_", opener=opener_for(OSError("offline"), OSError("offline")))
        self.assertEqual(res["state"], "unknown")
        self.assertIn("offline", res["error"])
        res = gu.check_update(str(TMP / "nowhere"), "_forever_", opener=opener_for(VERSIONS))
        self.assertEqual((res["state"], res["error"]), ("unknown", "build.info"))


class BattlenetTests(unittest.TestCase):
    def test_args_like_the_wow_launcher(self):
        local = {"product": "wow_forever", "region": "eu", "build": "b", "version": "v", "locale": "deDE"}
        self.assertEqual(gu.battlenet_args("C:/Games/World of Warcraft", local),
                         ["--game=wow_dede", "--productcode=wow_forever", "--gamepath=C:/Games/World of Warcraft"])
        self.assertEqual(gu.battlenet_args("R", dict(local, locale="")), ["--productcode=wow_forever", "--gamepath=R"])
        self.assertEqual(gu.battlenet_args("R", None), [])

    def test_open_app_with_game_page(self):
        root = make_root("bn1", [build_row()])
        exe = TMP / "Battle.net" / "Battle.net.exe"
        exe.parent.mkdir(exist_ok=True)
        exe.write_bytes(b"")
        calls = []
        with mock.patch.object(gu, "battlenet_exe", return_value=exe):
            how = gu.open_battlenet(str(root), "_forever_", popen=lambda args, **kw: calls.append((args, kw)))
        self.assertEqual(how, "app")
        self.assertEqual(calls[0][0], [str(exe), "--game=wow_dede", "--productcode=wow_forever", f"--gamepath={root}"])
        self.assertEqual(calls[0][1]["cwd"], str(exe.parent))

    def test_open_falls_back_to_wow_launcher(self):
        root = make_root("bn2", [build_row()])
        (root / "World of Warcraft Launcher.exe").write_bytes(b"")
        calls = []
        with mock.patch.object(gu, "battlenet_exe", return_value=None):
            how = gu.open_battlenet(str(root), "_forever_", popen=lambda args, **kw: calls.append(args))
        self.assertEqual((how, calls), ("launcher", [[str(root / "World of Warcraft Launcher.exe")]]))

    def test_no_battlenet_outside_windows(self):
        if not sys.platform.startswith("win"):
            self.assertIsNone(gu.battlenet_exe())


class QuietTests(unittest.TestCase):
    def test_quiet_for_uses_newest_index_file(self):
        root = make_root("q1", [build_row()])
        data = root / "Data" / "data"
        data.mkdir(parents=True)
        now = time.time()
        os.utime(root / ".build.info", (now - 300, now - 300))
        for name, age in (("0000000010.idx", 200), ("0100000011.idx", 12)):
            (data / name).write_bytes(b"")
            os.utime(data / name, (now - age, now - age))
        self.assertAlmostEqual(gu.quiet_for(str(root), now), 12, delta=0.5)

    def test_quiet_for_without_files(self):
        self.assertGreater(gu.quiet_for(str(TMP / "nowhere")), 1e8)


# ----- Ablauf im Fenster (ohne Tk: die Fenster-Teile sind Attrappen) ------------------------- #
from leeroy.ui.common import CommonMixin  # noqa: E402


class Var:
    def __init__(self, v=""):
        self.v = v

    def get(self):
        return self.v

    def set(self, v):
        self.v = v


class FakeApp(CommonMixin):
    def __init__(self, root: Path):
        self.root_var, self.flavor_var = Var(str(root)), Var("_forever_")
        self.cfg = {}
        self.running_jobs = {}                      # busy = ein schreibender Vorgang läuft
        self.banners, self.timers, self.launched, self.opened, self.status = {}, [], [], [], []
        self.wow_version_var = Var()

    # Fenster-Attrappen
    def notify(self, text, kind="info", actions=(), key="", timeout=0, **kw):
        key = "toast" if kind in ("ok", "info") else (key or text)
        self.banners[key] = (text, kind, list(actions))
        return key

    def press(self, key, i):
        """Knopf Nummer i der Meldung drücken (Beschriftung je nach Sprache)."""
        text, kind, actions = self.banners.pop(key)
        actions[i][1]()

    def dismiss(self, key):
        self.banners.pop(key, None)

    def info(self, text, **kw):
        self.notify(text, "info")

    def after(self, ms, fn):
        self.timers.append((ms, fn))

    def set_status(self, text):
        self.status.append(text)

    def run_quiet(self, func, on_done):
        try:
            res = func()
        except Exception as e:  # noqa: BLE001
            on_done(None, e)
        else:
            on_done(res, None)

    def _launch_wow(self, exe):
        self.launched.append(exe)

    def open_battlenet(self, for_update=False):
        self.opened.append(for_update)

    def run_timers(self, *, ms=None):
        """Fällige Timer ausführen (nur die, die jetzt da sind)."""
        todo = [t for t in self.timers if ms is None or t[0] == ms]
        self.timers = [t for t in self.timers if t not in todo]
        for _, fn in todo:
            fn()


UPDATE = {"state": "update", "local": "1.60.1.1", "remote": "1.60.2.60200", "target": "bbbb2222",
          "product": "wow_forever"}


class PlayFlowTests(unittest.TestCase):
    def setUp(self):
        self.root = make_root(f"flow{time.monotonic_ns()}", [build_row(key="0123abcd", version="1.60.1.1")])
        (self.root / "_forever_" / "Wow.exe").write_bytes(b"x")
        self.app = FakeApp(self.root)

    def age_files(self, seconds=120):
        t = time.time() - seconds
        os.utime(self.root / ".build.info", (t, t))

    def test_current_starts_wow(self):
        with mock.patch("leeroy.ui.common.check_update", return_value=dict(UPDATE, state="current")):
            self.app.start_wow()
        self.assertEqual(len(self.app.launched), 1)
        self.assertEqual(self.app.opened, [])

    def test_unknown_or_error_starts_wow_as_before(self):
        with mock.patch("leeroy.ui.common.check_update", return_value={"state": "unknown", "error": "offline"}):
            self.app.start_wow()
        with mock.patch("leeroy.ui.common.check_update", side_effect=OSError("boom")):
            self.app.start_wow()
        self.assertEqual(len(self.app.launched), 2)

    def test_check_can_be_switched_off(self):
        self.app.cfg["wow_update_check"] = False
        with mock.patch("leeroy.ui.common.check_update") as cu:
            self.app.start_wow()
        cu.assert_not_called()
        self.assertEqual(len(self.app.launched), 1)

    def test_update_opens_battlenet_waits_and_starts_wow(self):
        app = self.app
        with mock.patch("leeroy.ui.common.check_update", return_value=UPDATE):
            app.start_wow()
        self.assertEqual((app.launched, app.opened), ([], [True]))
        self.assertIn("wowupdate", app.banners)
        self.assertIn("1.60.2.60200", app.banners["wowupdate"][0])
        app.run_timers()                           # noch der alte Build: weiter warten
        self.assertEqual(len(app.timers), 1)
        self.assertEqual(app.launched, [])
        (self.root / ".build.info").write_text("\n".join([BUILD_HEAD, build_row()]) + "\n", encoding="utf-8")
        app.run_timers()                           # neuer Build, aber die App hat eben erst geschrieben
        self.assertEqual(app.launched, [])
        self.assertEqual(len(app.timers), 1)
        self.age_files()
        app.run_timers()                           # fertig: Hinweis weg, Start in drei Sekunden
        self.assertNotIn("wowupdate", app.banners)
        self.assertIn("toast", app.banners)
        self.assertEqual(app.wow_version_state["state"], "current")
        app.run_timers()
        self.assertEqual(len(app.launched), 1)

    def test_autostart_waits_while_busy_and_can_be_off(self):
        app = self.app
        app.running_jobs = {1: {"kind": "write", "label": "Updates"}}
        app._autostart_wow(time.time() + 60)
        self.assertEqual(app.launched, [])
        self.assertEqual(app.timers[0][0], 5000)
        app.running_jobs = {}
        app.run_timers()
        self.assertEqual(len(app.launched), 1)
        app2 = FakeApp(self.root)
        app2.cfg["wow_update_autostart"] = False
        with mock.patch("leeroy.ui.common.check_update", return_value=UPDATE):
            app2.start_wow()
        (self.root / ".build.info").write_text("\n".join([BUILD_HEAD, build_row()]) + "\n", encoding="utf-8")
        self.age_files()
        app2.run_timers()
        self.assertEqual(app2.launched, [])
        self.assertIn("wowupdate-done", app2.banners)

    def test_pressing_play_twice_keeps_one_watcher(self):
        app = self.app
        with mock.patch("leeroy.ui.common.check_update", return_value=UPDATE):
            app.start_wow()
            app.start_wow()
        self.assertEqual(len(app.timers), 2)
        app.run_timers()
        self.assertEqual(len(app.timers), 1)        # der ältere Beobachter hört auf

    def test_cancel_and_other_folder_stop_waiting(self):
        app = self.app
        with mock.patch("leeroy.ui.common.check_update", return_value=UPDATE):
            app.start_wow()
        app.press("wowupdate", 1)                        # „Nicht warten“
        self.assertIsNone(app._wow_update_wait)
        app.run_timers()
        self.assertEqual(app.timers, [])
        with mock.patch("leeroy.ui.common.check_update", return_value=UPDATE):
            app.start_wow()
        app.flavor_var.set("_classic_")
        app.run_timers()
        self.assertEqual((app.timers, app._wow_update_wait), ([], None))
        self.assertNotIn("wowupdate", app.banners)

    def test_start_anyway(self):
        app = self.app
        with mock.patch("leeroy.ui.common.check_update", return_value=UPDATE):
            app.start_wow()
            app.press("wowupdate", 0)                    # „Trotzdem starten“
        self.assertEqual(len(app.launched), 1)

    def test_background_check_hints_once_per_build(self):
        app = self.app
        with mock.patch("leeroy.ui.common.check_update", return_value=UPDATE):
            app.check_wow_version(silent=True)
            self.assertIn("wowupdate-avail", app.banners)
            self.assertIn("1.60.2.60200", app.wow_version_var.get())
            app.dismiss("wowupdate-avail")
            app.check_wow_version(silent=True)          # gleiches Update: nicht noch einmal
            self.assertNotIn("wowupdate-avail", app.banners)
            app.check_wow_version(silent=False)         # „Jetzt prüfen“: immer
            self.assertIn("wowupdate-avail", app.banners)
        with mock.patch("leeroy.ui.common.check_update", return_value=dict(UPDATE, state="current")):
            app.check_wow_version(silent=False)
        self.assertNotIn("wowupdate-avail", app.banners)
        self.assertIn("1.60.1.1", app.status[-1])

    def test_background_check_quiet_while_waiting(self):
        app = self.app
        with mock.patch("leeroy.ui.common.check_update", return_value=UPDATE):
            app.start_wow()
            app.check_wow_version(silent=True)
        self.assertNotIn("wowupdate-avail", app.banners)

    def test_save_options_keeps_switches(self):
        app = self.app
        app.auto_backup_var, app.check_start_var = Var(True), Var(False)
        app.wow_check_var, app.wow_autostart_var = Var(False), Var(True)
        app.self_update_var = Var("")
        with mock.patch("leeroy.ui.common.save_config"):
            try:
                app.save_options()
            except AttributeError:                     # weitere Fenster-Teile fehlen der Attrappe – egal
                pass
        self.assertEqual((app.cfg["wow_update_check"], app.cfg["wow_update_autostart"]), (False, True))


if __name__ == "__main__":
    unittest.main()
