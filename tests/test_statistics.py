"""Statistik-Bausteine, Vorlagen, Zeiträume (Spieltag ab 04:00, Woche Mo–So) und Discord-Post-Aufträge.

Reine Logik, ohne Fenster und ohne Netz: python3 -m unittest tests.test_statistics
"""
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("APPDATA", tempfile.mkdtemp(prefix="lz-stats-"))
sys.path.insert(0, str(ROOT))

from leeroy import autopost as ap  # noqa: E402
from leeroy import metrics as mt  # noqa: E402
from leeroy.i18n import set_language  # noqa: E402
from leeroy.sessions import normalize_session  # noqa: E402


def ts(*args) -> float:
    return datetime(*args).timestamp()


def session(char: str, start: float, played: int = 3600, xp: int = 1000, loot: int = 0, **kw) -> dict:
    raw = {"char": char, "name": char.split("-")[0], "class": "WARRIOR", "start": start, "stop": start + played,
           "saved": start + played, "played": played, "level": {"from": 20, "to": 21}, "xp": {"total": xp},
           "money": {"v": 2, "start": 0, "stop": loot, "income": loot, "spent": 0, "gain": {"loot": loot} if loot else {}},
           "kills": {"n": 5, "normal": 5}}
    raw.update(kw)
    return normalize_session(raw)


class PeriodTests(unittest.TestCase):
    def test_play_day_starts_at_four(self):
        self.assertEqual(mt.play_day(ts(2026, 11, 24, 1, 30)).isoformat(), "2026-11-23")   # 1:30 nachts: noch Montag
        self.assertEqual(mt.play_day(ts(2026, 11, 24, 4, 0)).isoformat(), "2026-11-24")
        self.assertEqual(mt.play_day(ts(2026, 11, 24, 1, 30), 0).isoformat(), "2026-11-24")  # Grenze Mitternacht

    def test_week_monday_to_sunday(self):
        self.assertEqual(mt.period_key("week", ts(2026, 11, 23, 12)), "2026-W48")          # Montag
        self.assertEqual(mt.period_key("week", ts(2026, 11, 30, 2)), "2026-W48")           # Sonntagnacht 2 Uhr
        self.assertEqual(mt.period_key("week", ts(2026, 11, 30, 5)), "2026-W49")
        begin, end = mt.period_bounds("week", "2026-W48")
        self.assertEqual((datetime.fromtimestamp(begin), datetime.fromtimestamp(end)),
                         (datetime(2026, 11, 23, 4), datetime(2026, 11, 30, 4)))
        self.assertEqual(mt.shift_period("week", "2026-W01", -1), "2025-W52")
        self.assertEqual(mt.shift_period("day", "2026-03-01", -1), "2026-02-28")
        self.assertEqual(mt.day_start_minutes("quatsch"), 240)


class TemplateTests(unittest.TestCase):
    def setUp(self):
        set_language("de")
        self.a = session("Rosen-Realm", ts(2026, 11, 24, 18), loot=50000)
        self.b = session("Distel-Realm", ts(2026, 11, 25, 20), played=1800, loot=0, xp=0)

    def test_blocks_and_options(self):
        ctx = mt.Ctx([self.a, self.b], prev=[self.a], period=True)
        rows = {label: value for label, value, _ in mt.render_template(mt.BUILTIN_TEMPLATES["alles"]["blocks"], ctx)}
        self.assertIn("1 h 30 min", rows["Spielzeit"])
        self.assertIn("▲ 50 %", rows["Spielzeit"])                         # Vergleich mit dem Zeitraum davor
        self.assertIn("/h", rows["Gold"])                                   # pro Stunde
        self.assertIn("Rosen", rows["Charaktere"])
        self.assertNotIn("Tode", rows)                                      # „nur wenn > 0“
        single = mt.Ctx([self.b])
        self.assertIsNone(mt.render_block({"id": "time.sessions"}, single))   # nur bei Zeiträumen
        self.assertIsNone(mt.render_block({"id": "gold.farmed", "nonzero": True}, single))
        self.assertEqual(mt.render_block({"id": "gold.farmed"}, single)[1], "0k")
        self.assertIsNone(mt.render_block({"id": "gibtsnicht"}, single))

    def test_balance_from_character_data(self):
        ctx = mt.Ctx([self.a, self.b], period=True, chars={"Rosen-Realm": {"money": 10000}, "Distel-Realm": {"money": 20000}})
        value = mt.render_block({"id": "gold.balance"}, ctx)[1]
        self.assertIn("gesamt 3g", value)

    def test_user_templates(self):
        cfg = {"stat_templates": {"u_x": {"name": "Meine", "blocks": [{"id": "xp.total"}, {"id": "weg"}]}, "kompakt": {}}}
        tpl = mt.all_templates(cfg)
        self.assertEqual([b["id"] for b in tpl["u_x"]["blocks"]], ["xp.total"])   # unbekannte Bausteine fallen weg
        self.assertTrue(tpl["kompakt"]["builtin"])                                  # mitgelieferte nicht überschreibbar
        self.assertEqual(mt.new_template_id(cfg, "X"), "u_x2")
        text = "".join(t for t, _ in mt.template_report(tpl["u_x"], mt.Ctx([self.a]), "Titel"))
        self.assertIn("Erfahrung:", text)

    def test_messages_split(self):
        many = [session(f"C{i}-R", ts(2026, 11, 24, 10) + i, played=600) for i in range(12)]
        msgs = mt.period_messages(mt.BUILTIN_TEMPLATES["kompakt"], "Woche", many, None, many, each=True)
        embeds = [e for m in msgs for e in m["embeds"]]
        self.assertEqual(len(embeds), 13)                                   # Überblick + je Charakter
        self.assertTrue(all(len(m["embeds"]) <= 10 for m in msgs))
        self.assertTrue(all(sum(mt._embed_size(e) for e in m["embeds"]) <= mt.EMBED_LIMIT for m in msgs))
        self.assertIn("Charaktere", [f["name"] for f in embeds[0]["fields"]])


class JobTests(unittest.TestCase):
    def setUp(self):
        set_language("de")
        self.url = "https://discord.com/api/webhooks/1/abc"

    def test_defaults_take_over_old_setting(self):
        jobs = ap.load_jobs({"discord_auto": True})
        self.assertEqual([j["when"] for j in jobs], ["session", "daily", "weekly"])
        self.assertTrue(jobs[0]["on"])
        self.assertFalse(jobs[2]["on"])
        self.assertEqual((jobs[2]["template"], jobs[2]["chars"]), ("alles", "each"))
        cfg = {"discord_sent": ["a"]}
        self.assertEqual(ap.job_state(cfg, jobs[0])["sent"], ["a"])         # schon gesendete bleiben gesendet

    def test_weekly_schedule(self):
        cfg = {}
        job = dict(ap.default_jobs(cfg)[2], on=True)
        self.assertIsNone(ap.due_period(job, cfg, ts(2026, 11, 25, 12)))   # eingeschaltet: beginnt mit der nächsten Woche
        self.assertEqual(cfg["discord_jobs_state"]["weekly"]["last"], "2026-W47")
        self.assertIsNone(ap.due_period(job, cfg, ts(2026, 11, 30, 3)))    # Sonntagnacht: Woche läuft noch
        self.assertEqual(ap.due_period(job, cfg, ts(2026, 11, 30, 4, 1)), ("send", "2026-W48"))
        self.assertIsNone(ap.due_period(job, cfg, ts(2026, 11, 30, 4, 1), wow_running=True))   # erst nach dem Ausloggen
        self.assertEqual(ap.due_period(job, cfg, ts(2026, 12, 3, 9)), ("send", "2026-W48"))   # nachgeholt
        ap.mark_sent(cfg, job, period="2026-W48")
        self.assertIsNone(ap.due_period(job, cfg, ts(2026, 12, 3, 9)))
        job["catch_up"] = False
        self.assertEqual(ap.due_period(job, cfg, ts(2026, 12, 9, 9)), ("skip", "2026-W49"))
        job["earliest"] = "12:00"
        job["catch_up"] = True
        ap.mark_sent(cfg, job, period="2026-W49")
        self.assertIsNone(ap.due_period(job, cfg, ts(2026, 12, 14, 11)))
        self.assertEqual(ap.due_period(job, cfg, ts(2026, 12, 14, 12)), ("send", "2026-W50"))
        job["when"] = "daily"                                                # umgestellt: neu beginnen statt alles nachholen
        self.assertIsNone(ap.due_period(job, cfg, ts(2026, 12, 14, 13)))
        self.assertEqual(ap.next_run_text(job, cfg, ts(2026, 12, 14, 13)), "15.12. 12:00")

    def test_period_messages(self):
        cfg = {}
        job = dict(ap.default_jobs(cfg)[1], on=True, show_balance=False)
        hist = [session("Rosen-R", ts(2026, 11, 24, 23), loot=30000), session("Rosen-R", ts(2026, 11, 25, 1), played=600),
                session("Rosen-R", ts(2026, 11, 25, 10))]
        msgs = ap.period_job_messages(job, cfg, "2026-11-24", hist)
        emb = msgs[0]["embeds"][0]
        self.assertIn("Tagesbericht · 24.11.2026", emb["title"])
        self.assertEqual(dict((f["name"], f["value"]) for f in emb["fields"])["Spielzeit"], "1 h 10 min (Ø 35 min pro Sitzung)")
        self.assertEqual(ap.period_job_messages(job, cfg, "2026-11-20", hist), [])        # keine Sitzung, nichts zu senden
        self.assertEqual(ap.period_job_messages(dict(job, only=["Andere-R"]), cfg, "2026-11-24", hist), [])

    def test_session_job(self):
        cfg = {}
        job = dict(ap.default_jobs(cfg)[0], on=True, min_played=10)
        short = session("A-R", ts(2026, 11, 24, 10), played=300)
        long = session("A-R", ts(2026, 11, 24, 12), played=1200)
        self.assertEqual([s["id"] for s in ap.session_job_todo(job, cfg, [long, short])], [long["id"]])
        ap.mark_sent(cfg, job, session_ids=[long["id"]])
        self.assertEqual(ap.session_job_todo(job, cfg, [long]), [])
        self.assertEqual(cfg["discord_sent"], [long["id"]])
        msg = ap.session_job_messages(job, cfg, long, [long])[0]
        self.assertEqual(msg["embeds"][0]["fields"][0]["name"], "Spielzeit")

    def test_urls_and_send(self):
        cfg = {"discord_webhook": self.url, "discord_share_webhook": ""}
        jobs = ap.load_jobs(cfg)
        self.assertEqual(ap.job_url(jobs[0], cfg), self.url)
        self.assertEqual(ap.job_url(dict(jobs[0], webhook="share"), cfg), self.url)      # ohne eigenen Teilen-Kanal
        self.assertEqual(ap.job_url(dict(jobs[0], webhook="own", url="https://example.com"), cfg), "")
        sent, waits = [], []
        mod = sys.modules[ap.discord_send.__module__]
        orig = ap.discord_send
        ap.discord_send = lambda url, payload, sleep=None: sent.append(payload)
        try:
            ap.send_messages(self.url, [{"a": 1}, {"b": 2}], sleep=waits.append)
        finally:
            ap.discord_send = orig
        self.assertEqual((len(sent), waits), (2, [1.0]))
        self.assertTrue(mod)


class TranslationTests(unittest.TestCase):
    def test_dynamic_texts_translated(self):
        """Namen, die erst zur Laufzeit durch tr() gehen (Bausteine, Kategorien, Aufträge …), haben eine Übersetzung."""
        from leeroy import reports as rp
        from leeroy.i18n import TRANSLATIONS
        texts = {x for m in mt.METRICS.values() for x in (m.label, m.title, m.desc) if x}
        texts |= {label for _, label in mt.CATEGORIES + mt.NAMED_PERIODS} | set(mt.OPTION_NAMES.values())
        texts |= set(ap.WHEN.values()) | set(ap.CHAR_MODES.values()) | set(ap.WEBHOOKS.values())
        texts |= set(rp.TRANSFER_NAMES.values()) | set(rp.MONEY_SOURCES.values())
        texts |= {t["name"] for t in mt.BUILTIN_TEMPLATES.values()} | {j["name"] for j in ap.default_jobs({})}
        missing = sorted(x for x in texts if x not in TRANSLATIONS["en"])
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
