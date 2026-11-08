"""Data access on top of edgartools. Every function returns plain, picklable data so the
Streamlit layer can cache it with ``st.cache_data``.

The ticker ``DEMO`` returns synthetic data from :mod:`edger.demo` without touching the network.
"""
from __future__ import annotations

import os
import re
import time
from functools import lru_cache

import pandas as pd

from . import demo
from .metrics import ALL_CONCEPTS

SEC_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"

FILING_COLUMNS = ["form", "filing_date", "report_date", "description", "url", "accession"]
INSIDER_COLUMNS = ["date", "insider", "position", "code", "type", "shares", "price", "value", "url"]


class CompanyNotFound(LookupError):
    pass


def is_demo(ticker: str) -> bool:
    return demo.is_demo(ticker)


def configure_identity(identity: str) -> None:
    """SEC requires a User-Agent with a name and email for every request."""
    from edgar import set_identity

    os.environ["EDGAR_IDENTITY"] = identity
    set_identity(identity)


def get_company(ticker: str):
    # Company() fetches the SEC submissions file; reuse it for an hour across calls.
    return _get_company(ticker.upper(), int(time.time() // 3600))


@lru_cache(maxsize=32)
def _get_company(ticker: str, _hour: int):
    from edgar import Company

    try:
        company = Company(ticker)
    except Exception as exc:  # edgartools raises different errors for unknown tickers
        raise CompanyNotFound(ticker) from exc
    if getattr(company, "not_found", False):
        raise CompanyNotFound(ticker)
    return company


def _safe(fn, default=None):
    try:
        value = fn()
    except Exception:
        return default
    return default if value is None else value


def fetch_profile(ticker: str) -> dict:
    if is_demo(ticker):
        return demo.profile(ticker)
    c = get_company(ticker)
    return {
        "name": _safe(lambda: c.name, ticker),
        "cik": _safe(lambda: int(c.cik)),
        "tickers": list(_safe(lambda: c.tickers, []) or []),
        "exchanges": list(_safe(lambda: c.get_exchanges(), []) or []),
        "industry": _safe(lambda: c.industry, ""),
        "fiscal_year_end": _safe(lambda: c.fiscal_year_end, ""),
        "category": _safe(lambda: str(c.filer_category), ""),
    }


def fetch_facts(ticker: str) -> pd.DataFrame:
    """XBRL company facts limited to the concepts the dashboard uses."""
    if is_demo(ticker):
        raw = demo.facts_frame(ticker)
    else:
        facts = get_company(ticker).get_facts()
        if facts is None:
            return pd.DataFrame()
        raw = facts.to_dataframe(include_metadata=True)
    return raw[raw["concept"].isin(ALL_CONCEPTS)].reset_index(drop=True)


def fetch_filings(ticker: str, limit: int = 400) -> pd.DataFrame:
    if is_demo(ticker):
        return demo.filings_frame()
    c = get_company(ticker)
    df = c.get_filings().to_pandas()
    if df.empty:
        return pd.DataFrame(columns=FILING_COLUMNS)
    df = df.sort_values("filing_date", ascending=False).head(limit)
    cik = int(c.cik)
    urls = [
        f"{SEC_ARCHIVES}/{cik}/{acc.replace('-', '')}/{doc}" if doc
        else f"{SEC_ARCHIVES}/{cik}/{acc.replace('-', '')}/{acc}-index.html"
        for acc, doc in zip(df["accession_number"], df["primaryDocument"].fillna(""))
    ]
    return pd.DataFrame({
        "form": df["form"].values,
        "filing_date": pd.to_datetime(df["filing_date"]).values,
        "report_date": df.get("reportDate", pd.Series([""] * len(df))).fillna("").values,
        "description": df.get("primaryDocDescription", pd.Series([""] * len(df))).fillna("").values,
        "url": urls,
        "accession": df["accession_number"].values,
    })


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def fetch_insider_trades(ticker: str, n_filings: int = 40) -> pd.DataFrame:
    """Transactions from the most recent Form 4 filings (one SEC request per filing)."""
    if is_demo(ticker):
        return demo.insider_frame()
    filings = get_company(ticker).get_filings(form="4").head(n_filings)
    frames = []
    for filing in filings:
        try:
            df = filing.obj().to_dataframe(detailed=True, include_metadata=True)
        except Exception:
            continue  # malformed or unsupported filing; skip rather than fail the page
        if df is None or df.empty or "Code" not in df.columns:
            continue
        frames.append(pd.DataFrame({
            "date": pd.to_datetime(df.get("Date", filing.filing_date), errors="coerce"),
            "insider": df.get("Insider", ""),
            "position": df.get("Position", ""),
            "code": df["Code"],
            "type": df.get("Transaction Type", ""),
            "shares": _num(df.get("Shares", pd.Series(dtype=float))),
            "price": _num(df.get("Price", pd.Series(dtype=float))),
            "value": _num(df.get("Value", pd.Series(dtype=float))),
            "url": filing.homepage_url,
        }))
    if not frames:
        return pd.DataFrame(columns=INSIDER_COLUMNS)
    out = pd.concat(frames, ignore_index=True)
    missing = out["value"].isna() & out["shares"].notna() & out["price"].notna()
    out.loc[missing, "value"] = out.loc[missing, "shares"] * out.loc[missing, "price"]
    return out.sort_values("date", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------- full statements
STATEMENTS = {"income": "income_statement", "balance": "balance_sheet", "cashflow": "cash_flow_statement"}
STATEMENT_COLUMNS = ["label", "depth", "is_abstract", "kind"]
MAX_STATEMENT_PERIODS = 3
# XBRL statement period columns look like "2025-09-27", "2025-09-27 (FY)", "2025-06-28 (Q3)" or "(YTD)".
_PERIOD_COL = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:\s*\((FY|YTD|Q\d)\))?$")
_SUFFIX = {None: "", "FY": "", "YTD": " 누적"}


def _value_kind(unit: str, label: str = "") -> str:
    u, lbl = (unit or "").lower(), (label or "").lower()
    if "share" in u and ("per" in u or "/" in u) or "per share" in lbl:
        return "per_share"
    if u in ("shares", "share") or (not u and "shares outstanding" in lbl):
        return "shares"
    return "money"


def normalize_xbrl_statement(raw: pd.DataFrame, max_periods: int = MAX_STATEMENT_PERIODS) -> pd.DataFrame:
    """edgartools ``Statement.to_dataframe()`` -> label/depth/is_abstract/kind + period columns.

    Keeps the newest ``max_periods`` periods, preferring discrete periods (FY, quarters) over
    year-to-date columns when both exist (10-Q income statements show both).
    """
    if raw is None or isinstance(raw, str) or raw.empty:
        return pd.DataFrame()
    if "dimension" in raw.columns:
        raw = raw[~raw["dimension"].fillna(False).astype(bool)]
    periods = []
    for col in raw.columns:
        m = _PERIOD_COL.match(str(col))
        if m:
            periods.append((f"{m.group(1)}-{m.group(2)}-{m.group(3)}", m.group(4), col))
    if not periods:
        return pd.DataFrame()
    discrete = [p for p in periods if p[1] != "YTD"]
    chosen = sorted(discrete or periods, key=lambda p: p[0], reverse=True)
    seen, cols, names = set(), [], []
    for date_s, suffix, col in chosen:
        name = f"{date_s[2:4]}.{date_s[5:7]}" + _SUFFIX.get(suffix, f" {suffix}")
        if name in seen:
            continue
        seen.add(name)
        cols.append(col)
        names.append(name)
        if len(cols) == max_periods:
            break

    out = pd.DataFrame({
        "label": raw.get("label", pd.Series([""] * len(raw), index=raw.index)).astype(str),
        "depth": pd.to_numeric(raw.get("level", 0), errors="coerce").fillna(0).astype(int),
        "is_abstract": raw.get("abstract", False),
    })
    out["is_abstract"] = out["is_abstract"].fillna(False).astype(bool)
    units = raw["unit"] if "unit" in raw.columns else pd.Series([""] * len(raw), index=raw.index)
    out["kind"] = [_value_kind(str(u) if pd.notna(u) else "", lbl) for u, lbl in zip(units, out["label"])]
    for col, name in zip(cols, names):
        out[name] = pd.to_numeric(raw[col], errors="coerce")
    empty = out[names].isna().all(axis=1) & ~out["is_abstract"]
    out = out[~empty]
    return out.reset_index(drop=True) if out[names].notna().any().any() else pd.DataFrame()


def _statement_from_filing(ticker: str, kind: str, period: str) -> tuple[pd.DataFrame, str]:
    c = get_company(ticker)
    fin = c.get_financials() if period == "annual" else c.get_quarterly_financials()
    if fin is None:
        return pd.DataFrame(), ""
    stmt = getattr(fin, STATEMENTS[kind])()
    if stmt is None:
        return pd.DataFrame(), ""
    try:
        raw = stmt.to_dataframe(view="summary", include_unit=True)
    except TypeError:  # older/newer signature
        raw = stmt.to_dataframe()
    return normalize_xbrl_statement(raw), ("최근 10-K" if period == "annual" else "최근 10-Q") + " 공시 원문 XBRL"


def _statement_from_facts(ticker: str, kind: str, period: str) -> tuple[pd.DataFrame, str]:
    facts = demo.entity_facts(ticker) if is_demo(ticker) else get_company(ticker).get_facts()
    if facts is None:
        return pd.DataFrame(), ""
    df = getattr(facts, STATEMENTS[kind])(periods=MAX_STATEMENT_PERIODS, period=period, as_dataframe=True)
    if not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame(), ""
    value_cols = [c for c in df.columns if c not in ("label", "depth", "is_abstract", "is_total",
                                                       "section", "confidence")][:MAX_STATEMENT_PERIODS]
    out = pd.DataFrame({
        "label": df["label"].astype(str).values,
        "depth": pd.to_numeric(df.get("depth", 0), errors="coerce").fillna(0).astype(int).values,
        "is_abstract": df.get("is_abstract", False).fillna(False).astype(bool).values,
        "kind": ["per_share" if "PerShare" in str(c) else "shares" if str(c).endswith("Shares") else "money"
                 for c in df.index],
    })
    for c in value_cols:
        out[str(c)] = pd.to_numeric(df[c], errors="coerce").values
    return out, "XBRL 데이터에서 재구성"


KEY_LINES = {
    "income": ["revenue", "gross_profit", "operating_income", "interest_expense", "pretax_income",
               "income_tax", "net_income", "eps", "shares_diluted"],
    "balance": ["cash", "current_assets", "assets", "current_liabilities", "debt_short", "debt_long",
                "liabilities", "equity"],
    "cashflow": ["ocf", "da", "capex", "fcf", "dividends", "buybacks"],
}


def _statement_from_key_lines(ticker: str, kind: str, period: str) -> tuple[pd.DataFrame, str]:
    """Last resort: the main line items the dashboard already computes."""
    from .metrics import DERIVED_LABELS, METRIC_BY_KEY, build_table

    table, _ = build_table(fetch_facts(ticker), period, MAX_STATEMENT_PERIODS)
    if table.empty:
        return pd.DataFrame(), ""
    table = table.iloc[::-1]
    rows = []
    for key in KEY_LINES[kind]:
        if key not in table or table[key].isna().all():
            continue
        m = METRIC_BY_KEY.get(key)
        rows.append({"label": DERIVED_LABELS.get(key) or m.label, "depth": 0, "is_abstract": False,
                     "kind": m.unit if m else "money",
                     **{lbl: v for lbl, v in zip(table["label"], table[key])}})
    return pd.DataFrame(rows), "주요 항목만 (XBRL 데이터에서 계산)"


def fetch_statement(ticker: str, kind: str, period: str = "annual") -> dict:
    """Full statement as {"table": DataFrame, "source": str, "error": str | None}.

    Primary source is the XBRL of the latest 10-K / 10-Q (exact line items and order as filed).
    If that fails or is empty, falls back to rebuilding it from the company facts API.
    """
    error = None
    if not is_demo(ticker):
        try:
            table, source = _statement_from_filing(ticker, kind, period)
            if not table.empty:
                return {"table": table, "source": source, "error": None}
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
    for builder in (_statement_from_facts, _statement_from_key_lines):
        try:
            table, source = builder(ticker, kind, period)
        except Exception as exc:
            table, source = pd.DataFrame(), ""
            error = error or f"{type(exc).__name__}: {exc}"
        if not table.empty:
            return {"table": table, "source": source, "error": None}
    return {"table": pd.DataFrame(), "source": "", "error": error}


# ---------------------------------------------------------------- reading filings
# (title, item keys tried in order) per form. Items differ by form; the first key found wins.
READABLE_SECTIONS = {
    "10-K": [("사업 개요", ["Item 1"]), ("리스크 요인", ["Item 1A"]),
             ("경영진 분석 (MD&A)", ["Item 7"]), ("법적 절차", ["Item 3"])],
    "10-Q": [("경영진 분석 (MD&A)", ["Part I, Item 2", "Item 2"]),
             ("리스크 요인 변경", ["Part II, Item 1A", "Item 1A"]),
             ("법적 절차", ["Part II, Item 1"])],
    "20-F": [("회사 정보", ["Item 4"]), ("주요 정보·리스크", ["Item 3"]), ("영업·재무 검토", ["Item 5"])],
    "40-F": [("사업 개요", ["business"]), ("리스크 요인", ["risk_factors"])],
}
READABLE_FORMS = ("10-K", "10-Q", "20-F", "40-F", "8-K", "6-K")
_8K_ITEMS = {
    "1.01": "중요 계약 체결", "1.02": "중요 계약 해지", "1.05": "사이버보안 사고", "2.01": "자산 인수·처분",
    "2.02": "실적 발표", "2.03": "채무 발생", "2.05": "구조조정 비용", "2.06": "자산 손상",
    "3.01": "상장 관련 통지", "4.01": "감사인 변경", "4.02": "재무제표 신뢰성 문제",
    "5.02": "임원·이사 변동", "5.03": "정관 변경", "5.07": "주주총회 결과", "7.01": "공정공시(Reg FD)",
    "8.01": "기타 중요 사항", "9.01": "재무제표·첨부",
}
MAX_SECTION_CHARS = 60_000


def _item_title(item: str) -> str:
    code = item.replace("Item", "").strip().rstrip(".")
    name = _8K_ITEMS.get(code)
    return f"{item} · {name}" if name else item


def _clip(text: str | None) -> str | None:
    if not text:
        return None
    text = text.strip()
    if len(text) > MAX_SECTION_CHARS:
        text = text[:MAX_SECTION_CHARS] + "\n\n… (너무 길어 이후 생략, 원문에서 확인하세요)"
    return text


def read_filing(ticker: str, accession: str, form: str) -> list[dict]:
    """Readable sections of a filing as [{"title", "text"}]. Empty list if nothing parsed."""
    if is_demo(ticker):
        return demo.filing_sections(form)
    from edgar import get_by_accession_number

    filing = get_by_accession_number(accession)
    base = form.replace("/A", "")
    sections: list[dict] = []
    try:
        obj = filing.obj()
    except Exception:
        obj = None

    if obj is not None and base in ("8-K", "6-K"):
        for item in list(_safe(lambda: obj.items, []) or []):
            text = _clip(_safe(lambda: obj.get(item)))
            if text and not item.endswith("9.01"):
                sections.append({"title": _item_title(item), "text": text})
        releases = _safe(lambda: obj.press_releases)
        if releases:
            for i in range(min(len(releases), 2)):
                text = _clip(_safe(lambda: releases[i].text()))
                if text:
                    sections.append({"title": "보도자료 (EX-99)", "text": text})
    elif obj is not None and base in READABLE_SECTIONS:
        for title, keys in READABLE_SECTIONS[base]:
            for key in keys:
                text = _safe(lambda: getattr(obj, key) if key.islower() else obj.get(key))
                if isinstance(text, str) and text.strip():
                    sections.append({"title": title, "text": _clip(text)})
                    break

    if not sections:  # unknown form or parser found nothing: fall back to the whole document
        text = _clip(_safe(lambda: filing.text()))
        if text:
            sections.append({"title": "본문", "text": text})
    return sections
