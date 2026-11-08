"""Compact number formatting for small screens."""
from __future__ import annotations

import math

_SYMBOLS = {"USD": "$", "EUR": "€", "JPY": "¥", "GBP": "£", "KRW": "₩", "CNY": "¥"}


def _is_missing(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


def scale_for(max_abs: float) -> tuple[float, str]:
    """Divisor and suffix that keep numbers to ~3 significant digits."""
    if max_abs >= 1e12:
        return 1e12, "T"
    if max_abs >= 1e9:
        return 1e9, "B"
    if max_abs >= 1e6:
        return 1e6, "M"
    if max_abs >= 1e3:
        return 1e3, "K"
    return 1, ""


def money(v, currency: str = "USD", digits: int = 1) -> str:
    if _is_missing(v):
        return "–"
    div, suffix = scale_for(abs(v))
    sym = _SYMBOLS.get(currency)
    num = f"{abs(v) / div:,.{digits}f}{suffix}"
    sign = "-" if v < 0 else ""
    return f"{sign}{sym}{num}" if sym else f"{sign}{num} {currency}"


def per_share(v, currency: str = "USD") -> str:
    if _is_missing(v):
        return "–"
    sym = _SYMBOLS.get(currency, "")
    sign = "-" if v < 0 else ""
    return f"{sign}{sym}{abs(v):,.2f}" + ("" if sym else f" {currency}")


def number(v, digits: int = 1) -> str:
    if _is_missing(v):
        return "–"
    div, suffix = scale_for(abs(v))
    return f"{v / div:,.{digits}f}{suffix}"


def pct(v, digits: int = 1, signed: bool = False) -> str:
    if _is_missing(v):
        return "–"
    return f"{v * 100:{'+' if signed else ''}.{digits}f}%"
