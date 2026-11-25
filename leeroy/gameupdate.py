"""Braucht WoW ein Update? Vergleicht den installierten Build (.build.info im WoW-Ordner) mit dem aktuellen Build auf
Blizzards Versionsserver – und öffnet bei Bedarf die Battle.net-App auf der richtigen Spielseite, damit sie das Update
lädt. Leeroyzan lädt keine Spieldateien selbst; das macht immer die Battle.net-App.

Dateien (schreibt die Battle.net-App):
- <WoW-Ordner>/.build.info – je Spielversion eine Zeile: Branch (Region), Active, Build Key, …, Version, Product
- <WoW-Ordner>/<_flavor_>/.flavor.info – der Produktname dieser Spielversion (z. B. wow_classic_era)
Versionsserver (öffentlich, ohne Anmeldung): https://<region>.version.battle.net/v2/products/<produkt>/versions,
als Rückweg http://<region>.patch.battle.net:1119/<produkt>/versions – eine Tabelle mit Region, BuildConfig, VersionsName.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

from .constants import USER_AGENT
from .wow import flavor_product

REGIONS = ("us", "eu", "kr", "tw")
VERSION_URLS = ("https://{region}.version.battle.net/v2/products/{product}/versions",
                "http://{region}.patch.battle.net:1119/{product}/versions")
TIMEOUT = 3          # Sekunden je Server – „Spielen“ soll nicht spürbar warten


def parse_table(text: str) -> list[dict[str, str]]:
    """Blizzards Tabellenformat (Kopfzeile „Name!TYP:0|…“, Zeilen mit „|“, Kommentare mit „##“) → Liste von Zeilen
    mit klein geschriebenen Spaltennamen."""
    rows: list[dict[str, str]] = []
    cols: list[str] | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if cols is None:
            if "!" not in line:
                continue
            cols = [c.split("!")[0].strip().lower() for c in line.split("|")]
            continue
        vals = line.split("|")
        rows.append({c: (vals[i].strip() if i < len(vals) else "") for i, c in enumerate(cols)})
    return rows


def product_code(root: str, flavor: str) -> str:
    """Produktname dieser Spielversion – aus .flavor.info, sonst aus dem Ordnernamen geraten."""
    try:
        text = (Path(root) / flavor / ".flavor.info").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return flavor_product(flavor)
    rows = parse_table(text)
    for r in rows:
        for v in r.values():
            if re.fullmatch(r"[a-z0-9_]+", v or ""):
                return v
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and "!" not in ln]
    return lines[0] if lines and re.fullmatch(r"[a-z0-9_]+", lines[0]) else flavor_product(flavor)


def local_build(root: str, flavor: str) -> dict | None:
    """Installierter Build dieser Spielversion: {"product", "region", "build", "version", "locale"} oder None."""
    try:
        text = (Path(root) / ".build.info").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    product = product_code(root, flavor)
    rows = [r for r in parse_table(text) if r.get("product", "").lower() == product.lower()]
    if not rows:
        return None
    rows.sort(key=lambda r: r.get("active") == "1", reverse=True)        # die aktive Zeile zuerst
    r = rows[0]
    locale = next((t for t in re.split(r"[\s?:]+", r.get("tags", "")) if re.fullmatch(r"[a-z]{2}[A-Z]{2}", t)), "")
    return {"product": product, "region": (r.get("branch") or "us").lower(), "build": r.get("build key", "").lower(),
            "version": r.get("version", ""), "locale": locale}


def fetch_versions(product: str, region: str = "us", timeout: float = TIMEOUT, opener=None) -> list[dict[str, str]]:
    """Aktuelle Builds eines Produkts vom Versionsserver (erst HTTPS, dann der alte Port 1119)."""
    opener = opener or urllib.request.urlopen
    host = region if region in REGIONS else "us"
    last: Exception | None = None
    for pattern in VERSION_URLS:
        url = pattern.format(region=host, product=product)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with opener(req, timeout=timeout) as r:
                rows = parse_table(r.read(200_000).decode("utf-8", "replace"))
            if rows:
                return rows
        except (OSError, ValueError) as e:
            last = e
    if last:
        raise last
    return []


def compare(local: dict, rows: list[dict[str, str]]) -> dict:
    """{"state": "current" | "update" | "unknown", "local", "remote", "target"} – target = Build, der kommen soll."""
    row = next((r for r in rows if r.get("region", "").lower() == local["region"]), None) or (rows[0] if rows else None)
    out = {"state": "unknown", "local": local["version"], "remote": "", "target": "", "product": local["product"]}
    if not row:
        return out
    remote_build = row.get("buildconfig", "").lower()
    out["remote"] = row.get("versionsname", "")
    out["target"] = remote_build
    if remote_build and local["build"]:
        out["state"] = "current" if remote_build == local["build"] else "update"
    elif out["remote"] and local["version"]:
        out["state"] = "current" if out["remote"] == local["version"] else "update"
    return out


def check_update(root: str, flavor: str, opener=None) -> dict:
    """Ganze Prüfung. Bei Fehlern (offline, unbekanntes Produkt) state = "unknown" mit "error"."""
    local = local_build(root, flavor)
    if not local:
        return {"state": "unknown", "error": "build.info", "product": product_code(root, flavor), "local": "", "remote": ""}
    try:
        rows = fetch_versions(local["product"], local["region"], opener=opener)
    except (OSError, ValueError) as e:
        return {"state": "unknown", "error": str(e), "product": local["product"], "local": local["version"], "remote": ""}
    return compare(local, rows)


def quiet_for(root: str, now: float | None = None) -> float:
    """Sekunden seit dem letzten Schreiben der Battle.net-App in den Spieldateien (.build.info und die Index-Dateien
    in Data/data). Erst wenn das eine Weile ruhig ist, ist das Update wirklich fertig."""
    import time
    paths = [Path(root) / ".build.info"]
    try:
        paths += list((Path(root) / "Data" / "data").glob("*.idx"))
    except OSError:
        pass
    newest = 0.0
    for p in paths:
        try:
            newest = max(newest, p.stat().st_mtime)
        except OSError:
            pass
    return max(0.0, (time.time() if now is None else now) - newest) if newest else 1e9


# ----- Battle.net-App ---------------------------------------------------------------------- #
def battlenet_exe() -> Path | None:
    """Pfad zur Battle.net.exe (Registry, sonst die üblichen Ordner) – nur unter Windows."""
    if not sys.platform.startswith("win"):
        return None
    cands: list[Path] = []
    try:
        import winreg
        for hive, key in ((winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Battle.net"),
                          (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Battle.net")):
            try:
                with winreg.OpenKey(hive, key) as k:
                    loc = winreg.QueryValueEx(k, "InstallLocation")[0]
                    if loc:
                        cands.append(Path(loc) / "Battle.net.exe")
            except OSError:
                pass
    except ImportError:
        pass
    for env in ("ProgramFiles(x86)", "ProgramFiles"):
        if os.environ.get(env):
            cands.append(Path(os.environ[env]) / "Battle.net" / "Battle.net.exe")
    return next((p for p in cands if p.is_file()), None)


def battlenet_args(root: str, local: dict | None) -> list[str]:
    """Wie der „World of Warcraft Launcher“ die App aufruft: Spielseite des Produkts im richtigen Ordner."""
    if not local:
        return []
    args = [f"--productcode={local['product']}", f"--gamepath={root}"]
    if local.get("locale"):
        args.insert(0, f"--game=wow_{local['locale'].lower()}")
    return args


def open_battlenet(root: str, flavor: str, popen=subprocess.Popen) -> str:
    """Öffnet die Battle.net-App auf der Seite dieser Spielversion. Gibt zurück, wie: "app", "launcher", "uri"."""
    exe = battlenet_exe()
    local = local_build(root, flavor)
    if exe:
        flags = 0x00000008 | 0x00000200 if sys.platform.startswith("win") else 0
        popen([str(exe), *battlenet_args(root, local)], cwd=str(exe.parent), close_fds=True, creationflags=flags)
        return "app"
    launcher = Path(root) / "World of Warcraft Launcher.exe"
    if launcher.is_file():
        flags = 0x00000008 | 0x00000200 if sys.platform.startswith("win") else 0
        popen([str(launcher)], cwd=str(launcher.parent), close_fds=True, creationflags=flags)
        return "launcher"
    os.startfile("battlenet://")       # noqa – nur Windows; sonst AttributeError beim Aufrufer
    return "uri"
