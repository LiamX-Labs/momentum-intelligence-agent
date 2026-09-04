"""
Catalyst detection via Alpaca News API.

Identifies recent news that could explain or sustain observed momentum:
  - Earnings beat / miss
  - Guidance changes
  - Analyst upgrades / downgrades
  - Major contracts / product announcements
  - M&A activity
  - Regulatory events
  - Sector developments

Returns structured catalyst information for LLM consumption.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
from dotenv import load_dotenv

from alpaca.data.historical.news import NewsClient
from alpaca.data.requests import NewsRequest

log = logging.getLogger(__name__)

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
if _ENV_PATH.exists():
    load_dotenv(_ENV_PATH)

_CATALYST_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("earnings_beat", re.compile(r"beat[s]?\s+(?:earnings|estimates|expectations|EPS)", re.I)),
    ("earnings_miss", re.compile(r"miss[esd]?\s+(?:earnings|estimates|expectations|EPS)", re.I)),
    ("guidance_raised", re.compile(r"(?:raised?|increase[d]?|boost[s]?)\s+(?:guidance|forecast|outlook)", re.I)),
    ("guidance_lowered", re.compile(r"(?:lower[sedd]?|cut[s]?|reduce[d]?)\s+(?:guidance|forecast|outlook)", re.I)),
    ("analyst_upgrade", re.compile(r"(?:upgrade[sd]?|initiate[d]?\s+(?:with\s+)?buy|raises?\s+(?:target|rating|price))", re.I)),
    ("analyst_downgrade", re.compile(r"(?:downgrade[sd]?|initiate[d]?\s+(?:with\s+)?sell|lower[s]?\s+(?:target|rating))", re.I)),
    ("major_contract", re.compile(r"(?:major|new|significant|large)\s+(?:contract|deal|partnership|agreement|order)", re.I)),
    ("product_launch", re.compile(r"(?:launch[esd]?|unveil[sedd]?|announce[d]?|release[d]?)\s+(?:new\s+)?(?:product|drug|platform|service)", re.I)),
    ("M_A", re.compile(r"(?:acquisition|acquire[sd]?|merger|merge[sd]?|buyout|takeover)", re.I)),
    ("regulatory", re.compile(r"(?:FDA|approval|authorized|cleared|regulatory|regulation|DOJ|SEC|investigation)", re.I)),
]

_CONCERN_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("layoffs", re.compile(r"(?:layoff[s]?|job\s+cut[s]?|reduction\s+in\s+force|restructuring)", re.I)),
    ("lawsuit", re.compile(r"(?:lawsuit|litigation|sue[sd]?|class\s+action)", re.I)),
    ("supply_chain", re.compile(r"supply\s+chain\s+(?:disruption|issue|shortage|problem|constraint)", re.I)),
    ("debt_issue", re.compile(r"(?:debt\s+(?:crisis|issue|concern)|default|bankruptcy)", re.I)),
]


@dataclass
class CatalystResult:
    symbol: str
    catalyst_flags: list[str] = field(default_factory=list)
    concern_flags: list[str] = field(default_factory=list)
    headline_count: int = 0
    top_headlines: list[str] = field(default_factory=list)
    catalyst_strength: float = 0.0
    error: Optional[str] = None


def _detect_catalysts(headline: str, description: str = "") -> list[str]:
    """Classify a headline into catalyst categories."""
    flags = []
    text = f"{headline} {description}"
    for flag, pattern in _CATALYST_PATTERNS:
        if pattern.search(text):
            flags.append(flag)
    return flags


def _detect_concerns(headline: str, description: str = "") -> list[str]:
    flags = []
    text = f"{headline} {description}"
    for flag, pattern in _CONCERN_PATTERNS:
        if pattern.search(text):
            flags.append(flag)
    return flags


def _yfinance_news_fallback(symbol: str, lookback_days: int = 14) -> list[dict]:
    """Fallback: fetch news headlines via yfinance Ticker.news.

    Returns list of dicts with 'headline' and 'summary' keys.
    """
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        raw_news = ticker.news
        if not raw_news:
            return []
        headlines = []
        cutoff = datetime.now().timestamp() - (lookback_days * 86400)
        for item in raw_news:
            content = item.get("content", {})
            pub_time = content.get("pubDate")
            if pub_time:
                try:
                    pub_ts = pd.Timestamp(pub_time).timestamp()
                except Exception:
                    pub_ts = 0
                if pub_ts < cutoff:
                    continue
            headlines.append({
                "headline": content.get("title", "") or item.get("title", ""),
                "summary": content.get("summary", "") or item.get("summary", ""),
            })
        return headlines
    except Exception:
        return []


def fetch_catalysts(
    symbols: list[str],
    lookback_days: int = 14,
    max_headlines: int = 100,
) -> dict[str, CatalystResult]:
    """Fetch recent news and detect catalysts for a list of symbols.

    Uses the Alpaca News API with a yfinance news fallback.
    """
    results: dict[str, CatalystResult] = {}
    today = datetime.now().date()

    for sym in symbols:
        cr = CatalystResult(symbol=sym)
        results[sym] = cr

        news_items: list[dict] = []

        # ── Primary: Alpaca News API ────────────────────────────
        try:
            import os
            key = os.environ.get("APCA_API_KEY_ID", "")
            secret = os.environ.get("APCA_API_SECRET_KEY", "") or key
            nc = NewsClient(api_key=key, secret_key=secret)

            request = NewsRequest(
                symbols=sym,
                start=datetime.combine(today - timedelta(days=lookback_days), datetime.min.time()),
                end=datetime.combine(today, datetime.max.time()),
                limit=max_headlines,
                include_content=False,
                exclude_contentless=True,
            )

            news_list = nc.get_news(request)
            news_data = news_list.news if hasattr(news_list, "news") else []
            for item in news_data:
                news_items.append({
                    "headline": getattr(item, "headline", ""),
                    "summary": getattr(item, "summary", "") or "",
                })
        except Exception:
            pass

        # ── Fallback: yfinance news ──────────────────────────────
        if not news_items:
            news_items = _yfinance_news_fallback(sym, lookback_days)

        cr.headline_count = len(news_items)
        all_flags: set[str] = set()
        all_concerns: set[str] = set()

        for item in news_items:
            headline = item.get("headline", "")
            summary = item.get("summary", "")
            all_flags.update(_detect_catalysts(headline, summary))
            all_concerns.update(_detect_concerns(headline, summary))
            cr.top_headlines.append(headline)

        cr.catalyst_flags = sorted(all_flags)
        cr.concern_flags = sorted(all_concerns)

        # Strength scoring
        strength = 0.0
        positive_flags = [
            "earnings_beat", "guidance_raised", "analyst_upgrade",
            "major_contract", "product_launch", "M_A",
        ]
        negative_flags = [
            "earnings_miss", "guidance_lowered", "analyst_downgrade",
        ]
        pos_count = sum(1 for f in positive_flags if f in cr.catalyst_flags)
        neg_count = sum(1 for f in negative_flags if f in cr.catalyst_flags)
        concern_count = len(cr.concern_flags)

        strength = min(1.0, max(0.0,
            0.4 * min(cr.headline_count, 10) / 10
            + 0.3 * (pos_count - neg_count) / max(pos_count + neg_count, 1)
            + 0.3 * (1.0 - concern_count / max(concern_count + 1, 1))
        ))
        cr.catalyst_strength = round(strength, 3)

    return results


def catalysts_to_df(results: dict[str, CatalystResult]) -> pd.DataFrame:
    rows = []
    for cr in results.values():
        rows.append(
            {
                "symbol": cr.symbol,
                "catalyst_flags": ",".join(cr.catalyst_flags),
                "concern_flags": ",".join(cr.concern_flags),
                "headline_count": cr.headline_count,
                "top_headlines": " | ".join(cr.top_headlines[:5]),
                "catalyst_strength": cr.catalyst_strength,
                "error": cr.error,
            }
        )
    return pd.DataFrame(rows)