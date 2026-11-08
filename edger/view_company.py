"""Single-company view: header, KPIs, and the 재무 / 주가·가치 / 공시 / 내부자 tabs."""
from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from . import charts, data, fmt, watchlist
from .metrics import (DERIVED_LABELS, METRIC_BY_KEY, cagr, dividend_history, historical_per, turnaround, yoy,
                      yoy_prev)
from .ui import (kpi_cards, metric_rows, load_dividends, retry_prices, load_filing_sections, load_filings, load_insiders, load_prices,
                 load_profile, load_snapshot, load_statement, load_table, plot,
                 safe_markdown_text, theme_mode)


BASES = {"연간": "annual", "TTM": "ttm", "분기": "quarterly"}
BASIS_NOTE = {"annual": "전년 대비", "ttm": "1년 전 TTM 대비", "quarterly": "전년 같은 분기 대비"}
# What each business type shows. Columns are table keys; labels override the defaults so a
# bank's "revenue" reads as net revenue. per_share columns are formatted as $ per share.
BUSINESS = {
    "general": {
        "name": "",
        "kpis": [("revenue", "매출"), ("operating_income", "영업이익"), ("net_income", "순이익"), ("eps", "EPS")],
        "pills": {"매출": "revenue", "영업이익": "operating_income", "EBITDA": "ebitda", "순이익": "net_income",
                  "EPS": "eps", "FCF": "fcf", "배당(DPS)": "dps", "주식수": "shares_diluted"},
        "margins": {"gross_margin": "매출총이익률", "ebitda_margin": "EBITDA 마진",
                    "operating_margin": "영업이익률", "net_margin": "순이익률"},
        "growth": ["revenue", "operating_income", "net_income", "eps", "fcf"],
        "summary": ["revenue", "operating_income", "net_income", "fcf"],
    },
    "bank": {
        "name": "은행",
        "kpis": [("revenue", "순영업수익"), ("net_interest_income", "순이자이익"), ("net_income", "순이익"),
                 ("eps", "EPS")],
        "pills": {"순영업수익": "revenue", "순이자이익": "net_interest_income", "비이자이익": "noninterest_income",
                  "대손비용": "provision", "순이익": "net_income", "EPS": "eps", "배당(DPS)": "dps"},
        "margins": {"efficiency_ratio": "효율성 비율(낮을수록 좋음)", "net_margin": "순이익률"},
        "growth": ["revenue", "net_interest_income", "net_income", "eps"],
        "summary": ["revenue", "net_interest_income", "provision", "net_income"],
        "note": "은행은 매출총이익·영업이익·유동비율 같은 일반 기업 지표가 맞지 않아 순이자이익, 효율성 비율"
                "(비이자비용 ÷ 순영업수익), 대손비용, 자기자본비율로 보여줍니다.",
    },
    "insurance": {
        "name": "보험",
        "kpis": [("revenue", "매출"), ("premiums", "보험료 수익"), ("net_income", "순이익"), ("eps", "EPS")],
        "pills": {"매출": "revenue", "보험료 수익": "premiums", "영업이익": "operating_income",
                  "순이익": "net_income", "EPS": "eps", "배당(DPS)": "dps"},
        "margins": {"operating_margin": "영업이익률", "net_margin": "순이익률"},
        "growth": ["revenue", "premiums", "net_income", "eps"],
        "summary": ["revenue", "premiums", "net_income"],
        "note": "보험사는 유동비율·EBITDA 같은 지표가 맞지 않아 보험료 수익과 자기자본비율 위주로 보여줍니다.",
    },
    "reit": {
        "name": "리츠",
        "kpis": [("revenue", "매출"), ("ffo", "FFO(추정)"), ("net_income", "순이익"),
                 ("ffo_per_share", "주당 FFO")],
        "pills": {"매출": "revenue", "FFO(추정)": "ffo", "주당 FFO": "ffo_per_share", "순이익": "net_income",
                  "배당(DPS)": "dps"},
        "margins": {"net_margin": "순이익률"},
        "growth": ["revenue", "ffo", "ffo_per_share", "dps"],
        "summary": ["revenue", "ffo", "net_income"],
        "note": "리츠는 감가상각이 커서 순이익보다 FFO(순이익 + 감가상각 + 손상 − 부동산 처분이익)로 봅니다. "
                "FFO는 공시 태그가 없어 이 공식으로 추정한 값이라 회사 발표치와 조금 다를 수 있습니다.",
    },
}
PER_SHARE_COLS = ("eps", "dps", "ffo_per_share")
TABS = {"📈 재무": "fin", "💹 주가·가치": "val", "💰 배당": "div", "📄 공시": "filings", "👤 내부자": "ins"}


def _label(col: str) -> str:
    return DERIVED_LABELS.get(col) or METRIC_BY_KEY[col].label


def render(ticker: str) -> None:
    with st.spinner(f"{ticker} 불러오는 중…"):
        try:
            profile = load_profile(ticker)
        except data.CompanyNotFound:
            st.error(f"'{ticker}' 에 해당하는 회사를 찾지 못했습니다. 티커를 확인해 주세요.")
            return
        except Exception as exc:
            st.error(f"SEC 데이터를 불러오지 못했습니다: {exc}")
            return
        try:
            snap = load_snapshot(ticker)
        except Exception as exc:
            snap = None
            st.warning(f"재무 데이터를 불러오지 못했습니다: {exc}")

    business = business_kind(profile)
    _header(ticker, profile, snap)
    annual = snap["annual"] if snap else pd.DataFrame()
    currency = snap["currency"] if snap else "USD"

    # One basis for the cards and the 재무 tab. It lives outside the tabs so it keeps its
    # value while another tab is open (only the open tab's widgets exist).
    basis = st.segmented_control("기준", list(BASES), default="연간", key="period",
                                 label_visibility="collapsed", help="연간: 회계연도 · TTM: 최근 4분기 합계 · 분기: 단일 분기") or "연간"
    period_key = BASES[basis]
    if period_key == "annual":
        table = annual
    else:
        try:
            table, currency = load_table(ticker, period_key, 12)
        except Exception as exc:
            table = pd.DataFrame()
            st.warning(f"{basis} 데이터를 불러오지 못했습니다: {exc}")
    kpi_table, kpi_period = table, period_key
    if table.empty and period_key != "annual" and not annual.empty:
        kpi_table, kpi_period = annual, "annual"
        st.caption(f"{basis} 데이터가 없어 카드는 연간 기준으로 보여줍니다 (아래 재무 탭 안내 참고).")
    _kpis(snap, kpi_table, kpi_period, currency, business)
    _signals(ticker, snap, kpi_table, annual, kpi_period, business)

    mode = theme_mode()
    # Stateful tabs: the open tab survives reruns, and only the open tab is rendered, so e.g.
    # the Form 4 requests behind 내부자 run only when someone actually opens it.
    labels = list(TABS)
    tabs = st.tabs(labels, key="company_tab", on_change="rerun")
    active = st.session_state.get("company_tab") or labels[0]
    for label, tab in zip(labels, tabs):
        if label != active:
            continue
        with tab:
            name = TABS[label]
            if name == "fin":
                _financials(ticker, table, annual, period_key, currency, mode, business)
            elif name == "val":
                _valuation(ticker, snap, annual, currency, mode, business)
            elif name == "div":
                _dividends(ticker, snap, annual, currency, mode)
            elif name == "filings":
                _filings(ticker)
            else:
                _insiders(ticker, mode)
    st.caption("데이터: SEC EDGAR (edgartools), 주가: Yahoo Finance. 투자 판단 전 원문 공시를 확인하세요.")


# ---------------------------------------------------------------- header & KPIs
def _header(ticker: str, profile: dict, snap: dict | None) -> None:
    """Name, price and the star on one compact block (the star sits right of the name)."""
    fye = profile.get("fiscal_year_end") or ""
    meta = [" · ".join((profile.get("tickers") or [ticker])[:2])]
    if profile.get("exchanges"):
        meta.append(profile["exchanges"][0])
    kind = BUSINESS[business_kind(profile)]["name"]
    meta.append(kind or (profile.get("industry") or ""))
    if len(fye) == 4:
        meta.append(f"{int(fye[:2])}월 결산")

    price_html = ""
    q = (snap or {}).get("quote") or {}
    if q.get("price"):
        qcur = q.get("currency") or "USD"
        chg = q.get("change")
        chg_html = ""
        if chg is not None:
            cls, arrow = ("ed-good", "▲") if chg >= 0 else ("ed-bad", "▼")
            chg_html = f'<span class="ed-hc {cls}">{arrow} {abs(chg) * 100:.2f}%</span>'
        extra = []
        if snap.get("market_cap"):
            extra.append(f"시총 {fmt.money(snap['market_cap'], qcur)}")
        per = (snap.get("valuation") or {}).get("per")
        if per:
            extra.append(f"PER {per:.1f}배")
        if q.get("source"):
            extra.append(q["source"])
        price_html = (f'<div class="ed-hprice"><span class="ed-hp">{html.escape(fmt.per_share(q["price"], qcur))}</span>'
                      f'{chg_html}</div><div class="ed-hmeta">{html.escape(" · ".join(extra))}</div>')

    with st.container(key="head"):
        left, right = st.columns([7, 1], vertical_alignment="top")
        left.markdown(
            f'<div class="ed-hname">{html.escape(profile.get("name", ticker))}</div>'
            f'<div class="ed-hmeta">{html.escape(" · ".join(m for m in meta if m))}</div>{price_html}',
            unsafe_allow_html=True)
        starred = ticker in watchlist.load()
        right.button("★" if starred else "☆", key="star", on_click=watchlist.toggle, args=(ticker,),
                     type="tertiary", help="관심종목에서 빼기" if starred else "관심종목에 추가")


def _kpis(snap: dict | None, table: pd.DataFrame, period: str, currency: str, business: str) -> None:
    items = []
    if not table.empty:
        tag = {"annual": table["label"].iloc[-1], "ttm": f"TTM {table['label'].iloc[-1]}",
               "quarterly": f"{table['label'].iloc[-1]}분기"}[period]
        note = BASIS_NOTE[period]
        for col, name in BUSINESS[business]["kpis"]:
            value, delta = yoy(table, col, period)
            shown = fmt.per_share(value, currency) if col in PER_SHARE_COLS else fmt.money(value, currency)
            items.append({"label": name, "value": shown, "delta": delta,
                          "word": turnaround(value, yoy_prev(table, col, period))})
        st.markdown(f'<div class="ed-sub" style="margin-top:0.6rem">실적 <b>{html.escape(tag)}</b> · 증감은 {note}</div>',
                    unsafe_allow_html=True)
    stale = (snap or {}).get("stale_since")
    if stale is not None:
        st.warning(f"⚠️ SEC에 있는 최신 실적이 {pd.Timestamp(stale):%Y-%m} 결산이라 오래됐습니다. "
                   "PER 등 주가 대비 지표는 지금 실적보다 과대·과소평가될 수 있습니다.")
    fx = (snap or {}).get("fx")
    if fx:
        rate = f"1 {fx['from']} = {fx['rate']:.4g} {fx['to']}로 환산" if fx["rate"] else "환율을 받지 못해 밸류에이션 생략"
        st.markdown(f'<div class="ed-sub">💱 재무제표는 {fx["from"]}, 주가는 {fx["to"]}(ADR) · '
                    f'밸류에이션은 {html.escape(rate)}</div>', unsafe_allow_html=True)
    if items:
        kpi_cards(items)


def _signals(ticker: str, snap: dict | None, table: pd.DataFrame, annual: pd.DataFrame,
             period: str, business: str) -> None:
    """Four one-line verdicts. Thresholds are rules of thumb, stated in each note, so the
    verdict can be checked rather than trusted."""
    rows = []
    v = (snap or {}).get("valuation") or {}

    # Valuation: current PER vs this company's own history (median at fiscal year ends).
    if business == "reit":
        p_ffo = v.get("p_ffo")
        if p_ffo:
            tone, word = ("good", "낮음") if p_ffo < 12 else ("warn", "높음") if p_ffo > 22 else (None, "보통")
            rows.append({"label": "밸류에이션", "value": word, "value_tone": tone,
                         "note": f"P/FFO {p_ffo:.1f}배 · 리츠는 보통 12~22배"})
    elif v.get("per"):
        per = v["per"]
        hist = pd.DataFrame()
        if not (snap or {}).get("fx") and not annual.empty:
            prices = load_prices(ticker, "10y")
            hist = historical_per(annual, prices) if not prices.empty else pd.DataFrame()
        hist_per = hist["per"].dropna() if not hist.empty else pd.Series(dtype=float)
        if len(hist_per) >= 3:
            med = float(hist_per.median())
            gap = per / med - 1
            tone, word = ("warn", "비쌈") if gap > 0.2 else ("good", "쌈") if gap < -0.2 else (None, "보통")
            rows.append({"label": "밸류에이션", "value": word, "value_tone": tone,
                         "note": f"PER {per:.1f}배 · 과거 {len(hist_per)}년 중앙값 {med:.1f}배보다 "
                                 f"{abs(gap) * 100:.0f}% {'높음' if gap >= 0 else '낮음'}"})
        else:
            rows.append({"label": "밸류에이션", "value": f"PER {per:.1f}배",
                         "note": "과거 PER 기록이 부족해 비교하지 않음"})
    elif snap and snap.get("market_cap") and ((snap.get("ttm") or {}).get("net_income") or 0) < 0:
        rows.append({"label": "밸류에이션", "value": "적자", "value_tone": "warn", "note": "순이익이 마이너스라 PER 없음"})

    # Growth: the selected basis, year over year.
    growth_col = "ffo" if business == "reit" else "revenue"
    _, g = yoy(table, growth_col, period) if not table.empty else (None, None)
    if g is not None:
        tone, word = ("good", "성장") if g >= 0.10 else ("bad", "역성장") if g < 0 else (None, "완만")
        name = "FFO" if business == "reit" else ("순영업수익" if business == "bank" else "매출")
        rows.append({"label": "성장", "value": word, "value_tone": tone,
                     "note": f"{name} {g * 100:+.1f}% ({BASIS_NOTE[period]}) · 10% 이상이면 성장"})

    # Profitability: margin direction for operating companies, ROE level for financials.
    src = annual if not annual.empty else table
    if business == "general" and not table.empty and table["operating_margin"].notna().sum() > 1:
        lag = 1 if period == "annual" else 4
        om = table["operating_margin"]
        now, prev = om.iloc[-1], om.iloc[-1 - lag] if len(om) > lag else None
        if pd.notna(now) and prev is not None and pd.notna(prev):
            d = now - prev
            tone, word = ("good", "개선") if d >= 0.01 else ("bad", "악화") if d <= -0.01 else (None, "유지")
            rows.append({"label": "수익성", "value": word, "value_tone": tone,
                         "note": f"영업이익률 {now * 100:.1f}% ({d * 100:+.1f}%p, {BASIS_NOTE[period]})"})
    elif not src.empty and src["roe"].notna().any():
        roe = float(src["roe"].dropna().iloc[-1])
        tone, word = ("good", "높음") if roe >= 0.12 else ("warn", "낮음") if roe < 0.08 else (None, "보통")
        rows.append({"label": "수익성", "value": word, "value_tone": tone,
                     "note": f"ROE {roe * 100:.1f}% · 12% 이상 높음, 8% 미만 낮음"})

    # Balance sheet, on the latest quarter / TTM like the stability section.
    try:
        q, _ = load_table(ticker, "quarterly", 12)
        t, _ = load_table(ticker, "ttm", 12)
    except Exception:
        q = t = pd.DataFrame()
    bs = q.iloc[-1] if not q.empty else (annual.iloc[-1] if not annual.empty else None)
    fl = t.iloc[-1] if not t.empty else (annual.iloc[-1] if not annual.empty else None)
    if bs is not None:
        if pd.notna(bs["equity"]) and bs["equity"] <= 0:
            rows.append({"label": "재무 안정성", "value": "자본 마이너스", "value_tone": "warn",
                         "note": "자사주 매입 등으로 자본이 음수 · 차입금 규모를 직접 확인하세요"})
        elif business in ("bank", "insurance"):
            er = bs["equity_ratio"]
            if pd.notna(er):
                rows.append({"label": "재무 안정성", "value": f"자기자본 {er * 100:.1f}%",
                             "note": "자본 ÷ 총자산 · 금융사는 업종 평균과 비교해서 봅니다"})
        elif business == "reit":
            if pd.notna(bs["debt"]) and bs["assets"]:
                lev = bs["debt"] / bs["assets"]
                tone, word = ("good", "양호") if lev < 0.40 else ("warn", "주의") if lev > 0.55 else (None, "보통")
                rows.append({"label": "재무 안정성", "value": word, "value_tone": tone,
                             "note": f"차입금/총자산 {lev * 100:.0f}% · 40% 미만 양호, 55% 초과 주의"})
        else:
            net = bs["net_debt"]
            ratio = fl.get("net_debt_ebitda") if fl is not None else None
            if pd.notna(net) and net <= 0:
                rows.append({"label": "재무 안정성", "value": "순현금", "value_tone": "good",
                             "note": f"현금이 차입금보다 {fmt.money(-net, (snap or {}).get('currency', 'USD'))} 많음"})
            elif ratio is not None and pd.notna(ratio):
                tone, word = ("good", "양호") if ratio < 1 else ("warn", "주의") if ratio > 3 else (None, "보통")
                rows.append({"label": "재무 안정성", "value": word, "value_tone": tone,
                             "note": f"순차입금/EBITDA {ratio:.1f}배 · 1배 미만 양호, 3배 초과 주의"})

    if rows:
        st.markdown("**한눈에 보기** <span class='ed-meta'>규칙 기반 참고용, 투자 판단 아님</span>",
                    unsafe_allow_html=True)
        metric_rows(rows)


# ---------------------------------------------------------------- 재무
def _financials(ticker: str, table: pd.DataFrame, annual: pd.DataFrame, period_key: str,
                currency: str, mode: str, business: str) -> None:
    if table.empty:
        if period_key != "annual" and not annual.empty:
            st.info("최근 분기 재무 데이터가 없습니다. 외국 기업(20-F 제출)은 SEC에 분기 실적을 XBRL로 내지 않거나 "
                    "반기(6-K)로만 내서, 연간 기준으로만 볼 수 있습니다. 위에서 '연간'을 선택하세요.")
        else:
            st.info("이 회사는 XBRL 재무 데이터가 없습니다 (펀드, 신규 상장사 등).")
        return
    if period_key == "ttm":
        st.caption("TTM = 각 분기 시점의 최근 4분기 합계. 계절성 없이 추세를 볼 수 있습니다.")

    cfg = BUSINESS[business]
    if cfg.get("note"):
        st.caption(f"🏷️ {cfg['name']} · {cfg['note']}")
    choices = {k: v for k, v in cfg["pills"].items() if table[v].notna().any()}
    pick = st.pills("지표", list(choices), default=next(iter(choices)), key="metric_pick",
                    label_visibility="collapsed") or next(iter(choices))
    col = choices[pick]
    unit_note = "주" if col == "shares_diluted" else currency
    st.markdown(f"**{html.escape(pick)}** <span class='ed-meta'>({unit_note})</span>", unsafe_allow_html=True)
    plot(charts.bar_series(table.dropna(subset=[col]), col, mode,
                           "" if col == "shares_diluted" else currency, per_share=(col in PER_SHARE_COLS)))
    if col == "shares_diluted":
        st.caption("가중평균 희석주식수. 줄어들면 자사주 매입, 늘어나면 주식 발행·보상 효과입니다.")

    margins = {k: v for k, v in cfg["margins"].items() if table[k].notna().any()}
    if margins:
        st.markdown("**마진**" if business != "bank" else "**효율성·이익률**")
        plot(charts.margin_lines(table, margins, mode))

    if period_key != "quarterly" and table[["roe", "roic"]].notna().any().any():
        st.markdown("**자본 수익률**")
        # ROIC needs operating income and debt in the industrial sense: not for financials.
        returns = {"roe": "ROE", "roa": "ROA"} if business != "general" else {"roe": "ROE", "roic": "ROIC", "roa": "ROA"}
        plot(charts.margin_lines(table, returns, mode))
        st.caption("ROE = 순이익 ÷ 평균 자본. ROIC = 세후 영업이익 ÷ 평균 투하자본(자본 + 차입금 − 현금), "
                   "세율은 실효세율(없으면 21%). ROA = 순이익 ÷ 평균 총자산.")

    _growth(table, period_key, cfg["growth"])

    _stability(ticker, annual, currency, business)

    if period_key == "ttm":
        st.markdown("**전체 재무제표**")
        st.caption("전체 재무제표는 공시 단위(연간·분기)로만 볼 수 있습니다. 위에서 연간 또는 분기를 선택하세요.")
    else:
        _statements(ticker, period_key, currency)

    with st.expander("요약 표로 보기"):
        view = pd.DataFrame({"기간": table["label"]})
        names = {v: k for k, v in cfg["pills"].items()}
        for c in cfg["summary"]:
            view[names.get(c, _label(c))] = [fmt.money(v, currency) for v in table[c]]
        if business == "general":
            view["영업이익률"] = [fmt.pct(v) for v in table["operating_margin"]]
        view["EPS"] = [fmt.per_share(v, currency) for v in table["eps"]]
        if period_key != "quarterly":
            view["ROE"] = [fmt.pct(v) for v in table["roe"]]
            if business == "general":
                view["ROIC"] = [fmt.pct(v) for v in table["roic"]]
        st.dataframe(view.iloc[::-1], hide_index=True, width="stretch")
    st.caption("XBRL 원천 데이터 기준. 분기 4Q와 분기 현금흐름은 누적치 차감으로 계산했습니다.")


def business_kind(profile: dict) -> str:
    """'general' | 'bank' | 'insurance' | 'reit' from edgartools' business category."""
    return {"Bank": "bank", "Insurance Company": "insurance", "REIT": "reit"}.get(
        profile.get("business") or "", "general")


def _times(x) -> str:
    return f"{x:.1f}배" if x is not None and pd.notna(x) else "–"


def _stability(ticker: str, annual: pd.DataFrame, currency: str, business: str) -> None:
    """Balance-sheet health on the latest quarter (MRQ), flow-based ratios on TTM — the
    convention most apps use — whatever basis is selected above."""
    try:
        mrq_table, _ = load_table(ticker, "quarterly", 12)
        ttm_table, _ = load_table(ticker, "ttm", 12)
    except Exception:
        mrq_table = ttm_table = pd.DataFrame()
    bs = mrq_table.iloc[-1] if not mrq_table.empty else (annual.iloc[-1] if not annual.empty else None)
    fl = ttm_table.iloc[-1] if not ttm_table.empty else (annual.iloc[-1] if not annual.empty else None)
    if bs is None:
        return
    bs_tag = f"{bs['label']} 분기말" if not mrq_table.empty else bs["label"]
    fl_tag = f"TTM {fl['label']}" if not ttm_table.empty else fl["label"]
    negative_equity = pd.notna(bs["equity"]) and bs["equity"] <= 0

    def ratio_value(v, pct=True):
        if negative_equity:
            return "자본 마이너스"
        return fmt.pct(v, 0) if pct else _times(v)

    debt_note = "–"
    if pd.notna(bs["debt"]):
        debt_note = f"장기 {fmt.money(bs['debt_long'], currency)} + 단기 {fmt.money(bs['debt_short'], currency)}"
    net = bs["net_debt"]
    rows = [{"label": "현금성자산", "value": fmt.money(bs["cash"], currency)}]
    if business != "bank":
        rows += [
            {"label": "총차입금", "value": fmt.money(bs["debt"], currency),
             "note": f"이자 붙는 빚 · {debt_note}" + (" · 리스부채 별도" if pd.notna(bs["lease"]) else "")},
            {"label": "순차입금" if not (pd.notna(net) and net < 0) else "순현금",
             "value": fmt.money(abs(net), currency) if pd.notna(net) else "–",
             "note": "총차입금 − 현금" if not (pd.notna(net) and net < 0) else "현금이 차입금보다 많음"},
        ]
    if business in ("bank", "insurance"):
        rows += [
            {"label": "자기자본비율", "value": fmt.pct(bs["equity_ratio"], 1),
             "note": "자본 ÷ 총자산. 금융사는 부채비율 대신 이 비율로 봅니다"},
        ]
        if business == "bank" and pd.notna(bs.get("deposits")):
            rows.append({"label": "예수금", "value": fmt.money(bs["deposits"], currency), "note": "고객 예금"})
    else:
        de_lease = bs["de_ratio_lease"]
        rows += [
            {"label": "부채비율", "value": ratio_value(bs["debt_ratio"]),
             "note": "총부채 ÷ 자본 (한국식, 영업부채 포함)"},
            {"label": "D/E", "value": ratio_value(bs["de_ratio"]),
             "note": "차입금 ÷ 자본 (미국 앱의 Debt/Equity)"
                     + (f" · 리스 포함 {fmt.pct(de_lease, 0)}" if pd.notna(de_lease) and not negative_equity else "")},
        ]
        if business == "reit":
            rows.append({"label": "차입금/총자산", "value": fmt.pct(bs["debt"] / bs["assets"], 0)
                         if pd.notna(bs["debt"]) and bs["assets"] else "–",
                         "note": "리츠의 레버리지 지표 (보통 30~50%)"})
        else:
            rows += [
                {"label": "유동비율", "value": fmt.pct(bs["current_ratio"], 0),
                 "note": "유동자산 ÷ 유동부채 · 100% 미만이면 1년 내 갚을 돈이 더 많음"},
                {"label": "이자보상배율", "value": _times(fl["interest_coverage"]),
                 "note": f"영업이익 ÷ 이자비용 · {fl_tag}"},
                {"label": "순차입금/EBITDA", "value": _times(fl.get("net_debt_ebitda"))
                 if pd.notna(net) and net > 0 else ("순현금" if pd.notna(net) else "–"),
                 "note": f"빚을 몇 년 치 영업현금으로 갚는지 · {fl_tag} · 3배 넘으면 부담"},
            ]
    st.markdown(f"**재무 안정성** <span class='ed-meta'>{html.escape(bs_tag)} 기준</span>",
                unsafe_allow_html=True)
    metric_rows(rows)
    if negative_equity:
        st.caption("자본이 마이너스입니다(자사주 매입·배당이 누적 이익보다 많은 경우 흔함). "
                   "부채비율·D/E는 의미가 없어 표시하지 않습니다.")


def _growth(table: pd.DataFrame, period_key: str, cols: list[str]) -> None:
    rpy = 1 if period_key == "annual" else 4  # rows per year
    first = "1년" if period_key == "annual" else "전년 동기"
    rows = []
    for col in cols:
        if table[col].isna().all():
            continue
        latest, one = yoy(table, col, period_key)
        word = turnaround(latest, yoy_prev(table, col, period_key))
        row = {"항목": _label(col), first: word or fmt.pct(one, signed=True)}
        if period_key != "quarterly":  # multi-year growth of single quarters is mostly noise
            row["3년 CAGR"] = fmt.pct(cagr(table, col, 3, rows_per_year=rpy), signed=True)
        rows.append(row)
    st.markdown("**성장률**")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("CAGR = 연평균 성장률. 시작·끝 값이 음수(적자)면 계산하지 않습니다(–).")


def _statements(ticker: str, period: str, currency: str) -> None:
    st.markdown("**전체 재무제표**")
    kinds = {"손익계산서": "income", "재무상태표": "balance", "현금흐름표": "cashflow"}
    pick = st.segmented_control("재무제표", list(kinds), default="손익계산서", key="stmt_kind",
                                label_visibility="collapsed") or "손익계산서"
    with st.spinner("재무제표 불러오는 중… (처음엔 공시 원문을 받느라 몇 초 걸립니다)"):
        try:
            res = load_statement(ticker, kinds[pick], period)
        except Exception as exc:
            res = {"table": pd.DataFrame(), "source": "", "error": str(exc)}
    df = res["table"]
    if df.empty:
        st.warning("재무제표를 불러오지 못했습니다." + (f" ({res['error']})" if res.get("error") else ""))
        return
    value_cols = [c for c in df.columns if c not in data.STATEMENT_COLUMNS]

    def cell(v, kind):
        if pd.isna(v):
            return ""
        if kind == "per_share":
            return fmt.per_share(v, currency)
        if kind == "shares":
            return fmt.number(v) + "주"
        return fmt.money(v, currency)

    rows = []
    for rec in df.to_dict("records"):  # not itertuples: period names like "25.09" get mangled
        label = ("\u2003" * max(int(rec["depth"]), 0)) + rec["label"]
        if rec["is_abstract"]:
            label = f"▸ {label}"
        rows.append({"항목": label, **{c: cell(rec[c], rec["kind"]) for c in value_cols}})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 height=min(38 + 35 * len(rows), 560),
                 column_config={"항목": st.column_config.TextColumn(width="medium")})
    st.caption(f"출처: {res['source']}. 최근 {len(value_cols)}개 기간. 표를 옆으로 밀면 다른 기간이 보입니다.")


# ---------------------------------------------------------------- 주가·가치
_RANGES = {"1년": 1, "3년": 3, "5년": 5, "10년": 10}


def _valuation(ticker: str, snap: dict | None, annual: pd.DataFrame, currency: str, mode: str,
               business: str = "general") -> None:
    prices = load_prices(ticker, "10y")
    if prices.empty:
        st.info("주가 차트를 불러오지 못했습니다 (Yahoo Finance·Stooq 모두 응답 없음, 또는 비상장·외국 종목). "
                "재무·공시 탭은 정상적으로 볼 수 있습니다.")
    else:
        rng = st.segmented_control("기간", list(_RANGES), default="1년", key="price_range",
                                   label_visibility="collapsed") or "1년"
        shown = prices[prices.index >= prices.index[-1] - pd.DateOffset(years=_RANGES[rng])]
        first, last = float(shown.iloc[0]), float(shown.iloc[-1])
        st.markdown(f"**주가** <span class='ed-meta'>{rng} {fmt.pct(last / first - 1, signed=True)}</span>",
                    unsafe_allow_html=True)
        plot(charts.price_line(shown, mode))
        year = prices[prices.index >= prices.index[-1] - pd.DateOffset(years=1)]
        hi, lo = float(year.max()), float(year.min())
        metric_rows([
            {"label": "52주 최고", "value": fmt.per_share(hi), "delta": f"현재가 {fmt.pct(last / hi - 1, 1, signed=True)}"},
            {"label": "52주 최저", "value": fmt.per_share(lo), "delta": f"현재가 {fmt.pct(last / lo - 1, 1, signed=True)}"},
        ])

    if not snap or not snap.get("market_cap"):
        _no_market_cap(snap)
        return
    v, flows = snap["valuation"], snap["ttm"] or {}
    basis = flows.get("label", "")
    stale = " · ⚠️ 오래된 실적" if snap.get("stale_since") is not None else ""
    st.markdown(f"**밸류에이션** <span class='ed-meta'>{html.escape(basis)} 기준{stale}</span>",
                unsafe_allow_html=True)

    def mult(x):
        return f"{x:.1f}배" if x is not None and pd.notna(x) else "–"

    vcur = snap["fx"]["to"] if snap.get("fx") else currency  # multiples are in the trading currency
    ev_note = f"EV(기업가치) = 시총 + 차입금 − 현금 = {fmt.money(v['ev'], vcur)}"
    rows = {
        "per": {"label": "PER", "value": mult(v["per"]), "note": "시가총액 ÷ 순이익 · 적자면 –"},
        "pbr": {"label": "PBR", "value": mult(v["pbr"]), "note": "시가총액 ÷ 자본총계"},
        "psr": {"label": "PSR", "value": mult(v["psr"]), "note": "시가총액 ÷ 매출"},
        "p_fcf": {"label": "P/FCF", "value": mult(v["p_fcf"]), "note": "시가총액 ÷ 잉여현금흐름"},
        "ev_ebitda": {"label": "EV/EBITDA", "value": mult(v["ev_ebitda"]),
                      "note": "부채 수준이 다른 회사끼리 비교할 때 유용 · " + ev_note},
        "ev_ebit": {"label": "EV/EBIT", "value": mult(v["ev_ebit"]), "note": "기업가치 ÷ 영업이익"},
        "ev_sales": {"label": "EV/매출", "value": mult(v["ev_sales"]), "note": "기업가치 ÷ 매출"},
        "peg": {"label": "PEG", "value": f"{v['peg']:.2f}" if v["peg"] else "–",
                "note": "PER ÷ EPS 3년 연평균 성장률(%) · 1 미만이면 성장 대비 싸다고 봄"},
        "p_ffo": {"label": "P/FFO", "value": mult(v["p_ffo"]),
                  "note": "리츠의 PER · 시가총액 ÷ FFO(추정)"},
        "ffo_payout": {"label": "FFO 대비 배당", "value": fmt.pct(v["ffo_payout"], 0),
                       "note": "배당금 ÷ FFO · 리츠는 100% 가까이 나눠주는 게 보통, 넘으면 주의"},
    }
    order = {
        "general": ["per", "ev_ebitda", "pbr", "psr", "p_fcf", "ev_ebit", "ev_sales", "peg"],
        "bank": ["per", "pbr", "peg"],
        "insurance": ["per", "pbr", "peg"],
        "reit": ["p_ffo", "ffo_payout", "per", "pbr", "ev_sales"],
    }[business]
    metric_rows([rows[k] for k in order])
    if business in ("bank", "insurance"):
        st.caption("금융사는 매출·현금흐름·EV 기반 지표가 의미가 없어 PER·PBR 위주로 봅니다.")

    st.markdown("**주당 지표**")
    eps_delta = fmt.pct(v["eps_growth"], 1, signed=True) + " (1년 전 대비)" if v["eps_growth"] is not None else None
    metric_rows([
        {"label": "EPS", "value": fmt.per_share(v["eps"], currency), "note": "희석 주당순이익 · 최근 4분기 합",
         "delta": eps_delta, "tone": None if v["eps_growth"] is None else ("good" if v["eps_growth"] >= 0 else "bad")},
        {"label": "BPS", "value": fmt.per_share(v["bps"], currency),
         "note": "주당순자산 = 자본 ÷ 주식수" + (" · ADR은 주식 1주와 달라 계산하지 않음" if snap.get("fx") else "")},
        {"label": "DPS", "value": fmt.per_share(v["dps"], currency), "note": "주당배당금 · 최근 4분기"},
        {"label": "주식수", "value": fmt.number(v["shares"]) + "주" if v["shares"] else "–",
         "note": "시가총액 ÷ 주가" if not snap.get("fx") else "ADR이라 계산하지 않음"},
    ])

    # Per-share history mixes ADR prices with ordinary-share EPS for foreign filers: skip.
    per = historical_per(annual, prices) if not snap.get("fx") else pd.DataFrame()
    if not per.empty and per["per"].notna().sum() >= 2:
        st.markdown("**연도별 PER** <span class='ed-meta'>회계연도 말 주가 ÷ 희석 EPS</span>",
                    unsafe_allow_html=True)
        plot(charts.per_bars(per, mode, current=v["per"]))
        hist = per["per"].dropna()
        if v["per"]:
            st.caption(f"과거 {len(hist)}년 PER 중앙값 {hist.median():.1f}배 · 현재 {v['per']:.1f}배")
    st.caption("주가는 Yahoo Finance(15분 캐시), 실적은 SEC 공시 기준이라 발표 직후엔 시차가 있을 수 있습니다.")


def _no_market_cap(snap: dict | None) -> None:
    if snap and snap["quote"].get("price"):
        reason = ("주가는 받았지만 발행주식수를 찾지 못했습니다 "
                  "(Yahoo 시총 없음, SEC 공시에 주식수·희석주식수 없음).")
    else:
        reason = ("주가를 받지 못했습니다. Yahoo Finance와 예비 출처(Stooq) 모두 응답이 없었습니다. "
                  "무료 서버는 여러 앱이 같은 IP를 써서 Yahoo가 잠시 막는 경우가 많습니다.")
    st.info(f"시가총액을 계산할 수 없어 밸류에이션 지표를 표시하지 않습니다. {reason}")
    st.button("🔄 주가 다시 불러오기", key="retry_prices", on_click=retry_prices, width="stretch")


# ---------------------------------------------------------------- 배당
def _dividends(ticker: str, snap: dict | None, annual: pd.DataFrame, currency: str, mode: str) -> None:
    # Yahoo's dividend history is in the trading currency (per ADR for foreign filers);
    # SEC figures stay in the filing currency.
    filing_currency = currency
    currency = ((snap or {}).get("quote") or {}).get("currency") or currency
    with st.spinner("배당 내역 불러오는 중…"):
        payments, ok = load_dividends(ticker)
        prices = load_prices(ticker, "10y")
    hist = dividend_history(payments, prices)
    yearly = hist["annual"]

    if not yearly.empty:
        _dividend_cards(hist, currency)
        view = st.segmented_control("배당 보기", ["연도별", "회차별"], default="연도별", key="div_view",
                                    label_visibility="collapsed") or "연도별"
        if view == "연도별":
            st.markdown("**연도별 주당배당금** <span class='ed-meta'>흐린 막대 = 올해(진행 중)</span>",
                        unsafe_allow_html=True)
            plot(charts.dividend_bars(yearly, mode, currency))
        else:
            st.markdown("**회차별 배당** <span class='ed-meta'>배당락일 기준, 최근 10년</span>",
                        unsafe_allow_html=True)
            plot(charts.dividend_payments(hist["payments"], mode, currency))
        if yearly["yield"].notna().sum() >= 2:
            st.markdown("**연도별 배당수익률** <span class='ed-meta'>연간 배당 ÷ 연말 주가, * = 최근 12개월</span>",
                        unsafe_allow_html=True)
            plot(charts.dividend_yield_line(yearly, mode))
        with st.expander("표로 보기"):
            table = pd.DataFrame({
                "연도": [f"{y}{' (진행 중)' if part else ''}" for y, part in zip(yearly.index, yearly["partial"])],
                "주당배당금": [fmt.per_share(v, currency) for v in yearly["dps"]],
                "증가율": [fmt.pct(v, signed=True) for v in yearly["growth"]],
                "횟수": yearly["count"].astype(int).values,
                "배당수익률": [fmt.pct(v, 2) for v in yearly["yield"]],
            }).iloc[::-1]
            st.dataframe(table, hide_index=True, width="stretch")
        st.caption("출처: Yahoo Finance 배당 내역 (액면분할 반영). 연도는 배당락일 기준 달력 연도입니다.")
    elif ok:
        st.info("배당 기록이 없습니다. 배당을 지급하지 않는 회사입니다 (자사주 매입으로 환원하는 경우는 아래 참고).")
    else:
        _dividends_from_sec(annual, filing_currency, mode)

    _shareholder_returns(snap)


def _dividend_cards(hist: dict, currency: str) -> None:
    yearly = hist["annual"]
    last_yield = yearly["yield"].dropna()

    def years(n):
        return f"{n}년" if n else "–"

    yld = f"수익률 {last_yield.iloc[-1] * 100:.2f}%" if len(last_yield) else None
    freq = f" · 연 {hist['per_year']}회" if hist["per_year"] else ""
    metric_rows([
        {"label": "최근 12개월 배당", "value": fmt.per_share(hist["ttm_dps"], currency), "delta": yld,
         "note": "최근 1년간 받은 주당배당금 합계 · 현재 주가 대비"},
        {"label": "최근 배당", "value": fmt.per_share(hist["last_amount"], currency),
         "delta": f"{hist['last_date']:%Y-%m-%d}", "note": f"배당락일 기준{freq}"},
        {"label": "연속 배당", "value": years(hist["paid_streak"]),
         "note": f"끊기지 않고 배당한 햇수 · 데이터 시작 {hist['first_year']}년부터 셈"},
        {"label": "연속 증액", "value": years(hist["raise_streak"]),
         "note": "1회 평균 배당금이 전년보다 늘어난 연속 햇수 · 특별배당·오류값은 제외"},
        {"label": "배당 성장률", "value": f"5년 {fmt.pct(hist['cagr5'], 1, signed=True)}",
         "delta": f"10년 {fmt.pct(hist['cagr10'], 1, signed=True)}", "note": "주당배당금 연평균 증가율"},
    ])


def _dividends_from_sec(annual: pd.DataFrame, currency: str, mode: str) -> None:
    """Yahoo failed: show the per-share dividends the company reported to the SEC."""
    st.info("Yahoo Finance에서 배당 내역을 받지 못해 SEC 공시의 주당배당금으로 대신 보여줍니다.")
    if annual.empty or annual["dps"].dropna().empty:
        st.caption("SEC 공시에도 주당배당금 항목이 없습니다.")
        st.button("🔄 다시 불러오기", key="retry_div", on_click=retry_prices, width="stretch")
        return
    st.markdown("**회계연도별 주당배당금** <span class='ed-meta'>SEC 공시 기준</span>", unsafe_allow_html=True)
    plot(charts.bar_series(annual.dropna(subset=["dps"]), "dps", mode, currency, per_share=True))
    st.button("🔄 Yahoo에서 다시 불러오기", key="retry_div", on_click=retry_prices, width="stretch")


def _shareholder_returns(snap: dict | None) -> None:
    if not snap or not snap.get("market_cap"):
        return
    v = snap["valuation"]
    st.markdown(f"**주주환원** <span class='ed-meta'>{html.escape((snap['ttm'] or {}).get('label', ''))} 기준</span>",
                unsafe_allow_html=True)
    flows = snap["ttm"] or {}
    currency = snap.get("currency", "USD")
    metric_rows([
        {"label": "배당성향", "value": fmt.pct(v["payout_ratio"], 0), "note": "배당금 지급액 ÷ 순이익 (SEC 현금흐름표)"},
        {"label": "자사주 매입액", "value": fmt.money(flows.get("buybacks"), currency),
         "note": "자사주 매입에 쓴 현금 (SEC 현금흐름표)"},
        {"label": "자사주 수익률", "value": fmt.pct(v["buyback_yield"], 2), "note": "자사주 매입액 ÷ 시가총액"},
        {"label": "총 주주수익률", "value": fmt.pct(v["shareholder_yield"], 2),
         "note": "(배당 + 자사주 매입) ÷ 시가총액 · SEC 현금 기준이라 위 배당수익률과 약간 다를 수 있음"},
    ])


# ---------------------------------------------------------------- 공시
FORM_GROUPS = {
    "정기보고서": {"10-K", "10-Q", "20-F", "40-F", "10-K/A", "10-Q/A", "20-F/A"},
    "수시공시": {"8-K", "8-K/A", "6-K"},
    "내부자": {"3", "4", "5", "4/A", "144"},
    "주총": {"DEF 14A", "DEFA14A", "PRE 14A"},
    "지분": {"SC 13G", "SC 13G/A", "SC 13D", "SC 13D/A", "SCHEDULE 13G", "SCHEDULE 13G/A",
             "SCHEDULE 13D", "SCHEDULE 13D/A"},
}


def _filings(ticker: str) -> None:
    try:
        filings = load_filings(ticker)
    except Exception as exc:
        filings = pd.DataFrame(columns=data.FILING_COLUMNS)
        st.warning(f"공시 목록을 불러오지 못했습니다: {exc}")

    _reader(ticker, filings)

    st.markdown("**공시 목록** <span class='ed-meta'>탭하면 SEC 원문</span>", unsafe_allow_html=True)
    group = st.pills("종류", ["전체", *FORM_GROUPS], default="전체", key="form_group",
                     label_visibility="collapsed") or "전체"
    shown = filings if group == "전체" else filings[filings["form"].isin(FORM_GROUPS[group])]
    limit = st.session_state.get("filings_limit", 20)
    if shown.empty:
        st.info("해당 공시가 없습니다.")
        return
    items = []
    for row in shown.head(limit).itertuples():
        items.append(
            f'<li><a href="{html.escape(row.url)}" target="_blank" rel="noopener">'
            f'<div class="ed-row"><span class="ed-title">{html.escape(row.form)}</span>'
            f'<span class="ed-meta">{row.filing_date:%Y-%m-%d}</span></div>'
            f'<div class="ed-desc">{html.escape(row.description or "") or "&nbsp;"}</div></a></li>')
    st.markdown(f'<ul class="ed-list">{"".join(items)}</ul>', unsafe_allow_html=True)
    if len(shown) > limit and st.button("더 보기", width="stretch", key="more_filings"):
        st.session_state["filings_limit"] = limit + 20
        st.rerun()


def _reader(ticker: str, filings: pd.DataFrame) -> None:
    readable = filings[filings["form"].str.replace("/A", "", regex=False).isin(data.READABLE_FORMS)].head(40)
    if readable.empty:
        return
    st.markdown("**📖 앱에서 읽기**")
    options = list(readable.index)
    pick = st.selectbox(
        "읽을 공시", options, index=None, key="reader_pick", label_visibility="collapsed",
        placeholder="10-K · 10-Q · 8-K 중 선택",
        format_func=lambda i: f"{readable.at[i, 'form']} · {readable.at[i, 'filing_date']:%Y-%m-%d}"
                              f"{' · ' + readable.at[i, 'description'] if readable.at[i, 'description'] else ''}",
    )
    if pick is None:
        return
    row = readable.loc[pick]
    with st.spinner("공시 본문을 불러오는 중… (큰 10-K는 10초 이상 걸릴 수 있습니다)"):
        try:
            sections = load_filing_sections(ticker, row["accession"], row["form"])
        except Exception as exc:
            sections = []
            st.warning(f"본문을 불러오지 못했습니다: {exc}")
    if not sections:
        st.info("앱에서 보여줄 수 있는 본문을 찾지 못했습니다.")
    for i, sec in enumerate(sections):
        with st.expander(f"{sec['title']} · {len(sec['text']):,}자", expanded=(i == 0)):
            st.markdown(safe_markdown_text(sec["text"]))
    st.link_button("SEC 원문 열기", row["url"], width="stretch")
    st.divider()


# ---------------------------------------------------------------- 내부자
CODE_LABELS = {"P": "장내매수", "S": "장내매도", "A": "주식부여", "M": "옵션행사", "F": "세금납부",
               "G": "증여", "C": "전환", "D": "회사반환", "X": "옵션행사", "J": "기타"}


def _insiders(ticker: str, mode: str) -> None:
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
        return
    market = trades[trades["code"].isin(["P", "S"])]
    buy, sell = market[market["code"] == "P"], market[market["code"] == "S"]
    metric_rows([
        {"label": "장내 매수", "value": fmt.money(buy["value"].sum()), "delta": f"{len(buy)}건",
         "note": "임원·대주주가 시장에서 산 금액 (Form 4 코드 P)"},
        {"label": "장내 매도", "value": fmt.money(sell["value"].sum()), "delta": f"{len(sell)}건",
         "note": "시장에서 판 금액 (코드 S) · 보상으로 받은 주식 매도가 많아 매수보다 흔함"},
    ])
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
        items.append(
            f'<li><a href="{html.escape(r.url)}" target="_blank" rel="noopener">'
            f'<div class="ed-row"><span class="ed-title">{html.escape(str(r.insider or ""))}</span>'
            f'<span class="ed-meta">{date_s}</span></div>'
            f'<div class="ed-row"><span class="ed-desc"><span class="ed-badge {cls}">{label}</span>'
            f'{html.escape(str(r.position or ""))}</span>'
            f'<span class="ed-meta">{html.escape(amount)} {value}</span></div></a></li>')
    st.markdown(f'<ul class="ed-list">{"".join(items)}</ul>', unsafe_allow_html=True)
