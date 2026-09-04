"""
Momentum Intelligence Agent — Main entry point.

Phase A: Core Trading Engine (quantitative screening)
Phase B: Fundamental Intelligence (financials, earnings, catalysts)
Phase C: Dual-Model AI (K2 Analyst → Qwen Critic)
Phase D: Deterministic Risk & Decision Engine
Phase E: Options Selector & Paper Execution

Architecture:
  K2 (Kimi K2-Instruct) — primary analyst, builds trading thesis
  Qwen (Qwen3-32B) — independent adversarial critic
  Python — deterministic risk engine + options selector + execution
"""

import json
import logging
import threading
from datetime import date, datetime, timedelta

import pandas as pd

from config import load_config
from market.universe import get_universe
from market.alpaca_data import fetch_bars
from market.technicals import compute_all_technicals
from market.momentum import run_momentum_engine
from market.regime import classify_regime

from fundamentals.financials import fetch_financials, financials_to_df
from fundamentals.earnings import fetch_earnings, earnings_to_df, should_reject_for_earnings
from fundamentals.news import fetch_catalysts, catalysts_to_df

from agents.analyst import run_analyst
from agents.critic import run_critic
from agents.reporter import run_reporter
from intelligence.schemas import K2AnalystOutput, QwenCriticOutput, ReporterOutput

from risk.validator import validate_trade, ValidationResult
from risk.limits import LimitCheckResult
from market.alpaca_data import get_account, get_positions
from fundamentals.earnings import EarningsSnapshot

from options.chain import fetch_option_chain
from options.selector import select_contract, SelectionResult
from options.greeks import approximate_delta
from risk.sizing import calculate_position_size, PositionSizeResult
from trading.execution import (
    build_order_request,
    execute_order,
    ExecutionResult,
)

from agents.monitor import (
    PositionRecord,
    MonitorResult,
    check_exit_conditions,
)
from trading.positions import liquidate_position, ExitResult
from database.repository import (
    record_candidate,
    record_entry,
    record_exit,
    record_order_fill,
    get_open_trades,
    get_performance_summary,
    update_candidate_gates,
    record_cycle_report,
    get_recent_candidate_for_symbol,
    get_cycle_count,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


def _fetch_vix() -> float | None:
    """Fetch current VIX close from yfinance. Returns None on failure."""
    import yfinance as yf
    end = date.today()
    start = end - timedelta(days=5)
    try:
        vix_data = yf.download("^VIX", start=start, end=end, progress=False, auto_adjust=True)
        if not vix_data.empty:
            return float(vix_data["Close"].iloc[-1])
    except Exception:
        pass
    return None


def run_cycle(lookback_days: int = 70) -> dict:
    cfg = load_config()
    run_id = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    demo_cfg = cfg.get("demo", {})
    demo_mode = demo_cfg.get("enabled", False)
    if demo_mode:
        log.info("=" * 65)
        log.info("  D E M O   M O D E   A C T I V E")
        log.info("  Qwen critic is advisory-only — concerns are logged but do not block trades")
        log.info("=" * 65)

    data_interval = cfg.get("data", {}).get("interval", "1d")
    bar_mult = cfg.get("data", {}).get("bar_multiplier", 1)
    spy_lookback_bars = cfg.get("data", {}).get("spy_lookback_bars", 800)
    lookback_bars = cfg.get("data", {}).get("lookback_bars", 400)

    log.info("=" * 65)
    log.info("PHASE A — Core Trading Engine")
    log.info("=" * 65)
    log.info(f"   Bar interval: {data_interval} (multiplier={bar_mult}, "
             f"lookback={lookback_bars} bars, spy_lookback={spy_lookback_bars} bars)")

    # 1. Load universe
    log.info("1. Loading S&P 500 universe...")
    universe = get_universe()
    log.info(f"   Universe size: {len(universe)} tickers")

    # 1b. Pre-load sector cache in background (runs concurrently with
    #     market data download so it doesn't add latency)
    sector_map: dict[str, str | None] = {}
    sector_thread: threading.Thread | None = None

    def _load_sectors() -> None:
        from market.sectors import get_sector_map
        nonlocal sector_map
        loaded = get_sector_map(universe)
        sector_map.update(loaded)
        assigned = sum(1 for v in loaded.values() if v)
        log.info(f"   Sector cache: {assigned}/{len(universe)} tickers mapped")

    sector_thread = threading.Thread(target=_load_sectors, daemon=True)
    sector_thread.start()

    end_date = date.today()
    end_dt = datetime.now()

    # 2. Fetch SPY with long history for accurate regime EMAs
    sp_days = max(365, spy_lookback_bars // max(1, bar_mult) * 2)
    log.info(f"2. Fetching SPY ({spy_lookback_bars} {data_interval} bars, ~{sp_days}d window)...")
    spy_df = fetch_bars(
        ["SPY", "AAPL"],
        start=end_dt - timedelta(days=sp_days),
        end=end_dt,
        interval=data_interval,
    )
    spy_df = spy_df[spy_df["symbol"] == "SPY"].copy()
    spy_df = compute_all_technicals(spy_df)
    log.info(f"   SPY: {len(spy_df)} bars")

    # 3. Fetch universe bars
    un_days = max(365, lookback_bars // max(1, bar_mult) * 2)
    log.info(f"3. Fetching universe bars ({lookback_bars} {data_interval} bars, ~{un_days}d window)...")
    universe_df = fetch_bars(
        universe,
        start=end_dt - timedelta(days=un_days),
        end=end_dt,
        interval=data_interval,
    )
    if universe_df.empty:
        log.error("No market data returned from Alpaca.")
        return {}

    log.info(f"   Fetched {len(universe_df)} bar records across {universe_df['symbol'].nunique()} symbols")

    if spy_df.empty:
        log.error("SPY data is empty — cannot compute relative strength.")
        return {}

    # 4. Compute technicals
    log.info("4. Computing technical indicators (EMA 5/10/20/50, RSI, ATR)...")
    universe_df = compute_all_technicals(universe_df)

    # 5. Run momentum engine (wait for sector cache to finish loading)
    log.info("5. Running momentum engine...")
    if sector_thread:
        sector_thread.join(timeout=60)
    momentum_df = run_momentum_engine(
        universe_df, spy_df, sector_map=sector_map if sector_map else None
    )

    # 6. Get latest date
    latest_date = momentum_df["date"].max()
    latest = momentum_df[momentum_df["date"] == latest_date].copy()
    log.info(f"   Latest data date: {latest_date}")

    # 7. Market regime — per build plan Section 16
    log.info("6. Classifying market regime...")
    vix_value = _fetch_vix()
    regime_result = classify_regime(spy_df, universe_df, vix=vix_value)
    log.info(
        f"   Regime: {regime_result.regime.value.upper()} "
        f"(max exposure: {regime_result.max_exposure:.0%})"
    )

    # 8. Rank candidates
    log.info("7. Ranking candidates by momentum score...")
    candidate_count = cfg["momentum"]["candidate_count"]
    min_score = cfg["decision"]["min_momentum_score"]

    ranked = latest.sort_values("momentum_score", ascending=False)
    qualified = ranked[ranked["momentum_score"] >= min_score]
    top_n = qualified.head(candidate_count)

    display_cols = [
        "symbol", "momentum_score", "momentum_rank",
        "return_5d", "return_10d", "return_20d",
        "relative_strength_5d", "rel_volume", "rsi_14",
    ]
    available_cols = [c for c in display_cols if c in top_n.columns]

    log.info(f"\n{'─'*65}")
    log.info(f"PHASE A RESULT — Top {len(top_n)} momentum candidates "
             f"(min_score={min_score}, regime={regime_result.regime.value.upper()})")
    log.info(f"{'─'*65}")
    for _, row in top_n.iterrows():
        parts = []
        for col in available_cols:
            val = row[col]
            parts.append(f"{col}={val:.1f}" if isinstance(val, float) else f"{col}={val}")
        log.info(f"  {row['symbol']:6s} | {' | '.join(parts)}")

    if top_n.empty:
        log.warning("No candidates passed the momentum threshold.")
        return {
            "candidates_df": momentum_df,
            "regime_result": regime_result,
            "top_n_df": top_n,
            "latest_date": latest_date,
            "enriched_df": pd.DataFrame(),
        }

    # ==================================================================
    # PHASE B — Fundamental Intelligence
    # ==================================================================
    log.info(f"\n{'='*65}")
    log.info(f"PHASE B — Fundamental Intelligence for {len(top_n)} candidates")
    log.info(f"{'='*65}")

    candidate_symbols = top_n["symbol"].tolist()

    # B1 — Financials
    log.info("B1. Fetching financial data...")
    financials = fetch_financials(candidate_symbols)
    fin_df = financials_to_df(financials)
    log.info(f"    Fetched {len(financials)} financial snapshots")

    # B2 — Earnings
    log.info("B2. Fetching earnings data...")
    earnings = fetch_earnings(candidate_symbols)
    earn_df = earnings_to_df(earnings)
    earnings_rejections = 0
    for sym, snap in earnings.items():
        if should_reject_for_earnings(snap, holding_days=cfg["risk"]["max_holding_days"]):
            log.warning(f"    ⚠ {sym}: earnings within holding period — would reject under MVP policy")
            earnings_rejections += 1
    log.info(f"    Fetched {len(earnings)} earnings snapshots "
             f"({earnings_rejections} with imminent earnings)")

    # B3 — Catalysts
    log.info("B3. Fetching news/catalyst data...")
    catalysts = fetch_catalysts(candidate_symbols)
    cat_df = catalysts_to_df(catalysts)
    total_headlines = sum(c.headline_count for c in catalysts.values())
    log.info(f"    Fetched {total_headlines} headlines across {len(catalysts)} symbols")

    # Merge enriched data
    enriched = top_n.copy()
    enriched = enriched.merge(
        fin_df[["symbol", "revenue_growth", "eps_growth", "gross_margin",
                 "operating_margin", "roe", "forward_pe", "pe_ratio",
                 "debt_to_ebitda", "debt_to_equity", "ebitda", "total_debt",
                 "fcf_yield", "ev_to_ebitda", "current_ratio",
                 "fundamental_quality", "net_income", "revenue"]],
        on="symbol", how="left",
    )
    enriched = enriched.merge(
        earn_df[["symbol", "latest_eps", "eps_surprise",
                  "next_earnings_date", "earnings_quarterly_growth"]],
        on="symbol", how="left",
    )
    enriched = enriched.merge(
        cat_df[["symbol", "catalyst_flags", "concern_flags",
                 "headline_count", "catalyst_strength"]],
        on="symbol", how="left",
    )

    # Display enriched profiles (Phase B summary)
    log.info(f"\n{'─'*65}")
    log.info(f"PHASE B RESULT — Enriched Candidate Profiles")
    log.info(f"{'─'*65}")
    for _, row in enriched.iterrows():
        log.info(f"  ◆ {row['symbol']} | momentum={row['momentum_score']:.0f} | "
                 f"fund_quality={row.get('fundamental_quality', 0):.2f} | "
                 f"catalyst_strength={row.get('catalyst_strength', 0):.2f}")

    # ==================================================================
    # PHASE C — Dual-Model AI: K2 Analyst → Qwen Critic
    # ==================================================================
    log.info(f"\n{'='*65}")
    log.info(f"PHASE C — Dual-Model AI")
    k2_model = cfg["models"]["primary"]["model"]
    qwen_model = cfg["models"]["critic"]["model"]
    log.info(f"  Primary Analyst: {k2_model}")
    log.info(f"  Adversarial Critic: {qwen_model}")
    log.info(f"{'='*65}")

    regime_label = regime_result.regime.value.upper()
    ai_results: list[dict] = []
    hr = cfg["hard_reject"]

    for _, row in enriched.iterrows():
        sym = row["symbol"]

        # ── Build raw evidence dicts (same for both agents) ──────────
        momentum_data = {
            "momentum_score": round(float(row["momentum_score"]), 1),
            "momentum_rank": int(row["momentum_rank"]),
            "return_5d_pct": round(float(row.get("return_5d", 0) or 0), 1),
            "return_10d_pct": round(float(row.get("return_10d", 0) or 0), 1),
            "return_20d_pct": round(float(row.get("return_20d", 0) or 0), 1),
            "relative_strength_5d_pct": round(float(row.get("relative_strength_5d", 0) or 0), 1),
            "rel_volume": round(float(row.get("rel_volume", 0) or 0), 2),
            "volume_zscore": round(float(row.get("volume_zscore", 0) or 0), 2),
            "rsi_14": round(float(row.get("rsi_14", 0) or 0), 1),
            "atr_pct": round(float(row.get("atr_pct", 0) or 0), 2),
        }

        fundamental_data = {
            "fundamental_quality": round(float(row.get("fundamental_quality", 0) or 0), 2),
            "revenue_growth": row.get("revenue_growth"),
            "eps_growth": row.get("eps_growth"),
            "gross_margin": row.get("gross_margin"),
            "operating_margin": row.get("operating_margin"),
            "roe": row.get("roe"),
            "forward_pe": row.get("forward_pe"),
            "pe_ratio": row.get("pe_ratio"),
            "ev_to_ebitda": row.get("ev_to_ebitda"),
            "fcf_yield": row.get("fcf_yield"),
            "ebitda": row.get("ebitda"),
            "total_debt": row.get("total_debt"),
            "debt_to_ebitda": row.get("debt_to_ebitda"),
            "debt_to_equity": row.get("debt_to_equity"),
            "current_ratio": row.get("current_ratio"),
            "net_income": row.get("net_income"),
            "revenue": row.get("revenue"),
        }

        earnings_data = {
            "latest_eps": row.get("latest_eps"),
            "eps_surprise": row.get("eps_surprise"),
            "earnings_quarterly_growth": row.get("earnings_quarterly_growth"),
            "next_earnings_date": str(row.get("next_earnings_date", "")),
        }

        catalyst_data = {
            "catalyst_flags": row.get("catalyst_flags", ""),
            "concern_flags": row.get("concern_flags", ""),
            "headline_count": row.get("headline_count", 0),
            "catalyst_strength": round(float(row.get("catalyst_strength", 0) or 0), 2),
        }

        # ── Cooldown: skip symbols analyzed within the last 4 hours ──
        recent = get_recent_candidate_for_symbol(sym, within_cycles=1)
        if recent:
            try:
                last_run_id = recent.get("run_id", "")
                last_run_time = datetime.fromisoformat(last_run_id)
                hours_since = (datetime.now() - last_run_time).total_seconds() / 3600
                if hours_since < 4:
                    log.info(f"\n  ▶ {sym} — on cooldown "
                             f"(last analyzed {hours_since:.1f}h ago, "
                             f"skip until {4 - hours_since:.1f}h remaining)")
                    continue
            except (ValueError, TypeError):
                pass  # unparseable timestamp — proceed with fresh analysis

        # ── Active position check: don't trade a symbol we already hold ──
        open_trades = get_open_trades()
        active_symbols = {t["symbol"] for t in open_trades}
        if sym in active_symbols:
            log.info(f"\n  ▶ {sym} — skipping, already have an active position")
            continue

        # ── Step 1: K2 Analyst ──────────────────────────────────────
        log.info(f"\n  ▶ {sym} — K2 Analyst...")
        k2 = run_analyst(
            symbol=sym,
            momentum=momentum_data,
            fundamentals=fundamental_data,
            earnings=earnings_data,
            catalysts=catalyst_data,
            regime=regime_label,
            model=k2_model,
        )

        if k2 is None:
            log.warning(f"    ✗ K2 failed for {sym} — skipping")
            continue

        log.info(f"    ✓ K2: {k2.direction} | conf={k2.confidence:.2f} | "
                 f"thesis: {k2.thesis[:90]}...")

        # ── Step 2: Qwen Critic (receives K2 thesis + raw evidence) ─
        log.info(f"    ▶ {sym} — Qwen Critic...")
        qwen = run_critic(
            symbol=sym,
            k2_output=k2,
            momentum=momentum_data,
            fundamentals=fundamental_data,
            earnings=earnings_data,
            catalysts=catalyst_data,
            model=qwen_model,
        )

        if qwen is None:
            log.warning(f"    ✗ Qwen failed for {sym} — using fallback rejection")
            qwen = QwenCriticOutput(
                symbol=sym,
                recommendation="REJECT",
                thesis_valid=False,
                adjusted_confidence=0.0,
                risk_score=1.0,
                momentum_assessment="WEAK",
                fundamental_assessment="NEGATIVE",
                catalyst_assessment="NEGATIVE",
                concerns=["Qwen critic failed — automatic rejection for safety"],
            )

        qwen_rec = "✓ APPROVE" if qwen.recommendation == "APPROVE" else "✗ REJECT"
        log.info(f"    {qwen_rec} | thesis_valid={qwen.thesis_valid} | "
                 f"adj_conf={qwen.adjusted_confidence:.2f} | "
                 f"risk={qwen.risk_score:.2f}")
        log.info(f"    momentum={qwen.momentum_assessment} | "
                 f"fundamental={qwen.fundamental_assessment} | "
                 f"catalyst={qwen.catalyst_assessment}")
        for c in qwen.concerns[:3]:
            log.info(f"      · {c}")

        # ── Step 3: Deterministic Decision Engine ───────────────────
        reject_reason = None

        demo_cfg = cfg.get("demo", {})
        demo_mode = demo_cfg.get("enabled", False)
        qwen_advisory = demo_cfg.get("qwen_advisory_only", True) and demo_mode
        override_risk = demo_cfg.get("override_risk_gates", True) and demo_mode

        # Hard reject rule: Qwen says REJECT
        if hr["qwen_recommendation_reject"] and qwen.is_rejected:
            if qwen_advisory:
                log.info(f"    ⚠ DEMO: Qwen rejected but advisory-only — "
                         f"logging concerns without blocking")
            else:
                reject_reason = f"Qwen rejected: recommendation={qwen.recommendation}, thesis_valid={qwen.thesis_valid}"

        # Hard reject rule: Qwen adjusted confidence too low
        if not reject_reason and qwen.adjusted_confidence < hr["qwen_confidence_below"]:
            if qwen_advisory:
                log.info(f"    ⚠ DEMO: Qwen confidence {qwen.adjusted_confidence:.2f} "
                         f"below threshold — advisory only")
            else:
                reject_reason = f"Qwen adjusted confidence {qwen.adjusted_confidence:.2f} below threshold {hr['qwen_confidence_below']}"

        # Hard reject rule: momentum too low
        if not reject_reason and float(row["momentum_score"]) < hr["momentum_below"]:
            reject_reason = f"Momentum score {row['momentum_score']:.0f} below {hr['momentum_below']}"

        # Hard reject rule: Qwen risk too high
        if not reject_reason and qwen.risk_score > hr["risk_score_above"]:
            if override_risk:
                log.info(f"    ⚠ DEMO: Qwen risk score {qwen.risk_score:.2f} "
                         f"above threshold — gate overridden")
            else:
                reject_reason = f"Qwen risk score {qwen.risk_score:.2f} above threshold {hr['risk_score_above']}"

        # Compute final score
        fsc = cfg["final_scoring"]
        final_score = (
            fsc["momentum_weight"] * (float(row["momentum_score"]) / 100)
            + fsc["relative_strength_weight"] * max(0, min(1,
                float(row.get("relative_strength_5d", 0) or 0) / 25 + 0.5))
            + fsc["fundamental_quality_weight"] * k2.fundamental_quality
            + fsc["catalyst_weight"] * k2.catalyst_strength
            + fsc["k2_confidence_weight"] * k2.confidence
            + fsc["qwen_adjusted_confidence_weight"] * qwen.adjusted_confidence
        )

        approved = reject_reason is None
        if approved and not demo_mode and k2.confidence < cfg["ai"]["min_confidence"]:
            reject_reason = f"K2 confidence {k2.confidence:.2f} below min {cfg['ai']['min_confidence']}"
            approved = False

        if approved:
            log.info(f"    ✅ APPROVED | final_score={final_score:.2f}")
        else:
            log.info(f"    ❌ REJECTED | reason: {reject_reason}")

        ai_results.append({
            "symbol": sym,
            "k2": k2,
            "qwen": qwen,
            "final_score": round(final_score, 3),
            "approved": approved,
            "reject_reason": reject_reason,
            "momentum_score": float(row["momentum_score"]),
        })

        # Journal: record candidate evaluation (full debate payload —
        # no truncation — so the dashboard can render the complete
        # K2 vs Qwen adversarial thesis exchange).
        record_candidate(
            symbol=sym,
            momentum_score=float(row["momentum_score"]),
            direction=k2.direction,
            k2_confidence=k2.confidence,
            qwen_recommendation=qwen.recommendation,
            qwen_confidence=qwen.adjusted_confidence,
            final_score=round(final_score, 3),
            approved=approved,
            reject_reason=reject_reason,
            thesis=k2.thesis,
            regime=regime_label,
            run_id=run_id,
            k2=k2.model_dump(),
            qwen=qwen.model_dump(),
            evidence={
                "momentum": momentum_data,
                "fundamentals": fundamental_data,
                "earnings": earnings_data,
                "catalysts": catalyst_data,
            },
        )

    # Phase C summary
    approved_count = sum(1 for r in ai_results if r["approved"])
    log.info(f"\n{'─'*65}")
    log.info(f"PHASE C RESULT — Dual-Model AI Analysis Complete")
    log.info(f"{'─'*65}")
    log.info(f"  Candidates analyzed : {len(ai_results)}")
    log.info(f"  K2+Qwen approved    : {approved_count}")
    log.info(f"  K2+Qwen rejected    : {len(ai_results) - approved_count}")
    log.info(f"{'─'*65}")
    for r in ai_results:
        mark = "✅" if r["approved"] else "❌"
        k2: K2AnalystOutput | None = r["k2"]
        qwen: QwenCriticOutput | None = r["qwen"]
        if k2 and qwen:
            log.info(f"  [{mark}] {r['symbol']:6s} | {k2.direction:4s} | "
                     f"K2_conf={k2.confidence:.2f} | "
                     f"Qwen_rec={'APPROVE' if qwen.recommendation == 'APPROVE' else 'REJECT'} | "
                     f"Qwen_adj={qwen.adjusted_confidence:.2f} | "
                     f"final={r['final_score']:.2f}")
            log.info(f"         K2 thesis: {k2.thesis[:130]}")
            if r["reject_reason"]:
                log.info(f"         Reject: {r['reject_reason']}")
            log.info(f"         Qwen assessments: momentum={qwen.momentum_assessment} | "
                     f"fund={qwen.fundamental_assessment} | catalyst={qwen.catalyst_assessment}")
        else:
            log.info(f"  [{mark}] {r['symbol']:6s} | "
                     f"final={r['final_score']:.2f}")

    log.info(f"\n{'='*65}")
    log.info("Phase A + B + C complete. Ready for Phase R (Cycle Reporter).")
    log.info(f"{'='*65}")

    # ==================================================================
    # PHASE R — Cycle Reporter (AI summary of all decisions)
    # ==================================================================
    log.info(f"\n{'='*65}")
    log.info(f"PHASE R — Cycle Reporter")
    log.info(f"{'='*65}")

    reporter_model = cfg.get("models", {}).get("reporter", {}).get("model", "deepseek-ai/DeepSeek-V3.2")
    cycle_number = get_cycle_count()

    reporter_decisions: list[dict] = []
    for r in ai_results:
        k2: K2AnalystOutput | None = r["k2"]
        qwen: QwenCriticOutput | None = r["qwen"]
        if k2 is None or qwen is None:
            continue
        reporter_decisions.append({
            "symbol": r["symbol"],
            "approved": r["approved"],
            "direction": k2.direction,
            "k2_confidence": k2.confidence,
            "k2_thesis": k2.thesis[:200],
            "qwen_recommendation": qwen.recommendation,
            "qwen_adjusted_confidence": qwen.adjusted_confidence,
            "qwen_risk_score": qwen.risk_score,
            "qwen_concerns": qwen.concerns,
            "qwen_contradictions": qwen.contradictions,
            "final_score": r["final_score"],
            "reject_reason": r.get("reject_reason"),
            "momentum_score": r["momentum_score"],
        })

    log.info(f"  Sending {len(reporter_decisions)} candidate decisions to reporter...")
    report = run_reporter(
        cycle_number=cycle_number,
        regime=regime_label,
        decisions=reporter_decisions,
        model=reporter_model,
    )

    if report:
        log.info(f"  ✓ Reporter summary ({len(report.summary)} chars):")
        for line in report.summary.split("\n")[:8]:
            log.info(f"    {line[:120]}")
        record_cycle_report(
            run_id=run_id,
            cycle_number=report.cycle_number,
            regime=report.regime,
            total_candidates=report.total_candidates,
            total_approved=report.total_approved,
            total_rejected=report.total_rejected,
            summary=report.summary,
            verdicts=[v.model_dump() for v in report.verdicts],
        )
        log.info(f"    Reporter recorded {len(report.verdicts)} verdicts")
    else:
        log.warning("  ✗ Reporter failed — continuing without cycle summary")

    log.info(f"\n{'='*65}")
    log.info("Phase A + B + C + R complete. Ready for Phase D (Risk & Decision Engine).")
    log.info(f"{'='*65}")

    # ==================================================================
    # PHASE D — Deterministic Risk & Decision Engine
    # ==================================================================
    log.info(f"\n{'='*65}")
    log.info(f"PHASE D — Deterministic Risk & Decision Engine")
    log.info(f"{'='*65}")

    # Fetch account state
    try:
        account = get_account()
        account_equity = float(account.get("equity", account.get("cash", 100000)))
        log.info(f"  Account equity: ${account_equity:,.0f}")
    except Exception:
        account_equity = 100_000.0
        log.info(f"  Account equity: ${account_equity:,.0f} (assumed — Alpaca unavailable)")

    try:
        positions = get_positions()
        current_positions_count = len(positions)
        current_exposure = sum(float(p.get("market_value", 0) or 0) for p in positions)
        current_premium = sum(
            float(p.get("cost_basis", 0) or 0) for p in positions
            if p.get("asset_class") == "us_option" or "option" in str(p.get("symbol", "")).lower()
        )
    except Exception:
        current_positions_count = 0
        current_exposure = 0.0
        current_premium = 0.0

    log.info(f"  Open positions   : {current_positions_count}")
    log.info(f"  Current exposure : ${current_exposure:,.0f}")
    log.info(f"  Option premium   : ${current_premium:,.0f}")

    approved_ai = [r for r in ai_results if r["approved"]]
    validated_trades: list[dict] = []

    if not approved_ai:
        log.info(f"\n  No AI-approved candidates to validate.")
    else:
        log.info(f"\n  Running {len(approved_ai)} AI-approved candidates through deterministic gates...")

        for r in approved_ai:
            sym = r["symbol"]
            k2: K2AnalystOutput = r["k2"]
            qwen: QwenCriticOutput = r["qwen"]

            log.info(f"\n  ── {sym} ──────────────────────────────────────────────")

            # Get earnings snapshot for this symbol
            earnings_snap = earnings.get(sym)

            # Use a placeholder option premium for risk validation
            # (real option chain selection happens in Phase E)
            if account_equity > 0:
                placeholder_premium = max(0.50, account_equity * 0.001 / 100)
            else:
                placeholder_premium = 5.00

            validation = validate_trade(
                symbol=sym,
                direction=k2.direction,
                k2_confidence=k2.confidence,
                qwen_recommendation=qwen.recommendation,
                qwen_confidence=qwen.adjusted_confidence,
                qwen_risk_score=qwen.risk_score,
                momentum_score=r["momentum_score"],
                final_score=r["final_score"],
                account_equity=account_equity,
                current_positions=current_positions_count,
                current_exposure=current_exposure,
                current_premium=current_premium,
                option_premium=placeholder_premium,
                regime_result=regime_result,
                earnings=earnings_snap,
            )

            # Display gate-by-gate results
            for gate_name, gate_passed, gate_detail in validation.gates:
                mark = "✅" if gate_passed else "❌"
                log.info(f"    {mark} {gate_name:20s} | {gate_detail}")

            if not validation.approved:
                log.info(f"    ❌ REJECTED — {validation.reason}")
                validated_trades.append({
                    "symbol": sym,
                    "k2": k2,
                    "qwen": qwen,
                    "approved": False,
                    "reason": validation.reason,
                    "gates": validation.gates,
                })
                update_candidate_gates(
                    symbol=sym,
                    run_id=run_id,
                    gates=validation.gates,
                    risk_approved=False,
                    risk_reason=validation.reason,
                )
                continue

            # Show position sizing
            if validation.position_size:
                sizing = validation.position_size
                log.info(f"    ✅ APPROVED — {sizing.max_contracts} contracts "
                         f"at ${sizing.cost_per_contract:.0f}/contract "
                         f"(total risk: ${sizing.total_cost:.0f}, "
                         f"{sizing.risk_pct:.1%} of portfolio)")

            validated_trades.append({
                "symbol": sym,
                "k2": k2,
                "qwen": qwen,
                "approved": True,
                "reason": "All gates passed",
                "gates": validation.gates,
                "position_size": validation.position_size,
            })
            update_candidate_gates(
                symbol=sym,
                run_id=run_id,
                gates=validation.gates,
                risk_approved=True,
                risk_reason="All gates passed",
                position_size={
                    "max_contracts": validation.position_size.max_contracts,
                    "cost_per_contract": validation.position_size.cost_per_contract,
                    "total_cost": validation.position_size.total_cost,
                    "risk_pct": validation.position_size.risk_pct,
                } if validation.position_size else None,
            )

            # Update running totals for subsequent validations
            current_positions_count += 1
            if validation.position_size:
                current_exposure += validation.position_size.total_cost
                current_premium += validation.position_size.total_cost

    # Phase D summary
    approved_count = sum(1 for t in validated_trades if t["approved"])
    log.info(f"\n{'─'*65}")
    log.info(f"PHASE D RESULT — Risk & Decision Engine")
    log.info(f"{'─'*65}")
    log.info(f"  AI-approved candidates : {len(approved_ai)}")
    log.info(f"  Risk-approved trades   : {approved_count}")
    log.info(f"  Risk-rejected trades   : {len(validated_trades) - approved_count}")
    log.info(f"{'─'*65}")
    for t in validated_trades:
        mark = "✅" if t["approved"] else "❌"
        k2: K2AnalystOutput = t["k2"]
        ps = t.get("position_size")
        if ps:
            log.info(f"  [{mark}] {t['symbol']:6s} | {k2.direction:4s} | "
                     f"{ps.max_contracts} contracts | "
                     f"risk=${ps.total_cost:.0f} | "
                     f"K2_conf={k2.confidence:.2f}")
        else:
            log.info(f"  [{mark}] {t['symbol']:6s} | {k2.direction:4s} | "
                     f"REJECTED: {t['reason']}")

    log.info(f"\n{'='*65}")
    log.info("Phase A + B + C + D complete. Ready for Phase E (Options Selector & Execution).")
    log.info(f"{'='*65}")

    # ==================================================================
    # PHASE E — Options Selector & Paper Execution
    # ==================================================================
    risk_approved = [t for t in validated_trades if t["approved"]]
    executed_trades: list[dict] = []

    if not risk_approved:
        log.info(f"\n{'='*65}")
        log.info(f"PHASE E — Options Selector & Execution")
        log.info(f"{'='*65}")
        log.info(f"  No risk-approved trades to execute.")
    else:
        log.info(f"\n{'='*65}")
        log.info(f"PHASE E — Options Selector & Execution for {len(risk_approved)} trades")
        log.info(f"{'='*65}")

        for t in risk_approved:
            sym = t["symbol"]
            k2: K2AnalystOutput = t["k2"]
            ps: PositionSizeResult = t["position_size"]
            direction = k2.direction
            direction_label = "CALL" if direction == "CALL" else "PUT"

            log.info(f"\n  ── {sym} ({direction_label}) ────────────────────────────────")

            # Use the latest close as approximate underlying price
            underlying_price = None
            symbol_rows = enriched[enriched["symbol"] == sym]
            if not symbol_rows.empty:
                underlying_price = float(symbol_rows.iloc[0].get("close", 0))

            # E1: Fetch option chain
            log.info(f"    Fetching option chain (underlying ~${underlying_price or '?'})...")
            contracts = fetch_option_chain(
                symbol=sym,
                direction=direction_label,
                min_dte=cfg["options"]["min_dte"],
                max_dte=cfg["options"]["max_dte"],
            )

            if not contracts:
                log.warning(f"    No option contracts found for {sym}")
                executed_trades.append({
                    "symbol": sym,
                    "direction": direction_label,
                    "executed": False,
                    "error": "No option contracts available in DTE range",
                    "k2": k2,
                })
                continue

            log.info(f"    Found {len(contracts)} contracts in {cfg['options']['min_dte']}-{cfg['options']['max_dte']} DTE range")

            # E2: Select best contract
            selection = select_contract(contracts, underlying_price=underlying_price)

            log.info(f"    Selection: {len(selection.candidates)} candidates passed filters")
            if selection.rejected:
                log.info(f"    Top rejections:")
                for sym_rej, reason in selection.rejected[:3]:
                    log.info(f"      · {sym_rej}: {reason}")

            if not selection.success:
                log.warning(f"    ❌ No contract selected: {selection.reason}")
                executed_trades.append({
                    "symbol": sym,
                    "direction": direction_label,
                    "executed": False,
                    "error": selection.reason,
                    "selection": selection,
                    "k2": k2,
                })
                continue

            contract = selection.selected
            log.info(f"    ✅ Selected: {contract.symbol}")
            log.info(f"       Strike=${contract.strike_price:.2f} | "
                     f"DTE={contract.dte} | "
                     f"Bid=${contract.bid_price or '?'} | "
                     f"Ask=${contract.ask_price or '?'} | "
                     f"Spread={contract.spread_pct or 0:.1%} | "
                     f"Delta={contract.delta or 'N/A'}")

            # E3: Recalculate position size with actual option premium
            sizing = calculate_position_size(
                account_equity=account_equity,
                option_premium=contract.ask_price or contract.last_price or 0,
            )

            if not sizing.is_valid:
                log.warning(f"    ❌ Position sizing failed: {sizing.error}")
                executed_trades.append({
                    "symbol": sym,
                    "direction": direction_label,
                    "executed": False,
                    "error": sizing.error,
                    "contract": contract,
                    "k2": k2,
                })
                continue

            log.info(f"    Position: {sizing.max_contracts} contracts "
                     f"at ${contract.ask_price or contract.last_price:.2f} "
                     f"(total cost: ${sizing.total_cost:.0f})")

            # E4: Build and execute order
            if not cfg["alpaca"]["paper"]:
                log.warning(f"    ⚠ Paper trading disabled in config — skipping execution")
                executed_trades.append({
                    "symbol": sym,
                    "direction": direction_label,
                    "executed": False,
                    "error": "Paper trading disabled",
                    "contract": contract,
                    "position_size": sizing,
                    "k2": k2,
                })
                continue

            order_req = build_order_request(
                symbol=sym,
                direction=direction_label,
                option_contract=contract,
                quantity=sizing.max_contracts,
                thesis=k2.thesis,
                confidence=k2.confidence,
            )

            result = execute_order(
                order_req,
                on_fill=lambda chunk: record_order_fill(
                    order_id=chunk["order_id"],
                    symbol=chunk["symbol"],
                    option_symbol=chunk["option_symbol"],
                    side="BUY",
                    chunk_qty=chunk["chunk_qty"],
                    status=chunk["status"],
                    filled_qty=chunk["filled_qty"],
                    filled_avg_price=chunk["filled_avg_price"],
                    chunk_index=chunk["chunk_index"],
                    chunk_count=chunk["chunk_count"],
                ),
            )

            if result.succeeded:
                log.info(f"    🚀 EXECUTED: {result.order_id}")
                log.info(f"       Contract: {result.option_symbol}")
                log.info(f"       Quantity: {result.quantity}")
                log.info(f"       Price: {result.limit_price or 'market'}")
                log.info(f"       Status: {result.status}")
                log.info(f"       Thesis: {k2.thesis[:80]}...")

                # Journal: record trade entry
                record_entry(
                    symbol=sym,
                    option_symbol=contract.symbol,
                    direction=direction_label,
                    quantity=sizing.max_contracts,
                    entry_price=contract.ask_price or contract.last_price or 0,
                    thesis=k2.thesis,
                    invalidation=k2.invalidation,
                    confidence=k2.confidence,
                    expected_holding_days=k2.expected_holding_days,
                    max_holding_days=cfg["risk"]["max_holding_days"],
                    momentum_rank=int(row["momentum_rank"]) if isinstance(row.get("momentum_rank"), (int, float)) else 0,
                    underlying_close=float(row["close"]) if isinstance(row.get("close"), (int, float)) else 0,
                    order_id=result.order_id,
                )
            else:
                log.warning(f"    ❌ Execution failed: {result.error}")

            executed_trades.append({
                "symbol": sym,
                "direction": direction_label,
                "executed": result.succeeded,
                "order_id": result.order_id,
                "status": result.status,
                "contract": contract,
                "position_size": sizing,
                "order_request": order_req,
                "execution_result": result,
                "error": result.error,
                "k2": k2,
            })

    # Phase E summary
    total_executed = sum(1 for t in executed_trades if t["executed"])
    log.info(f"\n{'─'*65}")
    log.info(f"PHASE E RESULT — Options Selection & Execution")
    log.info(f"{'─'*65}")
    log.info(f"  Trades attempted   : {len(executed_trades)}")
    log.info(f"  Executed           : {total_executed}")
    log.info(f"  Failed             : {len(executed_trades) - total_executed}")
    log.info(f"{'─'*65}")
    for t in executed_trades:
        mark = "🚀" if t["executed"] else "❌"
        k2: K2AnalystOutput = t["k2"]
        if t["executed"]:
            log.info(f"  [{mark}] {t['symbol']:6s} | {t['direction']:4s} | "
                     f"order={str(t.get('order_id', 'N/A'))[:12]} | "
                     f"qty={t['order_request'].quantity} | "
                     f"thesis: {k2.thesis[:80]}...")
        else:
            log.info(f"  [{mark}] {t['symbol']:6s} | {t['direction']:4s} | "
                     f"error: {t.get('error', 'unknown')}")

    # ==================================================================
    # PHASE F — Position Monitoring & Auto-Exit
    # ==================================================================
    log.info(f"\n{'='*65}")
    log.info(f"PHASE F — Position Monitoring & Auto-Exit")
    log.info(f"{'='*65}")

    open_trades = get_open_trades()
    exited_positions: list[dict] = []

    if not open_trades:
        log.info(f"  No open positions to monitor.")
    else:
        log.info(f"  Monitoring {len(open_trades)} open positions...")

        latest_data_date = momentum_df["date"].max()
        latest_momentum = momentum_df[momentum_df["date"] == latest_data_date].copy()
        today_latest = momentum_df[momentum_df["date"] == latest_data_date].copy()

        for trade in open_trades:
            sym = trade["symbol"]
            log.info(f"\n  ── Monitoring {sym} ({trade['option_symbol']}) ──")

            # Get current momentum rank
            current_rank = None
            current_close = None
            current_ema20 = None
            current_rsi = None

            sym_rows = today_latest[today_latest["symbol"] == sym]
            if not sym_rows.empty:
                row = sym_rows.iloc[0]
                current_rank = int(row["momentum_rank"]) if "momentum_rank" in row else None
                current_close = float(row["close"]) if "close" in row else None
                current_ema20 = float(row["ema_20"]) if "ema_20" in row else None
                current_rsi = float(row["rsi_14"]) if "rsi_14" in row else None

            # Try to get current option price from Alpaca
            current_price = None
            try:
                from dotenv import load_dotenv; from pathlib import Path; import os
                load_dotenv(Path(__file__).resolve().parent / ".env")
                k = os.environ.get("APCA_API_KEY_ID", "").strip()
                s = os.environ.get("APCA_API_SECRET_KEY", "").strip() or k
                from alpaca.data import OptionHistoricalDataClient
                from alpaca.data.requests import OptionLatestQuoteRequest
                oc = OptionHistoricalDataClient(api_key=k, secret_key=s)
                qs = oc.get_option_latest_quote(
                    OptionLatestQuoteRequest(symbol_or_symbols=[trade["option_symbol"]])
                )
                if trade["option_symbol"] in qs:
                    q = qs[trade["option_symbol"]]
                    if hasattr(q, "bid_price") and q.bid_price and q.bid_price > 0:
                        current_price = float(q.bid_price)
                    elif hasattr(q, "ask_price") and q.ask_price:
                        current_price = float(q.ask_price)
            except Exception:
                pass

            if current_price is None and trade.get("entry_price"):
                current_price = float(trade["entry_price"])

            # Build position record
            entry_time = datetime.fromisoformat(trade["entry_time"]) if trade.get("entry_time") else datetime.now()
            pos = PositionRecord(
                symbol=sym,
                option_symbol=trade["option_symbol"],
                direction=trade["direction"],
                entry_time=entry_time,
                entry_price=float(trade.get("entry_price", 0)),
                quantity=int(trade.get("quantity", 1)),
                thesis=trade.get("thesis", ""),
                invalidation=trade.get("invalidation", ""),
                confidence=float(trade.get("confidence", 0.5)),
                expected_holding_days=int(trade.get("expected_holding_days", 5)),
                max_holding_days=int(trade.get("max_holding_days", 10)),
                entry_momentum_rank=int(trade.get("entry_momentum_rank", 0)),
                entry_close=float(trade.get("entry_close", 0)),
                order_id=trade.get("order_id", ""),
            )

            # Run exit checks
            monitor = check_exit_conditions(
                position=pos,
                current_price=current_price,
                current_momentum_rank=current_rank,
                current_regime=regime_label,
                current_close=current_close,
                ema_20=current_ema20,
                rsi_14=current_rsi,
                today=date.today(),
            )

            log.info(f"    Price: ${current_price or '?'} | "
                     f"PnL: {monitor.current_pnl_pct or 0:.1%} | "
                     f"Days held: {monitor.days_held} | "
                     f"Rank: {monitor.current_momentum_rank or '?'}")

            if monitor.exit_triggers:
                for trigger in monitor.exit_triggers:
                    log.info(f"    ⚠ {trigger}")

            if not monitor.should_exit:
                log.info(f"    ✅ Holding — no exit conditions triggered")
                continue

            # ── EXECUTE EXIT ─────────────────────────────────────
            log.info(f"    🔴 EXIT: {monitor.exit_reason}")
            exit_result = liquidate_position(
                option_symbol=pos.option_symbol,
                exit_reason=monitor.exit_reason,
                on_fill=lambda chunk: record_order_fill(
                    order_id=chunk["order_id"],
                    symbol=chunk["symbol"],
                    option_symbol=chunk["option_symbol"],
                    side="SELL",
                    chunk_qty=chunk["chunk_qty"],
                    status=chunk["status"],
                    filled_qty=chunk["filled_qty"],
                    filled_avg_price=chunk["filled_avg_price"],
                    chunk_index=chunk["chunk_index"],
                    chunk_count=chunk["chunk_count"],
                ),
            )

            if exit_result.succeeded:
                log.info(f"    ✅ Exit submitted: {exit_result.order_id} "
                         f"status={exit_result.status}")

                record_exit(
                    option_symbol=pos.option_symbol,
                    exit_price=exit_result.exit_price or current_price,
                    exit_reason=monitor.exit_reason,
                )
            else:
                log.warning(f"    ❌ Exit failed: {exit_result.error}")

            exited_positions.append({
                "symbol": sym,
                "option_symbol": pos.option_symbol,
                "exit_reason": monitor.exit_reason,
                "exit_result": exit_result,
                "monitor": monitor,
            })

        # Also check Alpaca for any positions not in our journal
        try:
            positions = get_positions()
            journal_symbols = {t["option_symbol"] for t in open_trades}
            for p in positions:
                p_sym = p.get("symbol", "")
                if p_sym and p_sym not in journal_symbols:
                    log.warning(f"    ⚠ Unjournaled position: {p_sym} — liquidating for safety")
                    lr = liquidate_position(
                        option_symbol=p_sym,
                        exit_reason="Unjournaled position — safety liquidation",
                        on_fill=lambda chunk: record_order_fill(
                            order_id=chunk["order_id"],
                            symbol=chunk["symbol"] or p_sym,
                            option_symbol=chunk["option_symbol"],
                            side="SELL",
                            chunk_qty=chunk["chunk_qty"],
                            status=chunk["status"],
                            filled_qty=chunk["filled_qty"],
                            filled_avg_price=chunk["filled_avg_price"],
                            chunk_index=chunk["chunk_index"],
                            chunk_count=chunk["chunk_count"],
                        ),
                    )
                    exited_positions.append({
                        "symbol": "UNKNOWN",
                        "option_symbol": p_sym,
                        "exit_reason": "Unjournaled safety liquidation",
                        "exit_result": lr,
                    })
        except Exception as e:
            log.debug(f"    Could not check unjournaled positions: {e}")

    # Phase F summary
    total_exited = len(exited_positions)
    perf = get_performance_summary()
    log.info(f"\n{'─'*65}")
    log.info(f"PHASE F RESULT — Position Monitoring & Exits")
    log.info(f"{'─'*65}")
    log.info(f"  Open positions      : {len(open_trades)}")
    log.info(f"  Exits triggered     : {total_exited}")
    log.info(f"  Historical trades   : {perf['total_trades']}")
    log.info(f"  Win rate            : {perf['win_rate']:.1%}")
    log.info(f"  Total P&L           : ${perf['total_pnl']:,.2f}")
    log.info(f"  Avg P&L             : ${perf['avg_pnl']:,.2f}")
    log.info(f"{'─'*65}")

    if exited_positions:
        for ep in exited_positions:
            er = ep.get("exit_result")
            log.info(f"  🔴 {ep['symbol']:6s} — {ep['exit_reason'][:70]}")
            if er and er.succeeded:
                log.info(f"     Order {er.order_id[:12]} — exit_price={er.exit_price}")

    log.info(f"\n{'='*65}")
    log.info("Phase A + B + C + D + E + F complete. ALL PHASES DONE.")
    log.info(f"{'='*65}")

    return {
        "candidates_df": momentum_df,
        "regime_result": regime_result,
        "top_n_df": top_n,
        "enriched_df": enriched,
        "financials": financials,
        "earnings": earnings,
        "catalysts": catalysts,
        "ai_results": ai_results,
        "validated_trades": validated_trades,
        "executed_trades": executed_trades,
        "exited_positions": exited_positions,
        "account_equity": account_equity,
        "latest_date": latest_date,
    }


def main():
    result = run_cycle(lookback_days=70)

    if result and result.get("executed_trades") or result.get("exited_positions"):
        executed = result.get("executed_trades", [])
        exited = result.get("exited_positions", [])
        successful = [t for t in executed if t["executed"]]
        trades_text = "trade" if len(successful) == 1 else "trades"
        if successful:
            log.info(f"\nPipeline complete: {len(successful)} {trades_text} executed, "
                     f"{len(exited)} exited.")
        perf = get_performance_summary()
        if perf["total_trades"] > 0:
            log.info(f"Performance: {perf['win_rate']:.0%} win rate, "
                     f"${perf['total_pnl']:,.0f} total P&L, "
                     f"{perf['total_trades']} closed trades")
    elif result and result.get("validated_trades"):
        validated = result["validated_trades"]
        approved = [t for t in validated if t["approved"]]
        log.info(f"\nPipeline complete: {len(approved)}/{len(validated)} trades approved but none executed.")
    elif result:
        log.warning("No validated trades — check AI results and risk gates.")
    else:
        log.error("Cycle failed to produce results.")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "dashboard":
        from dashboard.app import run
        run(host="0.0.0.0", port=8080, debug=True)
    elif len(sys.argv) > 1 and sys.argv[1] == "--autonomous":
        from config import get_config, load_config
        cfg = load_config()
        interval = cfg.get("scheduler", {}).get("interval_minutes", 15) * 60
        auto_enabled = cfg.get("scheduler", {}).get("enabled_on_start", True)
        from scheduler import start
        start(interval_seconds=interval, enabled=auto_enabled)
        log.info(f"Autonomous mode: cycle every {interval // 60} min, enabled={auto_enabled}")
        log.info("Press Ctrl+C to stop")
        import time as _time
        try:
            while True:
                _time.sleep(60)
        except KeyboardInterrupt:
            from scheduler import stop
            stop()
            log.info("Shutdown complete")
    elif len(sys.argv) > 1 and sys.argv[1] == "--once":
        main()
    else:
        main()