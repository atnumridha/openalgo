# OpenAlgo chart toolkit port

Port the user's approved TradingView visual analysis into the running Neo chart at localhost:5001. The active checkout is `~/.codex/worktrees/neo-native/openalgo`; the primary checkout is a different branch. Develop against a snapshot of that frontend in `workspace/chart-toolkit-port/frontend`, preserve existing modifications, and apply only reviewed chart files to the active checkout. Do not restart the broker service or change execution settings.

## Approved behavior

- Blue EMA 9 and orange EMA 15, fixed by the user's later instruction; optional Bollinger bands.
- Directional RSI 14 zone exit with matching MACD 12/26/9 cross within five chart bars and strengthening histogram. One confirmed BULL/BEAR per timing event; four historical labels by default. Live preview is separate from confirmed state.
- Confirmed pivot support/resistance boxes (10 left, 5 right), two nearest zones per side. Valid rising support/falling resistance diagonals with wick validation.
- Repeated highs/lows produce estimated liquidity pools after the second pivot confirms. Distinguish active, taken and swept pools. Mark strong closed-candle breakouts and wick sweeps separately.
- Previous completed 1D, 4H and 1H high/low references from a suitable broker timeframe, never derive lower-timeframe ranges from larger chart candles. Labels include source timeframe and price; merge coincident labels.
- Compact status and current numeric checks; context indicators color coded. Unavailable volume-dependent values hidden.
- Own European BSM IV calculator using selected option and matched underlying candles, explicit strike/expiry/rate assumptions, freshness, no fabricated IV Rank. IV remains separate from price signals.
- Work with selected standard OHLC bars at any supported timeframe. Broker market coverage is explicit; no claim of unsupported crypto feeds.

## Implementation and verification

1. Pure TypeScript calculations and fixtures: warmup, prefix stability, live/closed separation, both directions, pivots, consumed liquidity, breakout strength, timeframe boundaries, BSM inversion and invalid inputs.
2. Canvas overlay primitive and lightweight EMA series; bounded object count, cached closed-bar results and scheduled updates. Compact dashboard and explicit settings.
3. Integrate with NeoMarketChart without touching order controls. Add native workspace toolkit toggle and market selection using broker symbols.
4. Test affected components and TypeScript build. Apply narrow changes and build the active frontend without backend restart.
5. Browser verification at multiple timeframes, historical/replay behavior, actual source freshness and visual clarity. Report feed limits honestly.

## Installed result

Installed in the active Neo checkout with backups under `workspace/chart-toolkit-port/backup`. The user's later instruction added a full-viewport dark chart, native browser full screen, quick timeframe buttons, and collapsed options/history controls. NIFTY's automation panel is outside the focused chart and is hidden for other markets. Crypto uses public Delta REST history and its current public candle WebSocket, without keys or private endpoints. A chart-only CSP exception allows that exact public REST host.

51 focused frontend tests, two security-header tests, TypeScript, lint and the active frontend build pass. Browser checks covered NIFTY 15m and 5m and BTCUSD 15m, live streaming, EMA colors, structure/labels, and full screen. Public candle calculations also exercised BTC/ETH at 1m, 5m, 1h and 1d. `workspace/chart-toolkit-port/validation.json` records the evidence. BankNifty and Sensex routing is implemented; no claim that every broker/timeframe combination was visually checked.

The current broker can take appreciably longer to return historical candles than streaming quotes. The chart controls remain usable while a history request is in progress. EMA smoothing, pivot confirmation and closed-candle signal confirmation retain their mathematical delays.

The first web-worker HUP hit a macOS Objective-C fork error. The web service was restored with its original startup command. Read-only database guards before and after showed no active/pending/owned desk entries and no unstopped native strategy run. No order or strategy-start action was invoked; execution settings were not changed.
