"use client";

import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import type { Config } from "@/lib/types";
import { Cpu, Shield, GanttChart, Settings2, Atom } from "lucide-react";

export function SystemInfo({ config }: { config: Config }) {
  return (
    <Card className="glass-card">
      <CardHeader className="border-b border-border px-4 py-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Cpu className="size-4 text-info" />
          System Configuration
        </CardTitle>
      </CardHeader>
      <CardContent className="p-4">
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          <Section icon={Cpu} title="Models">
            <Row label="Primary Analyst" value={config.models?.primary?.model ?? "—"} />
            <Row label="Adversarial Critic" value={config.models?.critic?.model ?? "—"} />
            <Row label="Fallback" value={config.models?.fallback?.model ?? "—"} />
          </Section>

          <Section icon={Shield} title="Risk Limits">
            <Row label="Max Risk / Trade" value={`${((config.risk?.max_risk_per_trade ?? 0.01) * 100).toFixed(0)}%`} />
            <Row label="Max Open Positions" value={String(config.risk?.max_open_positions ?? 5)} />
            <Row label="Max Portfolio Premium" value={`${((config.risk?.max_portfolio_option_premium ?? 0.2) * 100).toFixed(0)}%`} />
            <Row label="Max Symbol Exposure" value={`${((config.risk?.max_symbol_exposure ?? 0.05) * 100).toFixed(0)}%`} />
            <Row label="Max Holding Days" value={`${config.risk?.max_holding_days ?? 10} days`} />
          </Section>

          <Section icon={GanttChart} title="Options">
            <Row label="DTE Range" value={`${config.options?.min_dte ?? 7}-${config.options?.max_dte ?? 21} days`} />
            <Row label="Target Delta" value={`${(config.options?.target_delta_min ?? 0.5).toFixed(2)}-${(config.options?.target_delta_max ?? 0.65).toFixed(2)}`} />
            <Row label="Max Bid-Ask Spread" value={`${((config.options?.max_bid_ask_spread_pct ?? 0.1) * 100).toFixed(0)}%`} />
          </Section>

          <Section icon={Settings2} title="Decision Engine">
            <Row label="Min Momentum Score" value={String(config.decision?.min_momentum_score ?? 60)} />
            <Row label="Min AI Confidence" value={`${((config.decision?.min_ai_confidence ?? 0.75) * 100).toFixed(0)}%`} />
            <Row label="Require Critic Approval" value={config.decision?.require_critic_approval ? "Yes" : "No"} />
          </Section>

          <Section icon={Atom} title="Momentum Engine">
            <Row label="Candidate Count" value={String(config.momentum?.candidate_count ?? 50)} />
            <Row label="Min Score" value={String(config.momentum?.min_score ?? 60)} />
            <Row label="Lookbacks" value={config.momentum?.lookbacks?.join(", ") ?? "1, 3, 5, 10, 20"} />
          </Section>

          <Section icon={Atom} title="Regime Limits">
            <Row label="Bull Max Exposure" value={`${((config.regime?.bull_max_exposure ?? 1.0) * 100).toFixed(0)}%`} />
            <Row label="Neutral Max Exposure" value={`${((config.regime?.neutral_max_exposure ?? 0.6) * 100).toFixed(0)}%`} />
            <Row label="Bear Max Exposure" value={`${((config.regime?.bear_max_exposure ?? 0.25) * 100).toFixed(0)}%`} />
          </Section>
        </div>
      </CardContent>
    </Card>
  );
}

function Section({
  icon: Icon,
  title,
  children,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-sm font-semibold text-muted-foreground">
        <Icon className="size-4" />
        {title}
      </div>
      <div className="space-y-1.5">{children}</div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between rounded-lg bg-white/[0.02] px-3 py-1.5 text-xs">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-mono text-foreground/90">{value}</span>
    </div>
  );
}