import { getDashboardData } from "@/lib/data";
import { DashboardClient } from "./dashboard-client";

// BUG FIX: this page reads trade_journal.json straight off disk via
// fs.readFileSync in getDashboardData() — that's not a signal Next.js's
// App Router recognizes as "dynamic" (only fetch()/cookies()/headers()/
// searchParams are), so with no dynamic dependency detected, Next
// statically pre-renders this route ONCE and serves that same cached
// HTML/RSC payload on every request from then on. Running main.py
// updates the file on disk, but the already-built page never re-reads
// it — nothing you do server-side shows up until a full `next build`.
// Forcing dynamic rendering makes Next re-run this Server Component
// (and re-read the journal) on every request/navigation.
export const dynamic = "force-dynamic";

export default function Home() {
  const data = getDashboardData();
  return <DashboardClient data={data} />;
}