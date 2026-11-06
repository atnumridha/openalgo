# CE/PE independent indicator support

> For agentic workers: use superpowers:executing-plans. User authorized the fix and selected underlying index by default, with both sources selectable.

**Goal:** Enable all nine independent indicator rows and price-event markers on CE/PE charts, without mixing premium direction with index direction.

**Architecture:** Resolve contract context explicitly; select underlying or premium candles for the six price indicators. IV/PCR use the resolved underlying and chart expiry; OI and index-volume MFI use the nearest active futures contract, named in the panel. Map signals to BUY CE/PE or AVOID CE/PE for the displayed contract. Keep raw signal rules unchanged. Existing BB+Chikou, candle-pattern, RSI+MACD and structural studies already consume displayed chart candles and must remain operable.

**Tech stack:** Existing React19, TypeScript, TanStack Query, Lightweight Charts; no new dependencies.

**Authorization and approach:** User: “Fix make sure all indicators work on PE CE as well.” Follow-up selected “Underlying index by default; allow both.” This supplies the missing design decision; execute the authorized fix without another approval cycle. Reuse the existing codex/neo-native-kotak worktree; develop in a writable frontend snapshot, build/test, then guarded install with backups.

## Constraints and review focus
- Price modes selectable on CE/PE: underlying default, premium alternative, source always visible.
- Preserve index/dashboard behavior and numerical rules; no automatic orders or fake SL/exit trades.
- Correct put inversion: underlying bearish favors BUY PE; premium bullish also favors BUY PE. Opposite bias means AVOID current contract; this is not a broker position exit.
- Recognize real broker option symbols/reference metadata; reject stale/mismatched references and unknown underlyings instead of guessing NIFTY.
- Use chart expiry for IV/PCR; context always uses underlying, never an option premium as spot. Expired data remains unavailable under existing freshness rules.
- Clear old source results on mode/symbol/interval changes; no future bars during replay; no turning an observed unfinished candle into a confirmed candle merely as wall clock advances.
- Futures MFI proxy allowed for underlying-index mode only; option-premium MFI requires genuine option volume.
- External context may remain WAIT on absent/stale feeds; do not fabricate historical IV/PCR/OI markers.

## Tasks
- [x] Add pure chart-context resolution and action labels; test CE/PE, NSE/BSE, stale metadata, stock/unknown contracts and both source modes.
- [x] Enable price events on option charts, add underlying history selection and visible source control; test close/replay/symbol switching and marker anchoring.
- [x] Route IV/PCR through the correct underlying and chart expiry; use named nearest active futures for OI/MFI; test independent availability and request identity.
- [ ] Run focused tests, typecheck, build and full suite; independent final review; guarded install; verify CE and PE in app.

## Validation
Run Vitest with bundled Node24 in workspace/option-indicator-support/frontend. Existing unrelated full-suite failures are recorded in workspace/candlestick-probability/VERIFICATION.txt; report any remaining by name. Test affected chart and context behavior before the production bundle is installed. Verify sources have not changed since snapshot before overwriting anything. No commit/push or orders in this task.

Implementation, review, automated checks and guarded installation completed. Browser CE underlying action verified. Final manual PE/source-switch visual check remains pending while Chrome is in use; automated PE/source-switch tests pass. See workspace/option-indicator-support/VERIFICATION.txt.
