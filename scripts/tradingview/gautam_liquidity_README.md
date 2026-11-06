# Gautam Jha — source liquidity indicator

Separate Pine v6 indicator: `gautam_liquidity_concepts.pine`. Uses public Gautam Jha / Stock Learners lessons reviewed in the source audit, not a private/proprietary formula. It does not combine the DPA, PK, BB/Chikou, OTE, EMA or ATR strategies.

## Automatic candidates and reviewed signals

Use a **standard 1-minute chart of the underlying** (for example NIFTY, SENSEX, BTC or Gold). The main worked example in the linked lesson is Gold; signals on other instruments are applications of those rules, not independently demonstrated profitable strategies.

1. Mark the **previous completed daily candle's wick high and low**. TradingView's symbol/exchange daily session determines these boundaries.
2. Above that high, wait for the first completed red response candle whose range extends beyond the line. Below the low, mirror with a green candle. No setup in the middle; an exact touch is insufficient.
3. Only the **immediately following candle** can confirm through the response low (Bear) / high (Bull).
4. **Original next-bar break** is now the default following the later “his approaches only” instruction. The selected response must complete first, then its high/low must break on the immediately following candle. The historical recorded entry uses the next tradable tick beyond the response extreme, or the opening price if it gaps through. It records at that candle's close; this is not a late-entry instruction or a tick-level reconstruction. The earlier **Candle close (user variant)** remains separately selectable: the next candle must CLOSE beyond the trigger. That hybrid is not the author's response-candle-close method.
5. The stop is the response candle's own opposite extreme. No ATR, fixed-R filter or invented tick buffer. A subsequent attempt requires a fresh higher external high / lower external low. The source limits **actual attempts to three** and **full losses to two**. Report these manually for the selected session; automatically counting every colour-based candidate as an actual trade would be false.
6. **Review the response body and logical T1 before treating a candidate as an entry.** His [16 September live DQRS explanation, 38:27–39:51](https://www.youtube.com/watch?v=tHnztgJisBA&t=2307s) uses the same previous-day high on Gold, rejects a doji-style initial response, asks for a body candle from fresh liquidity, and cautions against hammers. No universal body ratio is given. The script therefore labels unreviewed events **Bull/Bear candidate** in yellow, keeps overall **WAIT**, and requires the response candle's **OPEN timestamp** plus a premarked valid T1. The response-close candidate notice is available before the next-bar entry window. If the original break occurs before review/order readiness, skip it. Historical approval redraws history and is not evidence of a forward-tested trade.
7. Mark the nearest preceding opposing swing manually for T1. The author gives no universal pivot sensitivity, so no automatic 2/2 pivot rule is substituted. With T1 blank the event remains a candidate, even if body approval is present. A provided target that has already been touched or lies on the wrong side prevents a stale-target entry. Choose the destination using information available before entry; do not extend it later to pursue desired profit.

Source: [beginner setup, daily marking 07:37](https://www.youtube.com/watch?v=wI9b968AvW8&t=457s), [short response/stop/target 09:45–10:32](https://www.youtube.com/watch?v=wI9b968AvW8&t=585s), [long mirror 11:23](https://www.youtube.com/watch?v=wI9b968AvW8&t=683s), [attempts/loss accounting 12:48–14:18](https://www.youtube.com/watch?v=wI9b968AvW8&t=768s), [fresh liquidity 15:55](https://www.youtube.com/watch?v=wI9b968AvW8&t=955s).

The daily manual-context window controls the validity of supplied targets and the **actual attempt and full stop-loss counts** you report. Keep it within your selected session and update the count; at three reported attempts or two full losses, Daily candidates/signals pause for that window. Update these manually; the script cannot enforce a broker/account limit. The script cannot know actual fills, partial profits or breakeven trades. The source's 20% runner is guidance, not an automatic exit: this indicator has no orders, trailing stops or invented partial-profit trigger.

## Discretionary setups stay manual

| Row | What you supply before it can signal | What the script checks |
|---|---|---|
| Daily | Automatic candidate; response-body approval timestamp and valid T1 for a reviewed entry; actual attempt/full-loss counts | Previous completed daily levels, fresh external move, response, next-candle entry, own-candle SL, reported source risk limits |
| Event | Verified completed failure/trap/COC context permitting the selected direct response, direction, level, **source-selected stop**, active-from/until, opposing target and approved response timestamp | Sweep of the marked level, directional response, immediate-next-candle break, supplied SL; only the approved complete plan is a reviewed entry |
| Pullback | Verified strong trend **and first pullback**, direction, pullback liquidity boundary, original untouched destination, active-from and valid-until, and approved response timestamp | Selected sweep/response/next-candle entry variant; destination untouched since activation and still ahead; only the approved response is a reviewed entry |

The manual plan must be marked **when the context is known**, before the response. Retrospectively marking a perfect historical level is not evidence of an executable forward signal. The script cannot verify whether the human-selected level, first pullback or destination is significant. The finite validity window prevents a marked plan from remaining armed forever.

The event and continuation rows select the disclosed sweep/response entry variant; they do not reproduce every discretionary example. The first CHoCH is a warning; the later trap lesson describes failure/retest and renewed CHoCH. Those structural judgments, candle quality, exhaustion and event destinations are **human checks**, not fabricated automatic signals. Direct and COC-style entries are distinct live variants: the current manual row does not automatically detect the first shift, its failure, and renewed shift. Daily open is available as a context line only.

Sources: [HTF reversals versus LTF continuation, Masterclass 1:47:20–1:53:28](https://www.youtube.com/watch?v=pth7Wl4ZyY8&t=6440s), [first CHoCH warning and later confirmation](https://www.youtube.com/watch?v=XHOxOGlaAKw&t=540s), [daily-open level context](https://www.youtube.com/watch?v=2ZhQndoS9kA&t=97s), [untouched liquidity](https://www.youtube.com/watch?v=SRWT_53TbBI&t=71s), [event context](https://www.youtube.com/watch?v=ZuRCCl7i2ZU&t=650s), [candle psychology](https://www.youtube.com/watch?v=oaCeTzsT_SY&t=367s), [large-context reversal](https://www.youtube.com/watch?v=b6u590ohHfo&t=415s).

## Reading the chart

- Reviewed **Bull** is green, reviewed **Bear** red, **WAIT** and unreviewed candidates yellow. Each row works independently. Overall shows a new entry only on its confirmation bar. Opposite simultaneous entries produce **WAIT · CONFLICT**; WAIT rows do not outvote a valid signal.
- `Now` is current setup status. `Latest · IST` is historical: **?** marks an unreviewed candidate and **✓** a response whose timestamp was approved. Values show the pending trigger/SL/T1 while pending; otherwise LAST candidate/entry/SL/T1. These are guides, not active orders or inferred trade outcomes.
- A 1m interval and standard underlying candles are required for entries. Larger intervals display the daily levels and the instruction to switch to 1m. Option premium, Heikin Ashi and other transformed bars are excluded.
- A missing chart interval cancels pending records. Original-break bars crossing trigger and stop/target show AMBIGUOUS rather than a clean historical signal. This is uncertainty about price ordering, not proof that a preplaced order was unfilled. The companion backtest retains such prospective orders and tests explicit OHLC paths; it does not delete their possible losses. These are recording/model boundaries, not additional author filters.
- Manual Event/Pullback rows default off. Set their inputs when you have identified the context; they show WAIT until then. Font size is selectable.

## TradingView

Paste the complete `.pine` file into Pine Editor and compile/update on chart. If account limits prevent adding another indicator, use an existing editable Pine slot; other strategy source files remain separate locally. This indicator is not a native Strategy Tester strategy. The separate `gautam_reviewed_strategy.pine` replays the sealed, retrospectively reviewed Daily ledger. Account alerts are not created automatically; the indicator provides **candidate review notices only** at response close and retrospective break-record notices. Reviewed Bull/Bear outputs are chart-only because approval inputs change per response. TradingView alerts store the original script/input snapshot: recreate a candidate alert after changing relevant inputs. See [TradingView’s alert FAQ](https://www.tradingview.com/pine-script-docs/faq/alerts/#if-i-change-my-script-does-my-alert-change). Pine strategies cannot place orders in the built-in Paper Trading account; the native emulator and Paper account are separate ([official FAQ](https://www.tradingview.com/pine-script-docs/faq/strategies/#can-i-connect-my-strategies-to-my-paper-trading-account)).

## Verification

Behavior tests extract and execute the actual production Pine engine using the existing PineTS runtime. They test sequence, mirrored directions, fresh attempts, expiry, gaps, target chronology, ambiguity, frozen guides and independent instances. TradingView's own compiler and chart display must also be checked; PineTS alone is not equivalent to TradingView.

Full research coverage: `docs/research/gautam-jha-concepts-2026-10-28.md`. The older channel inventory is discovery only. No claim of having watched all channel uploads or having mastered the author's discretionary judgment.

## Additional popular/live review

The initial selected review has expanded to full available-caption reading of all **23 completed official Live replays in the current snapshot**. The consolidated [demo index](../../docs/research/gautam-live-demo-index-2026-10-28.md) preserves **202 example/context records**, **72 mistake/failure/process entries**, and **18 selected visual checks across six sessions**. This is not continuous visual review of all videos or all channel uploads. Non-live foundations and popular lessons remain covered at the explicitly recorded depths in the earlier reports.

The [entry/exit lesson 11:24–14:19](https://www.youtube.com/watch?v=jqCY5RLWdNE&t=684s) also teaches **response-candle close** where the chosen setup permits, **next-candle high cross**, and expert running-candle entry. Its response-close example is a discretionary PPT option-premium setup. That differs from the retained optional **next candle closes beyond the response extreme** user variant. The indicator does not reconstruct PPT or running-candle entries, option-premium examples, automatic COC, or discretionary live partials.

Further event lessons make the boundary explicit: a level and body colour alone are insufficient. The Event row requires your completed trap/failure/COC assessment for the selected direct-response variant and a manually chosen source stop. It does not copy the daily stop into every event example. Different event variants and cross-market confirmations in the examples remain manual and are not universally required.

## Reviewed one-month BTC test

The [test report](../../docs/validation/gautam-reviewed-month-2026-10-28.md) covers 43,200 actual 1m bars, 28 September–28 October 2026, using the selected 1 BTC / 0.8 T1 / 0.2 T2 / original-SL variant. All 216 prospective discovery charts ended at response close; 126 approvals and 90 rejections were sealed before outcomes. Discovery is a **conservative subset**: raw colour-response freshness can omit later discretionary bodies. It is not an exhaustive count of the author's trades. Approvals are subjective retrospective Codex applications, not Gautam's actual signals.

The full-month local model lost **$5,357.53 before funding** after assumed fees, with 47 entries. TradingView natively compiled both files and matched the local **$2,290.92 loss** for its loaded 19–28 October overlap (14 entries, 28 exit legs). Basic-plan Deep Backtesting blocked the full native month. The final chart runs the live indicator, with the Paper account connected and flat; no Paper orders were submitted. Do not treat research coverage, unit tests or a native compile as proof of profitability.
