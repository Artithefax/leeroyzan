"""Discord Rich Presence (python3 tests/test_presence.py): Rahmen, Begrüßung, Anzeige setzen und zurücknehmen.

Ein kleiner Stellvertreter für das Discord-Programm lauscht auf einem Unix-Socket und spricht dasselbe
Protokoll (nicht unter Windows – dort gibt es dafür benannte Pipes). Die Anzeige-Texte laufen überall.
"""
import json
import os
import shutil
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="lz-rpc-"))
os.environ.setdefault("APPDATA", str(TMP / "appdata"))
sys.path.insert(0, str(ROOT))

import leeroy.api as lz  # noqa: E402


class FakeDiscord:
    """Nimmt Verbindungen an und merkt sich alle Befehle. mode: ok | reject | error | silent | ping"""

    def __init__(self, path: Path, mode: str = "ok"):
        self.path, self.mode = path, mode
        self.frames: list[tuple[int, dict]] = []
        self.closed = threading.Event()
        self.srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.srv.bind(str(path))
        self.srv.listen(2)
        threading.Thread(target=self._serve, daemon=True).start()

    @staticmethod
    def _recv(conn, n):
        buf = b""
        while len(buf) < n:
            chunk = conn.recv(n - len(buf))
            if not chunk:
                raise ConnectionError
            buf += chunk
        return buf

    @staticmethod
    def _send(conn, op, payload):
        data = json.dumps(payload).encode()
        conn.sendall(struct.pack("<II", op, len(data)) + data)

    def _serve(self):
        while True:
            try:
                conn, _ = self.srv.accept()
            except OSError:
                return
            self.closed.clear()
            try:
                while True:
                    op, size = struct.unpack("<II", self._recv(conn, 8))
                    data = json.loads(self._recv(conn, size))
                    self.frames.append((op, data))
                    if self.mode == "silent":
                        continue
                    if op == 0:
                        if self.mode == "reject":
                            self._send(conn, 2, {"code": 4000, "message": "Invalid Client ID"})
                            break
                        self._send(conn, 1, {"cmd": "DISPATCH", "evt": "READY", "data": {"v": 1, "user": {"username": "rosenbert"}}})
                    elif op == 1:
                        if self.mode == "ping":
                            self._send(conn, 3, {"p": 1})
                            self._send(conn, 1, {"cmd": "DISPATCH", "evt": "ACTIVITY_JOIN", "data": {}, "nonce": None})
                        evt = "ERROR" if self.mode == "error" else None
                        self._send(conn, 1, {"cmd": data["cmd"], "evt": evt, "nonce": data["nonce"],
                                             "data": {"message": "bad activity"} if evt else data["args"]["activity"]})
            except (ConnectionError, OSError, struct.error):
                pass
            finally:
                conn.close()
                self.closed.set()

    def stop(self):
        self.srv.close()


@unittest.skipIf(sys.platform.startswith("win"), "Unix-Socket als Stellvertreter für Discord")
class IpcTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="rpc-", dir=TMP))
        self.servers, self.clients = [], []
        self._timeout = lz.module_of("DiscordPresence").IPC_TIMEOUT
        lz.module_of("DiscordPresence").IPC_TIMEOUT = 0.5

    def tearDown(self):
        lz.module_of("DiscordPresence").IPC_TIMEOUT = self._timeout
        for c in self.clients:
            c.close()
        for s in self.servers:
            s.stop()

    def discord(self, mode="ok", slot=0):
        s = FakeDiscord(self.dir / f"discord-ipc-{slot}", mode)
        self.servers.append(s)
        return s

    def client(self):
        pr = lz.DiscordPresence("123", paths=lambda: [str(self.dir / f"discord-ipc-{i}") for i in range(10)])
        self.clients.append(pr)
        return pr

    def test_show_change_clear(self):
        srv = self.discord()
        pr = self.client()
        act = lz.presence_activity("_forever_", 1794300000)
        self.assertTrue(pr.update(act))
        self.assertEqual(pr.user, "rosenbert")
        self.assertEqual(srv.frames[0], (0, {"v": 1, "client_id": "123"}))
        op, cmd = srv.frames[1]
        self.assertEqual((op, cmd["cmd"], cmd["args"]["pid"], cmd["args"]["activity"]), (1, "SET_ACTIVITY", os.getpid(), act))
        self.assertTrue(pr.update(dict(act)))                          # unverändert: nichts senden
        self.assertEqual(len(srv.frames), 2)
        act2 = lz.presence_activity("_forever_", 1794300000, {"name": "Rosenbert", "level": 22, "class": "WARRIOR"}, lz.CLASS_NAMES)
        self.assertTrue(pr.update(act2))
        self.assertEqual(srv.frames[2][1]["args"]["activity"]["state"], "Rosenbert · Stufe 22 Krieger")
        self.assertTrue(pr.update(None))                               # löschen
        self.assertIsNone(srv.frames[3][1]["args"]["activity"])
        pr.close()
        self.assertTrue(srv.closed.wait(2))                            # Discord sieht das Ende der Verbindung
        self.assertFalse(pr.connected)
        self.assertTrue(pr.update(None))                               # ohne Verbindung gibt es nichts zu löschen
        self.assertEqual(len(srv.frames), 4)

    def test_pings_and_other_events_are_skipped(self):
        srv = self.discord("ping")
        pr = self.client()
        self.assertTrue(pr.update(lz.presence_activity("_retail_", 5)))
        for _ in range(100):                                           # der Pong kommt kurz nach unserer Antwort an
            if (4, {"p": 1}) in srv.frames:
                break
            time.sleep(0.01)
        self.assertIn((4, {"p": 1}), srv.frames)
        self.assertTrue(pr.connected)

    def test_no_discord(self):
        pr = self.client()
        self.assertFalse(pr.connect())
        self.assertFalse(pr.update(lz.presence_activity("_forever_", 5)))
        (self.dir / "discord-ipc-0").write_text("kein Socket")         # Überbleibsel: nächste Adresse nehmen
        srv = self.discord(slot=1)
        self.assertTrue(pr.update(lz.presence_activity("_forever_", 5)))
        self.assertEqual(len(srv.frames), 2)

    def test_rejected_silent_and_errors(self):
        self.discord("reject")
        pr = self.client()
        self.assertFalse(pr.update(lz.presence_activity("_forever_", 5)))
        self.assertFalse(pr.connected)
        self.servers.pop().stop(); (self.dir / "discord-ipc-0").unlink()
        self.discord("silent")
        self.assertFalse(pr.connect())                                 # keine Antwort: nach der Wartezeit aufgeben
        self.servers.pop().stop(); (self.dir / "discord-ipc-0").unlink()
        srv = self.discord("error")
        self.assertFalse(pr.update(lz.presence_activity("_forever_", 5)))
        self.assertFalse(pr.connected)                                 # nach einem Fehler neu verbinden
        self.assertIsNone(pr.shown)
        srv.mode = "ok"
        self.assertTrue(pr.update(lz.presence_activity("_forever_", 5)))

    def test_discord_restart(self):
        srv = self.discord()
        pr = self.client()
        act = lz.presence_activity("_forever_", 5)
        self.assertTrue(pr.update(act))
        srv.stop(); (self.dir / "discord-ipc-0").unlink()
        pr._pipe.s.shutdown(socket.SHUT_RDWR)                          # Discord wurde beendet
        self.assertFalse(pr.update(lz.presence_activity("_forever_", 6)))
        srv2 = self.discord()
        self.assertTrue(pr.update(act))                                # dieselbe Anzeige wird neu gesendet
        self.assertEqual(srv2.frames[1][1]["args"]["activity"], act)


class ActivityTests(unittest.TestCase):
    def test_titles(self):
        for flavor, title in (("_forever_", "WoW Forever"), ("_classic_beta_", "WoW Forever"), ("_retail_", "World of Warcraft"),
                              ("_classic_era_", "WoW Classic Era"), ("_classic_", "WoW Classic"), ("_classic_ptr_", "WoW Classic PTR"),
                              ("", "World of Warcraft")):
            self.assertEqual(lz.game_title(flavor), title)

    def test_activity(self):
        lz.set_language("de")
        a = lz.presence_activity("_forever_", 1794300000.7)
        self.assertEqual(a, {"details": "WoW Forever", "timestamps": {"start": 1794300000},
                             "assets": {"large_image": "logo", "large_text": "Leeroyzan"}})
        char = {"name": "Rosenbert", "level": 22, "class": "WARRIOR"}
        lz.set_language("en")
        self.assertEqual(lz.presence_activity("_forever_", 1, char, lz.CLASS_NAMES)["state"], "Rosenbert · Level 22 Warrior")
        lz.set_language("de")
        self.assertEqual(lz.presence_activity("_forever_", 1, {"name": "Rosenbert", "level": 0, "class": ""})["state"], "Rosenbert")
        self.assertEqual(lz.presence_activity("_forever_", 1, {"name": "Xy", "level": 0, "class": "MAGE"}, lz.CLASS_NAMES)["state"], "Xy · Magier")
        self.assertNotIn("state", lz.presence_activity("_forever_", 1, {"name": "", "level": 5}))
        long = lz.presence_activity("_forever_", 1, {"name": "N" * 200, "level": 60, "class": "MAGE"}, lz.CLASS_NAMES)
        self.assertEqual(len(long["state"]), 128)
        json.dumps(long)

    def test_latest_char(self):
        chars = {"a": {"name": "Alt", "lastSeen": 5}, "b": {"name": "Neu", "lastSeen": 9}, "c": {"name": "Nie", "lastSeen": 0}}
        self.assertEqual(lz.latest_char(chars)["name"], "Neu")
        self.assertIsNone(lz.latest_char({}))
        self.assertIsNone(lz.latest_char(None))

    def test_paths(self):
        paths = lz.ipc_paths()
        self.assertTrue(all("discord-ipc-" in p for p in paths))
        self.assertGreaterEqual(len(paths), 10)
        self.assertRegex(lz.DISCORD_APP_ID, r"^\d{17,20}$")


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
