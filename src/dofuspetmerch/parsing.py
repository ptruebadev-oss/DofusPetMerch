"""Numbers and item names as the game shows them and as a Spanish-speaking user types them."""
from __future__ import annotations

import math
import re
import unicodedata

# Characters OCR commonly confuses with digits.
_DIGIT_FIXES = str.maketrans({"O": "0", "o": "0", "D": "0", "Q": "0", "l": "1", "I": "1", "|": "1", "!": "1", "i": "1"})
_SEPARATORS = re.compile("[.,'\\s\u00a0\u202f:]")

# Whitespace trimmed from typed numbers and sheet cells, including the French thousands space.
# The Apps Script has its own copy (WS_RE); tests/parity_cases.json checks both agree.
WHITESPACE = " \t\n\r\f\v\u00a0\u2007\u2009\u202f\ufeff"
_SPACES = re.compile(f"[{WHITESPACE}]")

# ASCII digits only (Python's \d would accept Arabic digits). Same rules as num_() in the
# Apps Script.
_THOUSANDS = re.compile(r"^-?[1-9][0-9]{0,2}(\.[0-9]{3})+$")  # '0.500' is a decimal, not 500
_NUMBER = re.compile(r"^-?([0-9]+(\.[0-9]*)?|\.[0-9]+)$")


def parse_kamas(text: str) -> int | None:
    """Kamas amount as shown by Dofus ("7.840", "1.000", "19", "7 840"), or None.

    The game never shows decimals in prices, so every '.', ',', ':' or space is a
    thousands separator."""
    if not text:
        return None
    t = text.strip()
    if not any(c.isdigit() for c in t):  # otherwise words like "Id" would parse
        return None
    t = _SEPARATORS.sub("", t.translate(_DIGIT_FIXES))
    return int(t) if t.isdigit() else None


def parse_number(text: str) -> float | None:
    """Number typed by a Spanish-speaking user. None if invalid or not finite.

    '20.000' -> 20000 (dot groups of three = thousands), '1.234,5' -> 1234.5,
    '12,5' -> 12.5, '12.5' -> 12.5, '0,25' -> 0.25, '1 000' -> 1000,
    '1,234.5' -> 1234.5 (English format when both separators appear).
    """
    t = _SPACES.sub("", text or "")
    if "," in t and "." in t and t.rfind(".") > t.rfind(","):
        t = t.replace(",", "")
    elif "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif _THOUSANDS.match(t):
        t = t.replace(".", "")
    if not _NUMBER.match(t):
        return None  # also rejects 'inf', 'nan', '1e3', '1_000'
    v = float(t)
    return v if math.isfinite(v) else None


def parse_xp(text: str) -> float | None:
    """XP per unit typed by the user ('10', '0,5', '0.5', '1.500'). None if invalid or <= 0."""
    v = parse_number(text)
    return v if v is not None and v > 0 else None


def format_number(v: float) -> str:
    """Number for a form field: exact, Spanish format, never an exponent ("5e+06"), and
    always read back unchanged by parse_number ("5.000.000", "12,5")."""
    if float(v).is_integer() and abs(v) >= 1000:
        return f"{int(v):,}".replace(",", ".")
    txt = f"{v:.10f}".rstrip("0").rstrip(".")
    return (txt if txt not in ("", "-0") else "0").replace(".", ",")


def normalize_name(text: str) -> str:
    """Lower-case, accent-less, single-spaced version of an item name for matching."""
    t = unicodedata.normalize("NFKD", text)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t).strip().lower()


def letters_only(text: str) -> str:
    """Upper-case letters of a word, for fuzzy keyword matching (COMPRAR, Lote...)."""
    return "".join(c for c in normalize_name(text) if c.isalpha()).upper()


def format_kamas(value: float) -> str:
    """7840 -> '7.840', like the Spanish client."""
    return f"{round(value):,}".replace(",", ".")


def format_xp(value: float) -> str:
    """Exact XP ('0,25', '1500'), never rounded."""
    return f"{value:g}".replace(".", ",")


def format_unit(value: float) -> str:
    """Unit prices: one decimal below 100 ('5,8'), whole kamas above ('739')."""
    if value >= 100:
        return format_kamas(value)
    return f"{value:.1f}".replace(".", ",")
