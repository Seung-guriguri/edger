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
.block-container {padding-top: 3.2rem; padding-bottom: 3rem; padding-left: 1rem; padding-right: 1rem; max-width: 760px;}
header[data-testid="stHeader"] {height: 0; background: transparent;}
h1 {font-size: 1.5rem !important; margin-bottom: 0 !important;}
h3 {font-size: 1.2rem !important; padding-bottom: 0 !important;}
[data-testid="stMetric"] {padding: 0.55rem 0.7rem;}
[data-testid="stMetricValue"] {font-size: 1.2rem;}
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
.ed-app {font-size: 1.05rem; margin-bottom: 0.4rem;}
/* company header */
.ed-hname {font-size: 1.2rem; font-weight: 700; line-height: 1.25;}
.ed-hmeta {color: #8a8984; font-size: 0.8rem; margin-top: 0.1rem;}
.ed-hprice {margin-top: 0.35rem; display: flex; align-items: baseline; gap: 0.5rem;}
.ed-hp {font-size: 1.6rem; font-weight: 700; font-variant-numeric: tabular-nums;}
.ed-hc {font-size: 0.95rem; font-weight: 600;}
.st-key-head [data-testid="stHorizontalBlock"] {flex-wrap: nowrap !important; gap: 0.25rem;}
.st-key-head [data-testid="stColumn"] {min-width: 0 !important;}
.st-key-head button {font-size: 1.5rem; padding: 0 0.25rem; min-height: 2.2rem;}
/* compact KPI grid (2 x n) */
.ed-kgrid {display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; margin: 0.3rem 0 0.9rem;}
.ed-k {border: 1px solid rgba(128,128,128,0.25); border-radius: 0.6rem; padding: 0.5rem 0.7rem;}
.ed-kl {color: #8a8984; font-size: 0.78rem;}
.ed-kv {font-size: 1.2rem; font-weight: 700; font-variant-numeric: tabular-nums; line-height: 1.3;}
.ed-kd {font-size: 0.78rem; font-weight: 600;}
/* metric list: label (+ small definition) on the left, value on the right */
.ed-rows {margin: 0.2rem 0 0.8rem;}
.ed-r {display: flex; justify-content: space-between; align-items: center; gap: 0.75rem;
       padding: 0.55rem 0.1rem; border-bottom: 1px solid rgba(128,128,128,0.16);}
.ed-r:last-child {border-bottom: none;}
.ed-rl {font-size: 0.92rem;}
.ed-rn {color: #8a8984; font-size: 0.75rem; margin-top: 0.1rem; line-height: 1.3;}
.ed-rv {font-size: 1rem; font-weight: 600; text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums;}
.ed-rd {font-size: 0.75rem; font-weight: 500; display: block;}
.ed-good {color: #0ca30c;} .ed-bad {color: #d03b3b;} .ed-warn {color: #c98500;}
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
    if period == "annual":
        return build_table(load_facts(ticker), period, n)
    return data.period_table(ticker, period, n)  # may fall back to Yahoo for foreign filers


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
def load_business(ticker: str) -> dict:
    return data.fetch_business(ticker)


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


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _cached_dividends(ticker: str) -> pd.Series:
    series, ok = market.dividends(ticker)
    if not ok:
        raise _NoPrice(ticker)
    return series


def load_dividends(ticker: str) -> tuple[pd.Series, bool]:
    """(per-payment dividends, ok). ok=False means the source failed (not cached)."""
    key = f"div:{ticker}"
    if _recently_failed(key):
        return pd.Series(dtype=float, name="dividend"), False
    try:
        return _cached_dividends(ticker), True
    except _NoPrice:
        _mark_failed(key)
        return pd.Series(dtype=float, name="dividend"), False


@st.cache_data(ttl=PRICE_TTL, show_spinner=False)
def _cached_fx(frm: str, to: str) -> float:
    rate = market.fx_rate(frm, to)
    if not rate:
        raise _NoPrice(f"{frm}{to}")
    return rate


def load_fx(frm: str, to: str) -> float | None:
    key = f"fx:{frm}{to}"
    if _recently_failed(key):
        return None
    try:
        return _cached_fx(frm, to)
    except _NoPrice:
        _mark_failed(key)
        return None


# Money amounts that must be converted when the filing currency differs from the trading
# currency. Per-share figures are not: an ADR is not one ordinary share.
_PER_SHARE_FLOWS = {"eps", "dps", "ffo_per_share"}


def _converted(values: dict | pd.Series | None, rate: float, keys) -> dict | None:
    if values is None:
        return None
    out = dict(values)
    for k in keys:
        v = out.get(k)
        if v is not None and not (isinstance(v, float) and pd.isna(v)):
            out[k] = v * rate
    return out


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
    if flows and quarterly.attrs.get("source") == "Yahoo":
        flows["label"] += " · Yahoo"
    if flows is None and not annual.empty:  # fall back to the latest fiscal years
        def fy(row_idx):
            last = annual.iloc[row_idx]
            return {"label": last["label"], "end": annual.index[row_idx],
                    **{k: (None if pd.isna(last.get(k)) else float(last.get(k))) for k in TTM_FLOWS}}
        flows = fy(-1)
        prev_flows = fy(-2) if len(annual) > 1 else None
    balance_src = quarterly if not quarterly.empty else annual
    balance = balance_src.iloc[-1] if not balance_src.empty else None

    quote_currency = q.get("currency") or "USD"
    fx = None
    if q.get("price") and quote_currency != currency:
        # Foreign filer / ADR (e.g. TSM reports in TWD, trades in USD). Only Yahoo's market cap
        # is trustworthy here: SEC share counts are ordinary shares, the price is per ADR.
        market_cap = q.get("market_cap")
        cap_source = "Yahoo Finance 시가총액" if market_cap else None
        rate = load_fx(currency, quote_currency)
        fx = {"from": currency, "to": quote_currency, "rate": rate}
        if rate and market_cap:
            money = [k for k in TTM_FLOWS if k not in _PER_SHARE_FLOWS]
            val = valuation(market_cap, _converted(flows, rate, money), _converted(balance, rate,
                            ["equity", "debt", "cash"]), price=None,
                            prev_flows=_converted(prev_flows, rate, money), eps_cagr=cagr(annual, "eps", 3))
        else:
            val = valuation(None, None, None)
    else:
        market_cap, cap_source = market_cap_estimate(ticker, q, quarterly, annual)
        val = valuation(market_cap, flows, balance, price=q.get("price"), prev_flows=prev_flows,
                        eps_cagr=cagr(annual, "eps", 3))
    return {
        "quote": q, "market_cap": market_cap, "cap_source": cap_source, "currency": currency, "ttm": flows,
        "fx": fx,
        # Earnings older than ~15 months make price-based multiples misleading (e.g. a foreign
        # filer whose latest XBRL annual report is two years old).
        "stale_since": (flows or {}).get("end") if flows and flows.get("end") is not None
        and (pd.Timestamp.today() - pd.Timestamp(flows["end"])).days > 450 else None,
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


def kpi_cards(items: list[dict]) -> None:
    """Compact 2-column cards: {label, value, delta (fraction or None), pp (bool)}.

    The change is written out with an arrow and sign, so colour is never the only cue.
    """
    import html as _html

    cells = []
    for it in items:
        d = it.get("delta")
        word = it.get("word")
        if word:
            cls = "ed-good" if word in ("흑자전환", "적자축소") else "ed-bad"
            delta = f'<div class="ed-kd {cls}">{_html.escape(word)}</div>'
        elif d is None or pd.isna(d):
            delta = '<div class="ed-kd ed-rn">–</div>'

        else:
            cls, arrow = ("ed-good", "▲") if d >= 0 else ("ed-bad", "▼")
            unit = "%p" if it.get("pp") else "%"
            delta = f'<div class="ed-kd {cls}">{arrow} {abs(d) * 100:.1f}{unit}</div>'
        cells.append(f'<div class="ed-k"><div class="ed-kl">{_html.escape(it["label"])}</div>'
                     f'<div class="ed-kv">{_html.escape(it["value"])}</div>{delta}</div>')
    st.markdown(f'<div class="ed-kgrid">{"".join(cells)}</div>', unsafe_allow_html=True)


def metric_rows(rows: list[dict]) -> None:
    """Compact metric list for phones. Each row: label, value, and optional note (definition,
    basis), delta (text under the value) and tone ('good' | 'bad' | 'warn') for the delta.

    Tone always comes with words in the delta, never colour alone.
    """
    import html as _html

    out = []
    for r in rows:
        note = f'<div class="ed-rn">{_html.escape(r["note"])}</div>' if r.get("note") else ""
        tone = {"good": "ed-good", "bad": "ed-bad", "warn": "ed-warn"}.get(r.get("tone"), "ed-rn")
        delta = f'<span class="ed-rd {tone}">{_html.escape(r["delta"])}</span>' if r.get("delta") else ""
        vtone = {"good": " ed-good", "bad": " ed-bad", "warn": " ed-warn"}.get(r.get("value_tone"), "")
        out.append(f'<div class="ed-r"><div><div class="ed-rl">{_html.escape(r["label"])}</div>{note}</div>'
                   f'<div class="ed-rv{vtone}">{_html.escape(str(r["value"]))}{delta}</div></div>')
    st.markdown(f'<div class="ed-rows">{"".join(out)}</div>', unsafe_allow_html=True)


def safe_markdown_text(text: str) -> str:
    """Filing text rendered as Markdown: escape '$' (LaTeX) and keep paragraphs."""
    text = text.replace("$", "\\$")
    return re.sub(r"\n{3,}", "\n\n", text)
