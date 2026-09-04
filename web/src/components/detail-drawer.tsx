"use client";

import * as React from "react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { DirectionBadge, StatusBadge } from "@/components/badges";
import type { Trade } from "@/lib/types";
import { formatDate, formatMoney } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Shield, BookOpen, AlertTriangle, Clock, DollarSign, Gauge, Calendar, TrendingUp } from "lucide-react";

export type DetailDrawerTrade = Trade;

export function DetailDrawer({
  trade,
  open,
  onOpenChange,
}: {
  trade: Trade | null;
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  if (!trade) return null;
  const t = trade;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full gap-0 p-0 sm:max-w-xl">
        <SheetHeader className="border-b border-border px-5 py-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <SheetTitle className="flex items-center gap-2 text-xl">
                {t.symbol}
                <DirectionBadge direction={t.direction} />
              </SheetTitle>
              <SheetDescription className="mt-1">
                {t.option_symbol} · {t.quantity} contract{t.quantity > 1 ? "s" : ""}
              </SheetDescription>
            </div>
            <StatusBadge open={!t.exit_time} />
          </div>
        </SheetHeader>

        <ScrollArea className="h-[calc(100vh-73px)]">
          <div className="space-y-5 px-5 py-5">
            {/* ── Summary grid ─────────────────────────────────── */}
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <SummaryBox label="Entry Price" value={`$${t.entry_price.toFixed(2)}`} icon={DollarSign} />
              <SummaryBox
                label="Exit Price"
                value={t.exit_price != null ? `$${t.exit_price.toFixed(2)}` : "—"}
                icon={DollarSign}
              />
              <SummaryBox
                label="P&L"
                value={t.pnl != null ? formatMoney(t.pnl) : "—"}
                tone={t.pnl != null ? (t.pnl >= 0 ? "bull" : "bear") : "neutral"}
                icon={Gauge}
              />
              <SummaryBox
                label="Confidence"
                value={t.confidence != null ? `${(t.confidence * 100).toFixed(0)}%` : "—"}
                icon={Shield}
                tone="info"
              />
            </div>

            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              <SummaryBox label="Entry Date" value={formatDate(t.entry_time)} icon={Clock} />
              <SummaryBox label="Exit Date" value={t.exit_time ? formatDate(t.exit_time) : "—"} icon={Clock} />
              <SummaryBox
                label="Holding Period"
                value={t.holding_days != null ? `${t.holding_days} days` : `Expected ${t.expected_holding_days}d`}
                icon={Calendar}
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <SummaryBox label="Entry Momentum Rank" value={t.entry_momentum_rank?.toString() ?? "—"} icon={TrendingUp} />
              <SummaryBox label="Expected Holding" value={`${t.expected_holding_days} days`} icon={Calendar} />
              <SummaryBox label="Max Holding" value={`${t.max_holding_days} days`} icon={Calendar} />
              <SummaryBox label="Order ID" value={t.order_id?.slice(0, 16) ?? "—"} icon={Clock} />
            </div>

            <Separator />

            {/* ── Thesis ───────────────────────────────────────── */}
            <div>
              <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-muted-foreground">
                <BookOpen className="size-4" />
                TRADING THESIS
              </div>
              <div className="rounded-xl border border-border bg-white/[0.02] p-4 text-sm leading-relaxed">
                {t.thesis}
              </div>
            </div>

            {/* ── Invalidation ─────────────────────────────────── */}
            {t.invalidation && (
              <div>
                <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-muted-foreground">
                  <AlertTriangle className="size-4 text-warn" />
                  INVALIDATION CONDITIONS
                </div>
                <div className="rounded-xl border border-warn/20 bg-warn-soft/30 px-4 py-3 text-sm text-warn">
                  {t.invalidation}
                </div>
              </div>
            )}

            {/* ── Exit reason ──────────────────────────────────── */}
            {t.exit_reason && (
              <div>
                <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-muted-foreground">
                  <AlertTriangle className="size-4 text-bear" />
                  EXIT REASON
                </div>
                <div className="rounded-xl border border-bear/20 bg-bear-soft/30 px-4 py-3 text-sm text-bear">
                  {t.exit_reason}
                </div>
              </div>
            )}
          </div>
        </ScrollArea>
      </SheetContent>
    </Sheet>
  );
}

function SummaryBox({
  label,
  value,
  icon: Icon,
  tone = "neutral",
}: {
  label: string;
  value: string;
  icon: React.ComponentType<{ className?: string }>;
  tone?: "bull" | "bear" | "neutral" | "info" | "warn";
}) {
  const toneClass = {
    bull: "text-bull",
    bear: "text-bear",
    neutral: "text-foreground",
    info: "text-info",
    warn: "text-warn",
  }[tone];
  return (
    <div className="rounded-xl border border-border bg-white/[0.02] p-3">
      <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
        <Icon className="size-3" />
        {label}
      </div>
      <div className={cn("mt-1 text-base font-bold tabular-nums tracking-tight", toneClass)}>
        {value}
      </div>
    </div>
  );
}