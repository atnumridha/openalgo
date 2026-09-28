# Rising profit stops — 28 September 2026

New managed scalping entries and newly queued research use `one-lot-cash300-profit-trail-v2`. Initial technical stops remain capped at ₹300 gross per whole lot, rounded toward entry. Actual fills, gaps, slippage and charges can exceed that planned amount.

| Best gross profit observed | Application stop |
| --- | --- |
| Below ₹300 | Initial technical stop, at most ₹300 planned gross loss |
| ₹300 | Estimated break-even after modeled entry/exit fees and sell slippage, if attainable |
| ₹600 | At least ₹300 gross profit, or the higher fee-aware break-even level |
| ₹900 | At least ₹600 gross profit |
| ₹1,500 (5× ₹300) | At least ₹1,200 gross profit |
| Higher | Continues ₹300 behind the peak, rounded to the contract tick |

The application stop only tightens. ₹900 and ₹1,500 are objectives, not promises or hard take-profit caps. The existing holding deadline still exits a trade, including losing trades. Partial profits are not assumed before fills. Initial stop risk can be less than ₹300 when the technical distance or tick geometry requires it; ₹1,500 is 5× the maximum risk, not necessarily 5× each trade's exact initial risk.

Kotak's broker-held fallback remains a fixed stop. **Rising profit protection is managed by OpenAlgo and needs the application, broker connection and price feed running.** On restart, the exact durable broker trigger is verified separately, must cover at least the original stop, and does not overwrite the higher application stop. Broker stop-limit fills are not guaranteed. Peak/stop recovery has the existing checkpoint durability interval; ticks since the latest checkpoint may be lost.

The ₹2,000 shared daily net-loss allowance, three consecutive net losses stopping entries for the rest of the session, drawdown pause, cash buffer, whole-lot sizing, and qualification/live-authorization gates remain. A later win does not refill a loss allowance. Existing frozen fixed-exit runs retain their recorded behavior. Old models cannot claim qualification for the new recipe; new research labels include the new exits. Saved strategies, Flow activation, account allocations and fee settings are not changed by this release.

## Fixed-signal historical comparison

Twenty replays compare old fixed exits and new profit trailing on the same five frozen ML development signal schedules, under base and stressed costs. Each window starts with an independent ₹25,000 account. Holding time is 15 minutes and cooldown is 5 minutes. No models were refitted or thresholds selected for this comparison. All protected final dates were excluded, and the old-exit replays reproduced prior saved trade exit times and net P&Ls exactly.

| Exit rule / costs | Trades | Net winners | Net win rate | Combined net P&L |
| --- | ---: | ---: | ---: | ---: |
| Fixed 3R / base | 344 | 124 | 36.05% | −₹18,592.16 |
| Rising stop / base | 380 | 157 | 41.32% | −₹16,955.74 |
| Fixed 3R / stress | 295 | 96 | 32.54% | −₹21,928.70 |
| Rising stop / stress | 287 | 111 | 38.68% | −₹21,670.78 |

Base-cost losses improved by ₹1,636.42 across five independent windows. All five new base-cost windows still lost money: dataset 3 −₹1,355.86; 4 −₹3,303.77; 5 −₹4,147.69; 6 −₹4,463.81; 7 −₹3,684.61. The largest base-cost gross winner was ₹2,388.75; one trade exceeded ₹1,500. Under stress, none reached ₹1,500 and the largest gross winner was ₹1,376.25.

This is exploratory reused-development evidence, not proof of profitability or live prediction accuracy. One-minute option candles cannot reveal their high/low ordering: the trailing simulation raises stops only at observed opens and closes, checking the existing/open-earned stop against the low before the closing update. Real tick monitoring can exit differently. Current Kotak costs were used retrospectively as the previously authorized research assumption. Aggregate totals are not returns from one continuous ₹25,000 portfolio.

Local evidence: `data/research/profit-trail-comparison-2026-09-28/manifest.json`, with 20 result files, hashes and selected sessions. Research source is bound in the manifest. Reproduction helper and verification receipts are in `data/research/profit-trail-verification-2026-09-28/`.

## Verification and review

Pure and integration tests exercise rising stops, a gross exit beyond ₹1,500, fee-aware break-even, sell slippage, price gaps, fee changes after admission, invalid tick refusal, checkpoint restoration, original planned-risk reporting, old-exit replay compatibility and ML/replay agreement. Independent review found one important issue: recovery confused the app ratchet with the fixed broker stop. A failing reproduction was added and fixed; broker evidence mismatch and weakened fallback protection are still rejected.

Review scope decisions: historical ticks and future profitability cannot be established with this candle dataset; old-model promotion remains blocked by source/version qualification; checkpoint frequency remains unchanged. Build, browser and final regression verification are recorded with this release's receipts.

Final verification: **4,151 backend tests passed**, 16 skipped, one expected failure; **53 affected frontend tests passed**. TypeScript/Vite production build and Python Ruff checks passed. There are existing Vite chunk-size and backend warning messages. A broad Biome check reports pre-existing formatting/import-order and one semantic-element diagnostic in the large strategy pages; these unrelated lines were left unchanged. Browser verification on an isolated host confirmed the objective, shared limits, trailing dependency disclosure and historical-test explanation. No order routes exist on that QA host.

Published as `4ee04806d` on `main`; the local app and research worker restarted ready. All 494 asset files present in the local served asset directory matched their on-disk hashes. The comparison's research-source hash matched the published source. Before/after snapshots confirmed unchanged saved strategies, Flow activation, capital, fee hashes, zero managed orders, zero risk trades and 60 previously consumed final sessions. There were no open managed runs before restart. The actual browser now requires login; authenticated UI checks were performed on the isolated host using the same production build, not represented as an authenticated live-broker test.
