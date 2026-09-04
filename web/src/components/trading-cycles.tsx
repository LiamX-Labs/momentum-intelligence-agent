"use client";

import * as React from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  DirectionBadge,
  RecommendationBadge,
  DecisionBadge,
  ScoreBar,
  RegimeBadge,
} from "@/components/badges";
import { CandidateDrawer } from "./candidate-drawer";
import type { Candidate, RunGroup } from "@/lib/types";
import { formatDate, formatPct0 } from "@/lib/format";
import { cn } from "@/lib/utils";
import { ChevronRight, Calendar, Zap, CheckCircle2, RotateCcw } from "lucide-react";

function ThesisPreview({ text }: { text: string }) {
  if (!text) return <span className="text-muted-foreground/50 italic">No thesis recorded</span>;
  return (
    <Tooltip>
<TooltipTrigger className="block max-w-[260px] cursor-default truncate text-[12px] text-muted-foreground text-left">
{text.slice(0, 80)}{text.length > 80 ? "…" : ""}
</TooltipTrigger>
      <TooltipContent side="left" className="max-w-md text-xs">
        {text}
      </TooltipContent>
    </Tooltip>
  );
}

function CandidateRow({
  c,
  onClick,
}: {
  c: Candidate;
  onClick: () => void;
}) {
  return (
    <tr
      onClick={onClick}
      className="cursor-pointer transition-colors hover:bg-white/[0.03] has-[:focus-visible]:bg-white/[0.05]"
    >
      <td className="px-3 py-3">
        <span className="text-sm font-bold">{c.symbol}</span>
        {c.reused && (
          <span className="ml-1.5 inline-flex items-center rounded-full bg-info-soft px-1.5 py-0.5 text-[10px] font-semibold text-info">
            <RotateCcw className="mr-0.5 size-2.5" />
            reused
          </span>
        )}
      </td>
      <td className="px-3 py-3">
        <DirectionBadge direction={c.direction} />
      </td>
      <td className="px-3 py-3">
        <div className="space-y-1">
          <span className="text-sm font-semibold tabular-nums">
            {c.momentum_score.toFixed(0)}
          </span>
          <ScoreBar value={c.momentum_score} colorFor={(v) =>
            v >= 75 ? "var(--bull-foreground)" : v >= 60 ? "var(--warn)" : "var(--bear-foreground)"
          } />
        </div>
      </td>
      <td className="px-3 py-3">
        <div className="space-y-1">
          <span className="text-sm tabular-nums">{formatPct0(c.k2_confidence)}</span>
          <ScoreBar value={c.k2_confidence * 100} colorFor={(v) =>
            v >= 70 ? "var(--bull-foreground)" : v >= 50 ? "var(--warn)" : "var(--bear-foreground)"
          } />
        </div>
      </td>
      <td className="px-3 py-3">
        <RecommendationBadge rec={c.qwen_recommendation} />
      </td>
      <td className="px-3 py-3 text-sm tabular-nums">{formatPct0(c.qwen_confidence)}</td>
      <td className="px-3 py-3 text-sm font-bold tabular-nums">{(c.final_score ?? 0).toFixed(2)}</td>
      <td className="px-3 py-3">
        <ThesisPreview text={c.thesis} />
      </td>
      <td className="px-3 py-3">
        <DecisionBadge approved={c.approved} />
      </td>
    </tr>
  );
}

function RunGroupCard({
  run,
  onCandidateClick,
}: {
  run: RunGroup;
  onCandidateClick: (c: Candidate) => void;
}) {
  return (
    <Card className="glass-card overflow-hidden">
      <CardHeader className="flex flex-row items-center justify-between border-b border-border px-4 py-3">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 rounded-lg bg-info-soft px-2.5 py-1">
            <Calendar className="size-3.5 text-info" />
            <span className="text-xs font-medium text-info">{formatDate(run.timestamp)}</span>
          </div>
          <Separator orientation="vertical" className="h-4" />
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Zap className="size-3" />
            {run.candidates.length} candidates
          </div>
          <Separator orientation="vertical" className="h-4" />
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <CheckCircle2 className="size-3 text-bull" />
            {run.approvedCount} approved
          </div>
          <RegimeBadge regime={run.regime} className="scale-90" />
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <ScrollArea className="max-h-[420px]">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                  Symbol
                </th>
                <th className="px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                  Dir
                </th>
                <th className="px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                  Momentum
                </th>
                <th className="px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                  K2 Conf
                </th>
                <th className="px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                  Qwen
                </th>
                <th className="px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                  Qwen Conf
                </th>
                <th className="px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                  Final
                </th>
                <th className="px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                  Thesis
                </th>
                <th className="px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                  Decision
                </th>
              </tr>
            </thead>
            <tbody>
              {run.candidates.map((c, i) => (
                <React.Fragment key={`${c.symbol}-${c.timestamp}-${i}`}>
                  {i > 0 && <tr><td colSpan={9} className="p-0"><Separator /></td></tr>}
                  <CandidateRow c={c} onClick={() => onCandidateClick(c)} />
                </React.Fragment>
              ))}
            </tbody>
          </table>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}

export function TradingCycles({
  runs,
  onCandidateClick,
}: {
  runs: RunGroup[];
  onCandidateClick: (c: Candidate) => void;
}) {
  if (!runs.length) {
    return (
      <Card className="glass-card p-10 text-center text-muted-foreground">
        No trading cycles yet. Run <code className="rounded bg-white/10 px-1.5 py-0.5 text-xs">python main.py</code> to generate evaluations.
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      {runs.map((run) => (
        <RunGroupCard key={run.run_id} run={run} onCandidateClick={onCandidateClick} />
      ))}
    </div>
  );
}