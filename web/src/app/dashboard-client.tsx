"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
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
import { useLivePositions, useAlpacaAccount, useAlpacaOrders } from "@/lib/live-positions";
import { LayoutDashboard, Activity, Layers, History, Cpu, Sparkles, RefreshCw, Circle, CircleDot, FileText, Clock, ListOrdered } from "lucide-react";

export function DashboardClient({ data }: { data: DashboardData }) {
  const router = useRouter();
  const [selectedCandidate, setSelectedCandidate] = React.useState<Candidate | null>(null);
  const [candidateDrawerOpen, setCandidateDrawerOpen] = React.useState(false);
  const [selectedTrade, setSelectedTrade] = React.useState<Trade | null>(null);
  const [tradeDrawerOpen, setTradeDrawerOpen] = React.useState(false);

  // Live position marks/delta/unrealized P&L from the Flask dashboard
  // backend (dashboard/app.py's /api/positions/live) -- the server-
  // rendered `data` prop only has the static entry-time snapshot from
  // trade_journal.json, so this is what powers the Current/Delta/
  // Unrealized P&L columns and the two live overview cards.
  const live = useLivePositions();

  // Live Alpaca account state (equity, cash, buying power) —
  // replaces the hardcoded journal-derived numbers with the
  // broker's actual balance.
  const account = useAlpacaAccount();

  // Live Alpaca order trail — broker-verified order history
  // including manual orders placed outside the system.
  const orders = useAlpacaOrders();

  // Auto-refresh the server-rendered data (candidates, trades, cycle
  // report, scheduler status) every few seconds so the dashboard
  // updates while main.py / the scheduler is running, without the
  // user needing to manually reload the tab. router.refresh() re-runs
  // page.tsx's Server Component (re-reading trade_journal.json) and
  // patches the tree in place -- client state here (selected tab,
  // open drawers) is preserved.
  React.useEffect(() => {
    const id = setInterval(() => router.refresh(), 8000);
    return () => clearInterval(id);
  }, [router]);

  const handleCandidateClick = React.useCallback((c: Candidate) => {
    setSelectedCandidate(c);
    setCandidateDrawerOpen(true);
  }, []);

  const handleTradeClick = React.useCallback((t: Trade) => {
    setSelectedTrade(t);
    setTradeDrawerOpen(true);
  }, []);

  return (
    <>
      {/* ── Header ─────────────────────────────────────────────── */}
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
            <span className="text-[11px] text-muted-foreground">Updated {timeAgo(data.now)}</span>
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6">
        {/* ── Tabbed Content ──────────────────────────────────── */}
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
            <TradingCycles
              runs={data.runs}
              onCandidateClick={handleCandidateClick}
            />
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
            <TradeHistory
              trades={data.history}
              onTradeClick={handleTradeClick}
            />
          </TabsContent>

          <TabsContent value="system" className="mt-0">
            <SystemInfo config={data.config} />
          </TabsContent>

          <TabsContent value="orders" className="mt-0">
            <AlpacaOrders orders={orders.data} loading={orders.loading} />
          </TabsContent>
        </Tabs>
      </main>

      {/* ── Drawers ───────────────────────────────────────────── */}
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
