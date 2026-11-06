# 51 Trading Strategies — separate OpenAlgo study

## Intent and authorization

Continue the user's previously requested 51-strategy extension now that Book visual acceptance is complete. Latest instruction: “Setup in our OpenAlgo with all 51 strategies.” Prior accepted choices remain: one plan with strategy-specific trend/confirmation, a thin guide, latest-ten confirmed candle labels, optional history/pending, dotted links, and preservation of existing indicators. This is implementation authorization for that continuation, not a new request for a design questionnaire. No trading orders, strategy bots, account limits, or TradingView scripts are changed.

## Source and coverage

Use the supplied Aseem Singhal PDF and the complete existing two-part source audit in `workspace/strategies51-2026-11-05/`. Include precisely 51 stable chapter IDs: 1.1–1.7, 2.1–2.7, 3.1–3.7, 4.1–4.4, 5.1–5.6, 6.1–6.13, 7.1–7.7. Every row contains its own entry, stop, target/conditional exit, timeframe, prerequisites, source gaps, and local conventions. No copied book pages or performance claims in the product.

All strategies receive executable evaluators for the evidence they require. A strategy can be waiting, confirmed, wrong timeframe, needs data, or needs supplied context. A missing fundamental event, discretionary Elliott/Gann anchor, option identity, historical OI selection, multi-leg state, or undefined source rule must never turn into an OHLC-invented signal. Context supplied by a person is labelled as such and scoped to symbol/interval. Source-explicit no-stop strategies must not acquire a fabricated source stop. Option-premium prices remain separate from underlying prices.

## Approach

1. Extend the existing Book engine: rejected because the user explicitly preserves it and its settings.
2. Separate chart study with shared read-only rendering/risk utilities: selected. It fits the existing chart and keeps old engines unchanged.
3. Independent strategy execution service: outside chart-guidance scope and unnecessary for displaying evidence.

Use a new `strategy51-guide` component directory, a typed 51-item source catalog, shared causal indicator series, per-chapter evaluators, a deterministic one-plan lifecycle, an own preference key, and a thin React guide. Reuse the existing Book drawing/risk utility without altering its files. Add a distinct study registration and bounded host hooks only.

## Calculations and causal rules

Canonical local formulas are explicit: SMA/EMA (SMA seed), Wilder RSI/ATR, MACD12/26/9, BB20/2, Williams R14, session HLC3 VWAP and weighted deviation, Traditional prior-session pivots/CPR, Supertrend7/3 or10/3 as relevant, Donchian20, HA and SAR. Missing source parameters use visible local defaults. Never call the title's MACD a condition for1.2 or standard pivots a condition for2.3. Use4L/4R fractals for3.4. Only confirmed swings qualify structure; recognition occurs after right bars close. Cloud comparisons use displaced historical spans, not future spans. No automatic loss-based size escalation for5.6.

The engine receives UTC OHLCV with real completion times and validated history observation metadata. Source identity, interval, replay and history correction are part of reconciliation. Forming candles may update progress but never create confirmed events. Validate finite positive OHLC geometry, timestamps, unique ascending bars, and chart source. Cap completion at min(now, observedAt). Session-last bars use host closeTime. Market-closed history is labelled last-session; stale/missing live history cannot promote an entry. Rebuild deterministically on corrections; no cross-chart plan retention.

Shared history calculations run once per completed dataset; detector scans are bounded. Each strategy keeps its source sequencing. Confirmation above/below a finished signal candle uses a later completed break unless a source specifically enters at the confirming close (labelled close reference). Source exact thresholds are kept, while qualitative structures use disclosed local pivots/tolerances. Unsupported direction mirrors stay disabled.

## Data and eligibility

Use the chart's verified source and existing read-only history API. Read matching completed1h history for Double RSI only while the study is enabled. Where available, read actual option contract/chain metadata and underlying history; never infer a historical highest-OI contract from current OI or a past ATM identity from current spot. Missing option selection evidence blocks that option entry while preserving independently valid chart context. Explicit external/manual prerequisites remain visible in the51-row catalog. Broker/API failures show their reason and retain no misleading current plan. Do not add account credentials, order requests, or broker side effects.

## Plan and risk

Select one currently eligible strategy automatically, or let the user focus any of51. A selected focus cannot inherit another strategy's plan. Keep the chosen plan frozen through subsequent candles until stop/target reference touch, source conditional exit, explicit source time exit, or local expiry. Simultaneous SL/target touches become ambiguous. No same-candle historical fill inference. A new setup does not overwrite an active plan; show alternatives in Details. Strategies without source numerical targets may use an independently switchable, clearly labelled local3R planning target. Preserve source targets1R/2R/3R/4R and partial-exit rules rather than replacing them globally.

Monetary sizing uses fixed user risk, explicit equity/costs and validated exact-instrument units. Default equity unset/risk0.25%; no account balance inferred. No quantity while units/equity unavailable. Keep source stop/target versus local reference distinctions visible. For multi-leg strategies show actual leg prerequisites and source management without suggesting a fictitious single underlying SL.

## Display

Study name: `51 strategies · live guide`; own selector ID `strategies-51-guide`. Compact summary: name/state, expected direction/next condition, Entry/SL/Target or conditional exit. Details: searchable/filterable51-row catalog, source page references, waiting reasons, numerical local conventions, display settings and risk. All51 remain discoverable; a strategy is never silently omitted for absent data. Latest-ten confirmed annotations default; pending/history off. Dotted leaders terminate on actual source candle coordinates. Bounded complete formations and two confirmed context trend lines; do not create a full-screen table over candles. Own storage key and no migration of old preferences. Enable the new study through normal chart UI after deployment.

## Acceptance

Tests prove51 unique source IDs, causal indicator values and time alignment, each evaluator's positive/negative evidence, wrong timeframe/data gates, option/underlying separation, no manufactured fundamental or discretionary triggers, no martingale escalation, prefix invariance, replay/corrections, frozen-plan ordering and ambiguous touches, safe preferences, compact UI and full catalog access, drawing source coordinates, and host activation/removal. Run targeted tests and production type/build to isolated output; disclose known unrelated baseline failures. Verify preserved old source hashes. Deploy verified hashed assets with index last and retain old chunks; no backend restart. Native OpenAlgo check: enable new study, inspect compact guide/catalog/dotted annotation/settings persistence and candle refresh; keep TradingView open.
