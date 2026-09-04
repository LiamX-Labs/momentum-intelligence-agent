"""
Earnings data fetcher via yfinance.

Collects latest EPS, surprise, guidance, next earnings date, and
historical earnings performance (last 4 quarters) from income_stmt.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional

import pandas as pd
import yfinance as yf

log = logging.getLogger(__name__)


@dataclass
class EarningsSnapshot:
    symbol: str

    latest_eps: Optional[float] = None
    eps_surprise: Optional[float] = None
    revenue_surprise: Optional[float] = None

    # Earnings dates
    next_earnings_date: Optional[date] = None
    earnings_quarterly_growth: Optional[float] = None

    # Historical (last 4 quarters)
    earnings_history: list[dict] = field(default_factory=list)

    error: Optional[str] = None


def _safe_optional_float(val: Any) -> Optional[float]:
    try:
        if val is None:
            return None
        return float(val)
    except (TypeError, ValueError):
        return None


def _parse_earnings_date(*candidates: Any) -> Optional[date]:
    """Parse yfinance earnings dates (unix ts, ISO string, Timestamp, or list-wrapped)."""
    for raw_date in candidates:
        if raw_date is None:
            continue
        if isinstance(raw_date, list) and len(raw_date) > 0:
            raw_date = raw_date[0]
        if raw_date is None:
            continue
        try:
            if isinstance(raw_date, date) and not isinstance(raw_date, datetime):
                return raw_date
            if isinstance(raw_date, datetime):
                return raw_date.date()
            if isinstance(raw_date, (int, float)):
                ts = float(raw_date)
                # Yahoo sometimes sends milliseconds
                if ts > 1e12:
                    ts /= 1000.0
                return datetime.fromtimestamp(ts).date()
            return pd.Timestamp(raw_date).date()
        except Exception:
            continue
    return None


def _earnings_date_from_calendar(ticker: yf.Ticker) -> Optional[date]:
    try:
        cal = ticker.calendar
    except Exception:
        return None
    if cal is None:
        return None
    raw = None
    if isinstance(cal, dict):
        raw = cal.get("Earnings Date") or cal.get("earningsDate")
    elif isinstance(cal, pd.DataFrame) and not cal.empty:
        if "Earnings Date" in cal.index:
            raw = cal.loc["Earnings Date"].iloc[0]
        elif "Earnings Date" in cal.columns:
            raw = cal["Earnings Date"].iloc[0]
    return _parse_earnings_date(raw)


def _extract_quarterly_eps(ticker: yf.Ticker) -> pd.DataFrame | None:
    """Extract quarterly EPS data from income_stmt.

    Returns a DataFrame with columns [Quarter, EPS, NetIncome] sorted descending
    by date, or None if income_stmt is unavailable/empty.
    """
    try:
        qis = ticker.quarterly_income_stmt
    except Exception:
        return None

    if qis is None or qis.empty:
        return None

    rows = []
    for col_date in qis.columns:
        date_val = pd.Timestamp(col_date)
        row = {"Quarter": date_val}

        if "Net Income" in qis.index:
            ni = qis.loc["Net Income", col_date]
            row["NetIncome"] = float(ni) if pd.notna(ni) else None
        else:
            row["NetIncome"] = None

        if "Net Income Common Stockholders" in qis.index:
            row["NetIncome"] = float(qis.loc["Net Income Common Stockholders", col_date]) if pd.notna(qis.loc["Net Income Common Stockholders", col_date]) else row.get("NetIncome")

        if "Diluted EPS" in qis.index:
            eps = qis.loc["Diluted EPS", col_date]
            row["EPS"] = float(eps) if pd.notna(eps) else None
        elif "Basic EPS" in qis.index:
            eps = qis.loc["Basic EPS", col_date]
            row["EPS"] = float(eps) if pd.notna(eps) else None
        else:
            row["EPS"] = None

        rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        return None
    df = df.sort_values("Quarter", ascending=False).reset_index(drop=True)
    return df


def fetch_earnings(symbols: list[str]) -> dict[str, EarningsSnapshot]:
    """Fetch earnings data for a list of symbols using income_stmt."""
    results: dict[str, EarningsSnapshot] = {}

    for sym in symbols:
        snap = EarningsSnapshot(symbol=sym)

        try:
            ticker = yf.Ticker(sym)

            eps_df = _extract_quarterly_eps(ticker)
            if eps_df is not None and not eps_df.empty:
                latest_row = eps_df.iloc[0]
                snap.latest_eps = latest_row.get("EPS")

                for _, row in eps_df.head(4).iterrows():
                    entry = {}
                    for k, v in row.items():
                        if isinstance(v, (pd.Timestamp, datetime)):
                            entry[k] = v.isoformat()
                        elif isinstance(v, float) and pd.isna(v):
                            entry[k] = None
                        else:
                            entry[k] = v
                    snap.earnings_history.append(entry)

            info = ticker.info or {}
            snap.earnings_quarterly_growth = (
                float(info["earningsQuarterlyGrowth"])
                if info.get("earningsQuarterlyGrowth") is not None
                else None
            )
            snap.revenue_surprise = (
                float(info["revenueSurprise"])
                if info.get("revenueSurprise") is not None
                else None
            )

            snap.eps_surprise = _safe_optional_float(
                info.get("earningsSurprise", info.get("epsSurprise"))
            )
            snap.next_earnings_date = _parse_earnings_date(
                info.get("earningsDate"),
                info.get("earningsTimestampStart"),
                info.get("earningsTimestamp"),
            )
            if snap.next_earnings_date is None:
                snap.next_earnings_date = _earnings_date_from_calendar(ticker)

        except Exception as exc:
            snap.error = str(exc)

        results[sym] = snap

    return results


def should_reject_for_earnings(
    snap: EarningsSnapshot,
    holding_days: int = 10,
    today: date | None = None,
) -> bool:
    """
    Return True if an earnings event falls within the expected holding
    period, making the trade too risky for the MVP.

    MVP policy: reject trades with earnings inside the holding window.
    """
    if snap.next_earnings_date is None:
        return False
    today = today or date.today()
    delta = (snap.next_earnings_date - today).days
    return 0 <= delta <= holding_days


def earnings_to_df(snapshots: dict[str, EarningsSnapshot]) -> pd.DataFrame:
    rows = []
    for snap in snapshots.values():
        rows.append(
            {
                "symbol": snap.symbol,
                "latest_eps": snap.latest_eps,
                "eps_surprise": snap.eps_surprise,
                "revenue_surprise": snap.revenue_surprise,
                "next_earnings_date": snap.next_earnings_date,
                "earnings_quarterly_growth": snap.earnings_quarterly_growth,
                "error": snap.error,
            }
        )
    return pd.DataFrame(rows)