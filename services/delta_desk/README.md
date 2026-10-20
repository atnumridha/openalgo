# Native Delta scalper desk

Open **Strategies → Delta AI scalper** (`/strategy/delta-scalper`). The page uses
OpenAlgo's React UI, authenticated session and CSRF-protected paper controls.
It talks to the already installed controller through a private JSON-lines child
using that controller's Python environment. Streamlit is not required for this
page; the controller and ledger are shared with its CLI and Streamlit desk.

## Server configuration

Set `DELTA_SCALPER_OWNER` to the owning OpenAlgo username before starting the app.
An absent owner binding fails closed; another user cannot read or control the
shared local account. Optional server-only settings:

- `DELTA_SCALPER_HOME`: defaults to `~/.codex/skills/delta-scalper`.
- `DELTA_SCALPER_STATE`: defaults to `~/.local/state/delta-scalper`.

Keep the established state directory. A new directory is not a way to reset
losses, pauses or position ownership. The controller must already be installed
with its `.venv/bin/python` and account-derived paper balance. No API credentials
are accepted by these routes or inherited from the web process.

## Operation

The initial profile is Historical. Choose Codex or local Ollama, model, reasoning,
AI-directed or EMA-filter mode, and continuous or timed operation. Changes apply
on the next explicit Start. The current serving provider is shown separately.
Opening the page starts observation only. Existing controller locks prevent a
second process across profiles and frontends. Pause, resume and stop delegate to
the existing controller; stop is queued and requires verification of stopped,
flat and zero unresolved intents. Manual and daily halts remain authoritative.

OpenAlgo's global Analyze/Live mode has no effect on these controls: the bridge
supports **paper only**. Live readiness is informational. Production execution
continues to require the scalper CLI, current-build testnet qualification and
explicit arming. FYERS and other stock strategies keep their own risk/execution
systems.

Account monitoring uses the installed GET-only Delta observer. Live P&L covers
all USD-settled account activity for the current India day; paper uses its own
ledger. The UI never adds these results together. INR uses 85 per USD. Stale or
unreconciled account net is unavailable. Completed-candle freshness is checked
separately from successful network polling. Paper equity uses its own India day.

The **Live / paper P&L** tab (`/strategy/delta-scalper?tab=pnl`) groups actual
Delta fills into flat-to-flat trades. It shows gross P&L, entry/exit fees including
GST, funding, net after full costs, and cash-wallet trading impact. Expand
**Details** for individual fills, maker/taker execution, order IDs, cash fees,
fee credits used and promotional awards. Currency defaults to INR; USD is
available. Promotional awards do not increase net P&L. Reversals allocate fees
by quantity. Prior-day entries, ambiguous fill sequences and unreconciled fees
leave full-trade net unavailable. Totals cover fully reconstructed closed trades;
unattributed wallet adjustments are shown separately. The enrichment runs only
inside the read-only helper and does not modify execution or the installed engine.

The Models & training view reads completed three-symbol evidence. Reference
agreement is not win rate. A trained model must have passing evaluation evidence
and match the evaluated digest before selection. The original `deepseek-r1:1.5b`
remains the previously approved experimental baseline. Training continues via
the installed offline Python workflow, requiring stopped, flat controllers; the
web page never starts a GPU training job alongside trading.

## Failure behavior

The bridge serializes requests, limits output, uses fixed operations and never
uses a shell or retries a mutation. If a control times out, refresh status before
retrying because the controller may have accepted it. A web-process restart
ends the observation helper; the separate Delta controller remains owned by its
existing locks and lifecycle. No automatic controller restart is introduced.

## Verification

Run backend tests with the repository interpreter and a valid log format:

```sh
LOG_FORMAT='%(message)s' python -m pytest test/delta_desk -q
```

Run the Delta React tests and build with Node supported by `frontend/package.json`.
Both the installed Python runtime and read-only live feeds should be verified
on the deployment host. Do not use real control buttons merely to smoke-test a
running strategy; lifecycle behavior is tested through isolated test doubles.
