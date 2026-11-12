"""Item identity: official name and icon from the public dofusdb.fr API, plus the icon cropped
from the screen the last time an item was read.

Disk layout in the data folder (kept stable across versions):
* ``cache/items_<lang>.json``: normalized name -> {"id", "names", "img_url", ...} or {"miss_at"}
* ``cache/icons/<id>.png``: official icons
* ``icons/captured/<slug>_<sha1>.png``: icons cropped from the screen
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from . import imgutil, net
from .parsing import normalize_name
from .paths import app_dir, write_json_atomic

API = "https://api.dofusdb.fr/items"
NEGATIVE_TTL = 7 * 24 * 3600  # re-ask about unknown names after a week
backoff = net.Backoff()
_lock = threading.Lock()
_memo: dict[Path, tuple[float, dict]] = {}


@dataclass
class ItemInfo:
    id: int
    names: dict
    img_url: str

    def name(self, lang: str) -> str:
        return self.names.get(lang) or self.names.get("fr") or ""


def _cache_file(lang: str) -> Path:
    return app_dir() / "cache" / f"items_{lang}.json"


def _official_icon_file(item_id) -> Path:
    return app_dir() / "cache" / "icons" / f"{item_id}.png"


def _read_cache(lang: str) -> dict:
    """The name cache, re-read only when the file changes on disk. {} if missing or corrupt."""
    path = _cache_file(lang)
    try:
        mtime = path.stat().st_mtime
        hit = _memo.get(path)
        if hit and hit[0] == mtime:
            return hit[1]
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    _memo[path] = (mtime, data)
    return data


def _write_cache(lang: str, key: str, value: dict) -> None:
    with _lock:
        cache = dict(_read_cache(lang))
        cache[key] = value
        path = _cache_file(lang)
        path.parent.mkdir(exist_ok=True)
        write_json_atomic(path, cache, indent=None)
        # Two writes within the file system's clock resolution keep the same mtime: the memo
        # must not then serve the older content.
        _memo[path] = (path.stat().st_mtime, cache)


def _cached_info(entry) -> ItemInfo | None:
    if not isinstance(entry, dict) or "id" not in entry:
        return None
    return ItemInfo(id=entry["id"], names=entry.get("names") or {}, img_url=entry.get("img_url") or "")


def lookup(name: str, lang: str, timeout: float) -> ItemInfo | None:
    """Find an item by its exact (localised) name. Never raises; None if unknown or offline."""
    try:
        key = normalize_name(name)
        if not key:
            return None
        entry = _read_cache(lang).get(key)
        if entry is not None:
            info = _cached_info(entry)
            if info or (isinstance(entry, dict) and time.time() - entry.get("miss_at", 0) < NEGATIVE_TTL):
                return info
        if backoff.active:
            return None
        q = urllib.parse.urlencode({f"name.{lang}": name.strip(), "$limit": 5})
        try:
            body, _ = net.open_url(urllib.request.Request(f"{API}?{q}"), timeout)
            data = json.loads(body.decode("utf-8")).get("data", []) or []
        except net.NETWORK_ERRORS:
            backoff.trip()
            return None
        hit = next((d for d in data if normalize_name(d.get("name", {}).get(lang, "")) == key), None)
        info = None
        if hit and "id" in hit:
            info = ItemInfo(id=int(hit["id"]), names=hit.get("name") or {}, img_url=hit.get("img") or "")
        _write_cache(lang, key, asdict(info) if info else {"miss_at": time.time()})
        return info
    except Exception:  # optional enrichment on the hotkey path: an odd API answer must not break it
        return None


def download_icon(info: ItemInfo, timeout: float) -> Path | None:
    """Download (once) the official icon and return its local path. Never raises."""
    p = _official_icon_file(info.id)
    if p.exists():
        return p
    if not info.img_url or backoff.active:
        return None
    try:
        body, _ = net.open_url(urllib.request.Request(info.img_url), timeout)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)
        return p
    except net.NETWORK_ERRORS:
        return None


def official_icon_path(name: str, lang: str) -> Path | None:
    """Official icon of ``name`` if it is already on disk; never hits the network."""
    info = _cached_info(_read_cache(lang).get(normalize_name(name)))
    if info is None:
        return None
    p = _official_icon_file(info.id)
    return p if p.exists() else None


def icon_filename(name: str) -> str:
    """Filesystem-safe, collision-resistant file name for an item name."""
    norm = normalize_name(name)
    slug = re.sub(r"[^a-z0-9]+", "_", norm).strip("_")[:40] or "item"
    digest = hashlib.sha1(norm.encode("utf-8")).hexdigest()[:8]
    return f"{slug}_{digest}.png"


def captured_icon_path(name: str) -> Path:
    return app_dir() / "icons" / "captured" / icon_filename(name)


def save_captured(name: str, img: np.ndarray | None) -> None:
    """Remember the icon seen on screen for ``name``. Never raises."""
    if not name or img is None or img.size == 0:
        return
    try:
        p = captured_icon_path(name)
        p.parent.mkdir(parents=True, exist_ok=True)
        imgutil.save(p, img)
    except (OSError, ValueError):
        pass


def resolve_icon(name: str, lang: str, use_dofusdb: bool) -> Path | None:
    """Best local icon: official (if dofusdb is enabled), else the captured one."""
    if use_dofusdb:
        p = official_icon_path(name, lang)
        if p:
            return p
    p = captured_icon_path(name)
    return p if p.exists() else None
