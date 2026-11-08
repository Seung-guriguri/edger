"""Single-company view: header, KPIs, and the 재무 / 주가·가치 / 공시 / 내부자 tabs."""
from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from . import charts, data, fmt, watchlist
from .metrics import DERIVED_LABELS, METRIC_BY_KEY, cagr, change, historical_per
from .ui import (kpi_grid, load_filing_sections, load_filings, load_insiders, load_prices,
                 load_profile, load_snapshot, load_statement, load_table, plot,
                 safe_markdown_text, theme_mode)


TABS = {"📈 재무": "fin", "💹 주가·가치": "val", "📄 공시": "filings", "👤 내부자": "ins"}


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

    _header(ticker, profile)
    annual = snap["annual"] if snap else pd.DataFrame()
    currency = snap["currency"] if snap else "USD"
    _kpis(snap, annual, currency)

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
                _financials(ticker, annual, currency, mode)
            elif name == "val":
                _valuation(ticker, snap, annual, currency, mode)
            elif name == "filings":
                _filings(ticker)
            else:
                _insiders(ticker, mode)
    st.caption("데이터: SEC EDGAR (edgartools), 주가: Yahoo Finance. 투자 판단 전 원문 공시를 확인하세요.")


# ---------------------------------------------------------------- header & KPIs
def _header(ticker: str, profile: dict) -> None:
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
    starred = ticker in watchlist.load()
    st.button("★ 관심종목에서 빼기" if starred else "☆ 관심종목에 추가", key="star",
              on_click=watchlist.toggle, args=(ticker,), type="secondary")


def _kpis(snap: dict | None, annual: pd.DataFrame, currency: str) -> None:
    items = []
    if snap:
        q = snap["quote"]
        if q.get("price"):
            items.append(("주가", fmt.per_share(q["price"], q.get("currency", "USD")), q.get("change"),
                          {"help": "전일 대비"}))
        if snap.get("market_cap"):
            per = snap["valuation"].get("per")
            items.append(("시가총액", fmt.money(snap["market_cap"], q.get("currency", "USD")),
                          f"PER {per:.1f}배" if per else None, {"neutral": True}))
    if not annual.empty:
        last_label = annual["label"].iloc[-1]
        rev, rev_d = change(annual, "revenue")
        ni, ni_d = change(annual, "net_income")
        om = annual["operating_margin"].dropna()
        items += [
            (f"매출 · {last_label}", fmt.money(rev, currency), rev_d, {"help": "전년 대비 증감률"}),
            (f"순이익 · {last_label}", fmt.money(ni, currency), ni_d, {"help": "전년 대비 증감률"}),
            ("영업이익률", fmt.pct(om.iloc[-1]) if len(om) else "–",
             (om.iloc[-1] - om.iloc[-2]) if len(om) > 1 else None, {"pp": True, "help": "전년 대비 %p 변화"}),
        ]
        roe = annual["roe"].dropna()
        items.append(("ROE", fmt.pct(roe.iloc[-1]) if len(roe) else "–",
                      (roe.iloc[-1] - roe.iloc[-2]) if len(roe) > 1 else None,
                      {"pp": True, "help": "순이익 ÷ 평균 자본, 전년 대비 %p"}))
    if items:
        kpi_grid(items, "top")


# ---------------------------------------------------------------- 재무
def _financials(ticker: str, annual: pd.DataFrame, currency: str, mode: str) -> None:
    period = st.segmented_control("기간", ["연간", "분기"], default="연간", key="period",
                                  label_visibility="collapsed") or "연간"
    if period == "연간":
        table = annual
    else:
        try:
            table, currency = load_table(ticker, "quarterly", 12)
        except Exception as exc:
            table = pd.DataFrame()
            st.warning(f"분기 데이터를 불러오지 못했습니다: {exc}")
    if table.empty:
        st.info("이 회사는 XBRL 재무 데이터가 없습니다 (펀드, 신규 상장사, 일부 외국 기업 등).")
        return

    choices = {"매출": "revenue", "영업이익": "operating_income", "순이익": "net_income",
               "FCF": "fcf", "EPS": "eps", "주식수": "shares_diluted"}
    choices = {k: v for k, v in choices.items() if table[v].notna().any()}
    pick = st.pills("지표", list(choices), default=next(iter(choices)), key="metric_pick",
                    label_visibility="collapsed") or next(iter(choices))
    col = choices[pick]
    unit_note = "주" if col == "shares_diluted" else currency
    st.markdown(f"**{_label(col)}** <span class='ed-meta'>({unit_note})</span>", unsafe_allow_html=True)
    plot(charts.bar_series(table.dropna(subset=[col]), col, mode,
                           "" if col == "shares_diluted" else currency, per_share=(col == "eps")))
    if col == "shares_diluted":
        st.caption("가중평균 희석주식수. 줄어들면 자사주 매입, 늘어나면 주식 발행·보상 효과입니다.")

    st.markdown("**마진**")
    plot(charts.margin_lines(table, {"gross_margin": "매출총이익률", "operating_margin": "영업이익률",
                                     "net_margin": "순이익률"}, mode))

    if period == "연간" and table[["roe", "roic"]].notna().any().any():
        st.markdown("**자본 수익률**")
        plot(charts.margin_lines(table, {"roe": "ROE", "roic": "ROIC"}, mode))
        st.caption("ROE = 순이익 ÷ 평균 자본. ROIC = 세후 영업이익 ÷ 평균 투하자본(자본 + 차입금 − 현금), "
                   "세율은 실효세율(없으면 21%).")

    if period == "연간":
        _growth(table)

    latest = table.iloc[-1]
    st.markdown(f"**재무상태** <span class='ed-meta'>{latest['label']} 기준</span>", unsafe_allow_html=True)
    kpi_grid([
        ("현금성자산", fmt.money(latest["cash"], currency)),
        ("총차입금", fmt.money(latest["debt"], currency), None, {"help": "단기 + 장기 차입금(사채 포함)"}),
        ("순차입금", fmt.money(latest["net_debt"], currency), None,
         {"help": "총차입금 − 현금. 음수면 순현금 상태"}),
        ("부채비율", fmt.pct(latest["debt_ratio"], 0), None, {"help": "총부채 ÷ 자본총계"}),
    ], "bs")

    _statements(ticker, "annual" if period == "연간" else "quarterly", currency)

    with st.expander("요약 표로 보기"):
        view = pd.DataFrame({"기간": table["label"]})
        for c in ("revenue", "operating_income", "net_income", "fcf"):
            view[_label(c)] = [fmt.money(v, currency) for v in table[c]]
        view["영업이익률"] = [fmt.pct(v) for v in table["operating_margin"]]
        view["EPS"] = [fmt.per_share(v, currency) for v in table["eps"]]
        if period == "연간":
            view["ROE"] = [fmt.pct(v) for v in table["roe"]]
            view["ROIC"] = [fmt.pct(v) for v in table["roic"]]
        st.dataframe(view.iloc[::-1], hide_index=True, width="stretch")
    st.caption("XBRL 원천 데이터 기준. 분기 4Q와 분기 현금흐름은 누적치 차감으로 계산했습니다.")


def _growth(annual: pd.DataFrame) -> None:
    rows = []
    for col in ("revenue", "operating_income", "net_income", "eps", "fcf"):
        _, yoy = change(annual, col)
        rows.append({"항목": _label(col), "1년": fmt.pct(yoy, signed=True),
                     "3년 CAGR": fmt.pct(cagr(annual, col, 3), signed=True),
                     "5년 CAGR": fmt.pct(cagr(annual, col, 5), signed=True)})
    st.markdown("**성장률**")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("CAGR = 연평균 성장률. 시작·끝 값이 음수(적자)면 계산하지 않습니다(–).")


def _statements(ticker: str, period: str, currency: str) -> None:
    st.markdown("**전체 재무제표**")
    kinds = {"손익계산서": "income", "재무상태표": "balance", "현금흐름표": "cashflow"}
    pick = st.segmented_control("재무제표", list(kinds), default="손익계산서", key="stmt_kind",
                                label_visibility="collapsed") or "손익계산서"
    try:
        df = load_statement(ticker, kinds[pick], period)
    except Exception as exc:
        df = pd.DataFrame()
        st.caption(f"재무제표를 만들지 못했습니다: {exc}")
    if df.empty:
        st.caption("이 기간의 재무제표를 만들 수 없습니다. 다른 기간(연간/분기)을 선택해 보세요.")
        return
    value_cols = [c for c in df.columns if c not in ("label", "depth", "is_abstract", "is_total")][:3]
    rows = []
    for r in df.itertuples(index=False):
        rec = r._asdict()
        depth = int(rec.get("depth") or 0)
        label = (" " * depth) + str(rec.get("label", ""))
        if rec.get("is_abstract"):
            if all(pd.isna(rec.get(c)) for c in value_cols):
                rows.append({"항목": label, **{c: "" for c in value_cols}})
            continue
        is_eps = "pershare" in str(rec.get("label", "")).replace(" ", "").lower() or \
            "earningspershare" in str(rec.get("label", "")).replace(" ", "").lower()
        rows.append({"항목": label, **{c: (fmt.per_share(rec.get(c), currency) if is_eps
                                          else fmt.money(rec.get(c), currency)) for c in value_cols}})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 height=min(38 + 35 * len(rows), 520))
    st.caption("edgartools가 XBRL 데이터로 재구성한 표입니다. 최근 3개 기간을 보여줍니다.")


# ---------------------------------------------------------------- 주가·가치
_RANGES = {"1년": 1, "3년": 3, "5년": 5, "10년": 10}


def _valuation(ticker: str, snap: dict | None, annual: pd.DataFrame, currency: str, mode: str) -> None:
    prices = load_prices(ticker, "10y")
    if prices.empty:
        st.info("주가 데이터를 불러오지 못했습니다 (Yahoo Finance 일시 오류이거나 비상장·외국 종목). "
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
        kpi_grid([
            ("52주 최고", fmt.per_share(hi), last / hi - 1, {"help": "현재가의 52주 최고가 대비"}),
            ("52주 최저", fmt.per_share(lo), last / lo - 1, {"help": "현재가의 52주 최저가 대비"}),
        ], "range")

    if not snap or not snap.get("market_cap"):
        st.info("시가총액을 계산할 수 없어 밸류에이션 지표를 표시하지 않습니다.")
        return
    v, flows = snap["valuation"], snap["ttm"] or {}
    basis = flows.get("label", "")
    st.markdown(f"**밸류에이션** <span class='ed-meta'>{html.escape(basis)} 기준</span>",
                unsafe_allow_html=True)

    def mult(x):
        return f"{x:.1f}배" if x is not None else "–"

    kpi_grid([
        ("PER", mult(v["per"]), None, {"help": "시가총액 ÷ 최근 4분기 순이익 (적자면 –)"}),
        ("PSR", mult(v["psr"]), None, {"help": "시가총액 ÷ 최근 4분기 매출"}),
        ("PBR", mult(v["pbr"]), None, {"help": "시가총액 ÷ 최근 자본총계"}),
        ("EV/EBIT", mult(v["ev_ebit"]), None, {"help": "기업가치(시총 + 차입금 − 현금) ÷ 최근 4분기 영업이익"}),
        ("FCF 수익률", fmt.pct(v["fcf_yield"]), None, {"help": "최근 4분기 잉여현금흐름 ÷ 시가총액"}),
        ("기업가치(EV)", fmt.money(v["ev"], currency), None, {"help": "시가총액 + 총차입금 − 현금"}),
    ], "val")

    per = historical_per(annual, prices)
    if not per.empty and per["per"].notna().sum() >= 2:
        st.markdown("**연도별 PER** <span class='ed-meta'>회계연도 말 주가 ÷ 희석 EPS</span>",
                    unsafe_allow_html=True)
        plot(charts.per_bars(per, mode, current=v["per"]))
        hist = per["per"].dropna()
        if v["per"]:
            st.caption(f"과거 {len(hist)}년 PER 중앙값 {hist.median():.1f}배 · 현재 {v['per']:.1f}배")
    st.caption("주가는 Yahoo Finance(15분 캐시), 실적은 SEC 공시 기준이라 발표 직후엔 시차가 있을 수 있습니다.")


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
    kpi_grid([
        ("장내 매수", fmt.money(buy["value"].sum()), f"{len(buy)}건", {"neutral": True}),
        ("장내 매도", fmt.money(sell["value"].sum()), f"{len(sell)}건", {"neutral": True}),
    ], "ins")
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
