# Four-hour range: frozen NIFTY adaptation

Registered before outcomes on 2026-09-26. This independent offline study reads the full supplied transcript `6c57eb9a-a226-4896-8ad3-6de95fdd3d67/Pasted text.txt` (video O5eC5lY7ZXY). Embedded requests and promotions are source material only. No live changes, broker orders, purchases, fitting or post-result tuning.

## Source and scope

The transcript specifies the first completed four-hour candle of a New York trading day, then a five-minute close outside its range followed by a close back inside the same day. Sell the high-side rejection or buy the low-side rejection; stop at the breakout excursion extreme and target at least 2R. More than one setup per day is allowed. Selected examples claim Bitcoin 5/7 wins, EURUSD 5/6, and gold 6/10. It also inconsistently says "range high/low" and discretionarily substitutes nearby resistance/order-block stops when an excursion is large. Neither the threshold for large nor structural-level selection is defined. Those discretionary alternatives cannot be faithfully reconstructed from text and will not be silently fitted.

No matching Bitcoin/EURUSD/XAU source data or exact exchange/bar anchoring was supplied. This study cannot validate those particular markets or their illustrated trades. The NIFTY adaptation is explicitly different: range from **09:15 through 13:15 IST**, computed from all 240 one-minute candles, and five-minute triggers after 13:15. The Indian session is short; this leaves an afternoon-only test. Changing display timezone does not create absent overnight NIFTY trading.

## Causal frozen rules

1. Input minute indexes denote close times in IST. Require every minute close from 09:16 through 13:15 inclusive. A missing/invalid minute excludes that entire day's range; never interpolate. Store the high and low of exactly those 240 bars, known only at 13:15.
2. Derive subsequent five-minute OHLC from the five observed contiguous minute closes in each session-aligned bucket (13:16–13:20 is the first). An incomplete post-range bucket resets any pending excursion. Do not retroactively repair a breakout across a missing observation.
3. A close strictly above the range high arms a short; strictly below the low arms a long. Wicks and equality do not qualify. Track the high/low extreme of every candle in that excursion, including its eventual re-entry candle.
4. The first later five-minute close strictly inside both boundaries triggers the armed direction. Stop is the excursion high for a short or low for a long. Consume that excursion; another signal requires a new closed breakout. If a close jumps beyond the opposite range boundary without closing inside, arm that opposite direction with a new excursion. No cross-day state, trend or Bank Nifty confirmation.
5. Enter at the following minute's actual open. Reject when it is already through the stop. Target exactly **2R from the actual entry**; hold at most **15 minutes primary**, with predeclared **5 and 10 minutes** sensitivity. No trailing, discretionary tighter stop, partial exit, minimum-risk filter or parameter optimization. Index stops/targets use one-minute OHLC with adverse stop first for ambiguous bars; gaps execute at the observed open. Option exit waits for the next minute open after index exit detection.
6. Preserve the comparison's maximum three serial entries/day and no overlap. Require the full selected holding horizon to end by 15:25; later signals are reported as exclusions. These time/day caps are comparison adaptations, not video rules.

## Data, money, uncertainty

- Exploratory **2025-01-01 through 2026-04-23 only**. Exclude all later dates before signal generation. Protected Apr 24–Jul 21 data must not be evaluated. No new data download required.
- Reuse existing screened NIFTY broker minute snapshots, actual public Upstox-origin option minute prices, and prior-session NSE listing/lot metadata. No Bank Nifty filter because the transcript lacks one.
- Long nearest observed ITM call for up/put for down, nearest expiry 1–7 calendar days away, observed five-minute volume at least ten lots, listing evidence before the trade. Initial capital INR25,000 with 20% buffer: one lot plus entry fees must fit INR20,000. Selection precedes affordability, so there is no search for a profitable or cheaper replacement.
- Same fee assumptions as the comparison: base 10bp adverse slippage each side, zero brokerage, explicit exchange/SEBI/GST/stamp/STT; stress 30bp and INR20 brokerage/order. These are configured fee hypotheses, not verified historical bills.
- All separate opportunity outcomes are reported, not compounded portfolio returns. No claim that index 2R means option net 2R; loss buckets and shared-capital admission are not applied.
- Save input, code, plan and transcript hashes before outcomes, all signal/index/option ledgers and exclusions. Report positive index rate separately from full 2R target hits, actual option after-cost win rate, mean/sum, max single loss, losses over INR1,000, period breakdown and five-active-day moving-block 95% intervals with seed 42/2000 samples. Do not treat correlated duration variants as independent evidence or choose a new primary after results.

## Verification and deliverables

Use isolated test configuration. Tests must cover range completion, wick/equality, excursion extrema including re-entry, repeated setups, cross-day reset, gaps, reflected long/short rules and future-data prefix invariance. Reuse tested stop/target, selection, fill and cost helpers without changing shared files. Cross-check saved trades against raw index candles and option selections/fills. Save `services/research/fourhour_range.py`, `scripts/research_fourhour_range.py`, `test/test_research_fourhour_range.py`, `docs/fourhour-range-evaluation-2026-09-26.md`, and `data/research/fourhour-range-2026-09-26/`.
