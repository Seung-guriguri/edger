"""Shared Streamlit pieces: styles, cached loaders, small widgets."""
from __future__ import annotations

import os
import re

import pandas as pd
import streamlit as st

from . import charts, data, market
from .metrics import build_table, latest_shares_outstanding, ttm, valuation

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
def load_statement(ticker: str, kind: str, period: str) -> pd.DataFrame:
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


@st.cache_data(ttl=PRICE_TTL, show_spinner=False)
def load_prices(ticker: str, period: str = "10y") -> pd.Series:
    return market.price_history(ticker, period)


@st.cache_data(ttl=PRICE_TTL, show_spinner=False)
def load_quote(ticker: str) -> dict:
    return market.quote(ticker)


@st.cache_data(ttl=PRICE_TTL, show_spinner=False)
def load_snapshot(ticker: str) -> dict:
    """Everything the valuation cards and the watchlist table need for one company."""
    annual, currency = load_table(ticker, "annual", 10)
    quarterly, _ = load_table(ticker, "quarterly", 12)
    q = load_quote(ticker)
    flows = ttm(quarterly)
    if flows is None and not annual.empty:  # fall back to the latest fiscal year
        last = annual.iloc[-1]
        flows = {"label": last["label"], "end": annual.index[-1],
                 **{k: (None if pd.isna(last.get(k)) else float(last.get(k)))
                    for k in ("revenue", "gross_profit", "operating_income", "net_income", "eps",
                              "ocf", "capex", "fcf")}}
    balance_src = quarterly if not quarterly.empty else annual
    balance = balance_src.iloc[-1] if not balance_src.empty else None

    market_cap = q.get("market_cap")
    if not market_cap and q.get("price"):
        shares = latest_shares_outstanding(load_facts(ticker))
        market_cap = q["price"] * shares if shares else None
    return {
        "quote": q, "market_cap": market_cap, "currency": currency, "ttm": flows,
        "balance": balance, "valuation": valuation(market_cap, flows, balance),
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
