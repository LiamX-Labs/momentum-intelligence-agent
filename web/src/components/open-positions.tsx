"use client";

import * as React from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { DirectionBadge } from "@/components/badges";
import type { Trade } from "@/lib/types";
import { formatMoney, formatPct } from "@/lib/format";
import { cn } from "@/lib/utils";
import { closePosition, type LivePosition } from "@/lib/live-positions";
import { Clock, BarChart3, X, Loader2, AlertTriangle } from "lucide-react";

function HoldingDaysBadge({ entryTime, expected }: { entryTime: string; expected: number }) {
  const days = Math.floor(
    (Date.now() - new Date(entryTime).getTime()) / 86400000
  );
  return (
    <span className={cn(
      "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
      days >= expected ? "bg-warn-soft text-warn" : "bg-white/8 text-foreground"
    )}>
      <Clock className="size-3" />
      {days}d / {expected}d
    </span>
  );
}

function PnlText({ value, pct }: { value: number | null | undefined; pct?: number | null }) {
  if (value == null) return <span className="text-muted-foreground">—</span>;
  const positive = value >= 0;
  return (
    <span className={cn("font-semibold tabular-nums", positive ? "text-bull" : "text-bear")}>
      {formatMoney(value)}
      {pct != null && <span className="ml-1 text-xs opacity-70">({formatPct(pct)})</span>}
    </span>
  );
}

function DeltaText({ delta }: { delta: number | null | undefined }) {
  if (delta == null) return <span className="text-muted-foreground">—</span>;
  return <span className="tabular-nums text-muted-foreground">{delta.toFixed(2)}</span>;
}

/** Confirmation modal + trigger button for the manual "Close Position" override. */
function ClosePositionAction({
  trade,
  onClosed,
}: {
  trade: Trade;
  onClosed: () => void;
}) {
  const [open, setOpen] = React.useState(false);
  const [closing, setClosing] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const handleConfirm = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setClosing(true);
    setError(null);
    try {
      await closePosition(trade.option_symbol, "Manual close (dashboard)");
      setOpen(false);
      onClosed();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Close failed");
    } finally {
      setClosing(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Button
        variant="outline"
        size="sm"
        className="h-7 gap-1 text-xs text-bear hover:bg-bear-soft"
        onClick={(e) => {
          e.stopPropagation();
          setOpen(true);
        }}
      >
        <X className="size-3" />
        Close
      </Button>
      <DialogContent onClick={(e) => e.stopPropagation()}>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <AlertTriangle className="size-4 text-warn" />
            Close {trade.symbol} position?
          </DialogTitle>
          <DialogDescription>
            This immediately submits a market sell-to-close for{" "}
            <span className="font-mono text-foreground">{trade.option_symbol}</span> ({trade.quantity}{" "}
            contracts). Large closes are automatically split into sub-500-contract orders. This cannot
            be undone.
          </DialogDescription>
        </DialogHeader>
        {error && (
          <p className="rounded-md bg-bear-soft px-3 py-2 text-xs text-bear">{error}</p>
        )}
        <DialogFooter>
          <DialogClose render={<Button variant="outline" disabled={closing} />}>
            Cancel
          </DialogClose>
          <Button
            variant="default"
            className="bg-bear text-white hover:bg-bear/90"
            disabled={closing}
            onClick={handleConfirm}
          >
            {closing && <Loader2 className="size-3.5 animate-spin" />}
            {closing ? "Closing…" : "Confirm Close"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function OpenPositions({
  trades,
  onTradeClick,
  livePositions,
  onPositionClosed,
}: {
  trades: Trade[];
  onTradeClick: (t: Trade) => void;
  /** option_symbol -> live mark/delta/PnL, from the Flask /api/positions/live endpoint. */
  livePositions?: Record<string, LivePosition>;
  onPositionClosed?: () => void;
}) {
  if (!trades.length) {
    return (
      <Card className="glass-card p-10 text-center text-muted-foreground">
        No open positions.
      </Card>
    );
  }

  const handleClosed = () => onPositionClosed?.();

  return (
    <Card className="glass-card overflow-hidden">
      <CardHeader className="border-b border-border px-4 py-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <BarChart3 className="size-4 text-info" />
          Open Positions
          <span className="ml-1 rounded-full bg-info-soft px-2 py-0.5 text-[11px] font-medium text-info">
            {trades.length}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <ScrollArea className="max-h-[560px]">
          {/* ── Desktop / tablet table (>=768px) ─────────────────── */}
          <table className="hidden w-full text-left text-sm md:table">
            <thead>
              <tr className="border-b border-border">
                <th className="px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Symbol</th>
                <th className="px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Option</th>
                <th className="px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Type</th>
                <th className="px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Qty</th>
                <th className="px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Entry</th>
                <th className="px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Current</th>
                <th className="px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Delta</th>
                <th className="px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Unrealized P&L</th>
                <th className="px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Holding</th>
                <th className="px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground" />
              </tr>
            </thead>
            <tbody>
              {trades.map((t, i) => {
                const live = livePositions?.[t.option_symbol];
                return (
                  <React.Fragment key={t.trade_id}>
                    {i > 0 && <tr><td colSpan={10} className="p-0"><Separator /></td></tr>}
                    <tr
                      onClick={() => onTradeClick(t)}
                      className="cursor-pointer transition-colors hover:bg-white/[0.03]"
                    >
                      <td className="px-4 py-3 font-bold">{t.symbol}</td>
                      <td className="px-4 py-3 font-mono text-[11px] text-muted-foreground">
                        {t.option_symbol.slice(0, 22)}{t.option_symbol.length > 22 ? "…" : ""}
                      </td>
                      <td className="px-4 py-3"><DirectionBadge direction={t.direction} /></td>
                      <td className="px-4 py-3 tabular-nums">{t.quantity}</td>
                      <td className="px-4 py-3 tabular-nums">${t.entry_price.toFixed(2)}</td>
                      <td className="px-4 py-3 tabular-nums">
                        {live?.current_price != null ? `$${live.current_price.toFixed(2)}` : "—"}
                      </td>
                      <td className="px-4 py-3"><DeltaText delta={live?.delta} /></td>
                      <td className="px-4 py-3">
                        <PnlText value={live?.unrealized_pnl} pct={live?.unrealized_pnl_pct} />
                      </td>
                      <td className="px-4 py-3">
                        <HoldingDaysBadge entryTime={t.entry_time} expected={t.expected_holding_days} />
                      </td>
                      <td className="px-4 py-3">
                        <ClosePositionAction trade={t} onClosed={handleClosed} />
                      </td>
                    </tr>
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>

          {/* ── Mobile stacked cards (<768px) ────────────────────── */}
          <div className="flex flex-col gap-2 p-3 md:hidden">
            {trades.map((t) => {
              const live = livePositions?.[t.option_symbol];
              return (
                <div
                  key={t.trade_id}
                  onClick={() => onTradeClick(t)}
                  className="cursor-pointer rounded-lg border border-white/[0.06] bg-white/[0.02] p-3 active:bg-white/[0.04]"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="font-bold">{t.symbol}</span>
                      <DirectionBadge direction={t.direction} />
                    </div>
                    <PnlText value={live?.unrealized_pnl} pct={live?.unrealized_pnl_pct} />
                  </div>
                  <p className="mt-1 font-mono text-[11px] text-muted-foreground">
                    {t.option_symbol}
                  </p>
                  <div className="mt-2 grid grid-cols-4 gap-2 text-xs">
                    <div>
                      <div className="text-[10px] uppercase text-muted-foreground">Qty</div>
                      <div className="tabular-nums">{t.quantity}</div>
                    </div>
                    <div>
                      <div className="text-[10px] uppercase text-muted-foreground">Entry</div>
                      <div className="tabular-nums">${t.entry_price.toFixed(2)}</div>
                    </div>
                    <div>
                      <div className="text-[10px] uppercase text-muted-foreground">Current</div>
                      <div className="tabular-nums">
                        {live?.current_price != null ? `$${live.current_price.toFixed(2)}` : "—"}
                      </div>
                    </div>
                    <div>
                      <div className="text-[10px] uppercase text-muted-foreground">Delta</div>
                      <DeltaText delta={live?.delta} />
                    </div>
                  </div>
                  <div className="mt-2 flex items-center justify-between">
                    <HoldingDaysBadge entryTime={t.entry_time} expected={t.expected_holding_days} />
                    <ClosePositionAction trade={t} onClosed={handleClosed} />
                  </div>
                </div>
              );
            })}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}
