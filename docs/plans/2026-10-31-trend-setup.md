# Trend setup implementation

Requested: implement all trend chart pattern references, plain English readings, colored candle names, completed-bar entry/stop/target, live BTCUSD verification.

1. Add causal EMA20/50 and confirmed-swing trend engine, with automatic higher timeframe and tests.
2. Extend shape geometry for missing reference families and bilateral triangle breaks. Attach structural measured-target metadata.
3. Add tick-safe setup lifecycle and scoped chart entry/stop/target lines. Stop/target collisions remain ambiguous.
4. Integrate same-instrument higher timeframe history with fixed observation cutoffs. Current history, source identity, errors, replay/range guards must remain effective. Higher timeframe disabled in historical replay/range unless historical source verified.
5. Show current/higher trends, conflict WAIT, confirmed active setup state in plain English. Preserve pattern-only colored labels.
6. Run focused tests, typecheck, full frontend suite; build/publish and inspect live BTCUSD in Chrome. Save data and screenshots. Live detection validates behavior, not profitability.
