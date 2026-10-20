# Liquidity extra confirmation · BTCUSD

The Trading page contains a **Liquidity extra confirmation · BTCUSD** panel below the chart. It runs through the existing Python strategy host. Browser closure does not stop an already running server process.

## Starting and controlling it

1. Open **Settings**, review the limits and **Save settings**. Initial settings are Paper, Review each entry, 5× leverage and at most one contract.
2. The global OpenAlgo mode must match: Analyze for Paper, Live for Live Delta. Select **Start PAPER** or **Start LIVE** explicitly.
3. The panel explains the current stage and, when eligible, the proposed entry, stop, target, quantity and estimated cash risk/reward. **Enter** approves the displayed revision only; a changed price or quantity requires a fresh approval. Automatic entries are a separate saved setting.
4. **Pause entries** keeps an existing trade under management. **Close owned trade** requests a reduce-only close and pauses new entries. **Stop runner & close owned trade** shuts down the process after requesting closure and reconciliation. Broker outages can leave unresolved state; inspect the broker and process log if the panel reports this.

Live start/entry is not performed by deploying this feature. Replay cannot submit entries. Existing positions from another strategy or the broker app are not silently adopted.

## What the transcript supplies

The supplied Hindi transcript describes skipping the first buying attempt, letting the sellers counterattack, and waiting for unexpected renewed buying before entry. It also describes partial booking and protecting the remainder. Its strength judgments and exact liquidity marking are discretionary.

The app makes these choices explicit:

- BTCUSD one-minute completed candles drive the sequence. Native 1H, 4H and daily highs/lows confirmed with strict two-left/two-right pivots supply potential liquidity references. Manual reference and target prices are supported. These references are price structure, not measured resting orders.
- After a low touch, skip the first green candle. Require a red candle to close below that green candle's open, with body at least 0.5 times the mean true range of the previous 14 bars. The threshold is editable. A subsequent green candle must close above the red candle's high.
- Freeze that renewed candle's high. Only a later consecutive observed bid crossing strictly above it triggers a long. The confirmation candle's own high cannot trigger its entry. Shorts reverse these conditions and are an optional inferred mirror, off by default.
- Stop: the pattern low minus one exchange tick (pattern high plus one tick for shorts). Runner target: nearest eligible opposing, untaken higher-timeframe reference, or an eligible manual target. No target is invented if one is unavailable.
- Candidate timeout: ten completed bars from the touch. A feed/reconnect gap over five seconds invalidates the candidate. Entry expires 15 seconds after the observed crossing, with a 0.25 true-range entry zone and spread checks. A reference is consumed by its first attempt rather than repeatedly re-entered.

These numerical rules, sizing and execution rules are app assumptions. This version does not claim to reproduce every discretionary decision in the video, establish a win rate, or add a new historical backtest result.

## Orders, risk and exits

Default editable limits: 5× leverage, one contract, $1 total planned loss, $25 margin, $1,000 notional, $3 daily realised loss and three entry attempts per IST day. Risk and reward estimates include ordinary product fees, GST and a slippage reserve; no promotional fee waiver is assumed. Quotes and order prices remain USD. Cash P&L follows the app's configured display currency; risk-setting inputs explicitly use USD.

Live preflight verifies connected Delta India credentials, isolated margin, auto top-up off, the selected broker leverage, available collateral, liquidation clearance and no conflicting BTCUSD position/orders. It does not change broker leverage or margin preferences silently. Entries are maker-only limits with attached native protective stops. Unfilled entries cancel after 15 seconds; a partial fill cancels the remaining entry quantity.

Maker-only is mandatory for this strategy's entries in both directions. Each live entry records `entry_execution: post_only` in the durable trade record and submits a GTC post-only limit. A post-only rejection does not fall back to market or IOC. An unknown submission outcome follows the existing intent reconciliation path rather than submitting another entry. An entry may therefore remain unfilled or be rejected when the book moves. Protective stops and emergency closes remain reduce-only and can execute as taker orders.

If at least two contracts fill, the first target sells/buys back half the filled contracts rounded down at 1R, only if that slice is estimated profitable after costs. Otherwise all contracts use the runner target. The remaining native stop moves toward fee-adjusted whole-trade breakeven after a confirmed partial exit. All exits are reduce-only. Native stops remain in place during target changes.

Once estimated whole-trade net profit exceeds $2, the protected floor becomes at least $1.50 and rises to peak net profit minus $0.50. Acknowledged stops never move backward. Funding, paid fees, expected close fees and adverse execution reserve contribute to the estimate. Gaps, liquidity and execution slippage can still produce a lower realised result. Maximum holding time defaults to 29 minutes; this does not guarantee a fee waiver.

## Persistence and timing

`db/liquidity/<owner-id>/config.json` stores non-secret settings. Separate `paper.sqlite` and `live.sqlite` ledgers store candidates, consumed IDs, commands, order intents, fills, fees, partial targets, net peaks and completed trades. Actual credentials remain with the existing connected-account service.

The hosted process aims for one-second polling. It uses REST snapshots, so slow requests can lengthen a cycle and intervening ticks can be missed. Exchange stops provide the primary protection; polling is not a tick-complete feed. The chart displays the server-owned entry, current stop and runner target when the panel is open and its snapshot is fresh. Older liquidity indicator plans are separate visual studies and do not execute orders.

After a restart, start the same strategy/mode to reconcile saved owned orders before any new entry. The existing Python host controls process restoration; this strategy is not installed as an unattended system startup job. Switching global mode pauses new entries while existing exposure continues to reconcile in its original mode. Unknown outcomes remain pending for broker reconciliation rather than being blindly retried.

The executor reuses the installed `delta-scalper` adapter through `strategies/confluence/live.py`. That adapter must remain installed on this machine. Exclusive controller/account locks prevent competing copies of this executor from submitting simultaneously, but cannot prevent manual broker activity. Do not manage the same position with another bot.

## Verification boundary

Automated tests exercise causal signal stages, both directions, equality/dojis, gaps, sizing, liquidation limits, approval revisions, synthetic fills, partials, targets, net trailing, restart reconstruction and command recovery. Paper fills require observed trade-through and estimated queue consumption; they remain a simulation. Exchange API sequencing follows the [official Delta API documentation](https://docs.delta.exchange/).

Deployment verification uses read-only public market data and UI checks. No live trade is placed to qualify this implementation. Exchange-specific fill/stop/target behavior must therefore still be observed on an explicitly started session before treating the full live lifecycle as verified.
