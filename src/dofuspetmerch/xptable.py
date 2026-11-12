"""Pet-XP table persisted as pet_xp.json in the data folder."""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

from rapidfuzz import fuzz, process

from .parsing import normalize_name, parse_xp
from .paths import app_dir, write_json_atomic


def now_ms() -> int:
    return int(time.time() * 1000)


def _new_meta(updated_at: int, dirty: bool = False, synced: bool = False) -> dict:
    return {"updated_at": int(updated_at), "dirty": bool(dirty), "synced": bool(synced)}


def _to_xp(v) -> float | None:
    """XP from a sheet cell: raw number (Apps Script) or text (CSV / formatted cell)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) and v > 0 else None
    return parse_xp(str(v)) if v is not None else None


def _key_of(entries: dict, norm: str) -> str | None:
    """Stored spelling of the entry whose normalized name is ``norm``."""
    return next((k for k in entries if normalize_name(k) == norm), None)


class XpTable:
    """Item name -> XP given to a pet per unit. Lookup is accent/case-insensitive and fuzzy.

    Besides ``entries`` (the only thing the rest of the app reads) it keeps sync
    bookkeeping for Google Sheets: per-entry ``meta`` {updated_at, dirty, synced} and
    ``tombstones`` (normalized name -> {"name", "at"}) for deletions not yet pushed.
    Mutations build new dicts and swap them in, so readers on other threads (the hotkey
    pipeline) never see a dict changing size under them.
    """

    def __init__(self, entries: dict[str, float] | None = None, path: Path | None = None):
        self.path = path
        self.entries: dict[str, float] = dict(entries or {})
        self.meta: dict[str, dict] = {k: _new_meta(0, dirty=True) for k in self.entries}
        self.tombstones: dict[str, dict] = {}
        self.last_sync: int = 0
        self.skew_ms: int = 0  # server clock - local clock, learned on each sync
        # Last item added or changed in this app (not by a Google Sheets import), local clock.
        self.last_added: dict = {}  # {"name": str, "at": ms}

    def now(self) -> int:
        return now_ms() + self.skew_ms

    @classmethod
    def load(cls, path: Path | None = None, strict: bool = False) -> "XpTable":
        """Empty table if the file is missing or unreadable; with ``strict``, ValueError instead
        (a reload must never replace a good table in memory with an empty one)."""
        path = path or app_dir() / "pet_xp.json"
        t = cls(path=path)
        if not path.exists():
            if strict:
                raise ValueError(f"no existe {path.name}")
            return t
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("version") == 2:
                for name, e in (data.get("entries") or {}).items():
                    t.entries[str(name)] = float(e["xp"])
                    t.meta[str(name)] = _new_meta(int(e.get("updated_at", 0)), bool(e.get("dirty")), bool(e.get("synced")))
                t.tombstones = {str(k): {"name": str(v.get("name", k)), "at": int(v.get("at", 0))} for k, v in (data.get("tombstones") or {}).items()}
                t.last_sync = int(data.get("last_sync", 0))
                t.skew_ms = int(data.get("skew_ms", 0))
                la = data.get("last_added") or {}
                try:  # a damaged hint must never cost the whole table
                    if isinstance(la, dict) and la.get("name"):
                        t.last_added = {"name": str(la["name"]), "at": int(la.get("at", 0))}
                except (TypeError, ValueError):
                    t.last_added = {}
            else:  # legacy {"name": xp}: never synced, push on first sync
                t.entries = {str(k): float(v) for k, v in data.items()}
                t.meta = {k: _new_meta(0, dirty=True) for k in t.entries}
        except (OSError, ValueError, AttributeError, KeyError, TypeError) as e:
            if strict:
                raise ValueError(f"{path.name} no se puede leer ({e})") from e
            return cls(path=path)
        return t

    def save(self) -> None:
        data = {
            "version": 2,
            "entries": {k: {"xp": v, **self.meta.get(k, _new_meta(0, True))} for k, v in sorted(self.entries.items(), key=lambda kv: kv[0].lower())},
            "tombstones": self.tombstones,
            "last_sync": self.last_sync,
            "skew_ms": self.skew_ms,
            "last_added": self.last_added,
        }
        write_json_atomic(self.path or app_dir() / "pet_xp.json", data)

    def set(self, name: str, xp: float, at: int | None = None) -> None:
        name = name.strip()
        entries, meta = dict(self.entries), dict(self.meta)
        existing = _key_of(self.entries, normalize_name(name))
        if existing and existing != name:
            entries.pop(existing, None)
            meta.pop(existing, None)
        entries[name] = float(xp)
        meta[name] = _new_meta(self.now() if at is None else at, dirty=True)
        tombs = dict(self.tombstones)
        tombs.pop(normalize_name(name), None)
        self.entries, self.meta, self.tombstones = entries, meta, tombs
        self.last_added = {"name": name, "at": now_ms()}

    def last_updated(self) -> tuple[str, int] | None:
        """(current name, local ms) of the last item added or changed in the app, if it is still
        in the table. Google Sheets imports don't count: they are not the user's additions."""
        name = self.last_added.get("name")
        key = _key_of(self.entries, normalize_name(name)) if name else None
        return (key, self.last_added.get("at", 0)) if key else None

    def remove(self, name: str, at: int | None = None) -> None:
        """Delete an entry; the deletion is remembered (tombstone) to push it to the sheet."""
        key = name if name in self.entries else _key_of(self.entries, normalize_name(name))
        if key is None:
            return
        entries, meta = dict(self.entries), dict(self.meta)
        entries.pop(key, None)
        meta.pop(key, None)
        tombs = dict(self.tombstones)
        tombs[normalize_name(key)] = {"name": key, "at": self.now() if at is None else at}
        self.entries, self.meta, self.tombstones = entries, meta, tombs

    def pending_ops(self) -> list[dict]:
        ops = [{"op": "upsert", "name": k, "xp": self.entries[k], "updated_at": m["updated_at"]}
               for k, m in self.meta.items() if m.get("dirty") and k in self.entries]
        ops += [{"op": "delete", "name": t["name"], "deleted_at": t["at"]} for t in self.tombstones.values()]
        return ops

    def apply_read(self, rows: dict[str, float], replace: bool = False) -> dict:
        """Import a read-only sheet: the sheet wins for every row it contains."""
        if replace and not rows:
            raise ValueError("La hoja no tiene filas válidas: no se reemplaza la tabla local")
        summary = {"added": 0, "updated": 0, "deleted": 0, "pushed": 0}
        entries, meta = dict(self.entries), dict(self.meta)
        seen = set()
        for name, xp in rows.items():
            n = normalize_name(name)
            seen.add(n)
            key = _key_of(entries, n)
            if key is None:
                summary["added"] += 1
            elif key != name or entries[key] != xp:
                summary["updated"] += 1
                entries.pop(key)
                meta.pop(key, None)
            else:
                continue
            entries[name] = float(xp)
            meta[name] = _new_meta(self.now(), dirty=False)
        # The sheet now has these rows: an old pending local delete must not remove them later.
        tombs = {n: t for n, t in self.tombstones.items() if n not in seen}
        if replace:
            for k in [k for k in entries if normalize_name(k) not in seen]:
                entries.pop(k)
                meta.pop(k, None)
                summary["deleted"] += 1
        self.entries, self.meta, self.tombstones = entries, meta, tombs
        self.last_sync = now_ms()
        return summary

    def reset_sync_state(self) -> None:
        """Call when the sync target (script URL) changes: nothing is known to be in the new
        sheet, so every local row must be pushed (and nothing deleted for being absent)."""
        self.meta = {k: {**m, "dirty": True, "synced": False} for k, m in self.meta.items()}
        self.last_sync = 0  # pending deletions (tombstones) are kept: harmless on a new sheet

    def apply_sync_result(self, sent_ops: list[dict], remote: dict) -> dict:
        """Merge the full sheet state returned by the Apps Script (last write wins)."""
        if not isinstance(remote, dict) or not isinstance(remote.get("rows"), list) \
                or not isinstance(remote.get("tombstones", []), list):
            raise ValueError("Respuesta de Apps Script incompleta (¿script antiguo? vuelve a copiarlo e implementarlo)")
        summary = {"added": 0, "updated": 0, "deleted": 0, "pushed": 0}
        entries, meta, tombs = dict(self.entries), {k: dict(v) for k, v in self.meta.items()}, dict(self.tombstones)
        rejected = {normalize_name(n) for n in remote.get("rejected") or []}

        # Acknowledge what we sent (unless edited again meanwhile, or rejected)
        for op in sent_ops:
            n = normalize_name(op["name"])
            if n in rejected:
                continue
            if op["op"] == "upsert":
                k = _key_of(entries, n)
                if k and meta.get(k, {}).get("updated_at") == op["updated_at"]:
                    meta[k].update(dirty=False, synced=True)
                    summary["pushed"] += 1
            elif n in tombs and tombs[n]["at"] == op["deleted_at"]:
                del tombs[n]
                summary["pushed"] += 1
        for n in rejected:  # server copy is newer: let the remote row win below
            k = _key_of(entries, n)
            if k:
                meta[k].update(dirty=False, updated_at=-1)
            tombs.pop(n, None)

        remote_rows: dict[str, dict] = {}
        for r in remote.get("rows") or []:
            xp = _to_xp(r.get("xp"))
            name = str(r.get("name", "")).strip()
            if name and xp is not None:
                remote_rows[normalize_name(name)] = {"name": name, "xp": xp, "at": int(r.get("updated_at") or 0)}
        for n, r in remote_rows.items():
            if n in tombs and tombs[n]["at"] >= r["at"]:
                continue  # our pending delete is newer
            k = _key_of(entries, n)
            if k is None:
                entries[r["name"]] = r["xp"]
                meta[r["name"]] = _new_meta(r["at"], dirty=False, synced=True)
                tombs.pop(n, None)
                summary["added"] += 1
                continue
            m = meta.setdefault(k, _new_meta(0, True))
            if m.get("dirty") and m["updated_at"] > r["at"]:
                continue  # local edit is newer: pushed next time
            if k != r["name"] or entries[k] != r["xp"]:
                summary["updated"] += 1
            entries.pop(k)
            meta.pop(k)
            entries[r["name"]] = r["xp"]
            meta[r["name"]] = _new_meta(r["at"], dirty=False, synced=True)

        for t in remote.get("tombstones") or []:
            n = normalize_name(str(t.get("name", "")))
            if n in remote_rows:
                continue
            k = _key_of(entries, n)
            if k is None:
                continue
            m = meta.get(k, _new_meta(0, True))
            if m.get("dirty") and m["updated_at"] > int(t.get("deleted_at") or 0):
                continue
            entries.pop(k)
            meta.pop(k, None)
            summary["deleted"] += 1

        # Local rows the sheet doesn't have. An entirely empty sheet (new sheet, renamed
        # tab...) is never taken as "everything was deleted by hand".
        empty_sheet = not remote_rows and not remote.get("tombstones")
        for k in list(entries):
            if normalize_name(k) in remote_rows:
                continue
            m = meta.setdefault(k, _new_meta(0, True))
            if m.get("synced") and not m.get("dirty") and not empty_sheet:
                entries.pop(k)  # deleted by hand in the sheet
                meta.pop(k)
                summary["deleted"] += 1
            elif not m.get("dirty"):
                m["dirty"] = True  # never pushed (e.g. imported in read mode): push next time
                if m["updated_at"] <= 0:
                    m["updated_at"] = self.now()

        if remote.get("now"):
            self.skew_ms = int(remote["now"]) - now_ms()
            self.last_sync = int(remote["now"])
        else:
            self.last_sync = self.last_sync or now_ms()
        self.entries, self.meta, self.tombstones = entries, meta, tombs
        return summary

    def lookup(self, name: str, min_score: float = 88) -> tuple[str, float] | None:
        """Return (canonical_name, xp) or None. Tolerates small OCR errors
        (about one wrong character in short names)."""
        entries = self.entries  # one snapshot: other threads may swap the dict meanwhile
        if not name or not entries:
            return None
        n = normalize_name(name)
        norm = {normalize_name(k): k for k in entries}
        k = norm.get(n)
        if k is None:
            best = process.extractOne(n, list(norm), scorer=fuzz.ratio)
            threshold = min(min_score, 100 - 100 / max(len(n), 1))
            if not best or best[1] < threshold:
                return None
            k = norm[best[0]]
        return k, entries[k]


SORT_COLUMNS = ("name", "xp")  # the max price is xp × a positive factor: it sorts like xp


def table_view(entries: dict[str, float], query: str = "", column: str = "name",
               descending: bool = False) -> list[tuple[str, float]]:
    """Rows to show: names containing every word of ``query`` (ignoring case and accents),
    sorted by ``column`` ("name" or "xp"; ties by name)."""
    words = normalize_name(query).split()
    rows = [(n, x) for n, x in entries.items() if all(w in normalize_name(n) for w in words)]
    rows.sort(key=lambda r: normalize_name(r[0]))
    if column == "xp":
        rows.sort(key=lambda r: r[1], reverse=descending)  # stable: equal XP keeps name order
    elif descending:
        rows.reverse()
    return rows
