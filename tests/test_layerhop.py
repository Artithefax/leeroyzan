"""Leeroylink: Layerwechsel zwischen zwei Spielern und die Realm-Zuordnung ohne Realm-Namen.

Zwei Leeroylink-Instanzen laufen in getrennten Lua-Umgebungen (tests/wow_stub.lua + tests/layer_stub.lua); der
Test trägt ihre Addon-Nachrichten, Einladungen und Gruppenwechsel hin und her wie der Server.
"""
import unittest
from pathlib import Path

try:
    from lupa import lua51
except ImportError:                                    # lupa fehlt
    lua51 = None

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent


class Client:
    def __init__(self, name: str, setup: str = "", login: bool = True):
        self.name = name
        self.lua = lua51.LuaRuntime(unpack_returned_tuples=True)
        g = self.lua.globals()
        g.ADDON_DIR = str(ROOT / "Leeroylink")
        g.TESTS_DIR = str(HERE)
        self.lua.execute('dofile(TESTS_DIR .. "/wow_stub.lua"); dofile(TESTS_DIR .. "/layer_stub.lua")')
        self.stub = g.STUB
        self.stub.me = name
        if setup:
            self.lua.execute(setup)
        self._fire = self.lua.eval("function(...) STUB.fire(...) end")
        if login:
            self.login()

    def login(self):
        self.lua.execute('STUB.loadAddon(ADDON_DIR); LZ = _G.Leeroylink; STUB.fire("ADDON_LOADED", "Leeroylink");'
                         'STUB.fire("PLAYER_LOGIN"); STUB.fire("PLAYER_ENTERING_WORLD", true, false); STUB.advance(1)')
        self.lz = self.lua.globals().LZ
        self.mod = self.lz.modules.LayerHop

    def fire(self, *args):
        self._fire(*args)

    def run(self, code: str):
        return self.lua.execute(code)

    def advance(self, sec: float):
        self.lua.globals().STUB.advance(sec)

    @staticmethod
    def items(t) -> list:
        return [t[i] for i in range(1, len(t) + 1)] if t is not None else []

    def take_outbox(self) -> list:
        out = [dict(m.items()) for m in self.items(self.stub.outbox)]
        self.run("STUB.outbox = {}")
        return out

    def chat(self) -> str:
        return "\n".join(str(x) for x in self.items(self.stub.chat))

    def state(self) -> str:
        return self.mod.State(self.mod)[0]


def deliver(src: Client, dst: Client, bnet_id: int | None = None) -> list:
    """Bringt die Nachrichten von src zu dst (Flüstern an dst, Gilde, oder Battle.net-Daten)."""
    msgs = src.take_outbox()
    for m in msgs:
        if m["chatType"] == "BN":
            dst.fire("BN_CHAT_MSG_ADDON", m["prefix"], m["msg"], "WHISPER", bnet_id)
        elif m["chatType"] == "GUILD" or (m.get("target") or "").split("-")[0] == dst.name:
            dst.fire("CHAT_MSG_ADDON", m["prefix"], m["msg"], m["chatType"], src.name + "-CAMWOWEU5Realm2PvP")
    return msgs


def join(guest: Client, hostc: Client):
    """Der Server nimmt den Gast in die Gruppe des Gastgebers auf."""
    guest.run(f'STUB.group = 2; STUB.party = {{ "{hostc.name}" }}')
    hostc.run(f'STUB.group = 2; STUB.leader = true; STUB.party = {{ "{guest.name}" }}')
    guest.fire("GROUP_ROSTER_UPDATE")
    hostc.fire("GROUP_ROSTER_UPDATE")


def friends(a: Client, b: Client):
    a.run(f'STUB.friends = {{ {{ name = "{b.name}", area = "Rotkammgebirge" }} }}')
    b.run(f'STUB.friends = {{ {{ name = "{a.name}", area = "Rotkammgebirge" }} }}')


@unittest.skipIf(lua51 is None, "lupa not installed")
class LayerHopTests(unittest.TestCase):
    def setUp(self):
        self.me = Client("Rosenbert")
        self.host = Client("Kaelith")
        friends(self.me, self.host)

    def hop(self) -> dict:
        c = self.me.mod.Find(self.me.mod, "kae")
        self.assertIsNotNone(c, "friend found by the beginning of the name")
        self.assertTrue(self.me.mod.Hop(self.me.mod, c))
        self.assertEqual(self.me.state(), "asking")
        return c

    def test_full_switch_with_popup(self):
        self.hop()
        req = deliver(self.me, self.host)
        self.assertEqual(len(req), 1)
        self.assertTrue(req[0]["msg"].startswith("LH1;REQ;1433;Rosenbert"), req[0]["msg"])
        popups = Client.items(self.host.stub.popups)
        self.assertEqual(len(popups), 1, "the host is asked first")
        self.assertIn("Rosenbert", popups[0]["text"])
        deliver(self.host, self.me)                      # ACK
        self.assertEqual(self.me.state(), "waiting")
        # the host clicks "Invite"
        self.host.run("StaticPopupDialogs.LEEROYLINK_LAYERHOP.OnAccept()")
        self.assertEqual(Client.items(self.host.stub.invited), ["Rosenbert-CAMWOWEU5Realm2PvP"])
        deliver(self.host, self.me)                      # INV
        self.me.fire("PARTY_INVITE_REQUEST", "Kaelith")
        self.assertEqual(self.me.stub.accepted, 1, "invite accepted automatically")
        self.assertIsNone(self.me.stub.hidden["PARTY_INVITE"], "the game's popup stays until the group is joined")
        join(self.me, self.host)
        self.assertGreaterEqual(self.me.stub.hidden["PARTY_INVITE"], 1, "then the game's invite popup is closed")
        self.assertEqual(self.me.state(), "joined")
        self.assertEqual(self.me.stub.left, 0)
        self.me.advance(7)
        self.assertEqual(self.me.stub.left, 1, "the group is left after the delay")
        self.assertEqual(self.me.state(), "idle")
        self.assertIn("auf dem Layer von Kaelith", self.me.chat())
        self.assertEqual(self.host.stub.left, 0, "the host never leaves")

    def test_invite_from_someone_else_is_ignored(self):
        self.hop()
        self.me.fire("PARTY_INVITE_REQUEST", "Fremder")
        self.assertEqual(self.me.stub.accepted, 0)

    def test_auto_invite_and_other_zone(self):
        self.host.run("LZ.modules.LayerHop.opt.autoInvite = true; STUB.map = 1429")   # host in Elwynn
        self.hop()
        deliver(self.me, self.host)
        self.assertEqual(len(Client.items(self.host.stub.popups)), 0, "no popup with auto invite")
        self.assertEqual(len(Client.items(self.host.stub.invited)), 1)
        deliver(self.host, self.me)                      # INV;1429
        self.me.fire("PARTY_INVITE_REQUEST", "Kaelith-CAMWOWEU5Realm2PvP")
        join(self.me, self.host)
        self.me.advance(20)
        self.assertEqual(self.me.stub.left, 0, "stays in the group until the zone is reached")
        self.assertIn("Wald von Elwynn", self.me.chat())
        self.me.run("STUB.map = 1429")
        self.me.fire("ZONE_CHANGED_NEW_AREA")
        self.me.advance(7)
        self.assertEqual(self.me.stub.left, 1)

    def test_late_message_replans(self):
        """The invite arrives before the addon message with the host's zone."""
        self.host.run("LZ.modules.LayerHop.opt.autoInvite = true; STUB.map = 1429")
        self.hop()
        deliver(self.me, self.host)
        inv = self.host.take_outbox()
        self.me.fire("PARTY_INVITE_REQUEST", "Kaelith")
        join(self.me, self.host)                         # planned: leave in 6 s (zone unknown)
        self.me.run("STUB.outbox = {}")
        self.host.run("STUB.outbox = {}")
        for m in inv:
            self.me.fire("CHAT_MSG_ADDON", m["prefix"], m["msg"], "WHISPER", "Kaelith")
        self.me.advance(10)
        self.assertEqual(self.me.stub.left, 0, "the earlier leave timer was cancelled")

    def test_host_refuses(self):
        cases = {
            "LZ.modules.LayerHop.opt.host = false": "nimmt keine Layer-Anfragen an",
            "STUB.combat = true": "im Kampf",
            "STUB.group = 3; STUB.leader = false; STUB.party = { 'A', 'B' }": "führt sie aber nicht",
            "STUB.friends = {}": "nur Anfragen von Freunden",
        }
        for setup, text in cases.items():
            with self.subTest(setup=setup):
                me, host = Client("Rosenbert"), Client("Kaelith")
                friends(me, host)
                host.run(setup)
                c = me.mod.Find(me.mod, "Kaelith")
                me.mod.Hop(me.mod, c)
                deliver(me, host)
                deliver(host, me)
                self.assertEqual(me.state(), "idle")
                self.assertIn(text, me.chat())
                self.assertEqual(len(Client.items(host.stub.invited)), 0)

    def test_requester_checks(self):
        c = self.me.mod.Find(self.me.mod, "Kaelith")
        self.me.run("STUB.combat = true")
        self.assertFalse(self.me.mod.Hop(self.me.mod, c))
        self.me.run("STUB.combat = false; STUB.group = 2; STUB.party = { 'Jemand' }")
        self.assertFalse(self.me.mod.Hop(self.me.mod, c))
        self.assertIn("Verlass sie zuerst", self.me.chat())
        self.me.run("STUB.group = 0; STUB.party = {}")
        self.assertTrue(self.me.mod.Hop(self.me.mod, c))
        self.me.advance(11)                              # nobody answers
        self.assertEqual(self.me.state(), "idle")
        self.assertIn("antwortet nicht", self.me.chat())
        self.assertFalse(self.me.mod.Hop(self.me.mod, c), "a second request waits a moment")
        self.me.advance(5)
        self.assertTrue(self.me.mod.Hop(self.me.mod, c))

    def test_never_leaves_own_group(self):
        self.me.run("STUB.group = 3; STUB.party = { 'A', 'B' }")
        self.assertFalse(self.me.mod.Leave(self.me.mod))
        self.assertEqual(self.me.stub.left, 0)

    def test_stay_and_leave_by_hand(self):
        self.me.run("LZ.modules.LayerHop.opt.autoLeave = false")
        self.hop()
        deliver(self.me, self.host)
        self.host.run("StaticPopupDialogs.LEEROYLINK_LAYERHOP.OnAccept()")
        self.me.fire("PARTY_INVITE_REQUEST", "Kaelith")
        join(self.me, self.host)
        self.me.advance(30)
        self.assertEqual(self.me.stub.left, 0)
        self.me.lz.HandleSlash(self.me.lz, "layer verlassen")
        self.assertEqual(self.me.stub.left, 1)

    def test_manual_accept_waits(self):
        """Without auto accept the game's invite popup may stay open longer than the usual wait."""
        self.me.run("LZ.modules.LayerHop.opt.autoAccept = false")
        self.hop()
        deliver(self.me, self.host)
        self.host.take_outbox()                          # the answer gets lost, only the invite arrives
        self.host.run("StaticPopupDialogs.LEEROYLINK_LAYERHOP.OnAccept()")
        self.me.fire("PARTY_INVITE_REQUEST", "Kaelith")
        self.assertEqual(self.me.stub.accepted, 0)
        self.me.advance(50)
        self.assertEqual(self.me.state(), "waiting")
        join(self.me, self.host)                         # accepted by hand
        self.assertEqual(self.me.state(), "joined")
        self.me.advance(7)
        self.assertEqual(self.me.stub.left, 1)

    def test_declined_popup(self):
        self.hop()
        deliver(self.me, self.host)
        deliver(self.host, self.me)
        self.host.run("StaticPopupDialogs.LEEROYLINK_LAYERHOP.OnCancel()")
        deliver(self.host, self.me)
        self.assertEqual(self.me.state(), "idle")
        self.assertIn("abgelehnt", self.me.chat())

    def test_battlenet_friend(self):
        me, host = Client("Rosenbert"), Client("Kaelith")
        me.run('STUB.bnFriends = { { account = "Kae#1234", id = 77, char = "Kaelith", area = "Rotkammgebirge" } }')
        host.run('STUB.bnFriends = { { account = "Rosi#9", id = 55, char = "Rosenbert", area = "Rotkammgebirge" } }')
        c = me.mod.Find(me.mod, "kae#")
        self.assertIsNotNone(c, "found by the Battle.net name")
        self.assertEqual(c["bnet"], 77)
        me.mod.Hop(me.mod, c)
        msgs = deliver(me, host, bnet_id=55)
        self.assertEqual(msgs[0]["chatType"], "BN")
        self.assertEqual(len(Client.items(host.stub.popups)), 1, "Battle.net friends may ask")
        deliver(host, me, bnet_id=77)
        self.assertEqual(me.state(), "waiting")

    def test_ping_and_list(self):
        self.host.run("STUB.inGuild = true; STUB.guild = { { name = 'Rosenbert-CAMWOWEU5Realm2PvP', zone = 'Dämmerwald' } }")
        self.me.mod.Ping(self.me.mod, True)
        deliver(self.me, self.host)
        deliver(self.host, self.me)                      # PONG
        report = self.me.mod.Report(self.me.mod)
        self.assertIn("Kaelith", report)
        self.assertIn("Leeroylink " + str(self.host.lz.version), report)
        self.me.mod.ShowWindow(self.me.mod)
        self.me.advance(1)
        self.assertTrue(self.me.lua.globals().LeeroylinkLayerHop.shown)
        self.me.lz.HandleSlash(self.me.lz, "layer")      # toggles it closed
        self.assertFalse(self.me.lua.globals().LeeroylinkLayerHop.shown)

    def test_no_messages_in_instances(self):
        self.me.run('STUB.instance = { "Die Todesminen", "party", 1, "", 5, 0, false, 36 }')
        c = self.me.mod.Find(self.me.mod, "Kaelith")
        self.assertFalse(self.me.mod.Hop(self.me.mod, c))
        self.me.mod.Ping(self.me.mod, True)
        self.assertEqual(self.me.take_outbox(), [])


@unittest.skipIf(lua51 is None, "lupa not installed")
class RealmTests(unittest.TestCase):
    """WoW Forever gibt seit dem 20.11.2026 keinen Realm mehr heraus."""

    OLD = '''
LeeroylinkDB = { schema = 1, settings = { modules = {}, opts = {}, minimap = {} }, global = {
  sessionLog = {
    { v = 2, id = "Rosenbert-Forever:100", char = "Rosenbert-Forever", realm = "", start = 100, saved = 200 },
    { v = 2, id = "Rosenbert-CAMWOWEU5Realm2PvP:50", char = "Rosenbert-CAMWOWEU5Realm2PvP", realm = "CAMWOWEU5Realm2PvP", start = 50 },
  },
  loot = { { t = 1, item = 1, char = "Rosenbert-Forever" } },
}, chars = {
  ["Rosenbert-CAMWOWEU5Realm2PvP"] = { lastSeen = 10, pos = { m = 1433, t = 1 }, tasks = { { text = "Alt" } },
    recipes = { Alchemie = { rank = 1 } }, leeroy = { deaths = 2, pullDeaths = 1, byZone = { A = 2 } }, bank = { [1] = 3 } },
  ["Rosenbert-Forever"] = { lastSeen = 20, pos = { m = 1429, t = 2 }, tasks = {}, recipes = { Schmiedekunst = { rank = 5 } },
    leeroy = { deaths = 1, pullDeaths = 0, byZone = { A = 1, B = 1 } }, bags = { [2] = 1 } },
  ["Twink-CAMWOWEU5Realm2PvP"] = { lastSeen = 5 },
} }
'''

    def client(self, name="Rosenbert", db=""):
        return Client(name, setup=db + '\nSTUB.realm = ""')

    def test_placeholder_is_adopted(self):
        c = self.client(db=self.OLD)
        self.assertEqual(c.lz.charKey, "Rosenbert-CAMWOWEU5Realm2PvP")
        chars = c.lz.db.chars
        self.assertIsNone(chars["Rosenbert-Forever"])
        ch = chars["Rosenbert-CAMWOWEU5Realm2PvP"]
        self.assertEqual(ch.pos.m, 1429, "newer values win")
        self.assertEqual(ch.tasks[1].text, "Alt", "an empty list does not replace data")
        self.assertEqual(ch.recipes.Alchemie.rank, 1)
        self.assertEqual(ch.recipes.Schmiedekunst.rank, 5)
        self.assertEqual((ch.leeroy.deaths, ch.leeroy.byZone.A, ch.leeroy.byZone.B), (3, 3, 1), "counters add up")
        self.assertEqual(ch.bank[1], 3)
        self.assertEqual(ch.bags[2], 1)
        log = c.lz.gdb.sessionLog
        self.assertEqual(log[1].char, "Rosenbert-CAMWOWEU5Realm2PvP")
        self.assertEqual(log[1].realm, "CAMWOWEU5Realm2PvP")
        self.assertEqual(log[1].id, "Rosenbert-Forever:100", "the session id stays (Leeroyzan knows it)")
        self.assertEqual(c.lz.gdb.loot[1].char, "Rosenbert-CAMWOWEU5Realm2PvP")
        self.assertEqual(c.lz.gdb.charAliases["Rosenbert-Forever"], "Rosenbert-CAMWOWEU5Realm2PvP")
        self.assertIn("gehört jetzt wieder zu Rosenbert-CAMWOWEU5Realm2PvP", c.chat())
        s = c.lz.modules.Session.Current(c.lz.modules.Session)
        self.assertEqual(s.realm, "CAMWOWEU5Realm2PvP", "new sessions carry the realm")

    def test_new_character_takes_the_accounts_realm(self):
        c = self.client("Neuling", db=self.OLD)
        self.assertEqual(c.lz.charKey, "Neuling-CAMWOWEU5Realm2PvP")

    def test_fresh_install_without_realm(self):
        c = self.client()
        self.assertEqual(c.lz.charKey, "Rosenbert-Forever")
        self.assertIsNone(c.lz.gdb.charAliases)

    def test_visible_realm_is_remembered(self):
        c = Client("Rosenbert")
        self.assertEqual(c.lz.charKey, "Rosenbert-CAMWOWEU5Realm2PvP")
        self.assertEqual(c.lz.gdb.realm, "CAMWOWEU5Realm2PvP")


if __name__ == "__main__":
    unittest.main()
