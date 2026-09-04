"""
Scrape the current S&P 500 constituents from Wikipedia and save as
a JSON ticker list for the universe module.

Run:  python -m market.sp500_scraper
"""

import json
import logging
from pathlib import Path

import pandas as pd


OUTPUT_PATH = Path(__file__).parent / "sp500_tickers.json"
WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

log = logging.getLogger(__name__)


def scrape() -> list[str]:
    log.info("Fetching S&P 500 constituents from Wikipedia...")
    tables = pd.read_html(WIKI_URL, storage_options=HEADERS)
    df = tables[0]
    tickers = df["Symbol"].tolist()
    log.info(f"Found {len(tickers)} tickers")
    return tickers


def save_tickers(tickers: list[str], path: Path | None = None) -> Path:
    path = path or OUTPUT_PATH
    with open(path, "w") as f:
        json.dump(tickers, f, indent=2)
    log.info(f"Saved {len(tickers)} tickers to {path}")
    return path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    tickers = scrape()
    save_tickers(tickers)
    print(f"✓ Scraped {len(tickers)} S&P 500 tickers to {OUTPUT_PATH}")