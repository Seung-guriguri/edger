"""Shared Streamlit pieces: styles, cached loaders, small widgets."""
from __future__ import annotations

import os
import re

import pandas as pd
import streamlit as st

from . import charts, data, market
from .metrics import TTM_FLOWS, build_table, cagr, latest_shares_outstanding, ttm, valuation

CACHE_TTL = 60 * 60 * 6  # SEC data changes slowly; also keeps us far below the 10 req/s limit
PRICE_TTL = 60 * 15

CSS = """
<style>
.block-container {padding-top: 1.2rem; padding-bottom: 3rem; padding-left: 1rem; padding-right: 1rem; max-width: 760px;}
header[data-testid="stHeader"] {height: 0; background: transparent;}
h1 {font-size: 1.5rem !important; margin-bottom: 0 !important;}
h3 {font-size: 1.2rem !important; padding-bottom: 0 !important;}
/* KPI grid: keep two cards per row even on narrow phones (Streamlit stacks columns by default) */
[class*="st-key-kpis"] [data-testid="stHorizontalBlock"] {flex-wrap: wrap; gap: 0.5rem;}
[class*="st-key-kpis"] [data-testid="stColumn"] {min-width: calc(50% - 0.25rem) !important; flex: 1 1 calc(50% - 0.25rem) !important;}
[data-testid="stMetric"] {padding: 0.55rem 0.7rem;}
[data-testid="stMetricValue"] {font-size: 1.3rem;}
[data-testid="stMetricLabel"] p {font-size: 0.8rem;}
/* Larger tap targets for tabs; let 4 tabs fit on a phone */
button[data-baseweb="tab"] {padding: 0.6rem 0.7rem; font-size: 0.95rem;}
.ed-sub {color: #8a8984; font-size: 0.85rem; margin: 0.1rem 0 0.6rem;}
.ed-list {list-style: none; padding: 0; margin: 0;}
.ed-list li {margin: 0 !important; padding: 0.65rem 0.1rem; border-bottom: 1px solid rgba(128,128,128,0.18);}
.ed-list a {text-decoration: none; color: inherit; display: block;}
.ed-row {display: flex; justify-content: space-between; align-items: baseline; gap: 0.5rem;}
.ed-title {font-weight: 600; font-size: 0.95rem;}
.ed-meta {color: #8a8984; font-size: 0.8rem; white-space: nowrap;}
.ed-desc {color: #8a8984; font-size: 0.82rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;}
.ed-badge {display: inline-block; font-size: 0.72rem; font-weight: 600; padding: 0.05rem 0.45rem; border-radius: 999px;
           border: 1px solid currentColor; margin-right: 0.35rem;}
.ed-buy {color: #2a78d6;} .ed-sell {color: #e34948;} .ed-other {color: #8a8984;}
/* filing reader: keep headings inside the text from shouting on a phone */
[data-testid="stExpander"] h1, [data-testid="stExpander"] h2 {font-size: 1.1rem !important;}
[data-testid="stExpander"] h3, [data-testid="stExpander"] h4 {font-size: 1rem !important;}
/* hidden helper iframes (browser storage bridge) take no space */
iframe[title="streamlit_js_eval.streamlit_js_eval"] {display: none;}
.element-container:has(iframe[title="streamlit_js_eval.streamlit_js_eval"]) {display: none;}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------- cached loaders
@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_profile(ticker: str) -> dict:
    return data.fetch_profile(ticker)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_facts(ticker: str) -> pd.DataFrame:
    return data.fetch_facts(ticker)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_table(ticker: str, period: str, n: int):
    return build_table(load_facts(ticker), period, n)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_statement(ticker: str, kind: str, period: str) -> dict:
    return data.fetch_statement(ticker, kind, period)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_filings(ticker: str) -> pd.DataFrame:
    return data.fetch_filings(ticker)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_filing_sections(ticker: str, accession: str, form: str) -> list[dict]:
    return data.read_filing(ticker, accession, form)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_insiders(ticker: str, n: int) -> pd.DataFrame:
    return data.fetch_insider_trades(ticker, n)


class _NoPrice(Exception):
    """Raised inside cached loaders so that a failed price lookup is not cached."""


@st.cache_data(ttl=PRICE_TTL, show_spinner=False)
def _cached_prices(ticker: str, period: str) -> pd.Series:
    s = market.price_history(ticker, period)
    if s.empty:
        raise _NoPrice(ticker)
    return s


@st.cache_data(ttl=PRICE_TTL, show_spinner=False)
def _cached_quote(ticker: str) -> dict:
    q = market.quote(ticker)
    if not q.get("price"):
        raise _NoPrice(ticker)
    return q


_RETRY_AFTER = 90  # seconds before retrying a failed price lookup (avoids hammering on every tap)


def _recently_failed(key: str) -> bool:
    import time

    failed = st.session_state.setdefault("_price_failures", {})
    return time.time() - failed.get(key, 0) < _RETRY_AFTER


def _mark_failed(key: str) -> None:
    import time

    st.session_state.setdefault("_price_failures", {})[key] = time.time()


def load_prices(ticker: str, period: str = "10y") -> pd.Series:
    key = f"hist:{ticker}:{period}"
    if _recently_failed(key):
        return pd.Series(dtype=float, name="close")
    try:
        return _cached_prices(ticker, period)
    except _NoPrice:
        _mark_failed(key)
        return pd.Series(dtype=float, name="close")


def load_quote(ticker: str) -> dict:
    key = f"quote:{ticker}"
    if _recently_failed(key):
        return market.empty_quote()
    try:
        return _cached_quote(ticker)
    except _NoPrice:
        _mark_failed(key)
        return market.empty_quote()


def retry_prices() -> None:
    """Forget failures so the next run asks the price sources again."""
    st.session_state.pop("_price_failures", None)


def market_cap_estimate(ticker: str, q: dict, quarterly: pd.DataFrame, annual: pd.DataFrame
                        ) -> tuple[float | None, str | None]:
    """(market cap, how it was obtained). Tries, in order: Yahoo's market cap, price x SEC
    cover-page shares outstanding, price x latest diluted weighted-average shares."""
    if q.get("market_cap"):
        return q["market_cap"], "Yahoo Finance 시가총액"
    price = q.get("price")
    if not price:
        return None, None
    shares = latest_shares_outstanding(load_facts(ticker))
    if shares:
        return price * shares, "주가 × SEC 공시 발행주식수"
    for table in (quarterly, annual):
        if not table.empty and table["shares_diluted"].notna().any():
            return price * float(table["shares_diluted"].dropna().iloc[-1]), "주가 × 희석주식수(추정)"
    return None, None


def load_snapshot(ticker: str) -> dict:
    """Everything the valuation cards and the watchlist table need for one company.

    Not cached itself (it only combines cached pieces), so a price that arrives after an
    earlier failure shows up immediately.
    """
    annual, currency = load_table(ticker, "annual", 10)
    quarterly, _ = load_table(ticker, "quarterly", 12)
    q = load_quote(ticker)
    flows, prev_flows = ttm(quarterly), ttm(quarterly, offset=4)
    if flows is None and not annual.empty:  # fall back to the latest fiscal years
        def fy(row_idx):
            last = annual.iloc[row_idx]
            return {"label": last["label"], "end": annual.index[row_idx],
                    **{k: (None if pd.isna(last.get(k)) else float(last.get(k))) for k in TTM_FLOWS}}
        flows = fy(-1)
        prev_flows = fy(-2) if len(annual) > 1 else None
    balance_src = quarterly if not quarterly.empty else annual
    balance = balance_src.iloc[-1] if not balance_src.empty else None

    market_cap, cap_source = market_cap_estimate(ticker, q, quarterly, annual)
    val = valuation(market_cap, flows, balance, price=q.get("price"), prev_flows=prev_flows,
                    eps_cagr=cagr(annual, "eps", 3))
    return {
        "quote": q, "market_cap": market_cap, "cap_source": cap_source, "currency": currency, "ttm": flows,
        "balance": balance, "valuation": val,
        "annual": annual,
    }


# ---------------------------------------------------------------- helpers
def theme_mode() -> str:
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except Exception:
        return "light"


def resolve_identity() -> str | None:
    try:
        secret = st.secrets.get("EDGAR_IDENTITY")
    except Exception:
        secret = None
    return secret or os.environ.get("EDGAR_IDENTITY") or st.session_state.get("identity")


def plot(fig) -> None:
    st.plotly_chart(fig, theme=None, config=charts.PLOTLY_CONFIG, width="stretch")


def kpi(col, label: str, value: str, delta: float | str | None = None, *, pp: bool = False,
        help: str | None = None, neutral: bool = False) -> None:
    if delta is None or isinstance(delta, str):
        d = delta
    else:
        d = f"{delta * 100:+.1f}%p" if pp else f"{delta * 100:+.1f}%"
    col.metric(label, value, d, border=True, help=help,
               delta_color="off" if neutral else "normal",
               delta_arrow="off" if neutral else "auto")


def kpi_grid(items: list[tuple], key: str) -> None:
    """Two cards per row. ``items`` are argument tuples for :func:`kpi` (without ``col``)."""
    with st.container(key=f"kpis_{key}"):
        for i in range(0, len(items), 2):
            cols = st.columns(2)
            for col, item in zip(cols, items[i:i + 2]):
                args, kwargs = (item[:-1], item[-1]) if isinstance(item[-1], dict) else (item, {})
                kpi(col, *args, **kwargs)


def safe_markdown_text(text: str) -> str:
    """Filing text rendered as Markdown: escape '$' (LaTeX) and keep paragraphs."""
    text = text.replace("$", "\\$")
    return re.sub(r"\n{3,}", "\n\n", text)
