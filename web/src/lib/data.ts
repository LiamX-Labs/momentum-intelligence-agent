import fs from "node:fs";
import path from "node:path";
import { load } from "js-yaml";
import type {
  Candidate,
  Config,
  CycleReport,
  DashboardData,
  Journal,
  Regime,
  RunGroup,
  Trade,
} from "./types";

// The Python project root is one level up from `web/`.
const PROJECT_ROOT = path.resolve(process.cwd(), "..");
const JOURNAL_PATH = path.join(PROJECT_ROOT, "trade_journal.json");
const CONFIG_PATH = path.join(PROJECT_ROOT, "config", "config.yaml");
const SCHEDULER_PATH = path.join(PROJECT_ROOT, ".scheduler_status.json");

function readSchedulerStatus() {
  try {
    const raw = fs.readFileSync(SCHEDULER_PATH, "utf-8");
    return JSON.parse(raw);
  } catch {
    return {
      enabled: false,
      running: false,
      cycle_count: 0,
      last_run: null,
      last_result: "",
      next_run: null,
      interval_seconds: 0,
      current_phase: "idle",
      error: null,
      updated: null,
    };
  }
}

export function readJournal(): Journal {
  try {
    const raw = fs.readFileSync(JOURNAL_PATH, "utf-8");
    const parsed = JSON.parse(raw);
    return {
      candidates: Array.isArray(parsed.candidates) ? parsed.candidates : [],
      trades: Array.isArray(parsed.trades) ? parsed.trades : [],
      reports: Array.isArray(parsed.reports) ? parsed.reports : [],
    };
  } catch {
    return { candidates: [], trades: [] };
  }
}

export function readConfig(): Config {
  try {
    const raw = fs.readFileSync(CONFIG_PATH, "utf-8");
    return load(raw) as Config;
  } catch {
    return {
      models: {
        primary: { provider: "featherless", model: "moonshotai/Kimi-K2-Instruct" },
        critic: { provider: "featherless", model: "Qwen/Qwen3-32B" },
        fallback: { provider: "featherless", model: "deepseek-ai/DeepSeek-V3.2" },
      },
      risk: {
        max_risk_per_trade: 0.01,
        max_open_positions: 5,
        max_portfolio_option_premium: 0.2,
        max_symbol_exposure: 0.05,
        max_holding_days: 10,
      },
      options: {
        min_dte: 7,
        max_dte: 21,
        target_delta_min: 0.5,
        target_delta_max: 0.65,
        max_bid_ask_spread_pct: 0.1,
      },
      decision: {
        min_momentum_score: 60,
        min_ai_confidence: 0.75,
        require_critic_approval: true,
      },
      regime: {
        bull_max_exposure: 1.0,
        neutral_max_exposure: 0.6,
        bear_max_exposure: 0.25,
      },
      momentum: { lookbacks: [1, 3, 5, 10, 20], candidate_count: 50, min_score: 60 },
    };
  }
}

function safeFloat(v: unknown, fallback = 0): number {
  const n = typeof v === "string" ? parseFloat(v) : (v as number);
  return typeof n === "number" && !Number.isNaN(n) ? n : fallback;
}

function groupCandidatesByRun(candidates: Candidate[]): RunGroup[] {
  const map = new Map<string, Candidate[]>();
  for (const c of candidates) {
    const key = c.run_id || c.timestamp.slice(0, 16);
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(c);
  }
  const groups: RunGroup[] = Array.from(map.entries()).map(([run_id, list]) => ({
    run_id,
    timestamp: list[0]?.timestamp ?? run_id,
    candidates: list,
    approvedCount: list.filter((c) => c.approved).length,
    regime: list[0]?.regime || "UNKNOWN",
  }));
  // Most recent run first
  groups.sort((a, b) => (a.timestamp < b.timestamp ? 1 : -1));
  return groups;
}

export function getDashboardData(): DashboardData {
  const journal = readJournal();
  const config = readConfig();

  const candidates = [...journal.candidates].sort((a, b) =>
    a.timestamp < b.timestamp ? 1 : -1
  );
  const trades = journal.trades;
  const openTrades = trades.filter((t) => t.exit_time == null);
  const history = trades.filter((t) => t.exit_time != null);

  // ── Performance ──────────────────────────────────────────────
  const wins = history.filter((t) => safeFloat(t.pnl) > 0);
  const losses = history.filter((t) => safeFloat(t.pnl) <= 0);
  const totalPnl = history.reduce((acc, t) => acc + safeFloat(t.pnl), 0);
  const winRate = history.length ? wins.length / history.length : 0;
  const avgTrade = history.length ? totalPnl / history.length : 0;
  const avgWinner = wins.length
    ? wins.reduce((acc, t) => acc + safeFloat(t.pnl), 0) / wins.length
    : 0;
  const avgLoser = losses.length
    ? losses.reduce((acc, t) => acc + safeFloat(t.pnl), 0) / losses.length
    : 0;

  const todayStr = new Date().toISOString().slice(0, 10);
  const todaysTrades = history.filter(
    (t) =>
      t.entry_time?.startsWith(todayStr) || t.exit_time?.startsWith(todayStr)
  );
  const dailyPnl = todaysTrades.reduce((acc, t) => acc + safeFloat(t.pnl), 0);

  // ── AI stats ─────────────────────────────────────────────────
  const avgK2Conf = candidates.length
    ? candidates.reduce((acc, c) => acc + (c.k2_confidence || 0), 0) /
      candidates.length
    : 0;
  const avgQwenConf = candidates.length
    ? candidates.reduce((acc, c) => acc + (c.qwen_confidence || 0), 0) /
      candidates.length
    : 0;
  const approvedCandidates = candidates.filter((c) => c.approved);
  const approveRate = candidates.length
    ? approvedCandidates.length / candidates.length
    : 0;

  // ── Equity (best-effort; paper account assumed $100k baseline) ─
  const equity = 100000 + totalPnl;
  const cash = 100000;

  // Build a simple cumulative equity series from closed trade history
  // (oldest → newest) for the header sparkline.
  const sortedHistory = [...history].sort((a, b) =>
    (a.exit_time || "") < (b.exit_time || "") ? -1 : 1
  );
  let running = 100000;
  const equitySeries = sortedHistory.map((t) => {
    running += safeFloat(t.pnl);
    return { t: t.exit_time || t.entry_time, v: running };
  });
  if (equitySeries.length === 0) {
    equitySeries.push({ t: new Date().toISOString(), v: 100000 });
  }

  const regime: Regime = (candidates[0]?.regime as Regime) || "UNKNOWN";

  const reports = journal.reports || [];
  const latestReport = reports.length > 0
    ? [...reports].sort((a, b) => (a.timestamp < b.timestamp ? 1 : -1))[0]
    : null;

  return {
    equity,
    cash,
    dailyPnl,
    totalPnl,
    openPositions: openTrades.length,
    winRate,
    avgTrade,
    totalTrades: history.length,
    avgK2Conf,
    avgQwenConf,
    approveRate,
    candidateCount: candidates.length,
    regime,
    runs: groupCandidatesByRun(candidates),
    openTrades,
    history: [...history].sort((a, b) =>
      (a.exit_time || "") < (b.exit_time || "") ? 1 : -1
    ),
    avgWinner,
    avgLoser,
    config,
    now: new Date().toISOString(),
    equitySeries,
    scheduler: readSchedulerStatus(),
    latestReport,
  };
}

export function findTrade(tradeId: string): Trade | null {
  const journal = readJournal();
  const trade =
    journal.trades.find((t) => t.trade_id === tradeId) ||
    journal.trades.find((t) => t.option_symbol === tradeId);
  return trade ?? null;
}
