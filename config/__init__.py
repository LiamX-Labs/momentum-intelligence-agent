import logging
import os
from pathlib import Path


class _YFinanceNoiseFilter(logging.Filter):
    """Drop yfinance 401/auth noise and delisted-ticker spam — Yahoo
    blocks cloud IPs but yfinance falls back to scraped endpoints.
    BF.B/BRK.B are known delisted share classes."""
    _NOISE = frozenset([
        "Invalid Crumb",
        "Unable to access this feature",
        "possibly delisted",
        "no timezone found",
        "Failed downloads",
    ])

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for noise in self._NOISE:
            if noise in msg:
                return False
        return True


# Apply BEFORE yfinance is imported — once the root logger has handlers,
# all yfinance ERRORs flow through here.
_noise_filter = _YFinanceNoiseFilter()
logging.getLogger().addFilter(_noise_filter)
logging.getLogger("yfinance").addFilter(_noise_filter)
logging.getLogger("urllib3").addFilter(_noise_filter)
logging.getLogger("peewee").setLevel(logging.WARNING)

from dotenv import load_dotenv
import yaml

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
if _ENV_PATH.exists():
    load_dotenv(_ENV_PATH)
else:
    load_dotenv()


_config: dict | None = None
_config_path: Path | None = None


def load_config(path: str | Path | None = None) -> dict:
    global _config, _config_path
    if path is None:
        path = Path(__file__).parent / "config.yaml"
    else:
        path = Path(path)

    with open(path) as f:
        _config = yaml.safe_load(f)
    _config_path = path
    return _config


def get_config() -> dict:
    if _config is None:
        return load_config()
    return _config


def reload_config() -> dict:
    return load_config(_config_path)