"""Pet-feeding profitability maths (pure functions).

Reference: a "Galleta enriquecedora" gives ``cookie_xp`` XP for ``cookie_price`` kamas.
We only want to buy food that is at least ``margin_pct`` % cheaper per XP than the cookie:

    kamas_per_xp   = cookie_price * (1 - margin_pct/100) / cookie_xp     (20000, 500, 12.5 -> 35)
    max_unit_price = item_xp * kamas_per_xp
    max_lot_price  = max_unit_price * lot_size

Maximum price of the cookie itself (pet levelling 1 -> 100 takes COOKIES_PER_PET cookies):

    breakeven = (pet_price_100 - pet_price_1) / COOKIES_PER_PET     (5M, 1M -> 11.111,1)

Rounded DOWN (a maximum price to pay). The desired profitability is not applied here:
margin_pct already does it when the cookie price is used for the food factor.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

COOKIES_PER_PET = 360  # cookies to level a pet from 1 to 100 (fixed by the game)


def kamas_per_xp(cookie_price: float, cookie_xp: float, margin_pct: float) -> float:
    if cookie_xp <= 0:
        raise ValueError("cookie_xp must be > 0")
    return cookie_price * (1 - margin_pct / 100.0) / cookie_xp


def cookie_breakeven(pet_price_100: float, pet_price_1: float) -> float:
    """Price per cookie at which feeding a level-1 pet to 100 costs the same as buying it at 100."""
    if pet_price_100 <= pet_price_1:
        raise ValueError("pet_price_100 must be greater than pet_price_1")
    return (pet_price_100 - pet_price_1) / COOKIES_PER_PET


def cookie_max_price(pet_price_100: float, pet_price_1: float) -> int | None:
    """Break-even per cookie rounded down, or None if the prices make no sense
    (level 100 must cost more than level 1, both > 0, result at least 1 kama)."""
    if pet_price_1 <= 0:
        return None
    try:
        price = math.floor(cookie_breakeven(pet_price_100, pet_price_1))
    except ValueError:
        return None
    return price if price >= 1 else None


def max_unit_price(item_xp: float, factor: float) -> float:
    return item_xp * factor


@dataclass(frozen=True)
class LotEval:
    lot: int
    price: int
    unit_price: float
    max_lot_price: float
    profitable: bool


def evaluate(rows: list[tuple[int, int]], max_unit: float) -> list[LotEval]:
    out = []
    for lot, price in rows:
        max_lot = max_unit * lot
        out.append(LotEval(lot, price, price / lot, max_lot, price <= max_lot))
    return out
