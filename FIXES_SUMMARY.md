# Fix Summary — Options Engine, Order Management, Tracking, UI

Run the tests yourself:  `pip install pytest --break-system-packages && pytest tests/ -v`
(9/9 passing — covers every item in the original "Verification & Testing Plan".)

## 1. Options selection algorithm

**Root cause, not just symptom:** two compounding bugs.

- `options/selector.py` only hard-rejected on delta when Alpaca's API returned *real*
  greeks. In paper trading that's usually absent, so it silently fell back to using an
  approximated delta for *scoring only* — meaning delta was effectively never enforced.
- The approximation itself (in the old `greeks.py`/`selector.py`) was a linear formula
  that isn't bounded correctly: for a deep OTM put it computed **delta = +1.0** (should
  be ~0), and the equivalent call-side formula did the same in reverse. Combined with a
  spread check that silently assumed a fake 5% spread whenever bid was $0 (instead of
  rejecting), garbage contracts like your $40-strike/$0.03-ask example sailed through
  every filter.

**Fix:**
- `options/greeks.py` — replaced with a proper Black-Scholes (normal-CDF) delta,
  correctly bounded and signed for all moneyness.
- `options/selector.py` — delta is now a **hard reject** using the best available
  delta (real or approximated), plus new strike-proximity (±10%), min-bid ($0.15),
  and min-open-interest (100) guards.
- `options/chain.py` — `spread_pct` no longer fabricates a 5% spread on a zero bid
  (returns `None`, which the selector treats as reject); `open_interest` is now
  actually populated (it comes from the *trading* API's `OptionContract.open_interest`
  field, not the snapshot — that's why it was always 0 before).
- `config/config.yaml` — added `strike_proximity_max_pct`, `min_bid_price`,
  `min_open_interest`; widened `target_delta_min` to 0.40 per spec.

I found the exact real-world instance of this bug sitting in your own
`trade_journal.json`: `MRNA260911P00040000`, entry price $0.03, 315 contracts,
against MRNA trading near $193.

## 2. Order sizing, execution & exit logic

- **Chunking** (`trading/execution.py`, `trading/positions.py`): any order over
  `execution.max_order_chunk_size` (500, configurable) is now split into sub-orders
  (1200 → 500+500+200) submitted sequentially. Verified against your exact MRNA
  scenario in `tests/test_bug_fixes.py`.
- **Unjournaled positions**: both chunked functions accept an `on_fill` callback,
  invoked immediately after each chunk fills — *before* the next chunk is submitted.
  `main.py` and `dashboard/app.py` wire this to a new `record_order_fill()` in
  `database/repository.py`, so a crash mid-multi-chunk-order can never leave more than
  one chunk unrecorded.
- **The actual "inverted PUT exit" bug**: it wasn't the EMA20 logic (I checked — that
  was already correct: PUT invalidated when `close > EMA20` is the right rule for a
  bearish thesis, so I left it alone). The real bug was in the **P&L calculation** in
  `agents/monitor.py` and `database/repository.py`: `entry_price`/`current_price` are
  the *option premium*, not the underlying's price, but the PUT branch flipped the sign
  as if you were short the underlying. Since this system only ever holds *long* options
  (long calls or long puts), P&L is always `(current − entry) / entry` regardless of
  call/put — a long put's premium rises as the underlying falls, so no sign flip is
  needed. The old code had it backwards, which would trigger stop-losses/profit-takes
  at exactly the wrong times. Verified: a put that gained $4.75→$6.50 now shows
  **+$1,750** instead of the old **−$1,750**.

## 3. Tracking (Orders / OpenPositions / ClosedPositions)

New `database/state_manager.py`: thread-safe SQLite store (WAL mode + a write lock)
implementing exactly the three models from the spec. The existing JSON journal
(`trade_journal.json`) stays as-is for the AI candidate/report audit trail the
dashboard already reads — `record_entry`/`record_exit`/`record_order_fill` now
write through to both, so SQLite becomes the authoritative, race-free ledger for
what's actually open/closed/in-flight, with zero breaking changes to existing call
sites in `main.py`.

## 4. Dashboard

Your existing Next.js dashboard (`web/`) was already solid, so I extended it rather
than rebuilding:
- Restructured tabs to match spec exactly: **Dashboard / Active Signals / Open
  Positions / Closed History / System Logs** (folded the overview cards + cycle
  report into an explicit "Dashboard" tab).
- `stats-grid.tsx`: added **Unrealized P&L** and **Open Exposure** cards.
- `open-positions.tsx`: added **Current Price**, **Delta**, and color-coded
  **Unrealized P&L** columns; a mobile stacked-card layout under 768px; and a
  **Close Position** button with a confirmation dialog.
- `dashboard/app.py` (Flask backend): added CORS, `GET /api/positions/live` (live
  mark/delta/P&L per position — uses Alpaca's own P&L math, so it's immune to the
  sign bug above by construction), and `POST /api/positions/<symbol>/close` wired to
  the chunked, journaled close path.
- New `web/src/lib/live-positions.ts` — polling hook + manual-close helper, pointed
  at the Flask backend via `NEXT_PUBLIC_API_BASE` (defaults to `localhost:8080`).

Full `npm run build` passes (0 TypeScript errors introduced; the only build failure
in this sandbox was Google Fonts being network-blocked here, not a code issue —
confirmed via a clean `tsc --noEmit` pass). Two pre-existing lint warnings
(`Date.now()` purity, in code I didn't touch) were already there before my changes.

## Running it

```bash
pip install -r requirements.txt
cd web && npm install && npm run build   # or npm run dev
```

Both dashboards (Flask on :8080, Next.js on :3000) read the same `trade_journal.json`
and now also the same `state.db`.

## 5. "Running main.py doesn't reflect on the frontend"

Root cause: `web/src/app/page.tsx` reads `trade_journal.json` via plain `fs.readFileSync`
inside a Server Component with no dynamic API usage (no `cookies()`/`headers()`/
`searchParams`). That's not a signal the Next.js App Router recognizes as "this page
needs fresh data on every request" — so it statically pre-renders the route once and
keeps serving that same cached HTML/RSC payload. `main.py` updates the file on disk
just fine; the already-built page just never re-reads it.

Fix:
- `web/src/app/page.tsx` — added `export const dynamic = "force-dynamic"` so the page
  (and its `getDashboardData()` call) actually re-runs on every request.
- `web/src/app/dashboard-client.tsx` — added a `router.refresh()` poll every 8s, so the
  dashboard updates *live* while a cycle is running instead of only on manual reload.

Verified: `npm run build`/`tsc --noEmit` clean (0 errors introduced; the only pre-existing
lint hit, `Date.now()` purity in `SchedulerBar`, was already there before any of these
changes).

If you're running `next start` (production) rather than `next dev`, you'll also need to
re-run `npm run build` after pulling these changes for the fix to take effect — dynamic
rendering is a build-time route classification.
