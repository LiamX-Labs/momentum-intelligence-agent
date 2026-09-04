"use client";

import * as React from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { StatsGrid } from "@/components/stats-grid";
import { TradingCycles } from "@/components/trading-cycles";
import { OpenPositions } from "@/components/open-positions";
import { TradeHistory } from "@/components/trade-history";
import { SystemInfo } from "@/components/system-info";
import { CandidateDrawer } from "@/components/candidate-drawer";
import { DetailDrawer } from "@/components/detail-drawer";
import { CycleReportView } from "@/components/cycle-report";
import { AlpacaOrders } from "@/components/alpaca-orders";
import { RegimeBadge } from "@/components/badges";
import type { DashboardData, Candidate, Trade } from "@/lib/types";
import { timeAgo } from "@/lib/format";
import { useLivePositions, useAlpacaAccount, useAlpacaOrders, API_BASE } from "@/lib/live-positions";
import { LayoutDashboard, Activity, Layers, History, Cpu, Sparkles, RefreshCw, Circle, CircleDot, FileText, Clock, ListOrdered, Loader2, WifiOff } from "lucide-react";

const EMPTY_DATA: DashboardData = {
  equity: 0,
  cash: 0,
  dailyPnl: 0,
  totalPnl: 0,
  openPositions: 0,
  winRate: 0,
  avgTrade: 0,
  totalTrades: 0,
  avgK2Conf: 0,
  avgQwenConf: 0,
  approveRate: 0,
  candidateCount: 0,
  regime: "UNKNOWN",
  runs: [],
  openTrades: [],
  history: [],
  avgWinner: 0,
  avgLoser: 0,
  config: {
    models: {
      primary: { provider: "featherless", model: "moonshotai/Kimi-K2-Instruct" },
      critic: { provider: "featherless", model: "Qwen/Qwen3-32B" },
      fallback: { provider: "featherless", model: "deepseek-ai/DeepSeek-V3.2" },
    },
    risk: { max_risk_per_trade: 0.01, max_open_positions: 5, max_portfolio_option_premium: 0.2, max_symbol_exposure: 0.05, max_holding_days: 10 },
    options: { min_dte: 7, max_dte: 21, target_delta_min: 0.5, target_delta_max: 0.65, max_bid_ask_spread_pct: 0.1 },
    decision: { min_momentum_score: 60, min_ai_confidence: 0.75, require_critic_approval: true },
    regime: { bull_max_exposure: 1.0, neutral_max_exposure: 0.6, bear_max_exposure: 0.25 },
    momentum: { lookbacks: [1, 3, 5, 10, 20], candidate_count: 50, min_score: 60 },
  },
  now: new Date().toISOString(),
  equitySeries: [],
  scheduler: { enabled: false, running: false, cycle_count: 0, last_run: null, last_result: "", next_run: null, interval_seconds: 0, current_phase: "idle", error: null, updated: null },
  latestReport: null,
};

function useDashboardData(intervalMs = 8000) {
  const [data, setData] = React.useState<DashboardData>(EMPTY_DATA);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  const fetchAll = React.useCallback(async () => {
    try {
      const [tradesRes, candidatesRes, schedulerRes] = await Promise.all([
        fetch(`${API_BASE}/api/trades`, { cache: "no-store" }),
        fetch(`${API_BASE}/api/candidates`, { cache: "no-store" }),
        fetch(`${API_BASE}/api/scheduler`, { cache: "no-store" }),
      ]);

      const tradesData = tradesRes.ok ? await tradesRes.json() : { open: [], history: [], performance: {} };
      const candidates: Candidate[] = candidatesRes.ok ? await candidatesRes.json() : [];
      const scheduler = schedulerRes.ok ? await schedulerRes.json() : EMPTY_DATA.scheduler;

      const history: Trade[] = tradesData.history || [];
      const openTrades: Trade[] = tradesData.open || [];

      const wins = history.filter((t: Trade) => (t.pnl ?? 0) > 0);
      const totalPnl = history.reduce((acc: number, t: Trade) => acc + (t.pnl ?? 0), 0);
      const winRate = history.length ? wins.length / history.length : 0;
      const avgTrade = history.length ? totalPnl / history.length : 0;

      const todayStr = new Date().toISOString().slice(0, 10);
      const todaysTrades = history.filter(
        (t: Trade) => t.entry_time?.startsWith(todayStr) || t.exit_time?.startsWith(todayStr)
      );
      const dailyPnl = todaysTrades.reduce((acc: number, t: Trade) => acc + (t.pnl ?? 0), 0);

      const avgK2Conf = candidates.length
        ? candidates.reduce((acc, c) => acc + (c.k2_confidence || 0), 0) / candidates.length
        : 0;
      const avgQwenConf = candidates.length
        ? candidates.reduce((acc, c) => acc + (c.qwen_confidence || 0), 0) / candidates.length
        : 0;
      const approvedCandidates = candidates.filter((c) => c.approved);
      const approveRate = candidates.length ? approvedCandidates.length / candidates.length : 0;

      const regime = (candidates[0]?.regime as DashboardData["regime"]) || "UNKNOWN";

      const map = new Map<string, Candidate[]>();
      for (const c of candidates) {
        const key = c.run_id || c.timestamp.slice(0, 16);
        if (!map.has(key)) map.set(key, []);
        map.get(key)!.push(c);
      }
      const runs = Array.from(map.entries()).map(([run_id, list]) => ({
        run_id,
        timestamp: list[0]?.timestamp ?? run_id,
        candidates: list,
        approvedCount: list.filter((c) => c.approved).length,
        regime: list[0]?.regime || "UNKNOWN",
      }));
      runs.sort((a, b) => (a.timestamp < b.timestamp ? 1 : -1));

      const sortedHistory = [...history].sort((a, b) =>
        (a.exit_time || "") < (b.exit_time || "") ? -1 : 1
      );
      let running = 100000;
      const equitySeries = sortedHistory.map((t) => {
        running += (t.pnl ?? 0);
        return { t: t.exit_time || t.entry_time, v: running };
      });

      setData({
        equity: 100000 + totalPnl,
        cash: 100000,
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
        runs,
        openTrades,
        history: [...history].sort((a, b) => ((a.exit_time || "") < (b.exit_time || "") ? 1 : -1)),
        avgWinner: wins.length ? wins.reduce((acc: number, t: Trade) => acc + (t.pnl ?? 0), 0) / wins.length : 0,
        avgLoser: history.length - wins.length ? (totalPnl - wins.reduce((acc: number, t: Trade) => acc + (t.pnl ?? 0), 0)) / (history.length - wins.length) : 0,
        config: EMPTY_DATA.config,
        now: new Date().toISOString(),
        equitySeries: equitySeries.length ? equitySeries : [{ t: new Date().toISOString(), v: 100000 }],
        scheduler,
        latestReport: null,
      });
      setError(null);
    } catch {
      setError("Backend unreachable — retrying...");
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    fetchAll();
    const id = setInterval(fetchAll, intervalMs);
    return () => clearInterval(id);
  }, [fetchAll, intervalMs]);

  return { data, loading, error };
}

export default function DashboardClient() {
  const [selectedCandidate, setSelectedCandidate] = React.useState<Candidate | null>(null);
  const [candidateDrawerOpen, setCandidateDrawerOpen] = React.useState(false);
  const [selectedTrade, setSelectedTrade] = React.useState<Trade | null>(null);
  const [tradeDrawerOpen, setTradeDrawerOpen] = React.useState(false);

  const { data, loading, error } = useDashboardData();
  const live = useLivePositions();
  const account = useAlpacaAccount();
  const orders = useAlpacaOrders();

  const handleCandidateClick = React.useCallback((c: Candidate) => {
    setSelectedCandidate(c);
    setCandidateDrawerOpen(true);
  }, []);

  const handleTradeClick = React.useCallback((t: Trade) => {
    setSelectedTrade(t);
    setTradeDrawerOpen(true);
  }, []);

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="text-center">
          <Loader2 className="mx-auto mb-4 size-8 animate-spin text-info" />
          <p className="text-sm text-muted-foreground">Connecting to trading engine...</p>
        </div>
      </div>
    );
  }

  return (
    <>
      <header className="sticky top-0 z-40 border-b border-border bg-background/70 backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3 sm:px-6">
          <div className="flex items-center gap-3">
            <div className="flex size-8 items-center justify-center rounded-lg bg-info-soft">
              <Sparkles className="size-4.5 text-info" />
            </div>
            <div>
              <h1 className="text-base font-bold tracking-tight">Momentum Intelligence</h1>
              <p className="text-[11px] text-muted-foreground">
                Autonomous AI Trading · K2 Analyst + Qwen Critic + Deterministic Risk
              </p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <SchedulerBar scheduler={data.scheduler} />
            <RegimeBadge regime={data.regime} />
            {error ? (
              <span className="flex items-center gap-1 text-[11px] text-warn">
                <WifiOff className="size-3" />
                {error}
              </span>
            ) : (
              <span className="text-[11px] text-muted-foreground">Updated {timeAgo(data.now)}</span>
            )}
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6">
        <Tabs defaultValue="dashboard" className="w-full">
          <TabsList className="mb-6 inline-flex h-auto flex-wrap gap-1 bg-white/[0.04] p-1">
            <TabsTrigger value="dashboard" className="flex items-center gap-1.5 data-[state=active]:glass-card">
              <LayoutDashboard className="size-3.5" />
              Dashboard
            </TabsTrigger>
            <TabsTrigger value="signals" className="flex items-center gap-1.5 data-[state=active]:glass-card">
              <Activity className="size-3.5" />
              Active Signals
            </TabsTrigger>
            <TabsTrigger value="positions" className="flex items-center gap-1.5 data-[state=active]:glass-card">
              <Layers className="size-3.5" />
              Open Positions
            </TabsTrigger>
            <TabsTrigger value="history" className="flex items-center gap-1.5 data-[state=active]:glass-card">
              <History className="size-3.5" />
              Closed History
            </TabsTrigger>
            <TabsTrigger value="system" className="flex items-center gap-1.5 data-[state=active]:glass-card">
              <Cpu className="size-3.5" />
              System Logs
            </TabsTrigger>
            <TabsTrigger value="orders" className="flex items-center gap-1.5 data-[state=active]:glass-card">
              <ListOrdered className="size-3.5" />
              Broker Orders
            </TabsTrigger>
          </TabsList>

          <TabsContent value="dashboard" className="mt-0">
            <div className="mb-8">
              <StatsGrid
                data={data}
                unrealizedPnl={live.totalUnrealizedPnl}
                openExposure={live.totalOpenExposure}
                account={account.data}
              />
            </div>
            {data.latestReport ? (
              <CycleReportView report={data.latestReport} />
            ) : (
              <EmptyReportPlaceholder />
            )}
          </TabsContent>

          <TabsContent value="signals" className="mt-0">
            <TradingCycles runs={data.runs} onCandidateClick={handleCandidateClick} />
          </TabsContent>

          <TabsContent value="positions" className="mt-0">
            <OpenPositions
              trades={data.openTrades}
              onTradeClick={handleTradeClick}
              livePositions={live.byOptionSymbol}
              onPositionClosed={live.refresh}
            />
          </TabsContent>

          <TabsContent value="history" className="mt-0">
            <TradeHistory trades={data.history} onTradeClick={handleTradeClick} />
          </TabsContent>

          <TabsContent value="system" className="mt-0">
            <SystemInfo config={data.config} />
          </TabsContent>

          <TabsContent value="orders" className="mt-0">
            <AlpacaOrders orders={orders.data} loading={orders.loading} />
          </TabsContent>
        </Tabs>
      </main>

      <CandidateDrawer
        candidate={selectedCandidate}
        open={candidateDrawerOpen}
        onOpenChange={setCandidateDrawerOpen}
      />
      <DetailDrawer
        trade={selectedTrade}
        open={tradeDrawerOpen}
        onOpenChange={setTradeDrawerOpen}
      />
    </>
  );
}

function SchedulerBar({ scheduler }: { scheduler: { enabled: boolean; running: boolean; cycle_count: number; last_result: string; next_run: string | null; interval_seconds: number; error: string | null } }) {
  const nextIn = scheduler.next_run
    ? Math.max(0, Math.floor((new Date(scheduler.next_run).getTime() - Date.now()) / 1000))
    : null;

  const nextStr =
    scheduler.running
      ? "running now"
      : nextIn != null && nextIn > 0
        ? `next run in ${Math.floor(nextIn / 60)}m ${nextIn % 60}s`
        : scheduler.enabled
          ? "pending"
          : "paused";

  return (
    <div className="flex items-center gap-1.5 rounded-full border border-white/[0.08] bg-white/[0.02] px-2.5 py-1">
      {scheduler.running ? (
        <RefreshCw className="size-3.5 animate-spin text-info" />
      ) : scheduler.enabled ? (
        <CircleDot className="size-3.5 text-bull" />
      ) : (
        <Circle className="size-3.5 text-muted-foreground" />
      )}
      <span className="text-[11px] font-medium text-muted-foreground">
        Cycle {scheduler.cycle_count} · {nextStr}
      </span>
    </div>
  );
}

function EmptyReportPlaceholder() {
  return (
    <Card className="glass-card overflow-hidden opacity-60">
      <CardHeader className="flex flex-row items-center gap-3 border-b border-border px-4 py-3">
        <div className="flex size-8 items-center justify-center rounded-lg bg-teal-soft">
          <FileText className="size-4 text-teal" />
        </div>
        <div>
          <CardTitle className="text-sm font-semibold">AI Reporter</CardTitle>
          <p className="text-[11px] text-muted-foreground">
            Summary will appear after the first trading cycle completes
          </p>
        </div>
      </CardHeader>
      <CardContent className="flex items-center justify-center px-5 py-10">
        <div className="text-center text-muted-foreground">
          <Clock className="mx-auto mb-2 size-8 opacity-30" />
          <p className="text-sm">No reports yet</p>
          <p className="mt-1 text-[11px]">
            The reporter agent generates a plain-English summary after each cycle,
            explaining what was approved, what was rejected, and why.
          </p>
        </div>
      </CardContent>
    </Card>
  );
}