import json
import shutil
import subprocess
import urllib.error
from pathlib import Path

import pytest

from dofuspetmerch import net
from dofuspetmerch import settings as config
from dofuspetmerch.parsing import parse_number
from dofuspetmerch.settings import Settings
from dofuspetmerch.sheets import client, layout
from dofuspetmerch.sheets.layout import GSheetError, parse_xp_csv
from dofuspetmerch.xptable import XpTable

HERE = Path(__file__).parent

ID = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
EXEC = "https://script.google.com/macros/s/AKfycbx123-abc_DEF/exec"


def fake_open(monkeypatch, body, ctype="text/csv", calls=None):
    def f(req, timeout):
        if calls is not None:
            calls.append(req)
        if isinstance(body, Exception):
            raise body
        return (body if isinstance(body, bytes) else body.encode("utf-8")), ctype

    monkeypatch.setattr(net, "open_url", f)


# ------------------------------------------------------------------ URLs
@pytest.mark.parametrize("url,expected", [
    (f"https://docs.google.com/spreadsheets/d/{ID}/edit#gid=123", f"https://docs.google.com/spreadsheets/d/{ID}/export?format=csv&gid=123"),
    (f"https://docs.google.com/spreadsheets/d/{ID}/edit?gid=5#gid=5", f"https://docs.google.com/spreadsheets/d/{ID}/export?format=csv&gid=5"),
    (f"https://docs.google.com/spreadsheets/d/{ID}/edit", f"https://docs.google.com/spreadsheets/d/{ID}/export?format=csv&gid=0"),
    ("https://docs.google.com/spreadsheets/d/e/2PACX-1vQabc_DEF/pubhtml", "https://docs.google.com/spreadsheets/d/e/2PACX-1vQabc_DEF/pub?output=csv&gid=0"),
    (ID, f"https://docs.google.com/spreadsheets/d/{ID}/export?format=csv&gid=0"),
])
def test_parse_sheet_url(url, expected):
    assert client.parse_sheet_url(url) == expected


@pytest.mark.parametrize("url", ["", "hola", "https://example.com/x"])
def test_parse_sheet_url_rejects(url):
    assert client.parse_sheet_url(url) is None


# ------------------------------------------------------------------- CSV
@pytest.mark.parametrize("text", [
    'Objeto,XP\nGobio,"0,5"\nTrucha,3\n',
    "\ufeffItem,XP\nGobio,0.5\nTrucha,3\n",
    "Nombre;XP (por unidad)\nGobio;0,5\nTrucha;3\n",
    "Mi tabla de XP,\n,\nObjeto,XP\nGobio,0.5\nTrucha,3\n",  # header on row 3
    "Gobio,0.5\nTrucha,3\n",  # no header
])
def test_parse_xp_csv_variants(text):
    rows, skipped = parse_xp_csv(text)
    assert rows == {"Gobio": 0.5, "Trucha": 3}
    assert skipped == 0


def test_parse_xp_csv_invalid_and_duplicates():
    rows, skipped = parse_xp_csv("Objeto,XP\nGobio,1\n,5\nMalo,abc\nCero,0\n\ngobio,2\n")
    assert rows == {"gobio": 2}
    assert skipped == 3


# ---------------------------------------------------------------- fetch
def test_fetch_sheet_ok(monkeypatch):
    calls = []
    fake_open(monkeypatch, "Objeto,XP\nGobio,10\n", calls=calls)
    assert client.fetch_sheet(f"https://docs.google.com/spreadsheets/d/{ID}/edit#gid=7") == ({"Gobio": 10}, 0)
    assert calls[0].full_url.endswith("export?format=csv&gid=7")


def test_fetch_sheet_private(monkeypatch):
    fake_open(monkeypatch, "<!DOCTYPE html><html>login</html>", "text/html; charset=utf-8")
    with pytest.raises(GSheetError, match="no es pública"):
        client.fetch_sheet(ID)


def test_fetch_sheet_bad_url():
    with pytest.raises(GSheetError):
        client.fetch_sheet("hola")


def test_offline_backoff(monkeypatch):
    calls = []
    fake_open(monkeypatch, urllib.error.URLError("offline"), calls=calls)
    with pytest.raises(GSheetError, match="Sin conexión"):
        client.fetch_sheet(ID)
    with pytest.raises(GSheetError):
        client.fetch_sheet(ID)  # automatic: skipped by back-off
    assert len(calls) == 1
    with pytest.raises(GSheetError):
        client.fetch_sheet(ID, manual=True)  # button press: retried
    assert len(calls) == 2


# --------------------------------------------------------------- script
def test_script_sync_posts_text_plain(monkeypatch):
    calls = []
    fake_open(monkeypatch, json.dumps({"ok": True, "now": 1, "rows": [], "tombstones": []}), "application/json", calls)
    ops = [{"op": "upsert", "name": "Gobio", "xp": 1, "updated_at": 5}]
    assert client.script_sync(EXEC, "secreto", ops)["ok"]
    req = calls[0]
    assert req.get_method() == "POST"
    assert req.get_header("Content-type").startswith("text/plain")
    assert json.loads(req.data) == {"token": "secreto", "ops": ops}


@pytest.mark.parametrize("body,ctype,match", [
    ('{"ok": false, "error": "token"}', "application/json", "Token"),
    ("<html>Google login</html>", "text/html", "Cualquier usuario"),
    ("not json", "text/plain", "no válida"),
])
def test_script_errors(monkeypatch, body, ctype, match):
    fake_open(monkeypatch, body, ctype)
    with pytest.raises(GSheetError, match=match):
        client.script_get(EXEC, "x")


def test_script_url_validation():
    with pytest.raises(GSheetError, match="/exec"):
        client.script_sync(EXEC[:-4] + "dev", "x", [])
    with pytest.raises(GSheetError):
        client.script_sync("https://example.com/exec", "x", [])


def test_apps_script_source_is_shipped():
    src = client.apps_script_source()  # what "Copiar código Apps Script" copies
    for fn in ("function doGet", "function doPost", "function onEdit", "const TOKEN"):
        assert fn in src


# ---------------------------------------------------------- XpTable v2
def test_legacy_file_migrates(tmp_path):
    p = tmp_path / "pet_xp.json"
    p.write_text('{"Gobio": 10, "Trucha": 2.5}', encoding="utf-8")
    t = XpTable.load(p)
    assert t.lookup("gobio") == ("Gobio", 10)
    assert t.meta["Gobio"] == {"updated_at": 0, "dirty": True, "synced": False}
    t.save()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["version"] == 2 and data["entries"]["Trucha"]["xp"] == 2.5
    t2 = XpTable.load(p)
    assert t2.entries == {"Gobio": 10, "Trucha": 2.5} and len(t2.pending_ops()) == 2


def test_corrupt_file_gives_empty_table(tmp_path):
    p = tmp_path / "pet_xp.json"
    p.write_text('{"version": 2, "entries": {"Gobio": {}}}', encoding="utf-8")
    assert XpTable.load(p).entries == {}


def test_settings_gsheet_mode_validated(tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"gsheet_mode": "loquesea"}', encoding="utf-8")
    assert Settings.load(p).gsheet_mode == Settings().gsheet_mode == "read"  # invalid -> default


def _table(tmp_path, **entries):
    t = XpTable(path=tmp_path / "xp.json")
    for name, xp in entries.items():
        t.set(name, xp, at=100)
    return t


def test_apply_read_merge_and_replace(tmp_path):
    t = _table(tmp_path, gobio=1, Local=5)
    s = t.apply_read({"Gobio": 2, "Nuevo": 3})
    assert t.entries == {"Gobio": 2, "Local": 5, "Nuevo": 3}  # sheet name wins, local-only kept
    assert s == {"added": 1, "updated": 1, "deleted": 0, "pushed": 0}
    assert not t.meta["Gobio"]["dirty"]
    t.apply_read({"Gobio": 2}, replace=True)
    assert t.entries == {"Gobio": 2}
    with pytest.raises(ValueError):
        t.apply_read({}, replace=True)
    assert t.entries == {"Gobio": 2}


def _remote(rows=(), tombs=(), rejected=(), now=10_000):
    return {"ok": True, "now": now, "rows": [{"name": n, "xp": x, "updated_at": a} for n, x, a in rows],
            "tombstones": [{"name": n, "deleted_at": a} for n, a in tombs], "rejected": list(rejected)}


def test_sync_push_ack_and_remote_add(tmp_path):
    t = _table(tmp_path, Gobio=1)
    ops = t.pending_ops()
    assert ops == [{"op": "upsert", "name": "Gobio", "xp": 1.0, "updated_at": 100}]
    s = t.apply_sync_result(ops, _remote(rows=[("Gobio", 1, 100), ("Trucha", 3, 50)]))
    assert t.entries == {"Gobio": 1, "Trucha": 3}
    assert t.pending_ops() == []
    assert s["pushed"] == 1 and s["added"] == 1
    assert t.meta["Gobio"]["synced"]


def test_sync_remote_newer_wins_local_newer_kept(tmp_path):
    t = _table(tmp_path, A=1, B=1)
    t.set("B", 9, at=500)  # local edit newer than remote
    t.apply_sync_result([], _remote(rows=[("A", 2, 300), ("B", 2, 300)]))
    assert t.entries["A"] == 2 and t.entries["B"] == 9
    assert t.meta["B"]["dirty"] and not t.meta["A"]["dirty"]


def test_sync_edit_during_request_stays_dirty(tmp_path):
    t = _table(tmp_path, A=1)
    ops = t.pending_ops()
    t.set("A", 5, at=200)  # user edits while the request is in flight
    t.apply_sync_result(ops, _remote(rows=[("A", 1, 100)]))
    assert t.entries["A"] == 5 and t.meta["A"]["dirty"]


def test_sync_local_delete_beats_older_remote_row(tmp_path):
    t = _table(tmp_path, A=1)
    t.remove("A", at=300)
    t.apply_sync_result([], _remote(rows=[("A", 1, 100)]))  # e.g. offline push failed earlier
    assert "A" not in t.entries
    assert [o["op"] for o in t.pending_ops()] == ["delete"]
    ops = t.pending_ops()
    t.apply_sync_result(ops, _remote(tombs=[("A", 300)]))
    assert t.pending_ops() == [] and "A" not in t.entries


def test_sync_remote_tombstone_and_hand_deleted_row(tmp_path):
    t = _table(tmp_path, A=1, B=1, C=1)
    t.apply_sync_result(t.pending_ops(), _remote(rows=[("A", 1, 100), ("B", 1, 100), ("C", 1, 100)]))
    s = t.apply_sync_result([], _remote(rows=[("A", 1, 100)], tombs=[("B", 400)]))  # C deleted by hand
    assert t.entries == {"A": 1}
    assert s["deleted"] == 2


def test_sync_rejected_takes_remote(tmp_path):
    t = _table(tmp_path, A=1)
    ops = t.pending_ops()
    t.apply_sync_result(ops, _remote(rows=[("A", 7, 900)], rejected=["A"]))
    assert t.entries["A"] == 7 and not t.meta["A"]["dirty"]


def test_sync_imported_rows_get_pushed(tmp_path):
    t = XpTable(path=tmp_path / "x.json")
    t.apply_read({"A": 1})  # read mode: not dirty, never synced
    t.apply_sync_result([], _remote())
    assert t.entries == {"A": 1}
    assert [o["name"] for o in t.pending_ops()] == ["A"]


def test_pending_ops_survive_restart(tmp_path):
    t = _table(tmp_path, A=1)
    t.remove("A", at=200)
    t.set("B", 2, at=300)
    t.save()
    t2 = XpTable.load(tmp_path / "xp.json")
    assert sorted(o["op"] for o in t2.pending_ops()) == ["delete", "upsert"]


def test_apps_script_logic_in_node():
    """Runs apps_script.js against a mocked SpreadsheetApp, plus the shared cases (needs Node.js)."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js no disponible")
    r = subprocess.run([node, str(HERE / "apps_script_test.js")], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr


# -------------------------------------------------------- regression tests
def _synced(tmp_path, **entries):
    t = _table(tmp_path, **entries)
    t.apply_sync_result(t.pending_ops(), _remote(rows=[(n, x, 100) for n, x in entries.items()]))
    assert t.pending_ops() == []
    return t


def test_new_empty_sheet_does_not_wipe_local(tmp_path):
    t = _synced(tmp_path, A=1, B=2)
    t.reset_sync_state()  # app does this when the script URL changes
    s = t.apply_sync_result([], _remote())
    assert t.entries == {"A": 1, "B": 2} and s["deleted"] == 0
    assert sorted(o["name"] for o in t.pending_ops()) == ["A", "B"]


def test_empty_sheet_without_reset_still_safe(tmp_path):
    t = _synced(tmp_path, A=1)
    t.apply_sync_result([], _remote())  # e.g. tab renamed: never "all deleted by hand"
    assert t.entries == {"A": 1}


def test_incomplete_response_rejected(tmp_path):
    t = _synced(tmp_path, A=1)
    with pytest.raises(ValueError):
        t.apply_sync_result([], {"ok": True})
    assert t.entries == {"A": 1}


def test_script_response_without_rows_is_error(monkeypatch):
    fake_open(monkeypatch, '{"ok": true}', "application/json")
    with pytest.raises(GSheetError, match="incompleta"):
        client.script_sync(EXEC, "x", [])


def test_legacy_value_does_not_beat_sheet(tmp_path):
    p = tmp_path / "pet_xp.json"
    p.write_text('{"Gobio": 0.5}', encoding="utf-8")
    t = XpTable.load(p)
    ops = t.pending_ops()
    assert ops[0]["updated_at"] == 0
    # the real script rejects at==0 when the row exists and returns the sheet value
    t.apply_sync_result(ops, _remote(rows=[("Gobio", 5, 0)], rejected=["Gobio"]))
    assert t.entries == {"Gobio": 5} and t.pending_ops() == []


def test_read_import_clears_old_tombstone(tmp_path):
    t = _synced(tmp_path, Gobio=1)
    t.remove("Gobio", at=500)
    t.apply_read({"Gobio": 2})
    assert t.pending_ops() == []
    t.apply_sync_result([], _remote(rows=[("Otro", 1, 100)]))
    assert "Gobio" in t.entries


def test_http_exception_becomes_gsheet_error(monkeypatch):
    import http.client
    fake_open(monkeypatch, http.client.IncompleteRead(b""))
    with pytest.raises(GSheetError):
        client.fetch_sheet(ID)


def test_reset_keeps_pending_deletions(tmp_path):
    t = _synced(tmp_path, A=1, B=1)
    t.remove("B", at=900)
    t.reset_sync_state()
    assert {(o["op"], o["name"]) for o in t.pending_ops()} == {("upsert", "A"), ("delete", "B")}


# ------------------------------------------------- header / column detection
LAYOUT_CASES = json.loads((HERE / "layout_cases.json").read_text(encoding="utf-8"))
PARITY = json.loads((HERE / "parity_cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", LAYOUT_CASES, ids=[str(c["rows"][0]) for c in LAYOUT_CASES])
def test_detect_layout_shared_cases(case):
    lay = layout.detect_layout(case["rows"])
    header = -1 if lay.header_row is None else lay.header_row
    assert [lay.name_col, lay.xp_col, header, lay.data_start] == case["expect"]
    assert lay.ambiguous == case.get("ambiguous", False)


@pytest.mark.parametrize("text", [
    'obj,exp\nGobio,"0,5"\nTrucha,3\n',
    "Nombre;Experiencia\nGobio;0,5\nTrucha;3\n",
    "ITEM,Experience\nGobio,0.5\nTrucha,3\n",
    "Artículo,Puntos de experiencia\nGobio,0.5\nTrucha,3\n",
    "XP,Objeto\n0.5,Gobio\n3,Trucha\n",
    "0.5,Gobio\n3,Trucha\n",
    "Notas,Nombre,Actualizado,exp.\nx,Gobio,5,0.5\n,Trucha,6,3\n",
    "Cosa,Valor\nGobio,0.5\nTrucha,3\n",
    "Objeto\tXP\nGobio\t0,5\nTrucha\t3\n",
])
def test_parse_xp_csv_header_variants(text):
    rows, skipped = parse_xp_csv(text)
    assert rows == {"Gobio": 0.5, "Trucha": 3}
    assert skipped == 0  # a header is never counted as an invalid row


def test_item_named_like_alias_is_data():
    assert parse_xp_csv("Exp,5\nGobio,1\n") == ({"Exp": 5, "Gobio": 1}, 0)


def test_invalid_rows_without_header_are_counted():
    rows, skipped = parse_xp_csv("Gobio,1\nTrucha,2\nRoto,abc\n")
    assert rows == {"Gobio": 1, "Trucha": 2} and skipped == 1


def test_alias_lists_match_apps_script():
    import re

    src = client.apps_script_source()
    for const in ("NAME_ALIASES", "NAME_PREFIXES", "XP_TOKENS", "XP_PREFIXES"):
        m = re.search(rf"const {const} = (\[.*?\]);", src)
        assert m, const
        assert json.loads(m.group(1)) == getattr(layout, const), const
    for const in ("HEADER_SEARCH_ROWS", "GUESS_SAMPLE_ROWS"):
        m = re.search(rf"const {const} = (\d+);", src)
        assert m and int(m.group(1)) == getattr(layout, const), const


@pytest.mark.parametrize("text,value", PARITY["numbers"], ids=[repr(c[0]) for c in PARITY["numbers"]])
def test_number_parsing_shared_cases(text, value):
    assert parse_number(text) == value  # same cases run against num_() in apps_script_test.js


@pytest.mark.parametrize("raw,trimmed", PARITY["trim"], ids=[repr(c[0]) for c in PARITY["trim"]])
def test_cell_trimming_shared_cases(raw, trimmed):
    assert layout._cell([raw], 0) == trimmed  # twin of cell_() in the Apps Script
    if not trimmed[0].isdigit() and not any(c in raw for c in "\t\n"):  # a name as read from a CSV
        assert parse_xp_csv(f"Objeto,XP\n{raw},1\n") == ({trimmed: 1}, 0)


def test_ambiguous_numeric_columns_refused():
    with pytest.raises(GSheetError, match="cabecera"):
        parse_xp_csv("Precio,Cosa,Valor\n100,Gobio,1\n200,Trucha,2\n")
    # with a header saying which column is XP it works
    assert parse_xp_csv("Precio,Objeto,XP\n100,Gobio,1\n200,Trucha,2\n") == ({"Gobio": 1, "Trucha": 2}, 0)


def test_script_layout_error_message(monkeypatch):
    fake_open(monkeypatch, '{"ok": false, "error": "layout"}', "application/json")
    with pytest.raises(GSheetError, match="cabecera"):
        client.script_get(EXEC, "x")


def test_first_row_with_zero_xp_is_data_not_header():
    assert parse_xp_csv("Gobio,0\nTrucha,3\nPez,2\n") == ({"Trucha": 3, "Pez": 2}, 1)


def test_dates_are_not_names():
    assert parse_xp_csv("12/11/2026,Gobio,1\n13/11/2026,Trucha,2\n") == ({"Gobio": 1, "Trucha": 2}, 0)


def test_number_elsewhere_in_header_row_keeps_header():
    assert parse_xp_csv("Objeto,XP,2024\nGobio,1,\n") == ({"Gobio": 1}, 0)
    assert parse_xp_csv("Objeto,XP,,Total,42\nGobio,1,,,\n") == ({"Gobio": 1}, 0)


def test_header_like_rows_are_never_items():
    assert parse_xp_csv("Objeto,XP,2024\nGobio,,5\n") == ({"Gobio": 5}, 0)
    assert parse_xp_csv("Objeto,XP\nGobio,1\nNombre,Experiencia\nTrucha,2\n") == ({"Gobio": 1, "Trucha": 2}, 0)


# ------------------------------------------------ hidden two-way sync (flag)
def test_sync_mode_hidden_but_preserved(tmp_path, monkeypatch):
    p = tmp_path / "c.json"
    p.write_text('{"gsheet_mode": "sync", "gsheet_script_url": "https://x/exec", "gsheet_token": "t"}', encoding="utf-8")
    s = Settings.load(p)
    assert s.gsheet_mode == "sync"  # stored value kept
    assert s.effective_gsheet_mode == "off"  # but the app runs as "off"
    s.save(p)
    s2 = Settings.load(p)
    assert (s2.gsheet_mode, s2.gsheet_script_url, s2.gsheet_token) == ("sync", "https://x/exec", "t")
    monkeypatch.setattr(config, "ENABLE_SHEET_SYNC", True)
    assert s2.effective_gsheet_mode == "sync"


def test_visible_modes_and_resolve(monkeypatch):
    assert list(config.visible_gsheet_modes()) == ["off", "read"]
    # UI shows "off" for a hidden stored "sync": saving without touching it keeps "sync"
    assert config.resolve_saved_gsheet_mode("off", "sync") == "sync"
    assert config.resolve_saved_gsheet_mode("read", "sync") == "read"  # user changed it
    assert config.resolve_saved_gsheet_mode("off", "read") == "off"
    assert config.resolve_saved_gsheet_mode("read", "read") == "read"
    monkeypatch.setattr(config, "ENABLE_SHEET_SYNC", True)
    assert "sync" in config.visible_gsheet_modes()
    assert config.resolve_saved_gsheet_mode("off", "sync") == "off"


def test_collapsed_sections_roundtrip(tmp_path):
    p = tmp_path / "c.json"
    s = Settings(collapsed_sections=["galleta"])
    s.save(p)
    assert Settings.load(p).collapsed_sections == ["galleta"]
    p.write_text('{"collapsed_sections": "roto"}', encoding="utf-8")
    assert Settings.load(p).collapsed_sections == []


def test_parse_xp_csv_ignores_the_cookie():
    rows, skipped = parse_xp_csv("NOMBRE,EXPERIENCIA\nGalleta enriquecida,500\nGALLETA ENRIQUECEDORA,500\nGobio,1\n")
    assert rows == {"Gobio": 1.0} and skipped == 0
