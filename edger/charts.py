"""Plotly figures tuned for phones: short, no mode bar, no drag/zoom (so a swipe scrolls
the page instead of panning the chart), legends on top, tap-to-see tooltips."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from . import fmt

# Reference categorical palette (validated light/dark steps) + diverging poles.
PALETTE = {
    "light": {"series": ["#2a78d6", "#eb6834", "#1baf7a"], "pos": "#2a78d6", "neg": "#e34948",
              "grid": "rgba(11,11,11,0.08)", "ink2": "#52514e"},
    "dark": {"series": ["#3987e5", "#d95926", "#199e70"], "pos": "#3987e5", "neg": "#e66767",
             "grid": "rgba(240,239,236,0.10)", "ink2": "#c3c2b7"},
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
