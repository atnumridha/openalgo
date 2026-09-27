# Strategy Research

Strategy Research includes deterministic historical screening and prospective Sandbox qualification for a saved Strategy Module strategy and its linked Flow. Historical reports distinguish unavailable evidence from zero outcomes. Import historical underlying and actual option candles with their point-in-time contract definitions; synthetic option prices and invented index volume are unsupported. Enrollment and release approval do not place orders or activate a Flow.

The shared risk policy limits the first filled trade to a planned ₹1,000 loss, then pools another ₹1,000 across all later trades in the same session. Profits do not replenish either bucket, and unused first-trade allowance does not transfer. Planned charges and exit slippage count toward risk. Total capital is ₹10,000 with a 20% cash buffer. A persistent 20% peak-equity drawdown prevents further entry across later sessions. Gaps can exceed planned loss: they are reported as actual losses and reduce remaining allowance. These rules do not guarantee a realized loss ceiling.

Replay uses `services/risk/budget.py` and the existing position risk evaluator. Replay deliberately permits only one long-option position at a time, a conservative subset of the shared two-position maximum. It does not yet research concurrent index and commodity portfolios, short options, spread margin, pyramiding, position averaging or overnight positions.

## Parameter comparison and ML research

In **Historical test**, import matching underlying and option history, choose a dataset, then select a **Test type**:

1. **Test one rule set** runs the existing deterministic development replay.
2. **Compare parameter values** accepts comma-separated values for the active rule's parameters. Unlisted parameters keep the values in the form. The screen shows the Cartesian product size and refuses empty, duplicate or more than 256 combinations. The worker uses the same execution, costs and risk model for every combination. Selection is deterministic, preferring complete outcomes and higher exploratory OOS net P&L, then lower drawdown, more trades and the configuration hash.
3. **Train a RandomForest model** evaluates predicted profitable option opportunities using causal underlying/option features. This is an optional research dependency. Install the pinned dependency group from the project directory with `uv sync --frozen --group research`, then restart the web app and research worker normally. Without it, the page explains the missing dependency and disables training.

For a comparison result, **Test selected parameters** creates a separate ordinary development run with the selected configuration and a link to its parent search. The server rechecks dataset, source, risk, report and configuration hashes and rejects incomplete selected results. Only that new development run can proceed through freeze, final evaluation and the existing qualification process. Searching many configurations makes the comparison OOS results exploratory; the winning row is not proof of profitability.

ML requires one-minute option execution bars with tick sizes and uses the filtered execution assumptions with a volatility-aware 10% stop and 2R target. The final 60 sessions are excluded before feature and outcome preparation. Earlier development sessions split chronologically: expanding validation folds use only the first 70%, then a model fitted on those training sessions predicts the later 30%. Training labels overlapping a fold's validation boundary are purged. Prediction opportunities with unknown outcomes remain in the prediction set, but are excluded from labelled accuracy calculations.

The ML result separates **prediction accuracy** from **executed-trade win rate** and shows the majority-class baseline, precision, recall, labelled/unlabelled counts, fold details and replay outcomes after costs. A high classification score can coexist with no trades or negative trading P&L. Saved evidence includes dependency versions, seed, training provenance, actual fitted tree state, model hashes and hashes of all prediction probabilities. Cancellation is checked while preparing features and between tree batches.

An ML development run can be **frozen** with its validated JSON forest and then evaluated once on the sealed final 60 sessions without refitting. A model that passes the development and final base/stress screens can be **explicitly installed** as a stopped, disabled Sandbox Flow strategy. The operator must review both Sandbox and Live allocations to ₹25,000, verify a current dated fee schedule with the same execution rates, and collect a separate prospective forward campaign before any reviewed live release. Model, source, strategy, Flow, broker, cost or allocation changes invalidate the relevant evidence. Installation, activation and live approval are separate actions; none occurs automatically. The adapter requires fresh completed index and option bars plus a fresh broker quote and waits when those observations are unavailable. Its broker-history loop and real fills have not been verified in operation. Optimization of deterministic rules retains its existing qualification path.

Complete replay reports also expose session-return CAGR, volatility, Sharpe and Sortino through the existing portfolio analytics module. They include zero-trade sessions, use 252-session annualization and a zero risk-free rate, and suppress undefined ratios. Short-window annualized values are unstable. No benchmark or alpha is invented.

The design takes conceptual inspiration from [Algorithmic Trading with Python](https://github.com/chrisconlan/algorithmic-trading-with-python), while reusing this application's existing indicators, execution and analytics. No upstream source was copied; the upstream [license](https://github.com/chrisconlan/algorithmic-trading-with-python/blob/master/license.txt) restricts commercial reuse.

See the [UI verification record](research-workflow-ui-verification-2026-09-27.md) for exercised flows and test-environment limitations.

## Import contract

Open `/strategy/research`, or use the authenticated `/strategy/api/research` endpoints. POST `/datasets` with `name`, `provider`, `metadata`, and exactly one of `rows` or `csv`. Dataset contents are immutable after normalization. Identical content returns the existing owner-scoped dataset. No dataset update/delete endpoint is provided.

Metadata fields:

| Field | Meaning |
|---|---|
| `underlying_symbol` | Exact underlying symbol used in the bars |
| `timezone` | `Asia/Kolkata` |
| `timestamp_convention` | `bar_close`; every timestamp includes an explicit UTC offset |
| `bar_minutes` | Underlying signal interval; whole number from 1 through 60 |
| `execution_bar_minutes` | Optional option interval, defaults to `bar_minutes`; positive integer dividing the signal interval |
| `session_open` | Optional explicit `HH:MM` opening time; required for the session-VWAP candidate, with no default |
| `session_close` | Required `HH:MM` intraday liquidation deadline, chosen for the instrument and period |
| `source_reference` | User-supplied source description or dataset reference |
| `contracts` | One to 2,000 point-in-time option definitions |

Each contract requires `symbol`, `underlying`, `exchange`, `option_type` (`CE` or `PE`), positive `strike`, ISO `expiry`, positive integer `lot_size`, positive `multiplier`, and `segment` (`index` or `mcx`). Optional positive `tick_size` is preserved in the content hash and required for filtered breakout. It controls adverse buy/sell rounding and executable stop/target increments. The monetary exposure is price times contract quantity times multiplier. Contract metadata is a supplied assertion recorded in provenance; v1 does not independently authenticate it against an exchange's historical contract master.

Each JSON row or CSV record requires `symbol,timestamp,open,high,low,close`. `volume` is optional and remains unavailable when omitted. Naive/future timestamps, duplicate symbol/timestamps, nonfinite numbers, invalid OHLC ranges and post-expiry option bars are rejected. Imports are capped at 20 MB and 100,000 bars. There are at most 100 datasets per owner. All source descriptions and canonical content hashes remain with each dataset.

At least 80 distinct observed underlying session dates are required to enqueue an experiment. Dates are supplied observations, not an independently verified exchange holiday calendar. The session-VWAP candidate requires an explicit `session_open`, and each imported session must start with its underlying closed bar exactly `session_open + bar_minutes`. A missing or late opening bar rejects the VWAP experiment with the offending session date; trend lookbacks may still use a later observed window. No opening time or earlier volume is guessed. Midnight-crossing market sessions are not supported by this screen.

## Rules and execution assumptions

All candidates use only underlying bars that have closed. Lookback defaults to 20, option stop distance to 10% of executed entry premium, and target distance to 20%. Rules reset each session. A gap in underlying candles resets trend lookback; the VWAP candidate stops signalling for the remainder of that incomplete session.

- **Trend and breakout:** buy a call when the close exceeds the previous N bars' highest high and the rolling N-bar mean rises. Buy a put on the symmetric falling-mean, lower-low breakout.
- **Trend, VWAP pullback and volume:** in the same rolling-mean direction, require a candle to touch within 0.2% of session VWAP and close back beyond VWAP with a confirming candle body. Its observed volume must be at least 1.2 times the previous N-bar average. VWAP weights typical price `(high + low + close) / 3` by observed volume. Missing underlying volume rejects this candidate; zero volume cannot provide a usable VWAP. This is an explicit public rule definition, not a reconstruction of any proprietary RTS signal.

For the two original candidates, at a signal close choose the nearest nonexpired listed expiry, then the strike closest to the underlying close, then symbol as the deterministic tie-breaker. A current option candle and the immediately subsequent option candle must exist. Fill the selected option at the next candle's open with adverse slippage. No same-candle entry and no switching to a different contract based on future profitability are permitted.

Entry uses the largest affordable whole-lot quantity within premium cash and shared planned-risk budgets. Each simulated completed trade has one entry order and one exit order. The observed open is evaluated before either later extreme: a gap through the stop or target fills at that open, then adverse slippage. When neither level triggers at the open and both are touched later in the same ambiguous OHLC candle, the stop is evaluated before the target. The intraday deadline uses an observed candle close. Missing option candles while exposed, or an absent liquidation candle, stop the replay with an incomplete outcome; net P&L and ending equity become unavailable. No replacement bar or closing price is fabricated.

The report's main drawdown uses net liquidation equity, including both order fees and adverse exit slippage. Its peak persists across trades and sessions. Known-order candle opens and closes update that peak; intrabar lows test the previously observed peak against the shared 20% drawdown rule. Crossing that limit exits at the first protective boundary (or the actual open on a gap) and permanently pauses further entry for that replay, even if prices later recover. If the original position stop is crossed first, later lows after that exit do not count. `closed_trade_max_drawdown_pct` separately preserves the closed-trade-only statistic. The explicit candle convention does not assume a candle's high preceded its low, so an unobserved intrabar high is not a new peak; tick data would be required to enforce or reconstruct every intrabar peak. Candle screening cannot establish spreads, depth, order latency, stop execution probability or partial fills.

### Filtered breakout and minute execution (v2)

`trend_breakout_filtered` is a new research hypothesis; it is not installed as a live Flow or presented as a proven profitable strategy. Original candidates remain available for comparison. The engine version and implementation hash invalidate promotion of runs from older implementations.

The filtered rule requires the previous 8-close mean above/below the previous 21-close mean, with that 21-close mean rising/falling relative to five bars earlier. These means exclude the current breakout bar, avoiding the original redundant confirmation. It permits 1–7 calendar days to expiry, premium 20–120, strike distance within 500 underlying points, and the latest observed option volume of at least 10 lots. It chooses the nearest expiry and closest strike among currently observed, affordable quotes. It never selects using future candle availability or performance. Maximum three filled entries per day and a 15-minute cooldown measured from the last exit apply.

The stop distance is the larger of the configured percentage and 1.5 times a simple 10-minute average true range, computed from 11 contiguous already-closed option bars. Stops wider than 25% of entry premium are refused. Target distance is the rounded stop distance multiplied by `target_pct / stop_pct` (default 2R). Gap entry prices are rechecked. All fills, fees, whole-lot sizing and shared capital/drawdown admission still apply. Fixed filter settings are saved in each run configuration; they are not extra UI tuning knobs.

A dataset may declare five-minute underlying bars and one-minute option bars using `bar_minutes: 5, execution_bar_minutes: 1`. Entry is at the open of the next option minute, after the signal closes; option exposure is checked minute by minute, while underlying lookback continuity remains five-minute. The timestamp records candle **close**, not its opening trade time. No resampling or synthetic candles occurs inside replay. Missing minute prices during exposure invalidate the result. Within-minute protective-exit/target ambiguity remains stop-first and is counted per split in Results. Minute OHLC cannot establish within-minute sequence or actual fills. The original candidates retain percentage targets; the filtered candidate alone uses volatility-adjusted reward multiples.

The bounded September 26 experiment and its acceptance rules were written before outcomes in [the experiment plan](plans/2026-09-26-replay-and-filtered-strategy.md). Current fees applied to older prices are labeled hypothetical scenarios. No historical screening result automatically activates trading.

### Offline technical ML experiment

The [technical ML training report](technical-ml-training-2026-09-26.md) records two models trained on 50 causal trend, candle, volatility and option features. The runner predicts costed option payoffs, saves its model and exact contract decisions, and evaluates later dates through the same shared risk engine. A separate diagnostic compares later feature distributions with training data, following the reviewed ML-for-trading material.

The September 26 experiment failed its profitability and sample-size screen. It remains an offline command-line research tool; it is not an available UI candidate or an activated ML Flow. Training and reproduction commands, all six selection outcomes, later-period losses and verification evidence are in the report. No final reserved sessions were used.

The user-requested [12-configuration follow-up](ml-walkforward-search-2026-09-26.md) adds an offline runner that retrains each configuration across three chronological folds, selects thresholds using earlier calibration periods and preserves every outcome. The strongest candidate is positive in two of three later periods, but none passes all development requirements. Cached labels are refused if the shared risk/cost implementation has changed. The reserved final period and live controls remain untouched.

The subsequent [prediction-quality experiment](ml-prediction-improvement-2026-09-26.md) tests option-direction-aligned inputs, recent training windows, overlap-aware weights and separately fitted expected-payoff calibration. It compares later prediction errors with the original model and simple mean forecasts, with trading rules fixed. Improvement is limited to one period and the prediction screen fails; no replacement model is promoted.

## Costs

The page now separates **Costs & limits → Historical test → Results → Sandbox & live**. The opening status shows the next action and the four capital limits. Detailed ledgers, fee overrides and reproducibility settings are expandable. Trading controls remain under Strategies; the global Live Mode badge does not override a Flow's explicit Sandbox mode.

Every run requires an explicit dated schedule. **Use Kotak Neo rates** loads an editable draft for Kotak Neo Trade API on Trade Free plans, scoped to **NSE options (NFO)**. Loading a draft makes no API mutation and does not enable trading. Saving it enables the existing managed capital profile; it does not approve or start live entries.

Verified on **2026-09-26** against [Kotak API brokerage](https://www.kotakneo.com/support/what-is-the-brokerage-for-using-neo-trade-api/) and the Options breakup in [Kotak's calculator](https://www.kotakneo.com/calculator/brokerage-calculator/):

| Item | Preset |
| --- | --- |
| API brokerage per order | ₹0 on Trade Free plans |
| NSE transaction charges plus IPFT | 0.03553% of premium turnover |
| SEBI | 0.0001% of turnover |
| GST | 18% of brokerage, exchange and SEBI charges |
| Stamp duty | 0.003% on buys |
| STT | 0.15% on sells |
| Adverse slippage | 10 basis points per side, **an editable planning assumption, not a Kotak rate** |

The calculator lists transaction charges as 0.0355299% and NSE options IPFT separately as ₹0.01/crore; the combined exchange field is 0.03553%. The preset starts on the verification date and requires the operator to choose its end date. This is not a historical fee table or a promise that rates will remain unchanged. Verify the actual plan, order estimate and contract note; BSE/MCX require their own verified assumptions. The UI uses ordinary percentages (18 means 18%); the API stores decimal fractions.

Required fields are `schedule_id`, `source`, `effective_from`, `effective_to`, `brokerage_per_order`, `exchange_rate`, `sebi_rate`, `gst_rate`, `stamp_buy_rate`, `stt_sell_rate`, and `slippage_bps`. Dates must cover the imported sessions. Rates are decimal fractions of turnover, so a 0.1% turnover rate is `0.001`. Slippage uses basis points, so 10 means 0.10%. Missing, nonfinite and negative values are refused. Explicit zero is accepted as a recorded assumption; it must not be used as a substitute for unknown rates.

Optional `exchange` and `broker` fields bind a schedule to a market and broker. Research refuses mismatched dataset contracts; managed admission refuses mismatched exchanges and live broker routes. The virtual Sandbox broker models the selected broker's costs. Existing unscoped custom schedules remain compatible. One profile currently stores one schedule: saving the NSE preset therefore blocks managed BSE/MCX entries instead of applying NSE fees to them.

For each filled order, brokerage is flat, exchange and SEBI fees apply to turnover, GST applies to brokerage plus exchange plus SEBI fees, and stamp duty applies on buy turnover or STT on sell turnover. The per-order total rounds to paise. Slippage affects both execution prices separately. Additional product-specific minimum/capped/tiered brokerage, expiry exercise taxes and tax regime changes within a dataset are not modelled; choose a compatible period and schedule or do not use that dataset for this screen. No partial-fill order-fee approximation is presented as actual fill evidence.

## Development, final holdout and release

The last 60 observed sessions stay outside development replay. Earlier sessions split chronologically 70% training and 30% exploratory out-of-sample (OOS). The headline metrics cover training; OOS has its own metrics and trade list. Stress replays OOS with 1.5 times brokerage and twice the slippage plus 10 basis points. The seeded 200-resample bootstrap samples session P&L blocks and reports the 5th/95th percentiles. Incomplete OOS outcomes suppress the bootstrap and unbounded-profit-factor/win-rate claims; known realized trades remain visible as partial evidence. Repeated candidate selection makes development OOS exploratory, not a final significance test.

A completed development run can be frozen. A separate final-test request copies that exact configuration and consumes its 60 holdout session dates transactionally before queueing. Consumed sessions cannot be reused after a cancellation, failure, restart, rename or changed candidate. Overlapping holdouts are refused. Previously consumed final sessions cannot become development data through an extended import, and previously exposed development dates cannot become a new final holdout through a shorter import. These controls are owner and underlying scoped; they do not claim to blind an operator to files they already possessed.

Each configuration binds dataset hash, parameters, fees, seed, risk-policy version, engine version and a SHA-256 fingerprint of the actual replay, dataset, cost and risk source. Changed source, including uncommitted edits, invalidates queued or frozen evaluations. Worker startup also verifies stored dataset integrity. Freezing preserves a candidate; it does not grant release approval.

Reports include net expectancy, profit factor, closed-trade drawdown, losing streak, win rate, exposure bars, deterministic trades, rejection counts, incomplete outcomes, OOS, stress and bootstrap summaries. Profit factor is unavailable with no losing trades, with a separate flag when positive winnings make it unbounded. No-trade expectancy/win rate are unavailable rather than zero.

### Forward qualification

On the same Research page, select a saved strategy and a completed sealed final run to enroll a campaign. The final screen must have at least 20 trades, positive net P&L and no incomplete outcomes. It is a screening reference: the forward campaign measures the exact saved strategy and linked Flow, and does not assert that arbitrary Flow logic is identical to a research candidate. Configure and run that Flow in Sandbox through its managed Strategy Module entry node.

Enrollment binds strategy rules, the Flow graph, relevant source files, pinned broker account, cost schedule and risk-policy version. Changing rules or assumptions requires a new campaign; the old history remains. Changing only the operational Sandbox/live switch or live enablement does not rewrite strategy rules. Entries must actually originate from the bound Flow execution, with its original graph snapshot, to count as evidence or use a release.

Each admitted paper trade is registered prospectively. Before submission the server records an authenticated broker quote with native market timestamp, bid/ask and sufficient depth. Filled order quantities and timestamps come automatically from durable managed-order records via the risk ledger; the UI cannot upload P&L or fabricate fills. BUY valuation is no better than the quoted ask and SELL no better than the bid, with adverse slippage and estimated per-order fees. Quotes must be at most five seconds old; quote-to-fill delay must be at most 30 seconds. Partial or unknown outcomes remain visible and must resolve; missing execution evidence cannot qualify.

Policy `forward-v1` requires **30 distinct forward trading sessions and 100 closed trades**, positive net expectancy, profit factor at least **1.2**, positive net P&L under doubled fees/slippage, and observed marked drawdown at most **15%**. Every registered trade must be accounted for, with no open positions, invalid evidence, risk breach or stale binding. Observed drawdown retains adverse marks even if prices recover; it cannot reconstruct price changes that the live observer never received. These thresholds are engineering release criteria and do not establish guaranteed profitability.

### Reviewed release

Review the campaign's executions and dated fee assumptions, then explicitly reconcile it with a reason. Sandbox fees remain modeled assumptions; no broker charges or contract-note reconciliation are claimed. Separately acknowledge and approve the evidence with a release reason. Both actions carry the exact displayed revision and evidence digest; a fill arriving during review requires a fresh review. Reconciliation also retries missing risk-ledger deliveries. A direct comparison against authoritative ledger revisions prevents a missed callback from leaving an outdated approval usable.

Approval is valid for seven days at most and binds the broker authentication epoch as well as the exact campaign version. A material login change, rule/source/account/cost change, risk pause, new paper trade or corrected evidence blocks further live entry pending review. Revocation is immediate. Existing daily live authorization, broker pinning, risk admission and protective-stop requirements remain independent. The release is checked at admission and immediately before actual entry submission. Protective exits bypass qualification failures.

Kotak login now persists its authenticated UCC alongside the token. Older stored sessions without that identity require a fresh broker login before campaign enrollment; changing configuration cannot relabel an old token as a different account. Account identifiers and tokens are hashed in campaign bindings, never exposed as credentials in qualification responses.

Approval does not set `live_enabled`, activate a Flow or send an order. A qualifying, approved campaign can pass the former permanent-denial gate once the existing operational live controls are deliberately enabled. Until then, the UI states the specific missing checks; no real forward result is implied by test fixtures.

## Official daily options history

Open **Research → Historical test → Daily options history** and select **Download NSE history** (or **Update NSE history**). No broker login, API key, upload or subscription is required for this public-source download. The same action is available by double-clicking **Update NSE Daily History.command** on macOS, or running `uv run python -m services.research.nse_download` from the project directory. The download starts with recent dates and checks every calendar date from 13 April 2020 through yesterday in India; it does not silently exclude special weekend trading sessions. Run Update again for new dates or to resume an interrupted download. Pause keeps completed files.

The card shows saved sessions, observed coverage, download progress, unavailable dates and validation failures. Its expandable view lists the prior session's most active NIFTY contracts. **Download latest NIFTY CSV** exports that day's observations, including untraded contracts marked `observed_trade=false`. Volume is a count of contracts; open interest is in underlying units. A daily close and a settlement price remain separate fields. A trade observation does not establish an executable quote or fill. Use only observations from a session strictly before the decision date; the snapshot service enforces this boundary and returns its age. It does not automatically change any existing Flow's entry rules.

Files are kept under the git-ignored `data/research/nse-daily/`: original exchange ZIPs in `raw/`, normalized daily JSON gzip files in `daily/`, and dated source URLs, SHA-256 hashes, validation counts and download state in `manifest.json`. Legacy exchange files are supported before 8 July 2024; later downloads use NSE's UDiFF format. Modern records retain exchange instrument identity, scheduled expiry and actual expiry so accelerated expiries do not collapse distinct contracts. Historical lot sizes absent from a legacy file remain unknown. Verified files are reused; damaged derived files are rebuilt from verified originals. Unavailable responses are cached for one day, and `--retry-missing` explicitly rechecks them. An unavailable date is not labelled a confirmed holiday. Access denial or rate limiting stops downloads without switching hosts. Transient network and server errors receive at most three attempts against the same URL, with increasing delay; an exhausted retry stops the batch for a later resume.

The downloader runs in a separate process with a single cross-process owner, bounded network prefetch, timeouts and download-size limits. It neither loads trading credentials nor imports broker/order modules. Closing the Research page does not stop it. The UI download controls and CSV export require a valid platform session. The original NSE source is [the derivatives reports page](https://www.nseindia.com/all-reports-derivatives). The third-party `sajal101agrawal/nse-options-last-5-years` archive is a sample cross-check only, not an automatic fallback; its processing code is not installed. No synthetic prices, Greeks, volume or open interest are created.

**Daily history is separate from intraday strategy qualification.** It supports daily liquidity/context analysis but cannot establish whether a five-minute entry, stop or target executed first. It is not added to the intraday dataset selector or used to approve a live release. NIFTY daily data does not fill the BSE SENSEX or MCX intraday-history gaps.

## Worker and storage

For the local desktop installation, [Start OpenAlgo.command](local-startup.md) starts both the app and the worker with the same `.env` and checks readiness. Stop cooperatively interrupts an active research job. The optional worker `--ready-file` argument is used by the supervisor and is not needed for manual operation.

Run the separate operating-system worker from the OpenAlgo project directory with the same environment/database as the web app:

```sh
.venv/bin/python -m services.research.worker
```

For one queued job and then exit:

```sh
.venv/bin/python -m services.research.worker --once
```

Requests never spawn a process, executor or thread. One database lease permits one worker per deployment. The lease lasts 120 seconds and renews during replay. Jobs are durable with explicit `queued`, `running`, `completed`, `failed`, `cancelled` and `interrupted` states. A replacement worker recovers stale running jobs as interrupted and never automatically replays consumed holdouts. Queued cancellation is immediate; running cancellation is checked periodically. Atomic database updates make an already committed cancellation win over a finishing worker, and an expired or replaced worker cannot commit final results. If no worker is online, the overview shows offline and queued work remains queued. At most ten jobs per owner may be active/queued, at most 5,000 run records are retained, and each replay stops at 5,000 completed trades with an incomplete outcome.

Tables use the normal `DATABASE_URL`, SQLAlchemy ORM, the shared engine factory and context-managed sessions. SQLite uses `NullPool`. Overview queries defer full datasets and reports; they return the latest 50 run summaries. No module retains market data in a process-wide cache. On shutdown the CLI releases its lease and disposes its engine. Administrative retention/archival is not supplied; preserve the session-use ledger when archiving, because deleting it removes holdout contamination protection.

## API summary

Responses use `{ "status": "success", "data": ... }`; invalid inputs return `{ "status": "error", "message": ... }`. All routes require the ordinary OpenAlgo login session and retain the application's CSRF protection.

| Method/path under `/strategy/api/research` | Result |
|---|---|
| `GET /` (without the trailing slash) | Dataset/run summaries, candidates, worker state and limits |
| `POST /datasets` | Immutable import; rows or CSV |
| `POST /runs` | Enqueue development with `dataset_id,candidate,parameters,costs,seed` |
| `GET /runs/<id>` | Owner-scoped configuration, status and report |
| `POST /runs/<id>/cancel` | Request durable cancellation |
| `POST /runs/<id>/freeze` | Freeze a completed, complete-outcome development version |
| `POST /runs/<id>/final-test` | Consume sealed sessions and enqueue exact frozen version |
| `GET /runs/<id>/release` | Associated campaigns, qualification and current release status |

| Method/path under `/strategy/api/qualification` | Result |
|---|---|
| `GET /` (without the trailing slash) | Owned campaigns, strategies and fixed policy |
| `POST /campaigns` | Enroll with `strategy_id,final_run_id` |
| `GET /campaigns/<id>` | Progress, execution evidence and review status |
| `POST /campaigns/<id>/reconcile` | Review with `reason,costs_confirmed,expected_revision,evidence_digest` |
| `POST /campaigns/<id>/approve` | Release with `reason,acknowledged,expected_revision,evidence_digest` |
| `POST /campaigns/<id>/revoke` | Revoke with `reason` |

Qualification requests are session authenticated, CSRF protected, limited to 64 KB and rate limited. There is no public quote or trade evidence upload endpoint. Storage is bounded to 20 campaigns per owner, 2,000 trades and 2,000 review audit records per campaign; reaching a bound blocks enrollment or further collection instead of silently dropping history. Qualification uses the existing execution lifecycle and requires no additional background worker.

Latest evidence: [240-session robustness tests, 26 September 2026](strategy-robustness-2026-09-26.md). The unchanged control lost in all four new periods and failed the criteria recorded before testing. Earlier implementation and candidate comparison: [corrected replay results](filtered-strategy-retest-2026-09-26.md).
# Conlan algorithm research additions (2026-09-27)

Two independent signal adapters are available as optional templates: SMA(5)-SMA(34) zero-cross and Bollinger(20, 2 sample standard deviations) reversal. They remain uninstalled until selected in Strategies → Available templates. Installation creates a stopped sandbox strategy and inactive Flow. Existing strategies are retained.

New RandomForest research jobs support a 5, 10 or 15-minute maximum holding time (default 15). The same horizon governs labels and replay exits. Training uses session-balanced average uniqueness weights. Reports include training feature importance, evaluation probability reliability, and Brier comparison against a training-only baseline. These are research diagnostics, not live qualification.

The independent offline component library is `services/research/conlan.py`. The reproducible study runner is `scripts/research_conlan_algorithms.py`; it requires explicit `--current-kotak-assumption`, reads the local store read-only, and does not update saved fees. It excludes protected final sessions, records input/source hashes and full evidence, and reports unavailable alternative revenue data explicitly. See [the results and limitations](conlan-algorithm-results-2026-09-27.md).
