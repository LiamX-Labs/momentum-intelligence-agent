"use client";

import * as React from "react";
import type { AlpacaAccountData, AlpacaOrder } from "./types";

// The Flask dashboard backend (dashboard/app.py) runs on a separate
// origin from the Next.js dev/prod server, so this is configurable via
// NEXT_PUBLIC_API_BASE. Defaults to the standard local dev port.
export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") || "http://localhost:8081";

export interface LivePosition {
  option_symbol: string;
  underlying_symbol: string | null;
  direction: "CALL" | "PUT" | null;
  qty: number;
  avg_entry_price: number | null;
  current_price: number | null;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  delta: number | null;
  cost_basis: number;
  thesis: string | null;
  trade_id: string | null;
}

interface LivePositionsResponse {
  positions: LivePosition[];
  total_unrealized_pnl: number;
  total_open_exposure: number;
  error?: string;
}

const EMPTY: LivePositionsResponse = {
  positions: [],
  total_unrealized_pnl: 0,
  total_open_exposure: 0,
};

/**
 * Polls the Flask backend's /api/positions/live endpoint for live
 * mark price, delta, and unrealized P&L on every open position.
 * Falls back to an empty (non-error) result if the backend can't be
 * reached, so the rest of the dashboard (which reads the static
 * trade_journal.json snapshot server-side) still renders normally.
 */
export function useLivePositions(intervalMs = 15000) {
  const [data, setData] = React.useState<LivePositionsResponse>(EMPTY);
  const [loading, setLoading] = React.useState(true);

  const refresh = React.useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/positions/live`, { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json: LivePositionsResponse = await res.json();
      setData(json);
    } catch {
      // Backend not reachable (e.g. dashboard/app.py not running) —
      // keep the dashboard usable, just without live marks.
      setData(EMPTY);
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    // Deferred via a resolved-promise tick rather than calling the
    // (async) refresh directly in the effect body, per
    // react-hooks/set-state-in-effect: an effect's synchronous portion
    // should not itself drive a state update.
    let cancelled = false;
    Promise.resolve().then(() => {
      if (!cancelled) refresh();
    });
    const id = setInterval(refresh, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [refresh, intervalMs]);

  const byOptionSymbol = React.useMemo(() => {
    const map: Record<string, LivePosition> = {};
    for (const p of data.positions) map[p.option_symbol] = p;
    return map;
  }, [data.positions]);

  return {
    positions: data.positions,
    byOptionSymbol,
    totalUnrealizedPnl: data.total_unrealized_pnl,
    totalOpenExposure: data.total_open_exposure,
    loading,
    refresh,
  };
}

/**
 * Manually close a position (emergency override from the dashboard).
 * Chunks server-side so it can't trip the broker's per-order cap.
 */
export async function closePosition(optionSymbol: string, reason?: string) {
  const res = await fetch(
    `${API_BASE}/api/positions/${encodeURIComponent(optionSymbol)}/close`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: reason || "Manual close (dashboard)" }),
    }
  );
  const json = await res.json();
  if (!res.ok || !json.success) {
    throw new Error(json.error || `Close failed (HTTP ${res.status})`);
  }
  return json as { success: true; order_id: string; status: string; exit_price: number | null };
}

const EMPTY_ACCOUNT: AlpacaAccountData = {
  equity: 0,
  cash: 0,
  buying_power: 0,
  portfolio_value: 0,
  long_market_value: 0,
  short_market_value: 0,
  daytrade_count: 0,
  last_equity: 0,
  initial_margin: 0,
  maintenance_margin: 0,
  account_number: "",
};

/**
 * Polls the Flask backend's /api/account endpoint for live Alpaca paper
 * account state (equity, cash, buying power, margin, etc.).
 */
export function useAlpacaAccount(intervalMs = 15000) {
  const [data, setData] = React.useState<AlpacaAccountData | null>(null);
  const [loading, setLoading] = React.useState(true);

  const refresh = React.useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/account`, { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json: AlpacaAccountData = await res.json();
      setData(json);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => {
      if (!cancelled) refresh();
    });
    const id = setInterval(refresh, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [refresh, intervalMs]);

  return { data, loading, refresh };
}

/**
 * Polls the Flask backend's /api/orders endpoint for the broker's
 * real order trail (includes manual orders placed outside the system).
 */
export function useAlpacaOrders(intervalMs = 15000) {
  const [data, setData] = React.useState<AlpacaOrder[]>([]);
  const [loading, setLoading] = React.useState(true);

  const refresh = React.useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/orders`, { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json: AlpacaOrder[] = await res.json();
      setData(json);
    } catch {
      setData([]);
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => {
      if (!cancelled) refresh();
    });
    const id = setInterval(refresh, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [refresh, intervalMs]);

  return { data, loading, refresh };
}
