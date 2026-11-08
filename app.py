"""Edger — a mobile-first SEC EDGAR company dashboard built on edgartools."""
from __future__ import annotations

import html
import os

import pandas as pd
import streamlit as st

from edger import charts, data, fmt
from edger.metrics import DERIVED_LABELS, METRIC_BY_KEY, build_table, change

st.set_page_config(page_title="Edger", page_icon="📊", layout="centered",
                   initial_sidebar_state="collapsed")

CACHE_TTL = 60 * 60 * 6  # SEC data changes slowly; also keeps us far below the 10 req/s limit

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
[data-testid="stMetricValue"] {font-size: 1.35rem;}
[data-testid="stMetricLabel"] p {font-size: 0.8rem;}
/* Larger tap targets for tabs */
button[data-baseweb="tab"] {padding: 0.6rem 0.9rem; font-size: 0.95rem;}
.ed-sub {color: var(--ed-muted, #8a8984); font-size: 0.85rem; margin: 0.1rem 0 0.6rem;}
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
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------- caching wrappers
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
def load_filings(ticker: str) -> pd.DataFrame:
    return data.fetch_filings(ticker)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_insiders(ticker: str, n: int) -> pd.DataFrame:
    return data.fetch_insider_trades(ticker, n)


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


def set_ticker(value: str) -> None:
    value = (value or "").strip().upper()
    if not value:
        return
    st.query_params["t"] = value
    recent = [t for t in st.session_state.get("recent", []) if t != value]
    st.session_state["recent"] = [value, *recent][:6]


def on_ticker_input() -> None:
    set_ticker(st.session_state.get("ticker_input", ""))


def on_recent_pick() -> None:
    pick = st.session_state.get("recent_pick")
    if pick:
        st.session_state["ticker_input"] = pick
        set_ticker(pick)
    st.session_state["recent_pick"] = None


def plot(fig) -> None:
    st.plotly_chart(fig, theme=None, config=charts.PLOTLY_CONFIG, width="stretch")


def kpi(col, label: str, value: str, delta: float | None, *, pp: bool = False, help: str | None = None):
    if delta is None:
        d = None
    else:
        d = f"{delta * 100:+.1f}%p" if pp else f"{delta * 100:+.1f}%"
    col.metric(label, value, d, border=True, help=help)


# ---------------------------------------------------------------- header & search
st.title("📊 Edger")
st.markdown('<div class="ed-sub">SEC EDGAR 공시 · 재무 · 내부자 거래</div>',
            unsafe_allow_html=True)

ticker = (st.query_params.get("t") or "").upper()
if "ticker_input" not in st.session_state:
    st.session_state["ticker_input"] = ticker
st.text_input("티커", key="ticker_input", on_change=on_ticker_input,
              placeholder="티커 입력 (예: AAPL, NVDA) 후 엔터", label_visibility="collapsed")
if st.session_state.get("recent"):
    st.pills("최근 본 종목", st.session_state["recent"], key="recent_pick", on_change=on_recent_pick,
             label_visibility="collapsed")

if not ticker:
    st.info("티커를 입력하세요. 네트워크 없이 둘러보려면 **DEMO** 를 입력하면 예시 데이터를 볼 수 있습니다.")
    st.stop()

identity = resolve_identity()
if not identity and not data.is_demo(ticker):
    st.warning("SEC는 모든 요청에 이름과 이메일(User-Agent)을 요구합니다. 한 번만 입력하면 됩니다.")
    with st.form("identity_form"):
        value = st.text_input("이름 이메일", placeholder="Hong Gildong hong@example.com")
        if st.form_submit_button("저장", width="stretch") and value.strip():
            st.session_state["identity"] = value.strip()
            st.rerun()
    st.caption("배포할 때는 `.streamlit/secrets.toml` 의 `EDGAR_IDENTITY` 에 넣어두면 이 단계가 생략됩니다.")
    st.stop()
if identity:
    data.configure_identity(identity)

with st.spinner(f"{ticker} 불러오는 중…"):
    try:
        profile = load_profile(ticker)
    except data.CompanyNotFound:
        st.error(f"'{ticker}' 에 해당하는 회사를 찾지 못했습니다. 티커를 확인해 주세요.")
        st.stop()
    except Exception as exc:
        st.error(f"SEC 데이터를 불러오지 못했습니다: {exc}")
        st.stop()

# ---------------------------------------------------------------- company header
meta = [" · ".join(profile.get("tickers") or [ticker])]
if profile.get("exchanges"):
    meta.append(", ".join(profile["exchanges"]))
if profile.get("industry"):
    meta.append(profile["industry"])
fye = profile.get("fiscal_year_end") or ""
if len(fye) == 4:
    meta.append(f"회계연도 말 {int(fye[:2])}/{int(fye[2:])}")
st.subheader(profile.get("name", ticker))
st.markdown(f'<div class="ed-sub">{html.escape(" · ".join(meta))}</div>', unsafe_allow_html=True)

try:
    annual, currency = load_table(ticker, "annual", 10)
except Exception as exc:
    annual, currency = pd.DataFrame(), "USD"
    st.warning(f"재무 데이터를 불러오지 못했습니다: {exc}")

if not annual.empty:
    last_label = annual["label"].iloc[-1]
    rev, rev_d = change(annual, "revenue")
    ni, ni_d = change(annual, "net_income")
    om = annual["operating_margin"].dropna()
    fcf, fcf_d = change(annual, "fcf")
    with st.container(key="kpis"):
        c1, c2 = st.columns(2)
        kpi(c1, f"매출 · {last_label}", fmt.money(rev, currency), rev_d, help="전년 대비 증감률")
        kpi(c2, f"순이익 · {last_label}", fmt.money(ni, currency), ni_d, help="전년 대비 증감률")
        c3, c4 = st.columns(2)
        kpi(c3, "영업이익률", fmt.pct(om.iloc[-1]) if len(om) else "–",
            (om.iloc[-1] - om.iloc[-2]) if len(om) > 1 else None, pp=True, help="전년 대비 %p 변화")
        kpi(c4, "잉여현금흐름", fmt.money(fcf, currency), fcf_d, help="영업현금흐름 − 설비투자, 전년 대비")

tab_fin, tab_filings, tab_insider = st.tabs(["📈 재무", "📄 공시", "👤 내부자"])
mode = theme_mode()

# ---------------------------------------------------------------- financials
with tab_fin:
    period = st.segmented_control("기간", ["연간", "분기"], default="연간", key="period",
                                  label_visibility="collapsed") or "연간"
    period_key = "annual" if period == "연간" else "quarterly"
    try:
        table, currency = (annual, currency) if period_key == "annual" else load_table(ticker, "quarterly", 12)
    except Exception as exc:
        table = pd.DataFrame()
        st.warning(f"분기 데이터를 불러오지 못했습니다: {exc}")

    if table.empty:
        st.info("이 회사는 XBRL 재무 데이터가 없습니다 (펀드, 신규 상장사, 일부 외국 기업 등).")
    else:
        choices = {"매출": "revenue", "영업이익": "operating_income", "순이익": "net_income",
                   "FCF": "fcf", "EPS": "eps"}
        choices = {k: v for k, v in choices.items() if table[v].notna().any()}
        pick = st.pills("지표", list(choices), default=next(iter(choices)), key="metric_pick",
                        label_visibility="collapsed") or next(iter(choices))
        col = choices[pick]
        title = DERIVED_LABELS.get(col) or METRIC_BY_KEY[col].label
        st.markdown(f"**{title}** <span class='ed-meta'>({currency})</span>", unsafe_allow_html=True)
        plot(charts.bar_series(table.dropna(subset=[col]), col, mode, currency, per_share=(col == "eps")))

        st.markdown("**수익성**")
        plot(charts.margin_lines(table, {"gross_margin": "매출총이익률", "operating_margin": "영업이익률",
                                         "net_margin": "순이익률"}, mode))

        latest = table.iloc[-1]
        st.markdown(f"**재무상태** <span class='ed-meta'>{latest['label']} 기준</span>", unsafe_allow_html=True)
        with st.container(key="kpis_bs"):
            b1, b2 = st.columns(2)
            b1.metric("현금성자산", fmt.money(latest["cash"], currency), border=True)
            b2.metric("부채비율", fmt.pct(latest["debt_ratio"], 0), border=True, help="총부채 ÷ 자본총계")

        with st.expander("표로 보기"):
            money_cols = ["revenue", "operating_income", "net_income", "fcf"]
            view = pd.DataFrame({"기간": table["label"]})
            for c in money_cols:
                view[DERIVED_LABELS.get(c) or METRIC_BY_KEY[c].label] = [fmt.money(v, currency) for v in table[c]]
            view["영업이익률"] = [fmt.pct(v) for v in table["operating_margin"]]
            view["EPS"] = [fmt.per_share(v, currency) for v in table["eps"]]
            st.dataframe(view.iloc[::-1], hide_index=True, width="stretch")
        st.caption("XBRL 원천 데이터 기준. 분기 4Q와 분기 현금흐름은 누적치 차감으로 계산했습니다.")

# ---------------------------------------------------------------- filings
FORM_GROUPS = {
    "정기보고서": {"10-K", "10-Q", "20-F", "40-F", "10-K/A", "10-Q/A", "20-F/A"},
    "수시공시": {"8-K", "8-K/A", "6-K"},
    "내부자": {"3", "4", "5", "4/A", "144"},
    "주총": {"DEF 14A", "DEFA14A", "PRE 14A"},
    "지분": {"SC 13G", "SC 13G/A", "SC 13D", "SC 13D/A", "SCHEDULE 13G", "SCHEDULE 13G/A",
             "SCHEDULE 13D", "SCHEDULE 13D/A"},
}

with tab_filings:
    try:
        filings = load_filings(ticker)
    except Exception as exc:
        filings = pd.DataFrame(columns=data.FILING_COLUMNS)
        st.warning(f"공시 목록을 불러오지 못했습니다: {exc}")
    groups = st.pills("종류", ["전체", *FORM_GROUPS], default="전체", key="form_group",
                      label_visibility="collapsed") or "전체"
    shown = filings if groups == "전체" else filings[filings["form"].isin(FORM_GROUPS[groups])]
    limit = st.session_state.get("filings_limit", 20)
    if shown.empty:
        st.info("해당 공시가 없습니다.")
    else:
        items = []
        for row in shown.head(limit).itertuples():
            desc = row.description or ""
            items.append(
                f'<li><a href="{html.escape(row.url)}" target="_blank" rel="noopener">'
                f'<div class="ed-row"><span class="ed-title">{html.escape(row.form)}</span>'
                f'<span class="ed-meta">{row.filing_date:%Y-%m-%d}</span></div>'
                f'<div class="ed-desc">{html.escape(desc) or "&nbsp;"}</div></a></li>')
        st.markdown(f'<ul class="ed-list">{"".join(items)}</ul>', unsafe_allow_html=True)
        if len(shown) > limit and st.button("더 보기", width="stretch", key="more_filings"):
            st.session_state["filings_limit"] = limit + 20
            st.rerun()

# ---------------------------------------------------------------- insiders
CODE_LABELS = {"P": "장내매수", "S": "장내매도", "A": "주식부여", "M": "옵션행사", "F": "세금납부",
               "G": "증여", "C": "전환", "D": "회사반환", "X": "옵션행사", "J": "기타"}

with tab_insider:
    n = st.segmented_control("최근 Form 4 개수", [20, 40, 80], default=20, key="n_form4",
                             format_func=lambda v: f"최근 {v}건") or 20
    with st.spinner("Form 4 불러오는 중… (건당 1회 SEC 요청)"):
        try:
            trades = load_insiders(ticker, n)
        except Exception as exc:
            trades = pd.DataFrame(columns=data.INSIDER_COLUMNS)
            st.warning(f"내부자 거래를 불러오지 못했습니다: {exc}")

    if trades.empty:
        st.info("최근 내부자 거래 보고(Form 4)가 없습니다.")
    else:
        market = trades[trades["code"].isin(["P", "S"])]
        buy, sell = market[market["code"] == "P"], market[market["code"] == "S"]
        with st.container(key="kpis_ins"):
            i1, i2 = st.columns(2)
            i1.metric("장내 매수", fmt.money(buy["value"].sum()), f"{len(buy)}건", delta_color="off", delta_arrow="off", border=True)
            i2.metric("장내 매도", fmt.money(sell["value"].sum()), f"{len(sell)}건", delta_color="off", delta_arrow="off", border=True)
        if not market.empty:
            st.markdown("**월별 장내 매매**")
            plot(charts.insider_monthly(market, mode))

        only_market = st.toggle("장내 매매(P/S)만 보기", value=False)
        rows = market if only_market else trades
        items = []
        for r in rows.head(40).itertuples():
            cls = "ed-buy" if r.code == "P" else "ed-sell" if r.code == "S" else "ed-other"
            label = CODE_LABELS.get(r.code, r.type or r.code)
            amount = fmt.number(r.shares, 1) + "주"
            if pd.notna(r.price) and r.price:
                amount += f" @ ${r.price:,.2f}"
            value = fmt.money(r.value) if pd.notna(r.value) else ""
            date_s = f"{r.date:%Y-%m-%d}" if pd.notna(r.date) else ""
            who = html.escape(str(r.insider or ""))
            pos = html.escape(str(r.position or ""))
            items.append(
                f'<li><a href="{html.escape(r.url)}" target="_blank" rel="noopener">'
                f'<div class="ed-row"><span class="ed-title">{who}</span><span class="ed-meta">{date_s}</span></div>'
                f'<div class="ed-row"><span class="ed-desc"><span class="ed-badge {cls}">{label}</span>{pos}</span>'
                f'<span class="ed-meta">{html.escape(amount)} {value}</span></div></a></li>')
        st.markdown(f'<ul class="ed-list">{"".join(items)}</ul>', unsafe_allow_html=True)

st.caption("데이터: SEC EDGAR (edgartools). 투자 판단의 근거로 쓰기 전에 원문 공시를 확인하세요.")
