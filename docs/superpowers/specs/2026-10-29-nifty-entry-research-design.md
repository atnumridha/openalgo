# NIFTY single-option entry research design

The user authorizes planning, internet research and historical backtesting to find a single CALL/PUT buying method with at least 80% net wins, larger average winners than losers, and eventual clear entry/exit/SL/S/R chart signals. Prior exit-only experiments failed. This phase researches entries; an unqualified method will not be installed as a validated strategy.

## Approach

Another stop grid retains the failed entries; unrestricted optimization risks fitting reused data. The chosen research approach is a bounded comparison of three source-informed underlying-index entries with common cost-aware option exits. This is the implementer's choice within the user's authorized research scope. Sources and all adaptations are recorded in `workspace/nifty-entry-80/new-entry-sources-2026-10-29.txt`.

Three families: first EMA20 pullback after ADX14 crosses above 30; fresh same-time 14-session noise-band breakout; failed previous-session high/low break in the direction of the last completed 15-minute EMA20 trend. Exact causal formulas/state rules are in the source note's implementation clarification. EMA uses SMA20 seed. Histories carry across normal session boundaries and reset at invalid/missing intraday blocks. Pending entry states reset every session.

## Frozen common choices

- 12 candidates = three entry families × 5%/10% premium stops × 1.5/2 net-risk targets. No additional outcome-driven tuning in this round.
- Underlying 5-minute bars require five exact, valid, unrepaired one-minute observations. Fifteen-minute bars require 15. Signals use completed bars only; next-minute option open executes. No spot VWAP: spot volume is zero.
- Context uses only official exchange-metadata dates. Previous-day levels and sigma samples require complete 375-minute regular sessions with no repaired/invalid bars. For sigma use the last 14 complete previous sessions and record their dates. Previous close/H/L are from the immediately preceding official session and require that session complete. No forward filling missing current context.
- Long ATM CE for bullish signal; long ATM PE for bearish. Reuse original nearest-expiry pair fixed at 09:19, one historical lot, one position at a time, maximum two entered trades per session. This selection differs from dynamic ATM at signal time and must be disclosed.
- Actual entries 09:45 through 14:30 IST. Close-confirmed entries; resting premium SL/targets may trigger intrabar. Maximum 45 minutes holding; mandatory 15:15 exit. No protection or partial exits in this experiment.
- Stop rounds up to INR0.05 without widening nominal risk. Target rounds up to the smallest tick satisfying required net gain after dated fees and INR0.50/unit/side slippage. Stress uses INR1/unit/side with unchanged orders.
- No legacy VWAP entry/bracket filtering. New candidate selection uses only its own conditions. Reuse verified payoff execution with an unrestrictive reference bracket derived from the signal close, and explicitly record that it is not a strategy stop.
- Stop/target both touched in one minute is unknown; adverse stop gaps use open; favorable target gaps fill conservatively at the resting target limit. Unknown ends the day's entries. No future high/low trading decisions.
- Reject qualification unless earlier >=100/later >=50 closed trades, zero unknown, >=80% net wins in each, average win > average loss, positive net and PF>=1.2 in each, positive later stress net. Report confidence intervals, monthly/side results and loss reasons.
- Earlier is Oct2024–Dec2025; later Jan–Jul21 2026. Both reused. No genuine out-of-sample claim. Inspect any newer data separately for QA; sparse previously used snapshots do not qualify as new validation.

## Deliverables

Separate research module/tests and result ledger in `workspace/nifty-entry-80`; frozen protocol, human report, all candidate results, selected comparison and independent execution review. No existing app, Pine script or broker order changes. Sources motivate hypotheses; their published win rates are not assigned to our adaptations.
