# TradingView combined indicator port

User requests TradingView.com Pine Script implementation of the existing EMA9/15/21, candle LONG/SHORT patterns, Fibonacci pivots(4), volume, RSI and RSI+MACD trend setup; also show EMA crossover. Platform confirmed. Layout preference pending; independent calculation work proceeds first.

- [x] Port source-defined three-EMA alignment with custom SMA seed/ATR warmup, confirmed signals, firstqualifierperregime, green/redX; separate optional9/15crossovermarks. Preserve current charttimeframe interpretation; noAuto5meligibility implied.
- [x] Port existing candlestick families to Pine functions, preserving operationaldefinitions and trendcontext. Return directional names, deduplicate sharednames, label only confirmedbars with dottedleaders and6-pointtext/tooltip. Document any unsupported family instead of claimingfullparity.
- [x] Port current RSI14/MACD12,26,9 timing: RSIexit30/70 and same-sideMACDcross within5bars, growinghistogram, onceperRSIexit. Inputs configurable.
- [x] Fibpreviouscompletedpivotperiod HLC, ratios.382/.618/1, adjustableanchorand4periodhistory; no futurehigherTFvalues. Volume/RSI pane layout follows useranswer.
- [x] Independent localPine numericaltests, staticbudgetchecks, TradingVieweditorcompile/render ifavailable. LocalPineTS is not officialTradingViewcompiler. No publishing/publicsharing, orders or brokerchanges.

Completed: official TradingView compilation and live DELTAIN:BTCUSD.P 1m rendering verified. Basic plan blocks saving another private script; source is loaded as an unsaved indicator and backed up locally. Existing S/R + EMA study replaced on chart to fit the two-indicator limit; its saved source was untouched.
