"""
Short-term momentum engine.

Calculates for every stock in the universe:
  - Multi-horizon returns (1/3/5/10/20 conceptual "days", scaled by bar_multiplier)
  - Relative strength vs SPY and vs sector
  - Volume metrics (avg volume, relative volume, z-score)
  - Momentum acceleration features
  - Composite momentum score (configurable weights, cross-sectionally normalized)
"""

import pandas as pd
import numpy as np

from config import get_config


LOOKBACK_LABELS = [1, 3, 5, 10, 20]


def _get_scaled_lookbacks() -> list[int]:
    cfg = get_config()
    mult = cfg.get("data", {}).get("bar_multiplier", 1)
    if mult == 1:
        return list(LOOKBACK_LABELS)
    return [max(1, int(lb * mult)) for lb in LOOKBACK_LABELS]


def _lookback_map() -> dict[int, int]:
    scaled = _get_scaled_lookbacks()
    return dict(zip(LOOKBACK_LABELS, scaled))


def compute_returns(df: pd.DataFrame) -> pd.DataFrame:
    """Compute multi-horizon returns per symbol (conceptual lookback labels,
    internally scaled by bar_multiplier for sub-daily intervals)."""
    lb_map = _lookback_map()
    results = []
    for symbol, group in df.groupby("symbol"):
        group = group.sort_values("date").copy()
        close = group["close"]
        for label, periods in lb_map.items():
            group[f"return_{label}d"] = close.pct_change(periods=periods) * 100
        results.append(group)
    return pd.concat(results, ignore_index=True)


def compute_volume_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Compute rolling average volume, relative volume, and volume z-score."""
    mult = get_config().get("data", {}).get("bar_multiplier", 1)
    w5 = max(1, int(5 * mult))
    w20 = max(1, int(20 * mult))
    results = []
    for symbol, group in df.groupby("symbol"):
        group = group.sort_values("date").copy()
        group["avg_volume_5d"] = group["volume"].rolling(w5).mean()
        group["avg_volume_20d"] = group["volume"].rolling(w20).mean()
        group["rel_volume"] = group["volume"] / group["avg_volume_20d"]

        vol_std = group["volume"].rolling(w20).std()
        group["volume_zscore"] = (
            (group["volume"] - group["avg_volume_20d"]) / vol_std.replace(0, np.nan)
        )
        results.append(group)
    return pd.concat(results, ignore_index=True)


def compute_relative_strength(
    df: pd.DataFrame,
    spy_df: pd.DataFrame,
    sector_map: dict[str, str | None] | None = None,
) -> pd.DataFrame:
    """Compute relative return vs SPY and (optionally) vs sector."""
    lb_map = _lookback_map()
    spy_close = spy_df.set_index("date")["close"]
    spy_returns = {}
    for label, periods in lb_map.items():
        spy_returns[label] = spy_close.pct_change(periods=periods) * 100

    symbols = df["symbol"].unique().tolist()
    sector_map = sector_map or {}

    # Build sector-level mean returns for each date
    df_temp = df.copy()
    df_temp["sector"] = df_temp["symbol"].map(sector_map)
    df_temp["sector"] = df_temp["sector"].replace({None: pd.NA, "": pd.NA})

    sector_means: dict[str, dict[str, pd.Series]] = {}
    for lb in LOOKBACK_LABELS:
        col = f"return_{lb}d"
        if col not in df_temp.columns:
            continue
        sector_means[str(lb)] = {}
        for sector, group in df_temp.groupby("sector"):
            if pd.isna(sector):
                continue
            sector_means[str(lb)][sector] = group.groupby("date")[col].mean()

    results = []
    for symbol, group in df.groupby("symbol"):
        group = group.sort_values("date").copy()
        for lb in LOOKBACK_LABELS:
            group[f"relative_strength_{lb}d"] = (
                group[f"return_{lb}d"]
                - group["date"].map(spy_returns[lb])
            )

        sector = sector_map.get(symbol)
        if sector:
            for lb in LOOKBACK_LABELS:
                sm = sector_means.get(str(lb), {}).get(sector)
                if sm is not None:
                    group[f"rel_sector_{lb}d"] = (
                        group[f"return_{lb}d"]
                        - group["date"].map(sm)
                    )
        results.append(group)
    return pd.concat(results, ignore_index=True)


def compute_acceleration(df: pd.DataFrame) -> pd.DataFrame:
    """Compute momentum acceleration/deceleration features."""
    if "return_5d" not in df.columns or "return_10d" not in df.columns:
        return df

    df = df.copy()
    df["accel_5d_vs_10d"] = df["return_5d"] - 0.5 * df["return_10d"]
    df["return_slope"] = df["return_5d"] - df["return_20d"]
    return df


def _winsorize(series: pd.Series, lower: float = 0.01, upper: float = 0.99) -> pd.Series:
    """Clip a series at the given lower/upper quantiles to bound outlier influence."""
    lo = series.quantile(lower)
    hi = series.quantile(upper)
    return series.clip(lower=lo, upper=hi)


def _robust_zscore(series: pd.Series) -> pd.Series:
    """Normalize cross-sectionally using median and MAD (median absolute deviation).

    Robust to outliers — a single extreme value won't compress the rest of the distribution.
    """
    median = series.median()
    mad = (series - median).abs().median()
    if mad == 0 or np.isnan(mad):
        return pd.Series(0.0, index=series.index)
    return 0.6745 * (series - median) / mad


def _cross_sectional_zscore(series: pd.Series, robust: bool = False) -> pd.Series:
    """Normalize a series cross-sectionally to z-scores.

    If robust=True, uses median/MAD instead of mean/std.
    """
    if robust:
        return _robust_zscore(series)
    mean = series.mean()
    std = series.std()
    if std == 0 or np.isnan(std):
        return pd.Series(0.0, index=series.index)
    return (series - mean) / std


def compute_momentum_score(df: pd.DataFrame, latest_only: bool = True) -> pd.DataFrame:
    """
    Compute composite momentum score with configurable weights.

    Weights (configurable in momentum.weights):
        return_5d:       30%
        return_10d:      25%
        return_20d:      20%
        relative_strength: 15%  (uses vs SPY, 5d)
        volume:          10%

    Outlier handling (configurable in momentum.scoring):
        winsorize:       clip factor values at winsor_lower / winsor_upper quantiles
        robust:          use median/MAD instead of mean/std for z-score normalization

    Each factor is cross-sectionally normalized (z-score) before combining.
    The final score is min-max scaled to 0-100.
    The rank is per-date (rank 1 = highest score on that date).
    """
    cfg = get_config()
    w = cfg["momentum"]["weights"]
    scoring = cfg.get("momentum", {}).get("scoring", {})
    do_winsor = scoring.get("winsorize", False)
    w_lower = scoring.get("winsor_lower", 0.01)
    w_upper = scoring.get("winsor_upper", 0.99)
    robust = scoring.get("robust", False)

    df = df.copy()

    def _z(series: pd.Series) -> pd.Series:
        s = series.astype(float)
        if do_winsor:
            s = _winsorize(s, lower=w_lower, upper=w_upper)
        return _cross_sectional_zscore(s, robust=robust)

    factors = {}

    if "return_5d" in df.columns:
        factors["return_5d"] = _z(df["return_5d"])

    if "return_10d" in df.columns:
        factors["return_10d"] = _z(df["return_10d"])

    if "return_20d" in df.columns:
        factors["return_20d"] = _z(df["return_20d"])

    if "relative_strength_5d" in df.columns:
        factors["relative_strength"] = _z(df["relative_strength_5d"])
    elif "relative_strength_10d" in df.columns:
        factors["relative_strength"] = _z(df["relative_strength_10d"])

    if "volume_zscore" in df.columns:
        factors["volume"] = df["volume_zscore"].fillna(0)
    elif "rel_volume" in df.columns:
        factors["volume"] = _z(df["rel_volume"])

    raw_score = pd.Series(0.0, index=df.index)
    for factor_name, weight in w.items():
        if factor_name in factors:
            raw_score += weight * factors[factor_name]

    df["momentum_raw"] = raw_score
    df["momentum_score"] = _cross_sectional_zscore(raw_score, robust=robust)
    df["momentum_score"] = (
        (df["momentum_score"] - df["momentum_score"].min())
        / (df["momentum_score"].max() - df["momentum_score"].min())
    ) * 100

    df["momentum_rank"] = df.groupby("date")["momentum_score"].rank(
        ascending=False, method="min"
    )

    return df


def run_momentum_engine(
    df: pd.DataFrame,
    spy_df: pd.DataFrame,
    sector_map: dict[str, str | None] | None = None,
) -> pd.DataFrame:
    """
    Full momentum pipeline:
    1. Compute returns
    2. Compute volume metrics
    3. Compute relative strength vs SPY (and vs sector if map provided)
    4. Compute acceleration features
    5. Compute composite momentum score
    """
    df = compute_returns(df)
    df = compute_volume_metrics(df)
    df = compute_relative_strength(df, spy_df, sector_map=sector_map)
    df = compute_acceleration(df)
    df = compute_momentum_score(df)
    return df