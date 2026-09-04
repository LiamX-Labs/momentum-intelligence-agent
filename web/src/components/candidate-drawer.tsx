"use client";

import * as React from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import type { Candidate } from "@/lib/types";
import {
  DirectionBadge,
  RecommendationBadge,
  DecisionBadge,
  ScoreBar,
} from "@/components/badges";
import { formatDate, formatPct0 } from "@/lib/format";
import { cn } from "@/lib/utils";
import {
  Bot,
  ShieldAlert,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Gauge,
  ListChecks,
  FlaskConical,
  RotateCcw,
} from "lucide-react";

function MiniScore({ label, value }: { label: string; value: number }) {
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-[11px]">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-semibold tabular-nums">{formatPct0(value)}</span>
      </div>
      <ScoreBar value={value * 100} />
    </div>
  );
}

function ChatBubble({
  side,
  name,
  subtitle,
  accent,
  icon: Icon,
  children,
}: {
  side: "left" | "right";
  name: string;
  subtitle: string;
  accent: "info" | "warn" | "bear" | "bull";
  icon: React.ComponentType<{ className?: string }>;
  children: React.ReactNode;
}) {
  const accentClasses = {
    info: "bg-info-soft text-info",
    warn: "bg-warn-soft text-warn",
    bear: "bg-bear-soft text-bear",
    bull: "bg-bull-soft text-bull",
  }[accent];
  const avatarClasses = {
    info: "bg-info-soft text-info",
    warn: "bg-warn-soft text-warn",
    bear: "bg-bear-soft text-bear",
    bull: "bg-bull-soft text-bull",
  }[accent];

  return (
    <div className={cn("flex gap-3", side === "right" && "flex-row-reverse")}>
      <div
        className={cn(
          "flex size-9 shrink-0 items-center justify-center rounded-full",
          avatarClasses
        )}
        style={{ border: "1px solid color-mix(in oklch, currentColor 25%, transparent)" }}
      >
        <Icon className="size-4.5" />
      </div>
      <div className={cn("flex max-w-[88%] flex-col gap-2", side === "right" && "items-end")}>
        <div className={cn("flex items-baseline gap-2", side === "right" && "flex-row-reverse")}>
          <span className="text-sm font-semibold">{name}</span>
          <span className="text-[11px] text-muted-foreground">{subtitle}</span>
        </div>
        <div
          className={cn(
            "rounded-2xl border px-4 py-3 text-sm leading-relaxed",
            accentClasses,
            side === "left" ? "rounded-tl-sm" : "rounded-tr-sm"
          )}
        >
          {children}
        </div>
      </div>
    </div>
  );
}

function Pill({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "bull" | "bear" | "warn" | "info" }) {
  const cls = {
    neutral: "bg-white/8 text-foreground",
    bull: "bg-bull-soft text-bull",
    bear: "bg-bear-soft text-bear",
    warn: "bg-warn-soft text-warn",
    info: "bg-info-soft text-info",
  }[tone];
  return (
    <span className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold", cls)}>
      {children}
    </span>
  );
}

function assessmentTone(v: string): "bull" | "bear" | "warn" | "neutral" {
  if (["STRONG", "POSITIVE"].includes(v)) return "bull";
  if (["WEAK", "EXHAUSTED", "NEGATIVE"].includes(v)) return "bear";
  if (["ADEQUATE", "ALREADY_PRICED", "UNCERTAIN"].includes(v)) return "warn";
  return "neutral";
}

export function CandidateDrawer({
  candidate,
  open,
  onOpenChange,
}: {
  candidate: Candidate | null;
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  if (!candidate) return null;
  const c = candidate;
  const k2 = c.k2;
  const qwen = c.qwen;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-h-[85vh] w-full gap-0 p-0 sm:max-w-2xl"
        showCloseButton
      >
        <DialogHeader className="border-b border-border px-6 py-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <DialogTitle className="flex items-center gap-2 text-xl">
                {c.symbol}
                <DirectionBadge direction={c.direction} />
                {c.reused && (
                  <span className="inline-flex items-center gap-1 rounded-full bg-info-soft px-2 py-0.5 text-[11px] font-semibold text-info">
                    <RotateCcw className="size-3" />
                    Reused
                  </span>
                )}
              </DialogTitle>
              <DialogDescription className="mt-1">
                {formatDate(c.timestamp)} · Momentum {c.momentum_score.toFixed(0)} · Regime {c.regime}
              </DialogDescription>
            </div>
            <DecisionBadge approved={c.approved} />
          </div>
        </DialogHeader>

        <ScrollArea className="max-h-[calc(85vh-73px)]">
          <div className="space-y-6 px-6 py-5">
            {/* ── Decision summary ─────────────────────────────── */}
            <div className="grid grid-cols-3 gap-3">
              <div className="rounded-xl border border-border bg-white/[0.02] p-3">
                <div className="text-[11px] uppercase tracking-wide text-muted-foreground">Final Score</div>
                <div className="mt-1 text-lg font-bold tabular-nums">{c.final_score.toFixed(2)}</div>
              </div>
              <div className="rounded-xl border border-border bg-white/[0.02] p-3">
                <div className="text-[11px] uppercase tracking-wide text-muted-foreground">K2 Confidence</div>
                <div className="mt-1 text-lg font-bold tabular-nums">{formatPct0(c.k2_confidence)}</div>
              </div>
              <div className="rounded-xl border border-border bg-white/[0.02] p-3">
                <div className="text-[11px] uppercase tracking-wide text-muted-foreground">Qwen Adjusted</div>
                <div className="mt-1 text-lg font-bold tabular-nums">{formatPct0(c.qwen_confidence)}</div>
              </div>
            </div>

            {!c.approved && (c.reject_reason || c.risk_reason) && (
              <div className="flex items-start gap-2 rounded-xl border bg-bear-soft px-4 py-3 text-sm text-bear"
                style={{ borderColor: "color-mix(in oklch, var(--bear-foreground) 20%, transparent)" }}
              >
                <XCircle className="mt-0.5 size-4 shrink-0" />
                <div>
                  <div className="font-semibold">Rejected</div>
                  <div className="mt-0.5 text-bear/90">{c.reject_reason || c.risk_reason}</div>
                </div>
              </div>
            )}
            {c.approved && (
              <div className="flex items-start gap-2 rounded-xl border bg-bull-soft px-4 py-3 text-sm text-bull"
                style={{ borderColor: "color-mix(in oklch, var(--bull-foreground) 20%, transparent)" }}
              >
                <CheckCircle2 className="mt-0.5 size-4 shrink-0" />
                <div className="font-semibold">Approved by dual-model AI review{c.risk_approved === false ? " — later rejected by risk gates" : ""}</div>
              </div>
            )}

            <Separator />

            {/* ── AI Debate ────────────────────────────────────── */}
            <div>
              <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-muted-foreground">
                <FlaskConical className="size-4" />
                AI ADVERSARIAL DEBATE
              </div>

              <div className="space-y-6">
                {/* K2 Analyst */}
                <ChatBubble side="left" name="K2 Analyst" subtitle="moonshotai/Kimi-K2-Instruct" accent="info" icon={Bot}>
                  {k2 ? (
                    <div className="space-y-3">
                      <p className="text-foreground/90">{k2.thesis || c.thesis}</p>
                      <div className="grid grid-cols-3 gap-3 pt-1">
                        <MiniScore label="Momentum" value={k2.momentum_quality} />
                        <MiniScore label="Fundamental" value={k2.fundamental_quality} />
                        <MiniScore label="Catalyst" value={k2.catalyst_strength} />
                      </div>
                      <div className="flex flex-wrap gap-1.5 pt-1">
                        <Pill tone={k2.catalyst_classification === "POSITIVE" ? "bull" : k2.catalyst_classification === "NEGATIVE" ? "bear" : "neutral"}>
                          Catalyst: {k2.catalyst_classification}
                        </Pill>
                        <Pill tone="neutral">Hold ~{k2.expected_holding_days}d</Pill>
                        <Pill tone={k2.risk_level > 0.6 ? "bear" : k2.risk_level > 0.35 ? "warn" : "bull"}>
                          Risk {formatPct0(k2.risk_level)}
                        </Pill>
                      </div>
                      {k2.key_risks?.length > 0 && (
                        <div className="pt-1">
                          <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-info/80">Key Risks</div>
                          <ul className="space-y-1 text-xs text-foreground/80">
                            {k2.key_risks.map((r, i) => (
                              <li key={i} className="flex gap-1.5">
                                <span className="text-info">•</span>
                                {r}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                      <div className="rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-xs text-foreground/70">
                        <span className="font-semibold text-info/80">Invalidation: </span>
                        {k2.invalidation}
                      </div>
                    </div>
                  ) : (
                    <p className="text-foreground/90">{c.thesis || "No K2 thesis recorded for this candidate."}</p>
                  )}
                </ChatBubble>

                {/* Qwen Critic */}
                <ChatBubble
                  side="right"
                  name="Qwen Critic"
                  subtitle="Qwen/Qwen3-32B · adversarial review"
                  accent={qwen?.recommendation === "APPROVE" ? "bull" : "bear"}
                  icon={ShieldAlert}
                >
                  {qwen ? (
                    <div className="space-y-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <RecommendationBadge rec={qwen.recommendation} />
                        <Pill tone={qwen.thesis_valid ? "bull" : "bear"}>
                          Thesis {qwen.thesis_valid ? "valid" : "invalid"}
                        </Pill>
                        <Pill tone={qwen.risk_score > 0.6 ? "bear" : qwen.risk_score > 0.35 ? "warn" : "bull"}>
                          Risk score {formatPct0(qwen.risk_score)}
                        </Pill>
                      </div>

                      <div className="flex flex-wrap gap-1.5">
                        <Pill tone={assessmentTone(qwen.momentum_assessment)}>Momentum: {qwen.momentum_assessment}</Pill>
                        <Pill tone={assessmentTone(qwen.fundamental_assessment)}>Fundamentals: {qwen.fundamental_assessment}</Pill>
                        <Pill tone={assessmentTone(qwen.catalyst_assessment)}>Catalyst: {qwen.catalyst_assessment}</Pill>
                      </div>

                      {qwen.concerns?.length > 0 && (
                        <div>
                          <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-foreground/70">
                            Concerns raised
                          </div>
                          <ul className="space-y-1 text-xs text-foreground/85">
                            {qwen.concerns.map((cn, i) => (
                              <li key={i} className="flex gap-1.5">
                                <AlertTriangle className="mt-0.5 size-3 shrink-0 text-warn" />
                                {cn}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {qwen.contradictions?.length > 0 && (
                        <div>
                          <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-foreground/70">
                            Contradictions found
                          </div>
                          <ul className="space-y-1 text-xs text-foreground/85">
                            {qwen.contradictions.map((cn, i) => (
                              <li key={i} className="flex gap-1.5">
                                <XCircle className="mt-0.5 size-3 shrink-0 text-bear" />
                                {cn}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {qwen.invalidation_conditions?.length > 0 && (
                        <div className="rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-xs text-foreground/70">
                          <div className="mb-1 font-semibold text-foreground/80">Invalidation conditions</div>
                          <ul className="space-y-0.5">
                            {qwen.invalidation_conditions.map((ic, i) => (
                              <li key={i}>• {ic}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  ) : (
                    <p>
                      No structured Qwen critique recorded — decision engine used {c.qwen_recommendation} at{" "}
                      {formatPct0(c.qwen_confidence)} adjusted confidence.
                    </p>
                  )}
                </ChatBubble>
              </div>
            </div>

            {/* ── Risk gates ───────────────────────────────────── */}
            {c.gates && c.gates.length > 0 && (
              <>
                <Separator />
                <div>
                  <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-muted-foreground">
                    <ListChecks className="size-4" />
                    DETERMINISTIC RISK GATES
                  </div>
                  <div className="space-y-1.5">
                    {c.gates.map(([name, passed, detail], i) => (
                      <div
                        key={i}
                        className={cn(
                          "flex items-start gap-2 rounded-lg border px-3 py-2 text-xs",
                          passed ? "bg-bull-soft/40" : "bg-bear-soft/40"
                        )}
                        style={{ borderColor: passed ? "color-mix(in oklch, var(--bull-foreground) 15%, transparent)" : "color-mix(in oklch, var(--bear-foreground) 15%, transparent)" }}
                      >
                        {passed ? (
                          <CheckCircle2 className="mt-0.5 size-3.5 shrink-0 text-bull" />
                        ) : (
                          <XCircle className="mt-0.5 size-3.5 shrink-0 text-bear" />
                        )}
                        <div>
                          <span className="font-semibold">{name}</span>
                          <span className="text-muted-foreground"> — {detail}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                  {c.position_size && (
                    <div className="mt-3 rounded-lg border bg-info-soft px-3 py-2 text-xs text-info"
                      style={{ borderColor: "color-mix(in oklch, var(--info) 15%, transparent)" }}
                    >
                      <Gauge className="mr-1.5 inline size-3.5" />
                      Sized for {c.position_size.max_contracts} contracts at $
                      {c.position_size.cost_per_contract.toFixed(0)}/contract — total risk $
                      {c.position_size.total_cost.toFixed(0)} ({formatPct0(c.position_size.risk_pct)} of portfolio)
                    </div>
                  )}
                </div>
              </>
            )}

            {/* ── Raw evidence ─────────────────────────────────── */}
            {c.evidence && (
              <>
                <Separator />
                <details className="group">
                  <summary className="cursor-pointer text-sm font-semibold text-muted-foreground select-none">
                    Raw evidence shown to both models
                  </summary>
                  <div className="mt-3 grid gap-3 sm:grid-cols-2">
                    {Object.entries(c.evidence).map(([key, val]) =>
                      val ? (
                        <div key={key} className="rounded-lg border border-border bg-black/20 p-3">
                          <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                            {key}
                          </div>
                          <pre className="max-h-40 overflow-auto whitespace-pre-wrap font-mono text-[11px] text-foreground/70">
                            {JSON.stringify(val, null, 2)}
                          </pre>
                        </div>
                      ) : null
                    )}
                  </div>
                </details>
              </>
            )}
          </div>
        </ScrollArea>
      </DialogContent>
    </Dialog>
  );
}