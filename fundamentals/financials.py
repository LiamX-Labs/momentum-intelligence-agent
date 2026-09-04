"""
Fundamental data fetcher using yfinance.

Collects growth metrics, balance sheet strength, and valuation ratios
for each candidate.  All data is returned as structured dicts suitable
for serialisation and LLM consumption.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd
import yfinance as yf

log = logging.getLogger(__name__)


@dataclass
class FinancialSnapshot:
    symbol: str

    # Growth
    revenue_growth: Optional[float] = None
    eps_growth: Optional[float] = None
    ebitda_growth: Optional[float] = None
    fcf_growth: Optional[float] = None

    # Margins
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    net_margin: Optional[float] = None

    # Returns
    roe: Optional[float] = None
    roic: Optional[float] = None

    # Balance sheet
    cash: Optional[float] = None
    total_debt: Optional[float] = None
    net_debt: Optional[float] = None
    ebitda: Optional[float] = None
    debt_to_ebitda: Optional[float] = None
    debt_to_equity: Optional[float] = None
    current_ratio: Optional[float] = None

    # Valuation
    pe_ratio: Optional[float] = None
    forward_pe: Optional[float] = None
    ev_to_ebitda: Optional[float] = None
    price_to_sales: Optional[float] = None
    fcf_yield: Optional[float] = None
    peg_ratio: Optional[float] = None

    # Raw income-statement line items
    net_income: Optional[float] = None
    revenue: Optional[float] = None

    # Derived quality score (0-1)
    fundamental_quality: float = 0.0

    raw: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


_REVENUE_ROWS = ("Total Revenue", "Operating Revenue", "Revenue")
_NET_INCOME_ROWS = (
    "Net Income",
    "Net Income Common Stockholders",
    "Net Income From Continuing Operation Net Minority Interest",
)
_EBITDA_ROWS = ("EBITDA", "Normalized EBITDA")


def _safe_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        if isinstance(val, float) and pd.isna(val):
            return None
        return float(val)
    except (TypeError, ValueError):
        return None


def _stmt_latest(stmt: Optional[pd.DataFrame], names: tuple[str, ...]) -> Optional[float]:
    """Return the most recent column for the first matching income-statement row."""
    if stmt is None or getattr(stmt, "empty", True):
        return None
    for name in names:
        if name in stmt.index:
            return _safe_float(stmt.loc[name].iloc[0])
    return None


def fetch_financials(symbols: list[str]) -> dict[str, FinancialSnapshot]:
    """Fetch fundamental data for a list of symbols.

    Returns a dict keyed by symbol.  Skips symbols that yfinance cannot
    resolve without halting the batch.
    """
    results: dict[str, FinancialSnapshot] = {}

    for sym in symbols:
        snap = FinancialSnapshot(symbol=sym)
        try:
            ticker = yf.Ticker(sym)
            info = ticker.info or {}
            snap.raw = info
        except Exception as exc:
            snap.error = str(exc)
            results[sym] = snap
            continue

        # ── Growth ──────────────────────────────────────────────
        snap.revenue_growth = _safe_float(info.get("revenueGrowth"))
        snap.eps_growth = _safe_float(info.get("earningsGrowth"))
        snap.ebitda_growth = _safe_float(info.get("ebitdaGrowth"))
        snap.fcf_growth = _safe_float(info.get("freeCashflowGrowth"))

        # ── Margins ─────────────────────────────────────────────
        snap.gross_margin = _safe_float(info.get("grossMargins"))
        snap.operating_margin = _safe_float(info.get("operatingMargins"))
        snap.net_margin = _safe_float(info.get("profitMargins"))

        # ── Returns ─────────────────────────────────────────────
        snap.roe = _safe_float(info.get("returnOnEquity"))
        # yfinance has no reliable returnOnCapital; ROA is the closest quote field.
        snap.roic = _safe_float(info.get("returnOnCapital"))
        if snap.roic is None:
            snap.roic = _safe_float(info.get("returnOnAssets"))

        # ── Balance sheet ───────────────────────────────────────
        snap.cash = _safe_float(info.get("totalCash"))
        snap.total_debt = _safe_float(info.get("totalDebt"))
        if snap.cash is not None and snap.total_debt is not None:
            snap.net_debt = snap.total_debt - snap.cash
        snap.current_ratio = _safe_float(info.get("currentRatio"))

        # Yahoo reports debtToEquity as a percentage (110.4 == 110.4%, i.e. 1.104x).
        dte_pct = _safe_float(info.get("debtToEquity"))
        if dte_pct is not None:
            snap.debt_to_equity = round(dte_pct / 100.0, 4)

        # ── Valuation ───────────────────────────────────────────
        snap.pe_ratio = _safe_float(info.get("trailingPE"))
        snap.forward_pe = _safe_float(info.get("forwardPE"))
        snap.ev_to_ebitda = _safe_float(info.get("enterpriseToEbitda"))
        snap.price_to_sales = _safe_float(info.get("priceToSalesTrailing12Months"))
        snap.peg_ratio = _safe_float(info.get("pegRatio"))

        fcf = _safe_float(info.get("freeCashflow"))
        market_cap = _safe_float(info.get("marketCap"))
        snap.fcf_yield = _safe_float(info.get("freeCashflowYield"))
        if snap.fcf_yield is None and fcf is not None and market_cap and market_cap > 0:
            snap.fcf_yield = round(fcf / market_cap, 6)

        # ── Income-statement line items ─────────────────────────
        inc = None
        try:
            inc = ticker.income_stmt
        except Exception:
            inc = None

        snap.revenue = _stmt_latest(inc, _REVENUE_ROWS) or _safe_float(
            info.get("totalRevenue")
        )
        snap.net_income = _stmt_latest(inc, _NET_INCOME_ROWS) or _safe_float(
            info.get("netIncomeToCommon")
        )
        snap.ebitda = _safe_float(info.get("ebitda")) or _stmt_latest(inc, _EBITDA_ROWS)

        if snap.total_debt is not None and snap.ebitda is not None and snap.ebitda > 0:
            snap.debt_to_ebitda = round(snap.total_debt / snap.ebitda, 2)
        else:
            snap.debt_to_ebitda = None

        # ── Quality score (simple composite) ────────────────────
        positives = 0
        total = 0
        for v in [
            snap.revenue_growth, snap.eps_growth, snap.roe, snap.roic,
            snap.gross_margin, snap.operating_margin,
        ]:
            if v is not None:
                total += 1
                if v > 0:
                    positives += 1

        if snap.current_ratio is not None:
            total += 1
            if snap.current_ratio >= 1.0:
                positives += 1

        if snap.debt_to_ebitda is not None:
            total += 1
            if snap.debt_to_ebitda < 3.0:
                positives += 1

        if snap.forward_pe is not None and snap.forward_pe > 0:
            total += 1
            if snap.forward_pe < 30:
                positives += 1

        snap.fundamental_quality = (
            round(positives / total, 3) if total > 0 else 0.0
        )

        results[sym] = snap

    return results


def financials_to_df(snapshots: dict[str, FinancialSnapshot]) -> pd.DataFrame:
    """Convert a dict of FinancialSnapshot to a flat DataFrame."""
    rows = []
    for snap in snapshots.values():
        rows.append(
            {
                "symbol": snap.symbol,
                "revenue_growth": snap.revenue_growth,
                "eps_growth": snap.eps_growth,
                "ebitda_growth": snap.ebitda_growth,
                "fcf_growth": snap.fcf_growth,
                "gross_margin": snap.gross_margin,
                "operating_margin": snap.operating_margin,
                "net_margin": snap.net_margin,
                "roe": snap.roe,
                "roic": snap.roic,
                "cash": snap.cash,
                "total_debt": snap.total_debt,
                "net_debt": snap.net_debt,
                "ebitda": snap.ebitda,
                "debt_to_ebitda": snap.debt_to_ebitda,
                "debt_to_equity": snap.debt_to_equity,
                "current_ratio": snap.current_ratio,
                "pe_ratio": snap.pe_ratio,
                "forward_pe": snap.forward_pe,
                "ev_to_ebitda": snap.ev_to_ebitda,
                "price_to_sales": snap.price_to_sales,
                "fcf_yield": snap.fcf_yield,
                "peg_ratio": snap.peg_ratio,
                "net_income": snap.net_income,
                "revenue": snap.revenue,
                "fundamental_quality": snap.fundamental_quality,
                "error": snap.error,
            }
        )
    return pd.DataFrame(rows)