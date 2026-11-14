"""Bilder von Wowhead (Talent-Icons, Baum-Hintergründe) als PNG im Datenordner – Tk kann kein JPEG lesen.

Umgewandelt wird unter Windows mit Bordmitteln (GDI+), sonst mit Pillow, falls installiert. Geht beides nicht,
gibt es kein Bild und die Oberfläche zeichnet einen Platzhalter.
"""
from __future__ import annotations

import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .config import config_dir, log
from .wowhead import wowhead_bytes

ICON_BASE = "https://wow.zamimg.com/images/wow/icons"
BACKGROUND_BASE = "https://wow.zamimg.com/images/wow/talents/backgrounds"
_LOCK = threading.Lock()
_GDIPLUS: dict = {}


def icon_url(name: str, size: str = "large") -> str:
    """size: small (18 px), medium (36 px) oder large (56 px)."""
    return f"{ICON_BASE}/{size}/{re.sub(r'[^a-z0-9_.-]', '', (name or 'inv_misc_questionmark').lower())}.jpg"


def background_url(env: str, tab) -> str:
    return f"{BACKGROUND_BASE}/{re.sub(r'[^a-z0-9_-]', '', str(env).lower())}/{int(tab)}.jpg"


def image_dir() -> Path:
    return config_dir() / "wowhead" / "img"


def image_path(url: str, size: tuple[int, int] | None = None) -> Path:
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", url.split("://", 1)[-1].split("/", 1)[-1])[-120:]
    name = re.sub(r"\.jpe?g$", "", name, flags=re.I)
    return image_dir() / (name + (f"@{size[0]}x{size[1]}" if size else "") + ".png")


def can_convert() -> bool:
    if os.name == "nt":
        return True
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


def _gdiplus():
    """GDI+ einmal je Prozess starten (bleibt bis zum Ende geladen)."""
    with _LOCK:
        if not _GDIPLUS:
            import ctypes
            from ctypes import wintypes

            class StartupInput(ctypes.Structure):
                _fields_ = [("GdiplusVersion", ctypes.c_uint32), ("DebugEventCallback", ctypes.c_void_p),
                            ("SuppressBackgroundThread", wintypes.BOOL), ("SuppressExternalCodecs", wintypes.BOOL)]
            gdi = ctypes.WinDLL("gdiplus")
            vp, pvp = ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)
            for name, args in (("GdiplusStartup", [ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(StartupInput), vp]),
                               ("GdipLoadImageFromFile", [ctypes.c_wchar_p, pvp]),
                               ("GdipCreateBitmapFromScan0", [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, vp, pvp]),
                               ("GdipGetImageGraphicsContext", [vp, pvp]),
                               ("GdipSetInterpolationMode", [vp, ctypes.c_int]),
                               ("GdipSetPixelOffsetMode", [vp, ctypes.c_int]),
                               ("GdipDrawImageRectI", [vp, vp, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]),
                               ("GdipDeleteGraphics", [vp]),
                               ("GdipSaveImageToFile", [vp, ctypes.c_wchar_p, vp, vp]),
                               ("GdipDisposeImage", [vp])):
                fn = getattr(gdi, name)
                fn.argtypes, fn.restype = args, ctypes.c_int
            token = ctypes.c_size_t()
            status = gdi.GdiplusStartup(ctypes.byref(token), ctypes.byref(StartupInput(1, None, False, False)), None)
            if status:
                raise OSError(f"GdiplusStartup: {status}")
            _GDIPLUS.update(gdi=gdi, token=token)
        return _GDIPLUS["gdi"]


def _convert_gdiplus(src: Path, dst: Path, size: tuple[int, int] | None) -> None:
    import ctypes
    import uuid
    gdi = _gdiplus()
    png = (ctypes.c_byte * 16).from_buffer_copy(uuid.UUID("557CF406-1A04-11D3-9A73-0000F81EF32E").bytes_le)   # PNG-Encoder

    def check(status: int, what: str) -> None:
        if status:
            raise OSError(f"{what}: GDI+ {status}")
    img, out, gfx = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
    check(gdi.GdipLoadImageFromFile(str(src), ctypes.byref(img)), "load")
    try:
        target = img
        if size:
            check(gdi.GdipCreateBitmapFromScan0(size[0], size[1], 0, 0x21808, None, ctypes.byref(out)), "bitmap")   # 24 Bit RGB
            check(gdi.GdipGetImageGraphicsContext(out, ctypes.byref(gfx)), "graphics")
            gdi.GdipSetInterpolationMode(gfx, 7)             # bikubisch, hohe Qualität
            gdi.GdipSetPixelOffsetMode(gfx, 2)
            check(gdi.GdipDrawImageRectI(gfx, img, 0, 0, size[0], size[1]), "draw")
            gdi.GdipDeleteGraphics(gfx)
            gfx = ctypes.c_void_p()
            target = out
        check(gdi.GdipSaveImageToFile(target, str(dst), ctypes.byref(png), None), "save")
    finally:
        if gfx:
            gdi.GdipDeleteGraphics(gfx)
        if out:
            gdi.GdipDisposeImage(out)
        gdi.GdipDisposeImage(img)


def _convert_pillow(src: Path, dst: Path, size: tuple[int, int] | None) -> None:
    from PIL import Image
    with Image.open(src) as im:
        im = im.convert("RGB")
        if size:
            im = im.resize(size, Image.LANCZOS)
        im.save(dst, "PNG")


def convert_to_png(src: Path, dst: Path, size: tuple[int, int] | None = None) -> None:
    """JPEG (oder ein anderes gängiges Format) -> PNG, auf Wunsch in anderer Größe."""
    tmp = dst.with_name(dst.name + f".{threading.get_ident()}.tmp")
    try:
        if os.name == "nt":
            _convert_gdiplus(src, tmp, size)
        else:
            _convert_pillow(src, tmp, size)
        os.replace(tmp, dst)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def raw_path(url: str) -> Path:
    """Die heruntergeladene Originaldatei – bleibt liegen, damit andere Größen ohne Netz entstehen können."""
    return image_dir() / "raw" / (image_path(url).stem + ".jpg")


def cached_image(url: str, size: tuple[int, int] | None = None, fetch: bool = True) -> Path | None:
    """PNG-Datei zu einem Bild von Wowhead; lädt und wandelt beim ersten Mal. None, wenn es nicht geht."""
    path = image_path(url, size)
    if path.is_file() and path.stat().st_size > 0:
        return path
    if not fetch or not can_convert():
        return None
    try:
        convert_to_png(_download(url), path, size)
        return path
    except Exception as e:  # noqa – Netz, Format, Platte: dann eben ohne Bild
        log.info("Bild %s nicht geladen: %s", url, e)
        return None


def _download(url: str) -> Path:
    raw = raw_path(url)
    if not raw.is_file() or not raw.stat().st_size:
        raw.parent.mkdir(parents=True, exist_ok=True)
        tmp = raw.with_name(raw.name + f".{threading.get_ident()}.tmp")
        tmp.write_bytes(wowhead_bytes(url))
        os.replace(tmp, raw)
    return raw


def _try_download(url: str) -> None:
    try:
        _download(url)
    except Exception as e:  # noqa
        log.info("Bild %s nicht geladen: %s", url, e)


def fetch_images(wanted: list[tuple[str, tuple[int, int] | None]]) -> int:
    """Lädt fehlende Bilder (mehrere gleichzeitig). Rückgabe: wie viele jetzt vorhanden sind."""
    todo = [(u, s) for u, s in dict.fromkeys(wanted) if not image_path(u, s).is_file()]
    if todo and can_convert():
        with ThreadPoolExecutor(max_workers=6) as pool:       # erst jede Datei einmal laden, dann die Größen erzeugen
            list(pool.map(_try_download, dict.fromkeys(u for u, _ in todo)))
            list(pool.map(lambda x: cached_image(*x), [x for x in todo if raw_path(x[0]).is_file()]))
    return sum(1 for u, s in dict.fromkeys(wanted) if image_path(u, s).is_file())
