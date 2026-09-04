"use client";

import * as React from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { DirectionBadge, StatusBadge } from "@/components/badges";
import type { Trade } from "@/lib/types";
import { formatDate, formatMoney, safeFloat } from "@/lib/format";
import { cn } from "@/lib/utils";
import { History } from "lucide-react";

export function TradeHistory({
  trades,
  onTradeClick,
}: {
  trades: Trade[];
  onTradeClick: (t: Trade) => void;
}) {
  if (!trades.length) {
    return (
      <Card className="glass-card p-10 text-center text-muted-foreground">
        No closed trades yet. Run the pipeline to generate trades.
      </Card>
    );
  }

  return (
    <Card className="glass-card overflow-hidden">
      <CardHeader className="border-b border-border px-4 py-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <History className="size-4 text-info" />
          Trade History
          <span className="ml-1 rounded-full bg-white/8 px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
            {trades.length} trades
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <ScrollArea className="max-h-[600px]">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Symbol</th>
                <th className="px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Option</th>
                <th className="px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Dir</th>
                <th className="px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Qty</th>
                <th className="px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Entry</th>
                <th className="px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Exit</th>
                <th className="px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">P&amp;L</th>
                <th className="px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Days</th>
                <th className="px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Exit Reason</th>
                <th className="px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Status</th>
              </tr>
            </thead>
            <tbody>
              {[...trades].reverse().map((t, i) => (
                <React.Fragment key={t.trade_id}>
                  {i > 0 && <tr><td colSpan={10} className="p-0"><Separator /></td></tr>}
                  <tr
                    onClick={() => onTradeClick(t)}
                    className="cursor-pointer transition-colors hover:bg-white/[0.03]"
                  >
                    <td className="px-3 py-3 font-bold">{t.symbol}</td>
                    <td className="px-3 py-3 font-mono text-[11px] text-muted-foreground">
                      {t.option_symbol.slice(0, 18)}{t.option_symbol.length > 18 ? "…" : ""}
                    </td>
                    <td className="px-3 py-3"><DirectionBadge direction={t.direction} /></td>
                    <td className="px-3 py-3 tabular-nums">{t.quantity}</td>
                    <td className="px-3 py-3 tabular-nums">${(t.entry_price ?? 0).toFixed(2)}</td>
                    <td className="px-3 py-3 tabular-nums">
                      {t.exit_price != null ? `$${t.exit_price.toFixed(2)}` : "—"}
                    </td>
                    <td className={cn("px-3 py-3 font-bold tabular-nums",
                      safeFloat(t.pnl) >= 0 ? "text-bull" : "text-bear"
                    )}>
                      {formatMoney(safeFloat(t.pnl))}
                    </td>
                    <td className="px-3 py-3 tabular-nums">{t.holding_days ?? "—"}</td>
                    <td className="px-3 py-3">
                      <Tooltip>
<TooltipTrigger className="block max-w-[160px] cursor-default truncate text-[11px] text-muted-foreground text-left">
{t.exit_reason?.slice(0, 40)}{t.exit_reason?.length > 40 ? "…" : ""}
</TooltipTrigger>
                        <TooltipContent side="left" className="max-w-sm text-xs">{t.exit_reason}</TooltipContent>
                      </Tooltip>
                    </td>
                    <td className="px-3 py-3"><StatusBadge open={false} /></td>
                  </tr>
                </React.Fragment>
              ))}
            </tbody>
          </table>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}