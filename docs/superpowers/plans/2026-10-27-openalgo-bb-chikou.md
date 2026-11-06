# OpenAlgo BB + Chikou chart option

Port the existing, user-approved candle-close BB + Chikou indicator to the running OpenAlgo chart at localhost:5001/trading. Source checkout: /Users/nmandal/.codex/worktrees/neo-native/openalgo. Prepare edits in workspace/bb-chikou-openalgo/frontend; preserve other chart and broker changes.

- Add an independent, persisted optional study named BB + Chikou · BULL / BEAR to the existing picker; do not enable it by default or couple it to the existing momentum toolkit.
- Match default Pine logic: SMA20, population BB2, full-candle clearance 26 bars back, first single-band touch, immediately next adjacent candle closing beyond setup high/low, positive SMA risk, closed candles only, weekday IST cash session, no cross-day setups.
- Draw bands, literal backward-shifted confirmed Chikou, BULL/BEAR markers, and latest fixed entry/stop/1R target. Restrict drawing to visible chart history and replay as-of time. References are not orders or managed positions.
- Test both directions, unconfirmed suppression, expiry, gaps, warmup, historical clearance, prefix stability, frozen levels, and picker persistence. Run focused chart tests, typecheck, build, and independent review.
- Back up and apply only the changed frontend source and verified build to the active checkout, then verify the selectable option in the user's browser. Do not restart the broker or alter execution settings.

## Installed and verified

- Installed 9 narrow chart source/test files and rebuilt frontend assets into the active Neo checkout. Existing modified source was backed up under workspace/bb-chikou-openalgo/backup; baseline hashes protected against concurrent overwrites. Existing hashed assets were retained for open tabs. No broker restart or order action.
- 77 focused tests across 10 files passed, including both directions, full-candle Chikou clearance, unconfirmed candles, setup expiry, time gaps, session boundaries, frozen levels, persistence, disable cleanup, and historical marker rendering. TypeScript and production build passed.
- Independent review found a last-40-marker cap that would hide older historical signals. Reproduced with a failing 45-signal drawing test, removed the history cap, and passed the full focused suite.
- Build adaptation: retain existing VITE_NEO_DESK_ENABLED=true. The isolated gitignored build workspace required an explicit TS/TSX source glob for Tailwind scanning. That scan directive is build-only in the isolated snapshot; the active stylesheet source was unchanged. Browser verification caught and corrected the route/styling issues before completion.
- Browser verification at localhost:5001/trading: new checkbox under Options, successfully enabled on Nifty 15m, setting retained after reload, correct original layout, blue Bollinger boundaries, SMA middle and purple backward-shifted Chikou line visible. Sensex shares the same selected-study calculation and existing symbol routing; no separate Sensex visual check claimed.
- Only default Pine settings are ported in this chart option (20 / 2 / 26, full-candle clearance, first touch, 1R, IST session); optional Pine squeeze settings and TradingView alert delivery are not wired into OpenAlgo notifications. Chart markers and indicative reference levels are visual analysis.
