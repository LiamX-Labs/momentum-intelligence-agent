"use client";

import * as React from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Badge } from "@/components/ui/badge";
import type { AlpacaOrder } from "@/lib/types";
import { formatDate, formatMoney } from "@/lib/format";
import { cn } from "@/lib/utils";
import { ListOrdered, Loader2 } from "lucide-react";

function OrderStatusBadge({ status }: { status: string }) {
  const colorMap: Record<string, string> = {
    filled: "bg-green-500/10 text-green-500 border-green-500/20",
    new: "bg-blue-500/10 text-blue-500 border-blue-500/20",
    accepted: "bg-blue-500/10 text-blue-500 border-blue-500/20",
    pending_new: "bg-blue-500/10 text-blue-500 border-blue-500/20",
    partially_filled: "bg-yellow-500/10 text-yellow-500 border-yellow-500/20",
    canceled: "bg-red-500/10 text-red-500 border-red-500/20",
    expired: "bg-red-500/10 text-red-500 border-red-500/20",
    rejected: "bg-red-500/10 text-red-500 border-red-500/20",
    suspended: "bg-orange-500/10 text-orange-500 border-orange-500/20",
    stopped: "bg-red-500/10 text-red-500 border-red-500/20",
    done_for_day: "bg-gray-500/10 text-gray-500 border-gray-500/20",
    pending_cancel: "bg-yellow-500/10 text-yellow-500 border-yellow-500/20",
    pending_replace: "bg-yellow-500/10 text-yellow-500 border-yellow-500/20",
    calculated: "bg-purple-500/10 text-purple-500 border-purple-500/20",
    held: "bg-orange-500/10 text-orange-500 border-orange-500/20",
  };
  const className = colorMap[status] || "bg-white/10 text-muted-foreground border-white/10";
  return (
    <Badge variant="outline" className={cn("text-[10px] font-medium", className)}>
      {status.replace(/_/g, " ")}
    </Badge>
  );
}

function SideLabel({ side }: { side: string }) {
  const isBuy = side === "buy";
  return (
    <span className={cn("text-[11px] font-bold", isBuy ? "text-bull" : "text-bear")}>
      {side.toUpperCase()}
    </span>
  );
}

export function AlpacaOrders({
  orders,
  loading,
}: {
  orders: AlpacaOrder[];
  loading: boolean;
}) {
  if (loading && !orders.length) {
    return (
      <Card className="glass-card p-10 text-center text-muted-foreground">
        <Loader2 className="mx-auto mb-2 size-5 animate-spin opacity-50" />
        <p className="text-sm">Fetching Alpaca order history...</p>
      </Card>
    );
  }

  if (!orders.length) {
    return (
      <Card className="glass-card p-10 text-center text-muted-foreground">
        <p>No orders found on the Alpaca account. Orders will appear here once trades execute.</p>
      </Card>
    );
  }

  return (
    <Card className="glass-card overflow-hidden">
      <CardHeader className="border-b border-border px-4 py-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <ListOrdered className="size-4 text-info" />
          Alpaca Orders
          <span className="ml-1 rounded-full bg-white/8 px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
            {orders.length} orders
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <ScrollArea className="max-h-[600px]">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Symbol</th>
                <th className="px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Side</th>
                <th className="px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Type</th>
                <th className="px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Qty</th>
                <th className="px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Filled</th>
                <th className="px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Avg Price</th>
                <th className="px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Status</th>
                <th className="px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Submitted</th>
                <th className="px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Filled At</th>
                <th className="px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">TIF</th>
              </tr>
            </thead>
            <tbody>
              {[...orders].sort((a, b) => {
                const ta = a.submitted_at ? new Date(a.submitted_at).getTime() : 0;
                const tb = b.submitted_at ? new Date(b.submitted_at).getTime() : 0;
                return tb - ta;
              }).map((o, i) => (
                <React.Fragment key={o.id}>
                  {i > 0 && <tr><td colSpan={10} className="p-0"><Separator /></td></tr>}
                  <tr className="transition-colors hover:bg-white/[0.03]">
                    <td className="px-3 py-3 font-mono text-[11px] font-bold">{o.symbol}</td>
                    <td className="px-3 py-3"><SideLabel side={o.side} /></td>
                    <td className="px-3 py-3 text-[11px] uppercase text-muted-foreground">{o.type}</td>
                    <td className="px-3 py-3 tabular-nums">{o.qty}</td>
                    <td className="px-3 py-3 tabular-nums">
                      {o.filled_qty > 0 ? (
                        <span className="text-bull font-medium">{o.filled_qty}</span>
                      ) : (
                        <span className="text-muted-foreground">{o.filled_qty}</span>
                      )}
                    </td>
                    <td className="px-3 py-3 font-mono tabular-nums text-[11px]">
                      {o.filled_avg_price != null ? `$${o.filled_avg_price.toFixed(4)}` : "—"}
                    </td>
                    <td className="px-3 py-3"><OrderStatusBadge status={o.status} /></td>
                    <td className="px-3 py-3 text-[11px] text-muted-foreground tabular-nums">
                      {formatDate(o.submitted_at)}
                    </td>
                    <td className="px-3 py-3 text-[11px] text-muted-foreground tabular-nums">
                      {o.filled_at ? formatDate(o.filled_at) : "—"}
                    </td>
                    <td className="px-3 py-3 text-[11px] text-muted-foreground">{o.time_in_force}</td>
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