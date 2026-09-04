"use client";

import * as React from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  DirectionBadge,
  DecisionBadge,
  RegimeBadge,
} from "@/components/badges";
import type { CycleReport } from "@/lib/types";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import {
  FileText,
  CheckCircle2,
  XCircle,
  Brain,
  Activity,
  Users,
} from "lucide-react";

function VerdictRow({
  v,
}: {
  v: {
    symbol: string;
    approved: boolean;
    direction: string;
    k2_agreed: boolean;
    qwen_agreed: boolean;
    final_score: number;
    why_approved_or_rejected: string;
    key_concern: string;
  };
}) {
  return (
    <div
      className={cn(
        "flex items-start gap-3 rounded-lg border px-3 py-2.5",
        v.approved ? "bg-bull-soft/30" : "bg-bear-soft/30"
      )}
      style={{
        borderColor: v.approved
          ? "color-mix(in oklch, var(--bull-foreground) 12%, transparent)"
          : "color-mix(in oklch, var(--bear-foreground) 12%, transparent)",
      }}
    >
      <div className="mt-0.5">
        <DecisionBadge approved={v.approved} />
      </div>
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-bold">{v.symbol}</span>
          <DirectionBadge direction={v.direction as "CALL" | "PUT"} />
          <span className="text-[11px] tabular-nums text-muted-foreground">
            score {v.final_score.toFixed(2)}
          </span>
          <div className="flex items-center gap-1 text-[10px]">
            <span className={cn("flex items-center gap-0.5 rounded px-1.5 py-0.5", v.k2_agreed ? "bg-bull-soft/50 text-bull" : "bg-bear-soft/50 text-bear")}>
              {v.k2_agreed ? <CheckCircle2 className="size-2.5" /> : <XCircle className="size-2.5" />}
              K2
            </span>
            <span className={cn("flex items-center gap-0.5 rounded px-1.5 py-0.5", v.qwen_agreed ? "bg-bull-soft/50 text-bull" : "bg-bear-soft/50 text-bear")}>
              {v.qwen_agreed ? <CheckCircle2 className="size-2.5" /> : <XCircle className="size-2.5" />}
              Qwen
            </span>
          </div>
        </div>
        <p className="text-xs text-foreground/80">{v.why_approved_or_rejected}</p>
        {v.key_concern && (
          <p className="text-[11px] text-warn">
            <span className="font-semibold">Key concern:</span> {v.key_concern}
          </p>
        )}
      </div>
    </div>
  );
}

export function CycleReportView({
  report,
}: {
  report: CycleReport;
}) {
  return (
    <Card className="glass-card overflow-hidden">
      <CardHeader className="flex flex-row items-center justify-between border-b border-border px-4 py-3">
        <div className="flex items-center gap-3">
          <div className="flex size-8 items-center justify-center rounded-lg bg-teal-soft">
            <FileText className="size-4 text-teal" />
          </div>
          <div>
            <CardTitle className="text-sm font-semibold">
              Cycle #{report.cycle_number} — AI Reporter Summary
            </CardTitle>
            <p className="text-[11px] text-muted-foreground">
              {formatDate(report.timestamp)} · {report.total_candidates} symbols analyzed
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <RegimeBadge regime={report.regime as "BULL" | "NEUTRAL" | "BEAR"} />
          <div className="flex items-center gap-2 text-[11px] tabular-nums">
            <span className="flex items-center gap-1 text-bull">
              <CheckCircle2 className="size-3" />
              {report.total_approved}
            </span>
            <span className="flex items-center gap-1 text-bear">
              <XCircle className="size-3" />
              {report.total_rejected}
            </span>
          </div>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {/* ── Executive summary ──────────────────────── */}
        <div className="border-b border-border px-5 py-4">
          <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-teal">
            <Brain className="size-3.5" />
            EXECUTIVE SUMMARY
          </div>
          <div className="space-y-2 text-sm leading-relaxed text-foreground/85">
            {report.summary
              .replace(/\\n/g, "\n")
              .split("\n")
              .filter(Boolean)
              .map((para, i) => (
                <p key={i}>{para}</p>
              ))}
          </div>
        </div>

        {/* ── Agent agreement matrix ────────────────── */}
        <div className="border-b border-border px-5 py-3">
          <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
            <Users className="size-3.5" />
            AGENT CONSENSUS
          </div>
          <div className="grid grid-cols-3 gap-3 text-center text-xs">
            <div className="rounded-lg border border-border bg-white/[0.02] px-3 py-2">
              <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
                Both Approved
              </div>
              <div className="mt-0.5 text-lg font-bold text-bull tabular-nums">
                {report.verdicts.filter((v) => v.k2_agreed && v.qwen_agreed).length}
              </div>
            </div>
            <div className="rounded-lg border border-border bg-white/[0.02] px-3 py-2">
              <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
                K2 Only
              </div>
              <div className="mt-0.5 text-lg font-bold text-warn tabular-nums">
                {report.verdicts.filter((v) => v.k2_agreed && !v.qwen_agreed).length}
              </div>
            </div>
            <div className="rounded-lg border border-border bg-white/[0.02] px-3 py-2">
              <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
                Both Rejected
              </div>
              <div className="mt-0.5 text-lg font-bold text-bear tabular-nums">
                {report.verdicts.filter((v) => !v.k2_agreed && !v.qwen_agreed).length}
              </div>
            </div>
          </div>
        </div>

        {/* ── Per-symbol verdicts ───────────────────── */}
        <div className="px-5 py-3">
          <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
            <Activity className="size-3.5" />
            PER-SYMBOL VERDICTS
          </div>
          <div className="space-y-2">
            {report.verdicts.map((v) => (
              <VerdictRow key={v.symbol} v={v} />
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}