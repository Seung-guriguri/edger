"""Synthetic company used for offline demos and tests (ticker ``DEMO``).

Facts are generated in the SEC companyfacts JSON shape and run through edgartools' own
parser, so the demo exercises the same code path as real data: quarterly cash flow is
reported year-to-date only and Q4 is never reported on its own, like real filings.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

TICKER = "DEMO"
_FIRST_FY = 2016
_LAST_FY = 2025


def profile() -> dict:
    return {
        "name": "Demo Robotics Inc. (예시 데이터)",
        "cik": 0,
        "tickers": [TICKER],
        "exchanges": ["Nasdaq"],
        "industry": "Industrial Machinery",
        "fiscal_year_end": "1231",
        "category": "Large Accelerated Filer",
    }


def _quarter_bounds(fy: int):
    starts = [date(fy, 1, 1), date(fy, 4, 1), date(fy, 7, 1), date(fy, 10, 1)]
    ends = [date(fy, 3, 31), date(fy, 6, 30), date(fy, 9, 30), date(fy, 12, 31)]
    return starts, ends


def _company_facts_json() -> dict:
    rng = np.random.default_rng(7)
    flows = {k: [] for k in ("Revenues", "GrossProfit", "OperatingIncomeLoss", "NetIncomeLoss",
                             "EarningsPerShareDiluted", "NetCashProvidedByUsedInOperatingActivities",
                             "PaymentsToAcquirePropertyPlantAndEquipment")}
    instants = {k: [] for k in ("CashAndCashEquivalentsAtCarryingValue", "Assets", "Liabilities",
                                "StockholdersEquity")}
    shares = 1.2e9
    revenue_fy = 18e9
    assets = 40e9
    for fy in range(_FIRST_FY, _LAST_FY + 1):
        revenue_fy *= 1 + rng.normal(0.11, 0.07)
        q_weights = np.array([0.23, 0.24, 0.25, 0.28]) + rng.normal(0, 0.005, 4)
        q_weights /= q_weights.sum()
        gm = 0.42 + rng.normal(0, 0.015)
        om = 0.17 + 0.006 * (fy - _FIRST_FY) + rng.normal(0, 0.02)
        if fy == 2020:
            om -= 0.12  # a bad year so the charts show a dip
        nm = om * 0.78
        starts, ends = _quarter_bounds(fy)
        filed_k = (date(fy + 1, 2, 10)).isoformat()

        q_rev = revenue_fy * q_weights
        values = {
            "Revenues": q_rev,
            "GrossProfit": q_rev * gm,
            "OperatingIncomeLoss": q_rev * om,
            "NetIncomeLoss": q_rev * nm,
            "EarningsPerShareDiluted": q_rev * nm / shares,
            "NetCashProvidedByUsedInOperatingActivities": q_rev * (nm + 0.07),
            "PaymentsToAcquirePropertyPlantAndEquipment": q_rev * 0.05,
        }
        ytd_only = {"NetCashProvidedByUsedInOperatingActivities",
                    "PaymentsToAcquirePropertyPlantAndEquipment"}
        for concept, qv in values.items():
            for q in range(3):  # 10-Q facts
                filed = (ends[q] + timedelta(days=35)).isoformat()
                fp = f"Q{q + 1}"
                if concept not in ytd_only:
                    flows[concept].append({"start": starts[q].isoformat(), "end": ends[q].isoformat(),
                                           "val": round(float(qv[q]), 2), "fy": fy, "fp": fp,
                                           "form": "10-Q", "filed": filed})
                if q > 0 or concept in ytd_only:
                    flows[concept].append({"start": starts[0].isoformat(), "end": ends[q].isoformat(),
                                           "val": round(float(qv[: q + 1].sum()), 2), "fy": fy, "fp": fp,
                                           "form": "10-Q", "filed": filed})
            flows[concept].append({"start": starts[0].isoformat(), "end": ends[3].isoformat(),
                                   "val": round(float(qv.sum()), 2), "fy": fy, "fp": "FY",
                                   "form": "10-K", "filed": filed_k})

        for q in range(4):
            assets *= 1.025
            equity = assets * (0.48 + 0.01 * rng.normal())
            form, filed = ("10-K", filed_k) if q == 3 else ("10-Q", (ends[q] + timedelta(days=35)).isoformat())
            for concept, v in (("Assets", assets), ("StockholdersEquity", equity),
                               ("Liabilities", assets - equity),
                               ("CashAndCashEquivalentsAtCarryingValue", assets * 0.12)):
                instants[concept].append({"end": ends[q].isoformat(), "val": round(float(v), 2), "fy": fy,
                                          "fp": "FY" if q == 3 else f"Q{q + 1}", "form": form, "filed": filed})

    usgaap = {}
    for concept, rows in {**flows, **instants}.items():
        unit = "USD/shares" if concept.startswith("EarningsPerShare") else "USD"
        for r in rows:
            r["accn"] = f"0000000000-{r['fy'] % 100:02d}-{r['fp']}"
        usgaap[concept] = {"label": concept, "units": {unit: rows}}
    return {"cik": 0, "entityName": profile()["name"], "facts": {"us-gaap": usgaap}}


def facts_frame() -> pd.DataFrame:
    from edgar.entity.parser import EntityFactsParser

    facts = EntityFactsParser.parse_company_facts(_company_facts_json())
    return facts.to_dataframe(include_metadata=True)


def filings_frame() -> pd.DataFrame:
    rows = []
    for fy in range(_LAST_FY, _LAST_FY - 3, -1):
        rows.append(("10-K", date(fy + 1, 2, 10), f"{fy}-12-31", "Annual report"))
        for q, m in ((3, 11), (2, 8), (1, 5)):
            rows.append(("10-Q", date(fy, m, 5), f"{fy}-{q * 3:02d}-30", "Quarterly report"))
        rows.append(("DEF 14A", date(fy + 1, 3, 20), "", "Proxy statement"))
        for m in (1, 4, 7, 10):
            rows.append(("8-K", date(fy, m, 28), "", "Earnings release"))
        for d in range(1, 12, 2):
            rows.append(("4", date(fy, d, 15), "", "Statement of changes in beneficial ownership"))
    df = pd.DataFrame(rows, columns=["form", "filing_date", "report_date", "description"])
    df["filing_date"] = pd.to_datetime(df["filing_date"])
    df["url"] = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type=10-K"
    return df.sort_values("filing_date", ascending=False).reset_index(drop=True)


def insider_frame() -> pd.DataFrame:
    rng = np.random.default_rng(3)
    people = [("Jane Park", "CEO"), ("Alex Kim", "CFO"), ("Sam Lee", "Director"),
              ("Chris Moon", "COO"), ("Robin Choi", "Director")]
    codes = [("S", "Sale"), ("S", "Sale"), ("P", "Purchase"), ("M", "Exercise"),
             ("F", "Tax Withholding"), ("A", "Award")]
    rows = []
    for i in range(60):
        name, pos = people[rng.integers(len(people))]
        code, typ = codes[rng.integers(len(codes))]
        shares = float(rng.integers(500, 40000))
        price = round(float(80 + i * 0.6 + rng.normal(0, 4)), 2)
        rows.append({
            "date": pd.Timestamp(date(2026, 10, 30)) - pd.Timedelta(days=int(i * 6 + rng.integers(0, 5))),
            "insider": name, "position": pos, "code": code, "type": typ,
            "shares": shares, "price": price if code in "SPF" else np.nan,
            "value": shares * price if code in "SPF" else np.nan,
            "url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type=4",
        })
    return pd.DataFrame(rows).sort_values("date", ascending=False).reset_index(drop=True)
