# Chart Setup Assistant — approved implementation

Authority: the user's complete approved plan in this chat, 16 October 2026. Signals are advisory, never entry submissions. Keep manual entry and exit controls.

## Global constraints
- Support NIFTY, BANKNIFTY, SENSEX; bullish BUY CE, bearish BUY PE.
- Pure, versioned shared strategy evaluators for live, replay, and historical audit. Causal completed candles, exchange sessions, holidays, freshness and continuity; no manufactured index volume or overnight candles.
- Separate chart setup readiness from account/order readiness. Clearly distinguish index level, strike, premium. REST prices are sampled snapshots, not every tick.
- Preserve unrelated dirty files, native active Trading page, secrets, broker configuration. Deploy only bounded files to existing isolated Kotak checkout after backup; restart using existing launchd launcher. Verify without placing orders.

## Task 1: signal engines
Create pure trend and opening-reversal evaluators and tests. Trend uses 250 completed 5m/60 completed 1m warmup, EMA20/50 rising context, Wilder ATR/ADX/RSI14, ADX20. Confirmed default: retest within3bars or sweep+confirmation; Early: first completed break by0.1ATR. Causal swing/prior-day/opening15m levels. Freeze entry, zone0.25ATR, invalidate beyond extreme0.1ATR, expire after2 further bars, missed beyondzone, require2R opposing room or projected2R. Rank retest before sweep thennearest.
Opening uses current-session strict2left/2right1m pivots, first/second numbered byconfirmation and frozen H2/L2. PE observed >H2 afterknown, first completed red (same breakbar allowed), subsequent tick strictly <red.low. CE inferred mirror: <L2 thenfirstgreen then subsequenttick >green.high. Doji skip, frozen trigger,5mexpiry thenfresh reference recross, one trigger/direction/session, restartcausality. No EMA/ADX gates/ATR buffer. Literal PE22608 break whileabove22590; CE22495 break whilebelow22500. Persistserializablestate, stableIDs, evidence/stage/timestamps.

## Task 2: monetary policy
Trend premium SL lower(entry−1.5optionATR, confirmedoptionlow−tick), R multiples1.5,2,3,4,5,6 default2. Opening ₹500 TOTAL netrisk, ₹1500 nettarget default. Tickroundstop towardlessrisk andtarget towardnetgoal; fees+slippage included; unsuitablebudgets explicit. Reconcileactualfills/qty withoutlooseningstop afterpartialfill. Persiststrategy/version/riskpolicy throughpreview, fills, protective stop andautomatic target. Sharedpure riskdecisions in services/risk. Preservelegacytrades.

## Task 3: chart/ticket UI
Add strategy/mode selection, progress/reasons/directional arrows, reference/signalcandle/trigger/remainingtime. Use setup adoptsrecommendedcontract andticketwithoutorder; preservedits onrefresh. Openingcashbudget/RR, quantities/fees showcorrectly. Read-onlyreplay distinguishesliveeligibility; existingmanualcontrolsunchanged. AllRRchoices. Followexistingterminalstyle.

## Task 4: runtime integration/persistence
AddsameDB setupstate/eventtape durablecheckpoint, boundedretention, peruser/underlying/session. Processobservedwebsocketevents safely, fallbacksampledREST; never turnmissedhistoricalcrossingsintofreshsignal. API snapshotstructuredresult andread-onlyreplay shareengine. Calendar-awarevalidbars. Reconcileonrestart. Accountfailurescannotmasqueradeaschartfailure.

## Task 5: replay/backtest/review/deployment
Audit availablehistoricalcoverage; separatefamily/mode netfees,expectancy,PF,drawdown,samplecounts andchronologicalholdout. Recordedticksforfaithfulintrabar,OHLCuncertaintydisclosed/conservativesamebaroutcomes. No inventedoptionfills/history. Meaningfulregressiontests,causality,fd-audit,freshreview. Backupboundeddeploy,launchdrestart,UIverifyallindices,UseSetup,replay,restoredstatewithouttrades. Reportcoveragelimits honestly.
