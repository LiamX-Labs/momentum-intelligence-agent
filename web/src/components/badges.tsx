import { cn } from "@/lib/utils";
import type { Direction, Recommendation, Regime } from "@/lib/types";
import { ArrowUpRight, ArrowDownRight } from "lucide-react";

export function DirectionBadge({ direction }: { direction: Direction }) {
  const isCall = direction === "CALL";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold",
        isCall ? "bg-bull-soft text-bull" : "bg-bear-soft text-bear"
      )}
    >
      {isCall ? <ArrowUpRight className="size-3" /> : <ArrowDownRight className="size-3" />}
      {direction}
    </span>
  );
}

export function RecommendationBadge({ rec }: { rec: Recommendation }) {
  const approve = rec === "APPROVE";
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold",
        approve ? "bg-bull-soft text-bull" : "bg-bear-soft text-bear"
      )}
    >
      {rec}
    </span>
  );
}

export function DecisionBadge({ approved }: { approved: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-bold tracking-wide",
        approved ? "bg-bull-soft text-bull" : "bg-bear-soft text-bear"
      )}
    >
      {approved ? "APPROVED" : "REJECTED"}
    </span>
  );
}

export function RegimeBadge({ regime, className }: { regime: Regime | string; className?: string }) {
  const map: Record<string, string> = {
    BULL: "bg-bull-soft text-bull",
    NEUTRAL: "bg-warn-soft text-warn",
    BEAR: "bg-bear-soft text-bear",
    UNKNOWN: "bg-muted text-muted-foreground",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-3 py-1 text-xs font-bold uppercase tracking-wider",
        map[regime] ?? map.UNKNOWN,
        className
      )}
    >
      {regime}
    </span>
  );
}

export function StatusBadge({ open }: { open: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold",
        open ? "bg-info-soft text-info" : "bg-muted text-muted-foreground"
      )}
    >
      {open ? "OPEN" : "CLOSED"}
    </span>
  );
}

export function ScoreBar({
  value,
  max = 100,
  className,
  colorFor,
}: {
  value: number;
  max?: number;
  className?: string;
  colorFor?: (v: number) => string;
}) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  const color =
    colorFor?.(value) ??
    (pct >= 75 ? "var(--bull-foreground)" : pct >= 55 ? "var(--warn)" : "var(--bear-foreground)");
  return (
    <div className={cn("h-1.5 w-full min-w-14 overflow-hidden rounded-full bg-white/8", className)}>
      <div
        className="h-full rounded-full transition-all"
        style={{ width: `${pct}%`, background: color }}
      />
    </div>
  );
}
