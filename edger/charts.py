"""Plotly figures tuned for phones: short, no mode bar, no drag/zoom (so a swipe scrolls
the page instead of panning the chart), legends on top, tap-to-see tooltips."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from . import fmt

# Reference categorical palette (validated light/dark steps) + diverging poles.
# Categorical order is fixed (never cycled): a ticker keeps its color while others come and go.
PALETTE = {
    "light": {"series": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"], "pos": "#2a78d6",
              "neg": "#e34948", "grid": "rgba(11,11,11,0.08)", "ink2": "#52514e"},
    "dark": {"series": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181"], "pos": "#3987e5",
             "neg": "#e66767", "grid": "rgba(240,239,236,0.10)", "ink2": "#c3c2b7"},
}

PLOTLY_CONFIG = {"displayModeBar": False, "scrollZoom": False, "responsive": True}


def _base(fig: go.Figure, mode: str, height: int = 260) -> go.Figure:
    p = PALETTE[mode]
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=8, t=28, b=8, pad=2),
        dragmode=False,
        hovermode="x unified" if len(fig.data) > 1 else "closest",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0, xanchor="left",
                    font=dict(size=12), title=None),
        font=dict(size=12, color=p["ink2"]),
        barcornerradius=4,
        bargap=0.35,
    )
    fig.update_xaxes(fixedrange=True, automargin=True, showgrid=False, type="category", tickfont=dict(size=11))
    fig.update_yaxes(fixedrange=True, automargin=True, nticks=5, gridcolor=p["grid"], zeroline=True,
                     zerolinecolor=p["grid"], tickfont=dict(size=11))
    return fig


def bar_series(table: pd.DataFrame, col: str, mode: str, currency: str, per_share: bool = False) -> go.Figure:
    s = table[col]
    if per_share:
        div, suffix, y = 1, "", s
        text = [fmt.per_share(v, currency) for v in s]
    else:
        div, suffix = fmt.scale_for(float(s.abs().max() or 0))
        y = s / div
        text = [fmt.money(v, currency) for v in s]
    p = PALETTE[mode]
    colors = [p["series"][0] if (v is None or v >= 0 or pd.isna(v)) else p["neg"] for v in s]
    fig = go.Figure(go.Bar(
        x=table["label"], y=y, marker_color=colors, customdata=text,
        hovertemplate="%{x}<br><b>%{customdata}</b><extra></extra>",
    ))
    fig = _base(fig, mode)
    fig.update_yaxes(ticksuffix=suffix, tickprefix="$" if currency == "USD" and not per_share else "")
    return fig


def margin_lines(table: pd.DataFrame, cols: dict[str, str], mode: str) -> go.Figure:
    p = PALETTE[mode]
    fig = go.Figure()
    for i, (col, label) in enumerate(cols.items()):
        if col not in table or table[col].isna().all():
            continue
        color = p["series"][i]
        fig.add_trace(go.Scatter(
            x=table["label"], y=table[col] * 100, name=label, mode="lines+markers",
            line=dict(width=2, color=color), marker=dict(size=8, color=color),
            hovertemplate=f"{label} %{{y:.1f}}%<extra></extra>",
        ))
    fig = _base(fig, mode, height=240)
    fig.update_yaxes(ticksuffix="%")
    return fig


def insider_monthly(trades: pd.DataFrame, mode: str) -> go.Figure:
    """Open-market buys up, sells down, by month."""
    p = PALETTE[mode]
    t = trades.dropna(subset=["date", "value"]).copy()
    t["month"] = t["date"].dt.to_period("M").dt.to_timestamp()
    buys = t[t["code"] == "P"].groupby("month")["value"].sum()
    sells = t[t["code"] == "S"].groupby("month")["value"].sum()
    months = pd.date_range(t["month"].min(), t["month"].max(), freq="MS") if not t.empty else []
    buys, sells = buys.reindex(months, fill_value=0), sells.reindex(months, fill_value=0)
    labels = [f"{m.year % 100:02d}.{m.month:02d}" for m in months]
    div, suffix = fmt.scale_for(float(max(buys.max() if len(buys) else 0, sells.max() if len(sells) else 0)))
    fig = go.Figure([
        go.Bar(x=labels, y=buys / div, name="매수", marker_color=p["pos"],
               customdata=[fmt.money(v) for v in buys],
               hovertemplate="매수 %{customdata}<extra></extra>"),
        go.Bar(x=labels, y=-sells / div, name="매도", marker_color=p["neg"],
               customdata=[fmt.money(v) for v in sells],
               hovertemplate="매도 %{customdata}<extra></extra>"),
    ])
    fig = _base(fig, mode, height=240)
    fig.update_layout(barmode="relative")
    fig.update_yaxes(tickprefix="$", ticksuffix=suffix)
    return fig


def price_line(prices: pd.Series, mode: str, currency: str = "USD") -> go.Figure:
    p = PALETTE[mode]
    sym = "$" if currency == "USD" else ""
    fig = go.Figure(go.Scatter(
        x=prices.index, y=prices.values, mode="lines", line=dict(width=2, color=p["series"][0]),
        hovertemplate=f"%{{x|%Y-%m-%d}}<br><b>{sym}%{{y:,.2f}}</b><extra></extra>",
    ))
    fig = _base(fig, mode, height=240)
    fig.update_xaxes(type="date", tickformat="%y.%m", nticks=6)
    fig.update_yaxes(tickprefix=sym, zeroline=False)
    fig.update_layout(hovermode="x")
    return fig


def per_bars(per: pd.DataFrame, mode: str, current: float | None = None) -> go.Figure:
    p = PALETTE[mode]
    data = per.dropna(subset=["per"])
    fig = go.Figure(go.Bar(
        x=data["label"], y=data["per"], marker_color=p["series"][0],
        customdata=[f"주가 ${r.price:,.2f} · EPS ${r.eps:,.2f}" for r in data.itertuples()],
        hovertemplate="%{x} PER <b>%{y:.1f}배</b><br>%{customdata}<extra></extra>",
    ))
    fig = _base(fig, mode, height=230)
    if current:
        fig.add_hline(y=current, line=dict(color=p["ink2"], width=1, dash="dot"),
                      annotation_text=f"현재 {current:.1f}배", annotation_position="top left",
                      annotation_font=dict(size=11, color=p["ink2"]))
    fig.update_yaxes(ticksuffix="배")
    return fig


def compare_lines(series: dict[str, pd.Series], mode: str, *, percent: bool, currency: str = "USD") -> go.Figure:
    """One line per ticker over fiscal-year labels. ``series`` keeps the watchlist order."""
    p = PALETTE[mode]
    fig = go.Figure()
    for i, (ticker, s) in enumerate(series.items()):
        if s is None or s.dropna().empty:
            continue
        color = p["series"][i % len(p["series"])]
        y = s * 100 if percent else s
        text = [fmt.pct(v) if percent else fmt.money(v, currency) for v in s]
        fig.add_trace(go.Scatter(
            x=list(s.index), y=y, name=ticker, mode="lines+markers",
            line=dict(width=2, color=color), marker=dict(size=8, color=color),
            customdata=text, hovertemplate=f"{ticker} %{{customdata}}<extra></extra>",
        ))
    fig = _base(fig, mode, height=260)
    if percent:
        fig.update_yaxes(ticksuffix="%")
    else:
        top = max((float(s.abs().max()) for s in series.values() if s is not None and not s.dropna().empty), default=0)
        div, suffix = fmt.scale_for(top)
        for tr in fig.data:
            tr.y = tuple(v / div if v is not None and not pd.isna(v) else None for v in tr.y)
        fig.update_yaxes(ticksuffix=suffix, tickprefix="$" if currency == "USD" else "")
    fig.update_layout(hovermode="x unified")
    return fig
