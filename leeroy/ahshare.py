"""AH-Preise mit Freunden teilen: als Datei (.lzprices) in Discord posten, bei Freunden importieren.

Jeder Preis trägt seinen eigenen Zeitstempel (wann er im Auktionshaus gesehen wurde). Beim Zusammenführen gilt je
Gegenstand der neueste Preis – egal, in welcher Reihenfolge die Dateien kommen. Preise, die älter sind als die
eingestellte Grenze (Standard 7 Tage), zählen nirgends mehr mit: nicht als aktueller Preis, nicht für Schnäppchen,
nicht im Tooltip im Spiel.
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from .auction import AUC_DAY0, auction_row
from .config import config_dir
from .constants import USER_AGENT
from .i18n import tr
from .sessions import _int

PRICE_EXT = ".lzprices"
PRICE_KIND = "leeroyzan-ah-prices"
PRICE_FORMAT = 1
DEFAULT_MAX_DAYS = 7
MAX_FILE = 8 * 1024 * 1024                  # Discord nimmt Anhänge bis 8 MB (ohne Nitro)
DISCORD_CDN_RE = re.compile(r"^https://(?:cdn\.discordapp\.com|media\.discordapp\.net)/attachments/\S+$")


class PriceError(Exception):
    """Datei oder Link enthält keine (gültigen) AH-Preise."""


def day_ts(day: int) -> int:
    """Auctionator-Tag (ab 1.1.2020) → Unix-Zeit am Ende dieses Tages."""
    return int((AUC_DAY0 + timedelta(days=int(day) + 1)).timestamp()) - 1


def ts_day(ts: float) -> int:
    """Unix-Zeit → Auctionator-Tag."""
    return (datetime.fromtimestamp(ts) - AUC_DAY0).days


# ----- Export ---------------------------------------------------------------------------- #
def export_prices(data: dict, realm: str, author: str = "", flavor: str = "", now: float | None = None) -> dict:
    """Die eigenen Auctionator-Preise eines Realms: {"p": {ID: [Preis, Zeitstempel]}}.
    Zeitstempel = Ende des Scantags, höchstens der Zeitpunkt, zu dem WoW die Daten gespeichert hat."""
    now = now or time.time()
    saved = int(data.get("mtime") or now)
    prices: dict[str, list[int]] = {}
    for key, e in (data.get("realms", {}).get(realm) or {}).items():
        r = auction_row(key, e, {})
        if r["id"] <= 0 or r["price"] <= 0:
            continue
        ts = min(day_ts(r["last"]), saved) if r["last"] else saved
        old = prices.get(str(r["id"]))
        if not old or ts > old[1]:
            prices[str(r["id"])] = [r["price"], int(ts)]
    return {"kind": PRICE_KIND, "v": PRICE_FORMAT, "flavor": flavor, "realm": realm, "by": author[:60],
            "at": int(now), "n": len(prices), "p": prices}


def prices_to_bytes(d: dict) -> bytes:
    return json.dumps(d, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def price_file_name(d: dict) -> str:
    realm = re.sub(r"[^\w-]+", "_", d.get("realm") or "Realm", flags=re.UNICODE).strip("_")[:30] or "Realm"
    return f"AH-Preise_{realm}_{datetime.fromtimestamp(d['at']):%Y-%m-%d_%H%M}{PRICE_EXT}"


def newest_ts(d: dict) -> int:
    return max((v[1] for v in d.get("p", {}).values()), default=0)


# ----- Import ---------------------------------------------------------------------------- #
def parse_prices(raw: bytes | str) -> dict:
    """Prüft eine .lzprices-Datei. Zeitstempel in der Zukunft werden auf jetzt gesetzt (falsche Uhr beim Freund)."""
    try:
        d = json.loads(raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw)
    except (ValueError, UnicodeDecodeError):
        raise PriceError(tr("Das ist keine Datei mit AH-Preisen.")) from None
    if not isinstance(d, dict) or d.get("kind") != PRICE_KIND or not isinstance(d.get("p"), dict):
        raise PriceError(tr("Das ist keine Datei mit AH-Preisen."))
    if _int(d.get("v")) > PRICE_FORMAT:
        raise PriceError(tr("Diese Preise stammen aus einer neueren Leeroyzan-Version – bitte Leeroyzan aktualisieren."))
    now = int(time.time())
    prices = {}
    for k, v in d["p"].items():
        if not str(k).isdigit() or not isinstance(v, list) or len(v) < 2:
            continue
        price, ts = _int(v[0]), _int(v[1])
        if price > 0 and ts > 0:
            prices[str(int(k))] = [price, min(ts, now)]
    if not prices:
        raise PriceError(tr("Die Datei enthält keine Preise."))
    return {"kind": PRICE_KIND, "v": PRICE_FORMAT, "flavor": str(d.get("flavor") or ""), "realm": str(d.get("realm") or "?"),
            "by": str(d.get("by") or "")[:60], "at": min(_int(d.get("at")) or now, now), "n": len(prices), "p": prices}


def fetch_discord_file(url: str) -> bytes:
    """Lädt einen Anhang, dessen Link man in Discord kopiert hat (nur Discord-Adressen)."""
    url = url.strip()
    if not DISCORD_CDN_RE.match(url):
        raise PriceError(tr("Das ist kein Link auf einen Discord-Anhang (Rechtsklick auf die Datei → Link kopieren)."))
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = r.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        raise PriceError(tr("Die Datei ist zu groß."))
    return data


# ----- Gespeicherte Preise von Freunden ---------------------------------------------- #
def shared_path(flavor: str) -> Path:
    name = re.sub(r"[^A-Za-z0-9]+", "", flavor) or "wow"
    return config_dir() / "ah_shared" / f"{name}.json"


def load_shared(flavor: str) -> dict:
    """{"realms": {Realm: {ID: [Preis, Zeitstempel, von]}}, "imports": [{by, realm, at, n, new}]}"""
    try:
        d = json.loads(shared_path(flavor).read_text(encoding="utf-8"))
        if isinstance(d, dict) and isinstance(d.get("realms"), dict):
            d.setdefault("imports", [])
            return d
    except (OSError, ValueError):
        pass
    return {"realms": {}, "imports": []}


def save_shared(flavor: str, store: dict) -> None:
    p = shared_path(flavor)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(p)


def merge_prices(store: dict, d: dict, realm: str | None = None) -> dict:
    """Führt eine Datei ein: je Gegenstand gilt der neueste Preis. Gibt {"new", "newer", "older"} zurück."""
    realm = realm or d["realm"]
    cur = store["realms"].setdefault(realm, {})
    res = {"new": 0, "newer": 0, "older": 0}
    for k, (price, ts) in d["p"].items():
        old = cur.get(k)
        if old is None:
            res["new"] += 1
        elif ts > old[1]:
            res["newer"] += 1
        else:
            res["older"] += 1
            continue
        cur[k] = [price, ts, d["by"]]
    store["imports"] = (store.get("imports", []) + [{"by": d["by"], "realm": realm, "at": d["at"], "n": d["n"],
                                                     "imported": int(time.time()), **res}])[-30:]
    return res


def prune_shared(store: dict, keep_days: int = 60, now: float | None = None) -> int:
    """Sehr alte geteilte Preise ganz entfernen (sie zählen ohnehin nicht mehr)."""
    cutoff = (now or time.time()) - keep_days * 86400
    n = 0
    for realm in list(store["realms"]):
        items = store["realms"][realm]
        for k in [k for k, v in items.items() if v[1] < cutoff]:
            del items[k]
            n += 1
        if not items:
            del store["realms"][realm]
    return n


def fresh_prices(store: dict, realm: str, max_days: int = DEFAULT_MAX_DAYS, now: float | None = None) -> dict[int, tuple]:
    """Geteilte Preise eines Realms, die noch zählen: {ID: (Preis, Zeitstempel, von)}."""
    cutoff = (now or time.time()) - max_days * 86400
    return {int(k): (v[0], v[1], v[2] if len(v) > 2 else "") for k, v in (store["realms"].get(realm) or {}).items()
            if v[1] >= cutoff}


def merge_into_entry(e: dict | None, price: int, ts: int) -> tuple[dict, bool]:
    """Ein geteilter Preis in einen Auctionator-Eintrag (Tagestief/-hoch): als Tag im Verlauf und – nur wenn er neuer
    ist als der eigene Scan – als aktueller Preis. Gibt (Eintrag, ist_aktuell) zurück. Der Eintrag wird kopiert."""
    day = ts_day(ts)
    src = e or {}

    def days_of(v) -> dict[str, int]:
        return {str(_int(k)): _int(x) for k, x in v.items()} if isinstance(v, dict) else {}
    e = {"m": _int(src.get("m")), "h": days_of(src.get("h")), "l": days_of(src.get("l")), "a": days_of(src.get("a"))}
    last = max((_int(d) for d in set(e["h"]) | set(e["l"])), default=0)
    key = str(day)
    if key not in e["l"]:                       # eigene Scans dieses Tages gehen vor
        e["l"][key] = price
        e["h"][key] = max(price, e["h"].get(key, 0))
    newest = day > last or not e["m"]
    if newest:
        e["m"] = price
    return e, newest


def shared_rows_for_realm(entries: dict, shared: dict[int, tuple]) -> tuple[dict, dict[str, dict]]:
    """Auctionator-Einträge eines Realms um geteilte Preise ergänzt. Gibt (Einträge, Herkunft je Schlüssel) zurück:
    Herkunft = {"by", "ts", "current"} für Gegenstände, deren Preis (auch) von Freunden kommt."""
    out = dict(entries)
    origin: dict[str, dict] = {}
    by_id = {}
    for key in entries:
        m = re.match(r"(?:[a-z]+:)?(\d+)$", key)
        if m:
            by_id[int(m.group(1))] = key
    for iid, (price, ts, by) in shared.items():
        key = by_id.get(iid, str(iid))
        e, current = merge_into_entry(entries.get(key), price, ts)
        out[key] = e
        origin[key] = {"by": by, "ts": ts, "current": current}
    return out, origin


def game_prices(store: dict, max_days: int = DEFAULT_MAX_DAYS, now: float | None = None, limit: int = 8000) -> dict:
    """Für Data.lua (Tooltips im Spiel), kompakt: {"days", "by": [Namen], "realms": {Realm: {ID: "Preis:Zeit:Name-Nr."}}}
    – nur, was noch zählt, je Realm die neuesten `limit` Preise."""
    by: list[str] = []
    realms = {}
    for realm in sorted(store.get("realms", {})):
        fresh = fresh_prices(store, realm, max_days, now)
        if not fresh:
            continue
        out = {}
        for iid, (price, ts, who) in sorted(fresh.items(), key=lambda kv: -kv[1][1])[:limit]:
            if who not in by:
                by.append(who)
            out[iid] = f"{price}:{ts}:{by.index(who) + 1}"
        realms[realm] = out
    return {"days": max_days, "by": by, "realms": realms} if realms else {}
