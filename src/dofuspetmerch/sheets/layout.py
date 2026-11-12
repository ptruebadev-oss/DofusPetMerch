"""The XP sheet format: which columns hold the item name and the XP, CSV import and TSV export.

``detect_layout`` has a twin, ``layout_`` in apps_script.js: change both, and add the case to
tests/layout_cases.json (run against both).
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass

from ..parsing import WHITESPACE, format_xp, normalize_name, parse_number, parse_xp


class GSheetError(Exception):
    """Google Sheets problem, with a Spanish message for the user."""


# Header aliases. apps_script.js declares the same lists (a test checks they match).
NAME_ALIASES = ["objeto", "objet", "object", "item", "items", "nombre", "name", "nom", "articulo",
                "recurso", "ressource", "resource", "alimento", "comida", "ingrediente", "producto"]
NAME_PREFIXES = ["obj", "nomb", "item", "artic", "recur", "ress", "alim"]
XP_TOKENS = ["xp", "pex"]
XP_PREFIXES = ["exp"]  # exp, exp., experiencia, experience, expérience
HEADER_SEARCH_ROWS = 5
AMBIGUOUS_MSG = ("Hay varias columnas con números y no se sabe cuál es la XP: "
                 "pon una cabecera con 'Objeto' y 'XP' en la hoja")
GUESS_SAMPLE_ROWS = 20


@dataclass(frozen=True)
class Layout:
    name_col: int
    xp_col: int
    header_row: int | None = None  # index of the header row, None if the table has none
    data_start: int = 0
    ambiguous: bool = False  # several numeric columns and no header saying which one is XP


_DATEISH = re.compile(r"^[0-9]{1,4}[/.-][0-9]{1,2}[/.-][0-9]{1,4}([ T].*)?$")


def _cell(row: list, j: int) -> str:
    return str(row[j]).strip(WHITESPACE) if j < len(row) and row[j] is not None else ""


def _lcell(row: list, j: int) -> str:
    """Cell as seen by the layout guess: dates count as empty (Apps Script sees Date objects)."""
    c = _cell(row, j)
    return "" if _DATEISH.match(c) else c


def _tokens(cell) -> list[str]:
    return re.sub(r"[^a-z0-9]+", " ", normalize_name(str(cell))).split()


def is_name_header(cell) -> bool:
    t = _tokens(cell)
    if not t:
        return False
    return t[0] in NAME_ALIASES or " ".join(t) in NAME_ALIASES or any(t[0].startswith(p) for p in NAME_PREFIXES)


def is_xp_header(cell) -> bool:
    return any(x in XP_TOKENS or any(x.startswith(p) for p in XP_PREFIXES) for x in _tokens(cell))


def looks_like_header(row: list, name_col: int) -> bool:
    """An old header left as data: the name cell is exactly a label ("Objeto", "Nombre"; not
    "Objeto raro") and another cell is an XP label. Such a row is never an item."""
    if " ".join(_tokens(_cell(row, name_col))) not in NAME_ALIASES:
        return False
    return any(j != name_col and is_xp_header(_cell(row, j)) for j in range(len(row)))


def _xp_column_fits(below: list[list], x: int) -> bool:
    """The rows under a candidate header agree with it: either nobody has a valid XP yet, or
    some row has one in column ``x``. Rejects e.g. "Objeto raro | experimental | 5" taken as
    a header with the notes column as XP."""
    data = [r for r in below if any(_cell(r, j) for j in range(len(r)))][:GUESS_SAMPLE_ROWS]
    any_xp = any(parse_xp(_cell(r, j)) is not None for r in data for j in range(len(r)))
    return not any_xp or any(parse_xp(_cell(r, x)) is not None for r in data)


def detect_layout(rows: list[list]) -> Layout:
    """Find which columns hold the item name and the XP, and whether there is a header row.

    1. Alias header in the first rows: a cell like "Objeto/obj/nombre/item…" and another like
       "XP/exp/experiencia/experience…" whose value is not a number (so an item really called
       "Exp" with XP 5 stays data). Rows above it (titles) are ignored.
    2. Otherwise guess: XP column = the one with most valid XP numbers (>= 50 %), name column =
       leftmost other column of mostly text. The first row is a header with unknown labels only
       if its XP cell is not a number and later rows are valid data.
    """
    for i, row in enumerate(rows[:HEADER_SEARCH_ROWS]):
        n = next((j for j in range(len(row)) if is_name_header(_cell(row, j))), None)
        x = next((j for j in range(len(row)) if j != n and is_xp_header(_cell(row, j))), None)
        if n is None or x is None:
            continue
        span = range(min(n, x), max(n, x) + 1)
        # A header has no numbers from the name to the XP column ("Objeto raro | 5 | experimental"
        # is data). A number elsewhere ("Objeto | XP | 2024") is allowed only if the rows below
        # agree with that XP column ("Objeto raro | experimental | 5" is data).
        num_in_span = any(parse_number(_cell(row, j)) is not None for j in span)
        num_outside = any(parse_number(_cell(row, j)) is not None for j in range(len(row)) if j not in span)
        if not num_in_span and (not num_outside or _xp_column_fits(rows[i + 1:], x)):
            return Layout(n, x, i, i + 1)

    sample = [i for i, r in enumerate(rows) if any(_lcell(r, j) for j in range(len(r)))][:GUESS_SAMPLE_ROWS]
    ncols = max((len(rows[i]) for i in sample), default=0)
    if ncols < 2:
        return Layout(0, 1)
    xp_col, best, numeric_cols = 1, -1.0, 0
    for j in range(ncols):
        cells = [_lcell(rows[i], j) for i in sample if _lcell(rows[i], j)]
        share = sum(parse_xp(c) is not None for c in cells) / len(cells) if cells else 0
        if share >= 0.5:
            numeric_cols += 1
            if share > best:
                xp_col, best = j, share
    name_col = None
    for j in range(ncols):
        if j == xp_col:
            continue
        cells = [_lcell(rows[i], j) for i in sample if _lcell(rows[i], j)]
        if cells and sum(parse_number(c) is None for c in cells) / len(cells) > 0.5:
            name_col = j
            break
    if name_col is None:
        name_col = 1 if xp_col == 0 else 0
    ambiguous = numeric_cols > 1
    first = sample[0]
    head = rows[first]
    # Unknown labels ("Cosa | Valor"): the XP cell is text, not a number (so "Gobio | 0" is data).
    if (_lcell(head, name_col) and _lcell(head, xp_col) and parse_number(_lcell(head, xp_col)) is None
            and any(_lcell(rows[i], name_col) and parse_xp(_lcell(rows[i], xp_col)) is not None for i in sample[1:])):
        return Layout(name_col, xp_col, first, first + 1, ambiguous)
    return Layout(name_col, xp_col, ambiguous=ambiguous)


# The cookie is the price reference, not pet food: sheets often list it, the table must not.
IGNORED_NAMES = frozenset({"galleta enriquecida", "galleta enriquecedora"})


def parse_xp_csv(text: str) -> tuple[dict[str, float], int]:
    """CSV/TSV of items and XP (header optional, any column order) -> ({name: xp}, skipped rows).
    Rows in ``IGNORED_NAMES`` are left out (not counted as skipped)."""
    text = text.lstrip("\ufeff")
    try:
        dialect = csv.Sniffer().sniff(text[:2048], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    lay = detect_layout(rows)
    if lay.ambiguous:
        raise GSheetError(AMBIGUOUS_MSG)
    name_col, xp_col = lay.name_col, lay.xp_col
    out: dict[str, float] = {}
    keys: dict[str, str] = {}
    skipped = 0
    for row in rows[lay.data_start:]:
        if not any(_cell(row, j) for j in range(len(row))) or looks_like_header(row, name_col):
            continue
        name, xp = _cell(row, name_col), parse_xp(_cell(row, xp_col))
        if not name or xp is None:
            skipped += 1
            continue
        n = normalize_name(name)
        if n in IGNORED_NAMES:
            continue
        if n in keys:  # duplicate: last one wins
            out.pop(keys[n])
        keys[n] = name
        out[name] = xp
    return out, skipped


def table_tsv(entries: dict[str, float]) -> str:
    """'Objeto<TAB>XP' rows, sorted, with comma decimals (Spanish-locale sheets read them as
    numbers). Pasted into a sheet, parse_xp_csv reads it back unchanged."""
    lines = ["Objeto\tXP"]
    for name, xp in sorted(entries.items(), key=lambda kv: kv[0].lower()):
        clean = " ".join(name.replace("\t", " ").split())
        lines.append(f"{clean}\t{format_xp(xp)}")
    return "\n".join(lines) + "\n"
