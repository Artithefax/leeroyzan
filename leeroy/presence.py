"""Discord Rich Presence: zeigt im Discord-Profil, dass und was gerade gespielt wird.

Spricht direkt mit dem laufenden Discord-Programm auf diesem PC (lokale Verbindung, kein Internet, kein Token):
unter Windows über die benannte Pipe \\\\.\\pipe\\discord-ipc-0 … 9, sonst über den Socket discord-ipc-0 … 9.
Nachrichten sind Rahmen aus Art (4 Byte), Länge (4 Byte) und JSON. Wird die Verbindung geschlossen,
nimmt Discord die Anzeige von selbst zurück.
"""
from __future__ import annotations

import json
import os
import socket
import struct
import sys
import time
import uuid

from .i18n import tr

OP_HANDSHAKE, OP_FRAME, OP_CLOSE, OP_PING, OP_PONG = 0, 1, 2, 3, 4
IPC_TIMEOUT = 3.0                # so lange auf eine Antwort von Discord warten (Sekunden)
MAX_FRAME = 1 << 20
PRESENCE_IMAGE = "logo"          # Name des Bilds unter „Rich Presence → Art Assets“ der Discord-Anwendung


def ipc_paths() -> list[str]:
    """Mögliche Adressen des Discord-Programms, in der Reihenfolge, in der Discord sie vergibt."""
    if sys.platform.startswith("win"):
        return [rf"\\.\pipe\discord-ipc-{i}" for i in range(10)]
    bases = [os.environ.get(k) for k in ("XDG_RUNTIME_DIR", "TMPDIR", "TMP", "TEMP")] + ["/tmp"]
    out = []
    for base in dict.fromkeys(b for b in bases if b):
        for sub in ("", "app/com.discordapp.Discord", "snap.discord"):
            out += [os.path.join(base, sub, f"discord-ipc-{i}") for i in range(10)]
    return out


class _SocketPipe:
    """Linux/macOS: Unix-Socket."""

    def __init__(self, path: str):
        self.s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.s.settimeout(IPC_TIMEOUT)
        try:
            self.s.connect(path)
        except OSError:
            self.s.close()
            raise

    def send(self, data: bytes) -> None:
        self.s.sendall(data)

    def recv(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self.s.recv(n - len(buf))          # socket.timeout ist ein OSError
            if not chunk:
                raise OSError("Discord hat die Verbindung geschlossen")
            buf += chunk
        return buf

    def close(self) -> None:
        self.s.close()


class _WindowsPipe:
    """Windows: benannte Pipe. Gelesen wird erst, wenn Daten da sind – so bleibt nie ein Lesevorgang hängen."""

    def __init__(self, path: str):
        import ctypes
        import msvcrt
        from ctypes import wintypes
        self.f = open(path, "r+b", buffering=0)
        self._avail = wintypes.DWORD(0)
        self._ref = ctypes.byref(self._avail)
        self._handle = wintypes.HANDLE(msvcrt.get_osfhandle(self.f.fileno()))
        self._peek = ctypes.windll.kernel32.PeekNamedPipe
        self._peek.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
                               ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        self._peek.restype = wintypes.BOOL

    def send(self, data: bytes) -> None:
        self.f.write(data)

    def recv(self, n: int) -> bytes:
        deadline = time.monotonic() + IPC_TIMEOUT
        while True:
            if not self._peek(self._handle, None, 0, None, self._ref, None):
                raise OSError("Discord hat die Verbindung geschlossen")
            if self._avail.value >= n:
                break
            if time.monotonic() > deadline:
                raise OSError("Discord antwortet nicht")
            time.sleep(0.03)
        buf = b""
        while len(buf) < n:
            chunk = self.f.read(n - len(buf))
            if not chunk:
                raise OSError("Discord hat die Verbindung geschlossen")
            buf += chunk
        return buf

    def close(self) -> None:
        self.f.close()


def open_pipe(path: str):
    return _WindowsPipe(path) if sys.platform.startswith("win") else _SocketPipe(path)


class DiscordPresence:
    """Eine Verbindung zum Discord-Programm. Nicht für mehrere Threads gleichzeitig gedacht."""

    def __init__(self, client_id: str, paths=ipc_paths, opener=open_pipe):
        self.client_id = str(client_id)
        self._paths, self._opener = paths, opener
        self._pipe = None
        self.shown: dict | None = None          # Anzeige, die Discord zuletzt bestätigt hat
        self.user = ""                           # Discord-Name aus der Begrüßung

    @property
    def connected(self) -> bool:
        return self._pipe is not None

    # Rahmen ------------------------------------------------------------------------ #
    def _send(self, op: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self._pipe.send(struct.pack("<II", op, len(data)) + data)

    def _read(self) -> tuple[int, dict]:
        op, size = struct.unpack("<II", self._pipe.recv(8))
        if size > MAX_FRAME:
            raise OSError("Antwort von Discord ist zu groß")
        try:
            data = json.loads(self._pipe.recv(size).decode("utf-8", "replace")) if size else {}
        except ValueError:
            data = {}
        return op, data if isinstance(data, dict) else {}

    def _answer(self, nonce: str = "") -> dict:
        """Liest bis zur Antwort auf unseren Befehl; Pings werden beantwortet, andere Ereignisse übergangen."""
        for _ in range(20):
            op, data = self._read()
            if op == OP_PING:
                self._send(OP_PONG, data)
            elif op == OP_CLOSE:
                raise OSError(f"Discord hat abgelehnt: {data.get('message') or data.get('code') or '?'}")
            elif op == OP_FRAME and (not nonce or data.get("nonce") == nonce):
                if data.get("evt") == "ERROR":
                    raise OSError(f"Discord meldet: {(data.get('data') or {}).get('message') or '?'}")
                return data
        raise OSError("Discord antwortet nicht auf den Befehl")

    # Verbindung -------------------------------------------------------------------- #
    def connect(self) -> bool:
        """True, wenn Discord läuft und die Anwendung angenommen hat."""
        if self._pipe is not None:
            return True
        for path in self._paths():
            try:
                self._pipe = self._opener(path)
            except OSError:
                continue
            try:
                self._send(OP_HANDSHAKE, {"v": 1, "client_id": self.client_id})
                ready = self._answer()
                self.user = str(((ready.get("data") or {}).get("user") or {}).get("username") or "")
                return True
            except (OSError, struct.error):
                self.close()
        return False

    def close(self) -> None:
        """Verbindung beenden – Discord nimmt die Anzeige dann zurück."""
        pipe, self._pipe, self.shown = self._pipe, None, None
        if pipe is not None:
            try:
                pipe.close()
            except OSError:
                pass

    def update(self, activity: dict | None) -> bool:
        """Anzeige setzen (oder mit None löschen). Sendet nur, wenn sich etwas geändert hat.
        True = Discord zeigt jetzt genau das an."""
        if activity is None and self._pipe is None:
            return True
        if not self.connect():
            return False
        if activity == self.shown and activity is not None:
            return True
        nonce = uuid.uuid4().hex
        try:
            self._send(OP_FRAME, {"cmd": "SET_ACTIVITY", "nonce": nonce,
                                  "args": {"pid": os.getpid(), "activity": activity}})
            self._answer(nonce)
        except (OSError, struct.error):
            self.close()
            return False
        self.shown = activity
        return True


# ----- Was angezeigt wird ------------------------------------------------------------- #
def game_title(flavor: str) -> str:
    """_forever_ -> WoW Forever, _classic_era_ -> WoW Classic Era, _retail_ -> World of Warcraft."""
    n = (flavor or "").strip("_").lower()
    if not n or n == "retail":
        return "World of Warcraft"
    if "forever" in n or n == "classic_beta":
        return "WoW Forever"
    return "WoW " + " ".join(w.upper() if w == "ptr" else w.capitalize() for w in n.split("_"))


def latest_char(chars: dict) -> dict | None:
    """Der zuletzt gespielte Charakter aus den Daten von Leeroylink."""
    seen = [c for c in (chars or {}).values() if c.get("lastSeen")]
    return max(seen, key=lambda c: c["lastSeen"]) if seen else None


def presence_activity(flavor: str, started: float, char: dict | None = None, class_names: dict | None = None) -> dict:
    """Die Anzeige im Discord-Profil: Spiel, auf Wunsch Charakter mit Stufe und Klasse, Spielzeit seit Start."""
    act = {"details": game_title(flavor)[:128], "timestamps": {"start": int(started)},
           "assets": {"large_image": PRESENCE_IMAGE, "large_text": "Leeroyzan"}}
    if char and char.get("name"):
        cls = char.get("class") or ""
        cls = tr((class_names or {}).get(cls, cls.title())) if cls else ""
        if char.get("level"):
            state = tr("{0} · Stufe {1} {2}", char["name"], char["level"], cls).strip()
        else:
            state = f"{char['name']} · {cls}" if cls else char["name"]
        if len(state) >= 2:
            act["state"] = state[:128]
    return act
