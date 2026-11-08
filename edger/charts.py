"""Plotly figures tuned for phones: short, no mode bar, no drag/zoom (so a swipe scrolls the
page instead of panning the chart), legends on top, tap-to-see tooltips.

Visual rules (see the data-viz guide this follows):
  - thin marks: 2px lines, 8px markers with a 2px ring in the surface colour, 4px rounded
    bar ends; hairline solid grid
  - selective direct labels: the latest value (and the extremes on the price chart), never a
    number on every point; end labels are dropped when lines converge
  - text never wears the series colour; tooltips use the surface colour, value first
  - category axes never rotate their labels: they are thinned instead
"""
from __future__ import annotations

import math

import pandas as pd
import plotly.graph_objects as go

from . import fmt

# Reference categorical palette (validated light/dark steps) + diverging poles.
# Categorical order is fixed (never cycled): a ticker keeps its colour while others come and go.
PALETTE = {
    "light": {"series": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6"],
              "pos": "#2a78d6",
              "neg": "#e34948", "grid": "rgba(11,11,11,0.08)", "axis": "rgba(11,11,11,0.18)",
              "ink": "#0b0b0b", "ink2": "#52514e", "surface": "#ffffff"},
    "dark": {"series": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9"],
             "pos": "#3987e5",
             "neg": "#e66767", "grid": "rgba(240,239,236,0.10)", "axis": "rgba(240,239,236,0.22)",
             "ink": "#f0efec", "ink2": "#c3c2b7", "surface": "#0e1117"},
}
FONT = '"Source Sans 3", "Source Sans Pro", -apple-system, "Apple SD Gothic Neo", sans-serif'
PLOTLY_CONFIG = {"displayModeBar": False, "scrollZoom": False, "responsive": True}
MAX_X_LABELS = 7  # on a ~360px phone, more category labels than this would have to rotate


def _base(fig: go.Figure, mode: str, height: int = 250, *, legend: bool | None = None,
          right: int = 8) -> go.Figure:
    p = PALETTE[mode]
    legend = len(fig.data) > 1 if legend is None else legend
    fig.update_layout(
        height=height,
        margin=dict(l=4, r=right, t=34 if legend else 12, b=4, pad=2),
        dragmode=False,
        hovermode="x unified" if len(fig.data) > 1 else "closest",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, xanchor="left",
                    font=dict(size=12, color=p["ink2"]), title=None, itemwidth=30),
        font=dict(family=FONT, size=12, color=p["ink2"]),
        hoverlabel=dict(bgcolor=p["surface"], bordercolor=p["axis"], font=dict(family=FONT, size=13, color=p["ink"])),
        barcornerradius=4,
        bargap=0.38,
    )
    fig.update_xaxes(fixedrange=True, automargin=True, showgrid=False, type="category", tickangle=0,
                     tickfont=dict(size=11), showline=True, linecolor=p["axis"], linewidth=1, ticks="")
    fig.update_yaxes(fixedrange=True, automargin=True, nticks=5, gridcolor=p["grid"], gridwidth=1,
                     zeroline=True, zerolinecolor=p["axis"], zerolinewidth=1, tickfont=dict(size=11),
                     showline=False)
    return fig


def _thin_categories(fig: go.Figure, labels) -> None:
    """Show at most MAX_X_LABELS evenly spaced category labels, always including the latest."""
    labels = list(labels)
    if len(labels) <= MAX_X_LABELS:
        return
    step = math.ceil(len(labels) / MAX_X_LABELS)
    keep = labels[::-1][::step][::-1]  # count back from the latest so it is always shown
    fig.update_xaxes(tickmode="array", tickvals=keep, ticktext=keep)


def _marker(color: str, mode: str, size: int = 8) -> dict:
    """Series-coloured dot with a 2px surface ring, so it stays legible over other lines."""
    return dict(size=size, color=color, line=dict(width=2, color=PALETTE[mode]["surface"]))


def _end_labels(fig: go.Figure, ends: list[tuple[object, float, str]], mode: str,
                y_range: float, min_gap: float = 0.07) -> bool:
    """Value labels just right of each line's last point. ``ends`` = (x, y, text).

    When two ends are closer than ``min_gap`` of the axis range the labels would collide;
    nudging them apart detaches them from their lines, so none are drawn (the legend and
    tooltip carry the values). Returns whether labels were drawn.
    """
    if not ends or y_range <= 0:
        return False
    ys = sorted(y for _, y, _ in ends)
    if any(b - a < min_gap * y_range for a, b in zip(ys, ys[1:])):
        return False
    for x, y, text in ends:
        fig.add_annotation(x=x, y=y, text=text, showarrow=False, xanchor="left", xshift=7,
                           font=dict(size=11, color=PALETTE[mode]["ink"]))
    return True


# ---------------------------------------------------------------- bars
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
    colors = [p["series"][0] if (v is None or pd.isna(v) or v >= 0) else p["neg"] for v in s]
    # Direct label on the latest bar only; the axis and tooltip carry the rest.
    labels = [""] * len(s)
    if len(s):
        labels[-1] = text[-1]
    fig = go.Figure(go.Bar(
        x=table["label"], y=y, marker_color=colors, customdata=text,
        text=labels, textposition="outside", cliponaxis=False, constraintext="none",
        textfont=dict(size=12, color=p["ink"]),
        hovertemplate="%{x}<br><b>%{customdata}</b><extra></extra>",
    ))
    fig = _base(fig, mode, legend=False, right=28)
    fig.update_layout(margin=dict(t=26))  # room for the label above (and beside) the latest bar
    fig.update_yaxes(ticksuffix=suffix, tickprefix="$" if currency == "USD" and not per_share else "")
    _thin_categories(fig, table["label"])
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
               hovertemplate="매수 <b>%{customdata}</b><extra></extra>"),
        go.Bar(x=labels, y=-sells / div, name="매도", marker_color=p["neg"],
               customdata=[fmt.money(v) for v in sells],
               hovertemplate="매도 <b>%{customdata}</b><extra></extra>"),
    ])
    fig = _base(fig, mode, height=230)
    fig.update_layout(barmode="relative")
    fig.update_yaxes(tickprefix="$", ticksuffix=suffix)
    _thin_categories(fig, labels)
    return fig


def per_bars(per: pd.DataFrame, mode: str, current: float | None = None) -> go.Figure:
    p = PALETTE[mode]
    data = per.dropna(subset=["per"])
    labels = [""] * len(data)
    if len(data):
        labels[-1] = f"{data['per'].iloc[-1]:.1f}배"
    fig = go.Figure(go.Bar(
        x=data["label"], y=data["per"], marker_color=p["series"][0],
        text=labels, textposition="outside", cliponaxis=False, constraintext="none", textfont=dict(size=12, color=p["ink"]),
        customdata=[f"주가 ${r.price:,.2f} · EPS ${r.eps:,.2f}" for r in data.itertuples()],
        hovertemplate="%{x} PER <b>%{y:.1f}배</b><br>%{customdata}<extra></extra>",
    ))
    fig = _base(fig, mode, height=230, legend=False, right=24)
    fig.update_layout(margin=dict(t=26))
    if current:
        # A reference line, not a gridline: solid hairline in the ink colour with its own label.
        fig.add_hline(y=current, line=dict(color=p["ink2"], width=1),
                      annotation_text=f"현재 {current:.1f}배", annotation_position="top left",
                      annotation_font=dict(size=11, color=p["ink"]))
    fig.update_yaxes(ticksuffix="배")
    _thin_categories(fig, data["label"])
    return fig


def dividend_bars(annual: pd.DataFrame, mode: str, currency: str = "USD") -> go.Figure:
    """Dividends per share by calendar year; the running year is drawn faded."""
    p = PALETTE[mode]
    sym = "$" if currency == "USD" else ""
    data = annual.tail(15)
    opac = [0.4 if part else 1.0 for part in data["partial"]]
    text, labels = [], []
    for year, r in data.iterrows():
        g = "" if pd.isna(r["growth"]) else f" ({r['growth'] * 100:+.1f}%)"
        note = f" · 진행 중 {int(r['count'])}회" if r["partial"] else f" · {int(r['count'])}회"
        text.append(f"{sym}{r['dps']:,.2f}{g}{note}")
        labels.append("")
    full = [i for i, part in enumerate(data["partial"]) if not part]
    if full:  # label the latest complete year
        labels[full[-1]] = f"{sym}{data['dps'].iloc[full[-1]]:,.2f}"
    x = [str(y) for y in data.index]
    fig = go.Figure(go.Bar(
        x=x, y=data["dps"], marker=dict(color=p["series"][0], opacity=opac),
        text=labels, textposition="outside", cliponaxis=False, constraintext="none", textfont=dict(size=12, color=p["ink"]),
        customdata=text, hovertemplate="%{x}<br><b>%{customdata}</b><extra></extra>",
    ))
    fig = _base(fig, mode, height=240, legend=False, right=20)
    fig.update_layout(margin=dict(t=26))
    fig.update_yaxes(tickprefix=sym)
    _thin_categories(fig, x)
    return fig


def dividend_payments(payments: pd.Series, mode: str, currency: str = "USD") -> go.Figure:
    """Each payment as a bar on its ex-date (last ~10 years)."""
    p = PALETTE[mode]
    sym = "$" if currency == "USD" else ""
    data = payments[payments.index >= payments.index[-1] - pd.DateOffset(years=10)]
    fig = go.Figure(go.Bar(
        x=data.index, y=data.values, marker_color=p["series"][0],
        hovertemplate=f"%{{x|%Y-%m-%d}}<br><b>{sym}%{{y:,.3f}}</b><extra></extra>",
    ))
    fig = _base(fig, mode, height=220, legend=False)
    fig.add_annotation(x=data.index[-1], y=float(data.iloc[-1]), text=f"{sym}{data.iloc[-1]:,.2f}",
                       showarrow=False, yanchor="bottom", yshift=4, font=dict(size=12, color=p["ink"]))
    fig.update_layout(margin=dict(t=26), bargap=0.25)
    fig.update_xaxes(type="date", tickformat="%y", nticks=8)
    fig.update_yaxes(tickprefix=sym)
    return fig


# ---------------------------------------------------------------- lines
def _line(fig: go.Figure, x, y, name: str, color: str, mode: str, hover: str, customdata=None) -> None:
    fig.add_trace(go.Scatter(
        x=x, y=y, name=name, mode="lines+markers", connectgaps=False, customdata=customdata,
        line=dict(width=2, color=color, shape="linear"), marker=_marker(color, mode),
        hovertemplate=hover,
    ))


def margin_lines(table: pd.DataFrame, cols: dict[str, str], mode: str) -> go.Figure:
    """Percent series (margins, returns). End labels show the latest value of each line."""
    p = PALETTE[mode]
    fig = go.Figure()
    ends, lo, hi = [], math.inf, -math.inf
    for i, (col, label) in enumerate(cols.items()):
        if col not in table or table[col].isna().all():
            continue
        y = table[col] * 100
        _line(fig, table["label"], y, label, p["series"][i], mode, f"{label} <b>%{{y:.1f}}%</b><extra></extra>")
        valid = y.dropna()
        ends.append((table["label"].loc[valid.index[-1]], float(valid.iloc[-1]), f"{valid.iloc[-1]:.1f}%"))
        lo, hi = min(lo, float(valid.min())), max(hi, float(valid.max()))
    labelled = _end_labels(fig, ends, mode, hi - lo if ends else 0)
    fig = _base(fig, mode, height=240, legend=True, right=46 if labelled else 8)
    fig.update_yaxes(ticksuffix="%")
    _thin_categories(fig, table["label"])
    return fig


def compare_lines(series: dict[str, pd.Series], mode: str, *, percent: bool, currency: str = "USD",
                  per_share: bool = False) -> go.Figure:
    """One line per ticker over fiscal-year labels. ``series`` keeps the watchlist order.
    Each line ends in its ticker name, so the legend is a backup rather than a lookup."""
    p = PALETTE[mode]
    fig = go.Figure()
    present = [s for s in series.values() if s is not None and not s.dropna().empty]
    top = max((float(s.abs().max()) for s in present), default=0)
    div, suffix = (1, "") if percent or per_share else fmt.scale_for(top)
    ends, lo, hi, labels = [], math.inf, -math.inf, []
    for i, (ticker, s) in enumerate(series.items()):
        if s is None or s.dropna().empty:
            continue
        labels = list(s.index) if len(s.index) > len(labels) else labels
        color = p["series"][i % len(p["series"])]
        y = s * 100 if percent else s / div
        text = [fmt.pct(v) if percent else fmt.per_share(v, currency) if per_share else fmt.money(v, currency)
                for v in s]
        _line(fig, list(s.index), y, ticker, color, mode, f"{ticker} <b>%{{customdata}}</b><extra></extra>", text)
        valid = y.dropna()
        ends.append((valid.index[-1], float(valid.iloc[-1]), ticker))
        lo, hi = min(lo, float(valid.min())), max(hi, float(valid.max()))
    labelled = _end_labels(fig, ends, mode, hi - lo if ends else 0)
    fig = _base(fig, mode, height=260, legend=True, right=52 if labelled else 8)
    if percent:
        fig.update_yaxes(ticksuffix="%")
    elif per_share:
        fig.update_yaxes(tickprefix="$" if currency == "USD" else "")
    else:
        fig.update_yaxes(ticksuffix=suffix, tickprefix="$" if currency == "USD" else "")
    fig.update_layout(hovermode="x unified")
    _thin_categories(fig, labels)
    return fig


def dividend_yield_line(annual: pd.DataFrame, mode: str) -> go.Figure:
    p = PALETTE[mode]
    data = annual.dropna(subset=["yield"]).tail(15)
    x = [str(y) + ("*" if part else "") for y, part in zip(data.index, data["partial"])]
    fig = go.Figure()
    _line(fig, x, data["yield"] * 100, "배당수익률", p["series"][0], mode,
          "%{x} 배당수익률 <b>%{y:.2f}%</b><extra></extra>")
    _end_labels(fig, [(x[-1], float(data["yield"].iloc[-1] * 100), f"{data['yield'].iloc[-1] * 100:.2f}%")],
                mode, 1.0)
    fig = _base(fig, mode, height=210, legend=False, right=50)
    fig.update_yaxes(ticksuffix="%", rangemode="tozero")
    _thin_categories(fig, x)
    return fig


def price_line(prices: pd.Series, mode: str, currency: str = "USD") -> go.Figure:
    """Closing prices with a light wash below, the period's high and low marked, and the
    latest price labelled. A crosshair follows the finger/pointer."""
    p = PALETTE[mode]
    sym = "$" if currency == "USD" else ""
    color = p["series"][0]
    lo_v, hi_v = float(prices.min()), float(prices.max())
    pad = (hi_v - lo_v) * 0.08 or hi_v * 0.02
    floor = lo_v - pad * 2.4  # room for the "최저" label under the low point, above the date axis
    fig = go.Figure([
        # invisible baseline at the bottom of the axis, so the wash fills to it (not to $0)
        go.Scatter(x=prices.index, y=[floor] * len(prices), mode="lines", line=dict(width=0),
                   hoverinfo="skip", showlegend=False),
        go.Scatter(x=prices.index, y=prices.values, mode="lines", fill="tonexty",
                   fillcolor=_alpha(color, 0.10), line=dict(width=2, color=color),
                   hovertemplate=f"%{{x|%Y-%m-%d}}<br><b>{sym}%{{y:,.2f}}</b><extra></extra>",
                   showlegend=False),
    ])
    fig = _base(fig, mode, height=250, legend=False, right=8)
    fig.update_layout(hovermode="x", margin=dict(t=22, b=4))
    fig.update_xaxes(type="date", tickformat="%y.%m", nticks=6, showspikes=True, spikemode="across",
                     spikethickness=1, spikecolor=p["axis"], spikedash="solid", spikesnap="cursor")
    fig.update_yaxes(tickprefix=sym, zeroline=False, range=[floor, hi_v + pad])

    hi_x, lo_x, last_x = prices.idxmax(), prices.idxmin(), prices.index[-1]
    marks = [(hi_x, hi_v, f"최고 {sym}{hi_v:,.2f}", "bottom"), (lo_x, lo_v, f"최저 {sym}{lo_v:,.2f}", "top")]
    for x, y, text, anchor in marks:
        if x == last_x:
            continue  # the latest-price label covers it
        fig.add_trace(go.Scatter(x=[x], y=[y], mode="markers", marker=_marker(p["ink2"], mode, 7),
                                 hoverinfo="skip", showlegend=False))
        # keep labels inside the plot: anchor toward the middle when the point is near an edge
        rel = (x - prices.index[0]) / (last_x - prices.index[0]) if last_x != prices.index[0] else 0.5
        fig.add_annotation(x=x, y=y, text=text, showarrow=False, yanchor=anchor,
                           yshift=6 if anchor == "bottom" else -6,
                           xanchor="left" if rel < 0.2 else "right" if rel > 0.8 else "center",
                           font=dict(size=11, color=p["ink2"]), bgcolor=p["surface"], borderpad=1)
    last_v = float(prices.iloc[-1])
    fig.add_trace(go.Scatter(x=[last_x], y=[last_v], mode="markers", marker=_marker(color, mode, 9),
                             hoverinfo="skip", showlegend=False))
    # The latest price sits above its dot, unless the period high is just before it (labels
    # would collide) — then it goes below.
    span = last_x - prices.index[0]
    near_high = hi_x != last_x and span.days > 0 and (last_x - hi_x) / span < 0.2
    fig.add_annotation(x=last_x, y=last_v, text=f"{sym}{last_v:,.2f}", showarrow=False, xanchor="right",
                       yanchor="top" if near_high else "bottom", yshift=-9 if near_high else 9,
                       font=dict(size=12, color=p["ink"]), bgcolor=p["surface"], borderpad=2)
    return fig


def _alpha(hex_color: str, a: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{a})"


# ---------------------------------------------------------------- revenue mix
def mix_columns(values: pd.DataFrame, mode: str, currency: str = "USD", max_parts: int = 5) -> go.Figure:
    """Stacked columns per fiscal year. Parts keep a fixed colour order (largest first) and
    anything past ``max_parts`` folds into one grey "기타" block."""
    p = PALETTE[mode]
    v = values.copy()
    if len(v) > max_parts:
        head, tail = v.iloc[:max_parts - 1], v.iloc[max_parts - 1:]
        v = pd.concat([head, pd.DataFrame([tail.sum()], index=[f"기타 {len(tail)}개"])])
    years = [f"FY{c.year % 100:02d}" if hasattr(c, "year") else str(c) for c in v.columns]
    div, suffix = fmt.scale_for(float(v.sum().max() or 0))
    fig = go.Figure()
    for i, (name, row) in enumerate(v.iterrows()):
        color = p["series"][i] if not str(name).startswith("기타") else p["axis"]
        fig.add_trace(go.Bar(
            x=years, y=row.values / div, name=str(name)[:24], marker=dict(color=color,
            line=dict(width=2, color=p["surface"])),  # 2px surface gap between stacked parts
            customdata=[fmt.money(x, currency) for x in row.values],
            hovertemplate=f"{str(name)[:30]} <b>%{{customdata}}</b><extra></extra>",
        ))
    fig = _base(fig, mode, height=280, legend=True)
    fig.update_layout(barmode="stack", bargap=0.45, barcornerradius=0,
                      legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, traceorder="normal"))
    fig.update_yaxes(ticksuffix=suffix, tickprefix="$" if currency == "USD" else "")
    return fig


# ---------------------------------------------------------------- donut
OTHER = {"light": "#b5b4ae", "dark": "#5c5b57"}  # neutral grey for the folded "기타" slice
_DARK_TEXT_SLOTS = {3}                             # yellow: near-black label (palette rule)


def donut_colors(labels: list[str], mode: str) -> list[str]:
    """Fixed categorical order for real parts; '기타…' always grey."""
    p = PALETTE[mode]
    out, i = [], 0
    for lbl in labels:
        if str(lbl).startswith("기타"):
            out.append(OTHER[mode])
        else:
            out.append(p["series"][i % len(p["series"])])
            i += 1
    return out


def fold_parts(values: pd.Series, max_parts: int = 6) -> pd.Series:
    """Largest items first; beyond ``max_parts`` slices the tail (and any existing '기타…'
    rows) fold into one '기타' slice, always last."""
    v = values.dropna()
    v = v[v > 0]
    is_other = [str(k).startswith("기타") for k in v.index]
    regular = v[[not o for o in is_other]].sort_values(ascending=False)
    other = float(v[is_other].sum())
    if len(regular) + (1 if other else 0) > max_parts:
        other += float(regular.iloc[max_parts - 1:].sum())
        regular = regular.iloc[:max_parts - 1]
    return pd.concat([regular, pd.Series({"기타": other})]) if other else regular


def donut(parts: pd.Series, mode: str, center_title: str, center_value: str,
          colors: list[str] | None = None, hover_values: list[str] | None = None) -> go.Figure:
    """A donut with the share printed on slices of >= 6% and a total in the hole.

    Identity is carried by the colour dot in the list rendered under the chart (that list is
    also the exact-number table view), so the chart itself has no legend."""
    p = PALETTE[mode]
    labels = [str(k) for k in parts.index]
    colors = colors or donut_colors(labels, mode)
    share = parts / parts.sum()
    text = [f"{s * 100:.0f}%" if s >= 0.06 else "" for s in share]
    text_colors = ["#0b0b0b" if (c == p["series"][3] or c == OTHER["light"]) else "#ffffff" for c in colors]
    fig = go.Figure(go.Pie(
        labels=labels, values=parts.values, hole=0.62, sort=False, direction="clockwise", rotation=0,
        marker=dict(colors=colors, line=dict(color=p["surface"], width=2)),
        text=text, textinfo="text", textposition="inside", insidetextorientation="horizontal",
        textfont=dict(family=FONT, size=13, color=text_colors),
        customdata=hover_values or labels,
        hovertemplate="%{label}<br><b>%{customdata}</b> · %{percent:.1%}<extra></extra>",
    ))
    fig.update_layout(
        height=250, margin=dict(l=4, r=4, t=4, b=4), showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT, size=12, color=p["ink2"]),
        hoverlabel=dict(bgcolor=p["surface"], bordercolor=p["axis"], font=dict(family=FONT, size=13, color=p["ink"])),
        annotations=[
            dict(text=center_title, x=0.5, y=0.58, showarrow=False, font=dict(size=12, color=p["ink2"])),
            dict(text=f"<b>{center_value}</b>", x=0.5, y=0.44, showarrow=False, font=dict(size=17, color=p["ink"])),
        ],
    )
    return fig


# ---------------------------------------------------------------- PER history & band
def per_line(hist: pd.DataFrame, mode: str, median: float | None = None) -> go.Figure:
    """Weekly PER with this company's median as a reference line and the latest value labelled."""
    p = PALETTE[mode]
    per = hist["per"]
    fig = go.Figure(go.Scatter(
        x=per.index, y=per.values, mode="lines", connectgaps=False, line=dict(width=2, color=p["series"][0]),
        hovertemplate="%{x|%Y-%m-%d}<br>PER <b>%{y:.1f}배</b><extra></extra>", showlegend=False,
    ))
    fig = _base(fig, mode, height=230, legend=False, right=8)
    fig.update_layout(hovermode="x", margin=dict(t=22))
    fig.update_xaxes(type="date", tickformat="%y", nticks=8, showspikes=True, spikemode="across",
                     spikethickness=1, spikecolor=p["axis"], spikedash="solid", spikesnap="cursor",
                     range=[per.index[0], per.index[-1]])
    valid = per.dropna()
    if not valid.empty:
        # extreme spikes (earnings near zero) would flatten everything else: clip the view
        top = float(valid.quantile(0.97)) * 1.15
        fig.update_yaxes(ticksuffix="배", zeroline=False, range=[0, max(top, float(valid.iloc[-1]) * 1.15)])
        fig.add_annotation(x=valid.index[-1], y=float(valid.iloc[-1]), text=f"{valid.iloc[-1]:.1f}배",
                           showarrow=False, xanchor="right", yanchor="bottom", yshift=8,
                           font=dict(size=12, color=p["ink"]), bgcolor=p["surface"], borderpad=2)
    if median:
        fig.add_hline(y=median, line=dict(color=p["ink2"], width=1),
                      annotation_text=f"중앙값 {median:.1f}배", annotation_position="top left",
                      annotation_font=dict(size=11, color=p["ink2"]))
    return fig


def per_band(hist: pd.DataFrame, multiples: list[float], mode: str, currency: str = "USD") -> go.Figure:
    """Price against 'TTM EPS x multiple' lines. Bands are an ordered series, so they use one
    grey ramp light -> dark; only the price wears the accent colour."""
    p = PALETTE[mode]
    sym = "$" if currency == "USD" else ""
    fig = go.Figure()
    n = len(multiples)
    eps = hist["eps"].where(hist["eps"] > 0)  # a band through negative earnings is meaningless
    ink = p["ink"].lstrip("#")
    r, g, b = (int(ink[i:i + 2], 16) for i in (0, 2, 4))
    for i, m in enumerate(multiples):
        # one ramp of the text colour (dark on light, light on dark): low multiple faint, high strong
        alpha = 0.18 + 0.42 * (i / max(n - 1, 1))
        grey = f"rgba({r},{g},{b},{alpha:.2f})"
        y = eps * m
        fig.add_trace(go.Scatter(
            x=hist.index, y=y, mode="lines", connectgaps=False, line=dict(width=1.3, color=grey),
            name=f"{m:g}배", hovertemplate=f"{m:g}배 {sym}%{{y:,.0f}}<extra></extra>", showlegend=False,
        ))
        last = y.dropna()
        if not last.empty:
            fig.add_annotation(x=last.index[-1], y=float(last.iloc[-1]), text=f"{m:g}배", showarrow=False,
                               xanchor="left", xshift=4, font=dict(size=10, color=p["ink2"]))
    fig.add_trace(go.Scatter(
        x=hist.index, y=hist["price"], mode="lines", line=dict(width=2, color=p["series"][0]), name="주가",
        hovertemplate=f"주가 <b>{sym}%{{y:,.2f}}</b><extra></extra>", showlegend=False,
    ))
    fig = _base(fig, mode, height=270, legend=False, right=40)
    fig.update_layout(hovermode="x unified", margin=dict(t=12))
    fig.update_xaxes(type="date", tickformat="%y", nticks=8, range=[hist.index[0], hist.index[-1]])
    top = float(hist["price"].max()) * 1.6  # keep the price readable when high bands run off
    fig.update_yaxes(tickprefix=sym, zeroline=False, range=[0, top])
    return fig
