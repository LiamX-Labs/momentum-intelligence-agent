import os
from pathlib import Path

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