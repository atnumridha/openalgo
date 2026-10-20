# Reviewed Stock Learners chart methods implementation plan

> For agentic workers: use superpowers:executing-plans for inline implementation. Steps are tracked below.

**Goal:** Extend the existing chart-only assistant with the methods established by the reviewed transcripts and selected local-video frames.

**Architecture:** Keep the existing single-file custom chart descriptor and deterministic evaluator, shared by live chart calculation and replay. Reuse coverage validation, known reference events, frozen risk plans and conservative OHLC ambiguity handling. Orders and broker protection remain separate.

**Tech stack:** JavaScript, openalgo-charts, Node test runner, existing indicator validator.

**Spec:** User's request to implement the strategy following the three transcript and local-video reviews. Source audit: docs/research/htf-liquidity-indicator.md, supplemented by temporary timestamped audits. User has authorized implementation; execute inline without another approval round.

## Global constraints

- Preserve unrelated dirty work and save a backup.
- Install only through the chart-indicator validator, never edit the installed file directly.
- No order submission, trade adoption or broker changes from chart signals.
- Keep one liquidity reference per enabled timeframe in focused view.
- No icons or emojis in code/docs. Prices remain native quote currency.
- Source discretion must remain explicit app settings; no verified win-rate claim.

## Decisions

- Default `verified`: strict liquidity sweep, first completed directional response, then a completed opposing candle whose body/range is at least 0.5 and whose close defeats the initial response's body. Freeze that opposing candle's high/low as renewed-break entry. SL beyond sweep-to-opposition extreme. Final break is intrabar; no reclaim of the original HTF level is required. The body threshold and precise body-failure definition are app choices.
- Keep `reversal` as Basic sweep for old saved settings. Keep `continuation` as Masterclass pullback sweep with untouched target.
- Add `protected`: same causally confirmed first pullback, but a breach of its reference before entry invalidates it. Entry is the high/low of a subsequent meaningful completed directional candle. Keep its preserved opposing extreme as target.
- Add `rally`: established directional displacement/travel at least 0.55 over configurable lookback; a completed directional candle with range at most 0.75 of prior mean ranges forms an entry. SL beyond that candle, target known opposing liquidity. After triggering, tighten from completed directional candles only; a subsequent opposing candle's high/low break exits. Never loosen the trail. These numerical tests are app approximations.
- Default additional SL buffer to zero; allow configurable ticks. Default fixed expiry to zero (none); optional bar expiry remains available. Newer same-frame reference cancels an untriggered verified plan.
- Targets come from known structure; missing target remains explicit. Preserve initial risk separately from trailing SL. Flag 1R as a partial-management milestone, not an executed exit.
- Intrabar trial sizing and the presenter's discretionary additions remain manual: chart OHLC cannot recover tick sequencing or infer quantity. Do not silently treat a forming-candle trial as the verified mode.

## Review focus

- Opposing candle may only become usable after completion, never trigger from its own earlier wick.
- Target taken before entry, same-bar ambiguity, dojis, equal prices and unknown references must not become valid wins.
- A protected reference must not be treated as a required sweep.
- Trailing uses only information known before the tested bar and never widens risk.
- Historical gaps, reload, replay prefix and forming last candles cannot create hindsight signals.

## Tasks

- [ ] Add failing behavioral tests for verified long/short stages, opponent quality, frozen trigger, missing target and causality.
- [ ] Extend evaluator and rerun source-guided and legacy suites.
- [ ] Add protected-reference and rally/trailing tests, implement and verify both directions and data-gap behavior.
- [ ] Expose modes and numerical app settings; display setup progress, initial risk, current trail and 1R milestone; retain Entry/SL/Target guides.
- [ ] Update canonical research notes and changelog with source evidence and app assumptions.
- [ ] Obtain focused independent review, resolve important findings, run final suites and validator.
- [ ] Install through gate, reload current chart, select verified mode and verify labels/settings without financial actions; save screenshot proof.

No commit or push is requested for this change.
