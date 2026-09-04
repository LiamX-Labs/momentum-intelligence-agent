"use client";

import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { formatMoney, formatMoneyCompact, formatPct0 } from "@/lib/format";
import { Line, LineChart, ResponsiveContainer, YAxis } from "recharts";
import type { DashboardData, AlpacaAccountData } from "@/lib/types";
import {
  Wallet,
  TrendingUp,
  TrendingDown,
  Layers,
  Target,
  ShieldCheck,
  Percent,
  Activity,
  PieChart,
} from "lucide-react";

function Sparkline({ data, positive }: { data: { v: number }[]; positive: boolean }) {
  return (
    <div className="h-8 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data}>
          <YAxis hide domain={["dataMin", "dataMax"]} />
          <Line
            type="monotone"
            dataKey="v"
            stroke={positive ? "var(--bull-foreground)" : "var(--bear-foreground)"}
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function StatCard({
  label,
  value,
  sub,
  icon: Icon,
  tone = "neutral",
  spark,
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  icon: React.ComponentType<{ className?: string }>;
  tone?: "bull" | "bear" | "neutral" | "info" | "warn";
  spark?: React.ReactNode;
}) {
  const toneClass = {
    bull: "text-bull",
    bear: "text-bear",
    neutral: "text-foreground",
    info: "text-info",
    warn: "text-warn",
  }[tone];
  const iconBg = {
    bull: "bg-bull-soft text-bull",
    bear: "bg-bear-soft text-bear",
    neutral: "bg-white/8 text-foreground",
    info: "bg-info-soft text-info",
    warn: "bg-warn-soft text-warn",
  }[tone];

  return (
    <Card className="glass-card relative overflow-hidden p-4 gap-2">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          {label}
        </span>
        <div className={cn("flex size-7 items-center justify-center rounded-lg", iconBg)}>
          <Icon className="size-3.5" />
        </div>
      </div>
      <div className={cn("text-2xl font-bold tabular-nums tracking-tight", toneClass)}>
        {value}
      </div>
      {sub && <div className="text-xs text-muted-foreground">{sub}</div>}
      {spark}
    </Card>
  );
}

export function StatsGrid({
  data,
  unrealizedPnl,
  openExposure,
  account,
}: {
  data: DashboardData;
  /** Live totals from the Flask /api/positions/live endpoint (see lib/live-positions.ts). */
  unrealizedPnl?: number;
  openExposure?: number;
  /** Live Alpaca account state from /api/account. When available, replaces the
   *  synthetic journal-derived equity/cash with the broker's actual balance. */
  account?: AlpacaAccountData | null;
}) {
  const liveEquity = account?.equity ?? data.equity;
  const liveCash = account?.cash ?? data.cash;
  const buyingPower = account?.buying_power;
  const portfolioValue = account?.portfolio_value;

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-8">
      <StatCard
        label="Account Equity"
        value={account ? formatMoneyCompact(liveEquity) : formatMoneyCompact(data.equity)}
        sub={account
          ? `Cash ${formatMoneyCompact(liveCash)}`
          : `Cash ${formatMoneyCompact(data.cash)}`}
        icon={Wallet}
        tone="neutral"
        spark={account
          ? undefined
          : <Sparkline data={data.equitySeries.map((p) => ({ v: p.v }))} positive={data.totalPnl >= 0} />}
      />
      <StatCard
        label="Realized P&L"
        value={formatMoney(data.totalPnl)}
        sub={`Today ${formatMoney(data.dailyPnl)}`}
        icon={data.totalPnl >= 0 ? TrendingUp : TrendingDown}
        tone={data.totalPnl >= 0 ? "bull" : "bear"}
      />
      <StatCard
        label="Unrealized P&L"
        value={unrealizedPnl == null ? "—" : formatMoney(unrealizedPnl)}
        sub="live open-position mark"
        icon={Activity}
        tone={unrealizedPnl == null ? "neutral" : unrealizedPnl >= 0 ? "bull" : "bear"}
      />
      <StatCard
        label="Open Exposure"
        value={openExposure == null ? "—" : formatMoneyCompact(openExposure)}
        sub="cost basis at risk"
        icon={PieChart}
        tone="info"
      />
      <StatCard
        label="Open Positions"
        value={data.openPositions}
        icon={Layers}
        tone="info"
      />
      <StatCard
        label="Win Rate"
        value={formatPct0(data.winRate)}
        sub={`${data.totalTrades} closed trades`}
        icon={Target}
        tone={data.winRate >= 0.5 ? "bull" : "bear"}
      />
      <StatCard
        label="K2 Confidence"
        value={formatPct0(data.avgK2Conf)}
        sub="avg across candidates"
        icon={ShieldCheck}
        tone="info"
      />
      <StatCard
        label="Qwen Approve Rate"
        value={formatPct0(data.approveRate)}
        sub={`${data.candidateCount} candidates analyzed`}
        icon={Percent}
        tone={data.approveRate >= 0.3 ? "bull" : "warn"}
      />
    </div>
  );
}
