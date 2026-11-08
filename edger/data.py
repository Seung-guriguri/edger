"""Data access on top of edgartools. Every function returns plain, picklable data so the
Streamlit layer can cache it with ``st.cache_data``.

The ticker ``DEMO`` returns synthetic data from :mod:`edger.demo` without touching the network.
"""
from __future__ import annotations

import os

import pandas as pd

from . import demo
from .metrics import ALL_CONCEPTS

SEC_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"

FILING_COLUMNS = ["form", "filing_date", "report_date", "description", "url"]
INSIDER_COLUMNS = ["date", "insider", "position", "code", "type", "shares", "price", "value", "url"]


class CompanyNotFound(LookupError):
    pass


def is_demo(ticker: str) -> bool:
    return ticker.upper() == demo.TICKER


def configure_identity(identity: str) -> None:
    """SEC requires a User-Agent with a name and email for every request."""
    from edgar import set_identity

    os.environ["EDGAR_IDENTITY"] = identity
    set_identity(identity)


def get_company(ticker: str):
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
        return demo.profile()
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
        raw = demo.facts_frame()
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
