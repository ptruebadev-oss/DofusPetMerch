"""Google Sheets over plain HTTP (no Google libraries, no OAuth in the app).

* Read-only: a sheet shared as "anyone with the link can view" is downloaded as CSV.
* Two-way sync: apps_script.js, deployed by the user as a web app; the app POSTs pending
  changes and receives the full table back.

Every public function raises only ``GSheetError``.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .. import net
from .layout import AMBIGUOUS_MSG, GSheetError, parse_xp_csv

backoff = net.Backoff()
_SCRIPT_URL = re.compile(r"^https://script\.google\.com/(a/[^/]+/)?macros/s/[A-Za-z0-9_-]+/exec$")


def apps_script_source() -> str:
    return (Path(__file__).parent / "apps_script.js").read_text(encoding="utf-8")


def parse_sheet_url(url: str) -> str | None:
    """Any Google Sheets link (or bare id) -> CSV export URL. None if unrecognised."""
    url = (url or "").strip()
    if not url:
        return None
    gid_m = re.search(r"[#?&]gid=(\d+)", url)
    gid = gid_m.group(1) if gid_m else "0"
    m = re.search(r"/spreadsheets/d/e/([A-Za-z0-9_-]+)", url)
    if m:  # "Publicar en la web" link
        return f"https://docs.google.com/spreadsheets/d/e/{m.group(1)}/pub?output=csv&gid={gid}"
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]{20,})", url)
    if m:
        return f"https://docs.google.com/spreadsheets/d/{m.group(1)}/export?format=csv&gid={gid}"
    if re.fullmatch(r"[A-Za-z0-9_-]{25,}", url):
        return f"https://docs.google.com/spreadsheets/d/{url}/export?format=csv&gid=0"
    return None


def _gviz_csv_url(export_url: str) -> str | None:
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]{20,})/export\?format=csv&gid=(\d+)", export_url)
    if not m:
        return None
    return f"https://docs.google.com/spreadsheets/d/{m.group(1)}/gviz/tq?tqx=out:csv&gid={m.group(2)}"


def _call(req: urllib.request.Request, timeout: float, manual: bool) -> tuple[bytes, str]:
    """``manual`` (a button press) ignores the offline back-off."""
    if not manual and backoff.active:
        raise GSheetError("Sin conexión con Google Sheets (se reintentará en unos minutos)")
    try:
        return net.open_url(req, timeout)
    except urllib.error.HTTPError as e:
        raise GSheetError(f"Google respondió con un error HTTP {e.code}") from e
    except net.NETWORK_ERRORS as e:
        backoff.trip()
        raise GSheetError("Sin conexión con Google Sheets") from e


def _looks_html(body: bytes, ctype: str) -> bool:
    return "text/html" in ctype.lower() or body.lstrip()[:1] == b"<"


def fetch_sheet(url: str, timeout: float = 8.0, manual: bool = False) -> tuple[dict[str, float], int]:
    """({name: xp}, skipped rows) of a public sheet."""
    csv_url = parse_sheet_url(url)
    if not csv_url:
        raise GSheetError("El enlace no parece de una hoja de Google Sheets")
    try:
        body, ctype = _call(urllib.request.Request(csv_url), timeout, manual)
    except GSheetError as e:
        # Some sheets refuse the export URL but serve the same CSV through gviz.
        alt = _gviz_csv_url(csv_url)
        if not alt or "HTTP 4" not in str(e):
            raise
        body, ctype = _call(urllib.request.Request(alt), timeout, manual)
    if _looks_html(body, ctype):
        raise GSheetError("La hoja no es pública: compártela como 'Cualquier persona con el enlace' (lector)")
    return parse_xp_csv(body.decode("utf-8-sig", errors="replace"))


def _check_script_url(exec_url: str) -> str:
    u = (exec_url or "").strip()
    if not _SCRIPT_URL.match(u):
        if u.endswith("/dev"):
            raise GSheetError("Usa la URL de la implementación que termina en /exec (no /dev)")
        raise GSheetError("La URL de Apps Script debe ser https://script.google.com/macros/s/.../exec")
    return u


def _script_json(body: bytes, ctype: str) -> dict:
    if _looks_html(body, ctype):
        raise GSheetError("Apps Script devolvió una página de Google: implementa la app web con "
                          "'Ejecutar como: Yo' y acceso 'Cualquier usuario'")
    try:
        data = json.loads(body.decode("utf-8"))
    except ValueError as e:
        raise GSheetError("Respuesta no válida de Apps Script") from e
    if not isinstance(data, dict):
        raise GSheetError("Respuesta no válida de Apps Script")
    if not data.get("ok"):
        if data.get("error") == "token":
            raise GSheetError("Token incorrecto: debe coincidir con TOKEN en el Apps Script")
        if data.get("error") == "layout":
            raise GSheetError(AMBIGUOUS_MSG)
        raise GSheetError(f"Apps Script: {data.get('error', 'error desconocido')}")
    if not isinstance(data.get("rows"), list) or not isinstance(data.get("tombstones", []), list):
        raise GSheetError("Respuesta de Apps Script incompleta: vuelve a copiar el código e implementa una versión nueva")
    return data


def script_get(exec_url: str, token: str, timeout: float = 15.0, manual: bool = False) -> dict:
    u = _check_script_url(exec_url) + "?" + urllib.parse.urlencode({"token": token or ""})
    return _script_json(*_call(urllib.request.Request(u), timeout, manual))


def script_sync(exec_url: str, token: str, ops: list[dict], timeout: float = 15.0, manual: bool = False) -> dict:
    u = _check_script_url(exec_url)
    body = json.dumps({"token": token or "", "ops": ops}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(u, data=body, method="POST", headers={"Content-Type": "text/plain;charset=utf-8"})
    return _script_json(*_call(req, timeout, manual))
