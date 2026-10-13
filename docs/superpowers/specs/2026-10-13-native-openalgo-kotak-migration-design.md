# Native OpenAlgo migration for Kotak Neo

Date: 13 October 2026. Status: design ready for user review; migration implementation has not started.

## Intended outcome

Use a clean copy of the official OpenAlgo application as the running trading platform. Configure the user's existing Kotak Neo account and integrate the strategies and features already developed for Neo Desk into native OpenAlgo pages and services. A working migration means the user can see account balances, actual option prices, strategy progress and order outcomes in one application, with explicit control over paper and live execution.

The current terminal remains available at port 8787 during migration. Existing journals, research data, broker reports and private configuration remain recoverable. The clean installation does not inherit unrelated modifications from the current checkout.

## Verified starting point

- Repository: https://github.com/marketcalls/openalgo.
- Official default branch: `main`; observed upstream commit: `f2d28cd54f6484a329032ecd62af138c663e2e0f`.
- Current development branch: `codex/kotak-nifty-scalper`, with uncommitted terminal work. Its checkout must not be reset or overwritten.
- Public source at the observed upstream commit was inspected. The Kotak adapter, broker callback, broker-login React page and native Scalping page match their current local counterparts.
- Upstream provides Flask, React, Kotak authentication/REST/streaming, native account books, Analyzer paper execution, a Python strategy host and shared risk services.
- The four private values needed for Kotak are present: UCC, current Trade API token, mobile and MPIN. Their contents were not printed or included in this document.
- Port 5000 already has a listener. Ports 5001, 8767 and 5557 had no listeners at inspection time. Recheck before startup; explicitly configure the selected ports without runtime fallback.
- The existing terminal is connected, Sandbox / Stopped and flat after the market close. The selected profile is ORB with a 6R target and index trailing stop.

## Selected approach

Create an isolated clean checkout from the verified official upstream commit, then extend the native application. Use OpenAlgo's broker session, normalized services, execution machinery, shared risk core, databases and React components. Integrate custom functionality into native Scalping, Trading, strategy, reports and dashboard pages.

Alternative approaches considered were embedding the existing terminal in an iframe or running a second broker/execution service beside OpenAlgo. The selected approach gives the user one broker connection, one execution-mode authority and native navigation while preserving the established strategy rules.

Use a dedicated instance at `http://127.0.0.1:5001` during validation, with WebSocket proxy port 8767 and ZeroMQ port 5557. Each instance owns its data directories and explicitly configured ports. Cutover to the user's primary terminal happens only after validation; stopping a strategy must retain management of any owned exposure.

## Credential and login integration

Configure the new instance from the current private settings using this mapping:

| Existing value | OpenAlgo configuration |
| --- | --- |
| `KOTAK_UCC` | `BROKER_API_KEY` |
| Current `KOTAK_API_TOKEN` | `BROKER_API_SECRET` |
| `KOTAK_MOBILE` | Server-side mobile value for the Kotak login callback |
| `KOTAK_MPIN` | Server-side MPIN value for the Kotak login callback |

Use the updated Trade API token; do not substitute the old API secret shared in chat. Store private configuration outside tracked source, with restricted file permissions, and generate fresh application encryption/session keys for the new instance.

The broker login form asks only for a fresh six-digit TOTP. The server supplies mobile and MPIN. A rejected TOTP must not replace an existing session or stop an active engine. Reuse a valid same-day broker session and existing authenticated browser session. A new browser must establish ownership through verified authentication; a cached server token alone does not authenticate an unknown browser. Preserve OpenAlgo session, CSRF, rate-limit and loopback protections. Never use forged browser metadata as an authentication mechanism.

If an OpenAlgo owner account already exists, bind the broker to that native account. If no owner exists in the new instance, establish the single owner through a successfully verified Kotak login and native account/session storage. Do not expose stored mobile, MPIN or tokens to React, logs or exported reports.

## Strategy and execution integration

Provide four selectable presets, with one active at a time:

| Preset | Entry model | Availability |
| --- | --- | --- |
| ORB with index trail | Confirmed 15m crossover of the complete 09:15–09:30 NIFTY range | Paper and Live |
| ORB with option controls | Same ORB entry, with option-risk and cash-profit controls | Paper and Live |
| Donchian with controls | Previous 20 completed bars, confirmed trend/data checks and option controls | Paper and Live |
| Price Break & Retest | Previous-three-bar break and later confirmed retest | Paper research only |

Keep the existing ORB with index trail selected. Bullish index setups buy CE; bearish setups buy PE. These are long-option purchases, not naked option selling. Contract identity, expiry, strike, lot size and tick size come from current broker metadata. Do not hardcode the expired 13 October contract for future sessions.

Shared rules:

- Signal timeframe: 15 minutes. Chart timeframe can be changed independently.
- Entry execution window: 09:45 through 15:15 IST, inclusive of a signal confirmed at 15:15.
- Scheduled owned-position square-off: 15:29 IST, independent of chart candle completion. Stops, targets and loss guards can exit earlier.
- Initial index target: 6R. Preserve each preset's existing trailing activation and distance rather than silently changing them.
- One broker lot at a time; expected NIFTY lot size 65, verified against metadata before trading.
- Option selection: observed premium near ₹50 ±5, subject to executable spread/depth, fresh data and affordability checks.
- Entry affordability uses fresh available Kotak trading limit and estimated entry costs; no fixed entry-budget cap is restored.
- Planned trade-risk limit ₹500, daily loss guard ₹1,000 and three-entry guard. Controlled presets retain their tighter option-risk conditions.
- Recovered historical setups do not create retrospective orders. Entries require fresh confirmed data; duplicates and same-bar reversals remain blocked.

Extract the established pure indicator and signal calculations with behavioral parity tests. Translate their results into native strategy execution. Risk rules belong in `services/risk/`; adapters translate state and do not maintain competing stop/target evaluators. Add missing index/option risk behavior to the shared core and its contract vectors.

Use native order ownership, reconciliation and audit paths. Persist the originating mode and profile, filled quantity, effective stops/targets, peaks and profit floors. A Live-owned position must exit through the Live path even if the platform-wide Analyzer setting changes. Claim an exit under the same lock that checks ownership; release a refused dispatch claim without dropping position management. Partial fills and partially cancelled orders retain their filled exposure.

Start the new instance in Analyzer mode with entries stopped. Configure paper allocation to match the user's trading allowance rather than using OpenAlgo's default ₹1 crore to imply affordability. A separate explicit user action arms real entries. No real buy, sell or square-off is submitted as a development test.

## Native user experience and feature carry-over

Use the official OpenAlgo navigation, components, typography and themes. Retain its built-in account books, option-chain tools, Python host, Analyzer and logging pages. Custom pages follow the same conventions and share the existing authenticated API.

- **Scalping and strategy controls:** selected preset, paper/live mode, start/stop, readiness reasons, entry counts, daily performance and ownership status. Display execution errors immediately and retain their recovery instructions.
- **Charts:** select NIFTY spot or an actual CE/PE contract by expiry and strike. Display option candles and quotes on their own premium scale. Support chart timeframes, Donchian 20, EMA 200, visual FVG, RSI, confirmed support/resistance and potential liquidity zones. Mark CE/PE buy signals, executed fills, effective SL, target and trailing levels. Chart selections persist across navigation.
- **Position controls:** current gross and estimated net running P&L; manual SL/target in option premium rupees; trailing activation/distance in net rupees; confirmable square-off of the exact terminal-owned position. Changes persist through reconnects. Stop entries leaves exits managed.
- **Dashboard:** live available trading limit, account P&L, separate strategy paper/live P&L, costs, NIFTY status, RSI and constituent advances/declines with timestamps and coverage. Stale or absent values are labelled explicitly.
- **Reports:** migrate archived broker fills and actual-fee imports with deduplication. Show gross P&L before fees, actual paid charges when reported and net P&L when complete. Estimated fees remain distinct. Zero-fill cancelled/rejected orders do not create fees or trades; filled portions remain included.
- **Fees:** preserve the current Trade Free promotion and its recorded validity dates. Apply ₹0 brokerage only within the confirmed promotional period; configure the applicable ₹10 plan rate afterward. Statutory charges remain. Do not label calculated estimates as paid contract-note charges.
- **Backtests:** preserve datasets and prior reports as historical artifacts. Offer new replay through the same signal/risk core, including chart annotations and compounding by affordable whole lots where selected. Support up to one year when real data exists. Show missing expired-option coverage and unresolved fills rather than inventing data or profits.

Register runtime custom chart indicators through OpenAlgo's documented indicator loader. Do not bundle user indicator files into the main frontend build or silently override existing built-in IDs. Follow the upstream chart-indicator skill during implementation.

## Data migration and cutover

Back up and checksum the current terminal journal, archived fills, fee imports, historical datasets, reports and public strategy configuration. Make a schema-aware migration with stable source IDs, counts and totals. Keep paper and real broker records distinct. Import no terminal-owned open exposure automatically into a new engine; any non-flat cutover requires explicit reconciliation of the exact broker order and position ownership.

Each migration is repeatable without duplicate fills, fees or orders. Retain a migration manifest and read-only source backups. Do not copy the current dirty checkout, build output, old virtual environment or unrelated local modifications into the clean installation.

## Verification and acceptance

1. Record upstream commit, dependency versions and clean baseline results before custom changes.
2. Validate native Kotak login/session restoration, master metadata, balances, positions, trade/order books, index and option quotes, historical candles and streams. Ask for a TOTP only if a genuinely new broker authentication is required.
3. Compare preserved signal/risk fixtures, including both CE and PE for all eligible presets; Price Retest remains paper-only. Test the 15:15 entry boundary and 15:29 timer in IST and UTC.
4. Exercise Analyzer orders end to end using deterministic data at the broker boundary: real native order submission, partial/full simulated fills, accounting, annotations, SL/target/trail exits, manual square-off, reconnect and restart. These fixtures do not become user trading results.
5. Verify shared execution-mode ownership, duplicate exits, refused exits, partial cancellation, stale quotes, failed authentication, uncertain opening data and timer behavior across supported runtime modes.
6. Test the actual React UI for TOTP-only broker login, navigation, option selection, indicators, readiness, paper controls, errors, manual protection, reports and replay. Never arm real orders as a UI test.
7. Reconcile imported fill counts, fees and P&L with source records. Run available actual-data backtests, reporting coverage and costs; no win-rate or profit guarantee is an acceptance criterion.
8. Verify one active preset, working account data and a clear daily-session checklist before cutover. Keep the previous terminal available for rollback until its data and controls are accounted for.

## Implementation boundaries

Deliver the migration in two connected, independently verifiable parts: (1) clean native installation, Kotak login/data integration and the four preset execution paths; (2) charts, manual controls, reports/backtests and market overview integrated into native pages. The intended deliverable includes both parts. Produce exact file/interface implementation plans after design approval, rather than importing the whole standalone backend unchanged.

Official upstream references: https://github.com/marketcalls/openalgo and https://docs.openalgo.in. Inspected public-source provenance: `/private/tmp/openalgo-upstream-audit-20261013/provenance.json`. No new installation, broker authentication or trading action has been performed for this migration design.
