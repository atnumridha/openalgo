# PK rejection correction

**Goal:** Correct the disclosed rejection/PK execution rules without replacing unknown indicator formulas with invented ones.

**Evidence:** User-provided Marathi transcript (7 September 2026 example) and the reviewed rejection diagrams. The seven-candle pattern in Sofien Kaabar's article is a different pattern and is excluded.

**Implementation decisions:** Replace the current approximation in place, preserving its source with the historical validation record. Use explicit manual S/R or selected external original S/R plots; default zero levels produce WAIT. Sweep candle color does not matter. The immediately following direction-colored candle confirms; its high/low arms a stop entry for the following three candles. Rejection stop modes are frozen S/R close invalidation or sweep-extreme price stop. PK entries require an explicitly supplied PK marker/time and use that PK candle's own extreme. No invented PK/R1/R2 generation or continuation labels. Optional R target is disabled by default because the transcript does not specify its formula.

**Scope of replay:** Apply to the underlying standard 5-minute index chart. Bull/BUY CALL and Bear/BUY PUT are direction labels; simulated positions are index units, not actual option premiums. Remove option-premium ATR stops and any implication of corrected option P&L. Actual cross-instrument option fills cannot be reconstructed by copying index levels into premium prices.

**Files:** `scripts/tradingview/video_master_candle_strategy.pine`, its README and behavioral tests; historical source in `docs/validation/video-master-candle/2026-10-27-approximation.pine`.

- [x] Write and observe failing actual-Pine tests for supplied rejection stops, color independence, strict next-candle confirmation, wick triggers on bars 1–3, expiry on bar 4, PK own-candle stop, source unconfigured WAIT, and frozen risk.
- [x] Implement and pass tests; retain BB/Chikou regression suite. 34/34 pass. Independent review finding on ambiguous native fills reproduced, guarded and verified by regression.
- [x] Compile/update the new draft in TradingView, preserve saved scripts, leave underlying chart in WAIT rather than supply a guessed S/R level. Successful native compilation/update and NIFTY 5-minute WAIT panel verified by screenshot.
- [x] Document verified corrections and unresolved automatic line/label generation; do not publish replacement option performance.

TradingView UI update completed after the user made Chrome available. The unsafe leave-site action was cancelled; symbol selection and draft replacement were completed inside the existing chart. Basic-plan script persistence remains a separate constraint; source is preserved locally.
