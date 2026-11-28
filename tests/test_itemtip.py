"""Gegenstands-Tooltip im Auktionshaus: Wowheads Tooltip-HTML → Zeilen wie im Spiel, und deren Anordnung.

Ohne Fenster: layout_tip bekommt eine Messfunktion mit fester Zeichenbreite.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("APPDATA", tempfile.mkdtemp(prefix="lz-tip-"))
sys.path.insert(0, str(ROOT))

from leeroy.i18n import cur_lang  # noqa: E402
from leeroy.wowhead import tooltip_lines  # noqa: E402

try:
    import tkinter  # noqa: F401 - layout_tip liegt im Fenster-Paket, braucht aber kein Fenster
    HAS_TK = True
except ImportError:
    HAS_TK = False

# Aufbau wie die Antwort von nether.wowhead.com/…/tooltip/item/<ID> (Feld "tooltip")
WEAPON = ('<table><tr><td><!--nstart--><b class="q5">Thunderfury, Blessed Blade of the Windseeker</b><!--nend--><!--ndstart--><!--ndend-->'
          '<span class="q"><br>Item Level <!--ilvl-->80</span><br><!--bo-->Binds when picked up<br>Unique'
          '<table width="100%"><tr><td>One-Hand</td><th><!--scstart2:7--><span class="q1">Sword</span><!--scend--></th></tr></table>'
          '<table width="100%"><tr><td><span><!--dmg-->44 - 115 Damage</span></td><th>Speed <!--spd-->1.90</th></tr></table>'
          '<span><!--dmg-->+ 16 - 30 Nature Damage</span><br><!--dps-->(53.9 damage per second)<br>'
          '<span><!--stat3-->+5 Agility</span><br>+8 Fire Resistance<br>'
          '<!--ebstats--><!--egstats--><!--sustats-->Durability 125 / 125<br>'
          '<!--rlstart-->Requires Level <!--rlvl-->60<!--rlend--></td></tr></table>'
          '<table><tr><td><span class="q2">Chance on hit: <a href="/classic/spell=21992" class="q2">Blasts your enemy with '
          'lightning.</a></span><!--pts--><!--itemEffects:0--><br>'
          '<div class="whtt-sellprice">Sell Price: <span class="moneygold">25</span> <span class="moneysilver">53</span> '
          '<span class="moneycopper">36</span></div></td></tr></table><!--?19019:1:60:60-->')
SET_ITEM = ('<table><tr><td><b class="q3">Bloodfang Hood</b><br>Binds when picked up<table width="100%"><tr><td>Head</td>'
            '<th><span class="q1">Leather</span></th></tr></table>190 Armor<br>Classes: <span class="c4">Rogue</span><br>'
            'Requires Level 60</td></tr></table><table><tr><td><span class="q2">Equip: Improves your chance to hit by 1%.</span>'
            '<br><br><span class="q"><a href="/item-set=213">Bloodfang Armor</a> (0/8)</span><div class="q0 indent">'
            '<span><a href="/item=16908">Bloodfang Hood</a></span><br><span>Bloodfang Pants</span></div><br>'
            '<span class="q0">(3) Set: +20 Armor.</span><span style="display: none">versteckt</span>'
            '<div class="whtt-extra whtt-droppedby">Dropped by: Onyxia</div></td></tr></table>')


def plain(lines):
    out = []
    for ln in lines:
        if ln is None:
            out.append("")
            continue
        text = "".join(t for t, _ in ln["left"])
        if ln.get("right"):
            text += " | " + "".join(t for t, _ in ln["right"])
        out.append(text)
    return out


class TooltipLinesTests(unittest.TestCase):
    def test_weapon(self):
        lines = tooltip_lines(WEAPON)
        self.assertEqual(plain(lines), [
            "Thunderfury, Blessed Blade of the Windseeker", "Item Level 80", "Binds when picked up", "Unique",
            "One-Hand | Sword", "44 - 115 Damage | Speed 1.90", "+ 16 - 30 Nature Damage", "(53.9 damage per second)",
            "+5 Agility", "+8 Fire Resistance", "Durability 125 / 125", "Requires Level 60",
            "Chance on hit: Blasts your enemy with lightning.", "Sell Price: 25g 53s 36" + ("k" if cur_lang() == "de" else "c")])
        self.assertEqual(lines[0]["left"], [("Thunderfury, Blessed Blade of the Windseeker", "q5")])
        self.assertEqual(lines[1]["left"][0][1], "q")                       # Gegenstandsstufe gelb
        self.assertEqual(lines[4]["right"], [("Sword", "q1")])
        self.assertEqual(lines[12]["left"][0][1], "q2")                     # „Trefferchance“ grün
        self.assertEqual([c for _, c in lines[-1]["left"]], ["", "gold", "", "silver", "", "copper"])

    def test_set_item(self):
        lines = tooltip_lines(SET_ITEM)
        self.assertEqual(plain(lines), [
            "Bloodfang Hood", "Binds when picked up", "Head | Leather", "190 Armor", "Classes: Rogue", "Requires Level 60",
            "Equip: Improves your chance to hit by 1%.", "", "Bloodfang Armor (0/8)", "Bloodfang Hood", "Bloodfang Pants", "",
            "(3) Set: +20 Armor.", "Dropped by: Onyxia"])
        self.assertEqual(lines[4]["left"], [("Classes: ", ""), ("Rogue", "c4")])
        self.assertEqual(lines[9]["left"][0][1], "q0")                       # Setteile grau
        self.assertEqual(lines[-1]["left"][0][1], "q0")                      # „Gedroppt von“ gedämpft

    def test_empty_and_broken(self):
        self.assertEqual(tooltip_lines(""), [])
        self.assertEqual(plain(tooltip_lines('<b class="q2">Kaputt<br><br><br>Rest<table')), ["Kaputt", "", "Rest"])


@unittest.skipUnless(HAS_TK, "needs tkinter")
class LayoutTests(unittest.TestCase):
    @staticmethod
    def layout(lines, max_w=200):
        from leeroy.ui.itemtip import layout_tip
        return layout_tip(lines, lambda text, big: len(text) * (9 if big else 7), lambda big: 18 if big else 14, max_w=max_w)

    def test_right_column_and_wrap(self):
        lines = [{"left": [("Name", "q3")]}, {"left": [("Kopf", "")], "right": [("Stoff", "q1")]},
                 {"left": [("Benutzen: " + "sehr " * 8 + "lang.", "q2")]}, None, {"left": [("Ende", "")]}]
        w, h, items = self.layout(lines)
        green = [i for i in items if i[3] == "q2"]
        self.assertGreater(len(green), 1)                                     # umgebrochen …
        self.assertTrue(all(x == 0 and len(t) * 7 <= 200 for x, _, t, _, _ in green))     # … innerhalb der Höchstbreite
        self.assertEqual(w, max(len(t) * 7 for _, _, t, _, _ in green))     # so breit wie die breiteste Zeile
        right = [i for i in items if i[2] == "Stoff"][0]
        self.assertEqual(right[0] + 5 * 7, w)                                 # rechtsbündig
        ys = sorted({i[1] for i in items})
        self.assertEqual(ys[:3], [0, 18, 32])                                 # Name groß, dann normale Zeilen
        ende = [i for i in items if i[2] == "Ende"][0]
        self.assertEqual(h, ende[1] + 14)
        self.assertEqual(ende[1], 32 + 14 * len(green) + 7)                   # Leerzeile = halbe Höhe

    def test_narrow_tooltip(self):
        w, h, items = self.layout([{"left": [("Leinenstoff", "q1")]}, {"left": [("Verkaufspreis: ", ""), ("10k", "copper")]}])
        self.assertEqual(w, 18 * 7)
        self.assertEqual(self.layout([{"left": [("Stoff", "q1")]}])[0], 120)  # Mindestbreite
        self.assertEqual([(x, t) for x, _, t, _, _ in items], [(0, "Leinenstoff"), (0, "Verkaufspreis: "), (15 * 7, "10k")])


if __name__ == "__main__":
    unittest.main()
