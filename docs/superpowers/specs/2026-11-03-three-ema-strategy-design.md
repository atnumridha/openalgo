# Additional EMA 9/15/21 strategy

Status: approved adaptation implemented and deployed on 3 November 2026. Live backend version3 confirmed with existing Auto On settings; no new trade fill has been observed.

Source: user's timestamped transcript of Facebook.mp4. Visual extraction failed in the installed macOS decoder; the exact crossover pictured and chart timeframe have not been verified. Claimed 5.5R/9.8R examples are not test evidence.

## Intent and approach

Add a separate strategy to the existing Delta crypto ensemble. Preserve the existing EMA9/15 pullback module. Replacing it or adding EMA21 as a mandatory gate to every strategy would conflict with the user's request to add this strategy additionally. This is the recommended approach; all eligible strategies still share one account exposure gate and one proposed order.

## Source rules

- Long: after a crossover, EMA9 > EMA15 > EMA21, all rising, with visible separation, and a candle closes above all three.
- Short: mirrored ordering and slopes, candle closes below all three.
- No entry while averages are flat/tangled or price repeatedly cuts them.
- Initial protective SL references EMA21 or the signal-candle extreme.
- Hold until a new opposite crossover, subject to protective SL/trailing.

## Proposed precise adaptation

- Evaluate completed 1-minute candles with the existing 5-minute direction filter, independently of chart view. This timeframe is inherited from the user's approved scalping setup, not specified in the transcript.
- One fresh setup on the first qualifying fully ordered alignment following a transition. Do not re-enter the same alignment after an exit or restart. No pullback is mandatory for this additional module.
- Each adjacent EMA gap must be at least 0.1 ATR14; all three slopes over three completed bars must agree. These are proposed numerical definitions of the source's visual gap/slope conditions, not claims made by the video.
- Initial SL beyond the farther of EMA21 and the signal candle's invalidation wick, buffered by 0.25 ATR, with the existing minimum noise distance and outward tick rounding. Never tighten SL merely to afford more lots.
- Use a completed opposite EMA9/15 crossover to exit this strategy. This is a proposed precise interpretation of the video's ambiguous 'next crossover'; do not wait for all three to finish reversing. Existing exchange SL remains active independently.
- Existing fee-aware structural trailing remains active: USD0.15 net peak makes fee-covered profit trailing eligible when structure allows; no guarantee of a positive realized exit. Stops never widen. No fixed 2R cap.
- Keep maker-only entries, reduce-only market exits, fresh quotes, verified account reconciliation, one exposure at a time, durable setup claims, and INR20 fee-inclusive planned-loss cap.
- Automatic size is capped by both balance affordability and structural risk. User permits up to 100% balance sizing below INR2,000; no policy above that threshold is invented here. Live fixed-lot configuration remains subject to user handoff.
- Display EMA21 and distinguish this strategy's signals from existing EMA9/15 crosses. Keep candles and optional pattern labels.

## Validation and activation

Test mirrored entry/exit rules, flat/tangled cases, forming-candle exclusion, fee/tick sizing, stale evidence, setup reuse, and restart reconciliation. Replay historical BTC candles without future bars, then inspect live read-only diagnostics. Do not present synthetic/replay results as realized profits. Publish only after checks and review. Final UI action arming live Auto requires the user.

Approval requested: this additional module and the precise adaptation above. No trading configuration or strategy code has been changed by this document.
