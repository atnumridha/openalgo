# OpenAlgo chart layout refinement

The user rejected the spacious simplified view and previously requested TradingView quality, fullscreen, EMA 9/15, clear BULL/BEAR, named support/resistance and optional liquidity/MTF detail.

Use the existing Lightweight Charts renderer. Keep a single 44px toolbar. Place the instrument/OHLC/EMA legend over the upper-left chart area and a compact confirmed-signal panel at upper right. On small screens put the panel at lower left. Preserve optional layers and existing signal/data/execution behavior.

Colors: chart #131722, panel #181c27, separators #2a2e39, text #d1d4dc, secondary text #959bad; preserve blue/orange EMAs and green/red direction colors. Use existing sans-serif typography, 11px numeric context and a compact 14px signal label. Default to approximately 110 visible candles on wide screens.

A larger dashboard would restore the visual clutter the user rejected; retaining full-width status bars does not meet their reference. The selected approach follows the user's prior TradingView direction.

Verify with existing chart/indicator tests, lint, TypeScript, production build and the live fullscreen page. Deploy frontend assets atomically and do not restart the backend or change trade execution.
