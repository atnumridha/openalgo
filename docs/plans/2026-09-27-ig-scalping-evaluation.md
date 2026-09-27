# IG scalping: frozen historical comparison

Registered before outcomes. This is an offline research extension using the existing comparison harness, not a change to any live strategy. No tuning, orders, activation, credentials or broker calls.

Source: https://www.ig.com/en/trading-strategies/four-simple-scalping-trading-strategies-190131, read 27 September 2026, including the four indicator chart images. These are NIFTY/options adaptations, not replications of the illustrated Brent, EURUSD, DAX and Wall Street trades. Article examples are incomplete specifications; the choices below complete them and are hypotheses, not IG performance claims.

## Frozen rules

All input indexes denote observed minute CLOSE in IST. Build complete session-aligned three- and five-minute candles from every constituent minute; never fill gaps. Indicators use observed completed bars, carrying history overnight. After a gap or session boundary require three consecutive intervals before entries. Missing bars are omitted, not treated as flat. Use simple moving averages (the article does not identify an averaging method).

- Stochastic: chart labels 14,5,3 and MA50/200. Interpret this as raw %K lookback14, five-bar SMA smoothing of K, then three-bar SMA D. A long requires K crossing above D with previous or current K <=20, SMA50>SMA200 and rising SMA200 over three bars. Shorts mirror at >=80 with descending trend. These exact trend/threshold/smoothing interpretations are assumptions. Exit an existing long on K>=80 or a bearish K/D cross, a short on K<=20 or bullish cross.
- MA: SMA5/20 cross up with rising SMA200 over three bars for calls. Puts require close crossing below SMA5, SMA5<SMA20 and falling SMA200, reflecting the different short entry described. No extra price-vs-SMA200 requirement. No indicator exit specified.
- SAR: chart acceleration start0.02, increment0.02, cap0.2. Initialize from first two closes, rising on a tie; initial SAR is their low/high opposite trend. Project from prior SAR/extreme, clamp to prior two lows/highs, reverse on strict penetration, reset acceleration on reversal. A completed-bar change of trend triggers one entry; stop at that bar's SAR; opposite reversal is an indicator exit. Require 20 observed bars before use. Do not enter repeatedly while dots stay on the same side.
- RSI: chart RSI14 and SMA20/50/100. Wilder RSI is seeded with the first 14 price changes (flat=50, gains-only=100, losses-only=0). Calls cross from <=30 to >30 while all three SMAs have positive three-bar change. Puts cross from >=70 to <70 while all three changes are negative. This strict definition of broadly aligned averages is an assumption; retain zero/sparse results rather than weaken it after seeing outcomes.

For stochastic/MA/RSI, use the lowest/highest of the five bars ending with the signal as the index stop (added because no precise stop is supplied). Enter at next observed minute open; reject gaps through the stop. All families have a fixed 2R index target, plus earlier stated indicator exit where applicable, and time cap. Stops/targets precede an indicator exit detected at the same minute close; ambiguous bars count stop first. Existing shared pure risk helpers decide breaches. Option exits use the following minute open after index exit detection. This allows a one-minute execution delay past the signal-based time cap.

Primary: each of the four families on **5-minute bars, 2R, 15-minute cap**. Predeclared 5/10-minute sensitivity for all four; additionally 3-minute source-chart sensitivity for stochastic/MA/RSI at all three holds. Total21 variants, four primary rankings. No selecting a new primary after results; these correlated variants are not independent trials. At most three serial index entries/day, full horizon ending by15:25; conservative index exit-time scheduling follows the existing comparison (it does not model simultaneous option positions or a one-minute option exit delay).

## Data and money

Use saved screened NIFTY minute snapshots, 2025-01-01 through2026-04-23; these are reused exploratory data, not fresh out-of-sample evidence. Protected Apr24–Jul21 outcomes remain unread. No new external prices required. One nearest eligible observed ITM NIFTY option lot, expiry1–7 days, prior-session NSE listing/lot evidence and completed five-minute quote volume>=10 lots. Selection uses only as-of data; on3m triggers its last5m quote may be0–4minutes old. Initial capitalINR25,000,20%buffer; entry premium+fees must fitINR20,000. Do not choose a replacement after affordability rejection.

Use existing base10bp/side,zero brokerage and stress30bp/side,INR20/order, with configured exchange/SEBI/GST/stamp/STT formulas. These are fee hypotheses, not verified bills. Report after-cost option win rate, full2R index target rate, sample/exclusions, mean/sum/worst outcome, losses beyondINR1,000, quarterly breakdown and moving-five-active-day95% intervals (2000 samples,seed42). Sum is independent opportunity outcomes, not a compounded portfolio or an account return. Shared daily loss buckets and operational option-premium stops are not part of this study.

## Implementation and checks

- [ ] Add `services/research/ig_scalping.py` pure aggregation, indicators and signals; tests in `test/test_research_ig_scalping.py`: exact crossing directions, trend refusals, seed/flat behavior, SAR reversal, incomplete candles, gaps and future-data prefix invariance.
- [ ] Add `scripts/research_ig_scalping.py`, recording plan/source/price hashes before outcomes. Reuse option-selection/execution/cost helpers unchanged. Save all21 outcomes/exclusions, not only winners.
- [ ] Independently reconstruct index exits including indicator exits and check raw option fills/fees and source hashes. Validate derived indicator values against separate calculations where practicable.
- [ ] Save `docs/ig-scalping-evaluation-2026-09-27.md`, link in docs index, present four primary results with uncertainty and comparison caveats.

Resource scope: local bounded frames; context-managed files/DuckDB using existing memory limits. No app DB or live runtime imports. Working in the existing research workspace preserves previous experiment artifacts and source hashes. No commit or push is part of this request.
