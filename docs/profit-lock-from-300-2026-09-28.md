# Profit protection starting at INR300

New managed scalping entries and newly configured research runs default to
`one-lot-technical-profit-lock-v4`. The user selected a maximum giveback of INR300,
with no fixed profit ceiling.

| Highest observed executable gross profit | Gross profit protected by stop |
|---:|---:|
| Below INR300 | Original technical stop |
| INR300 | INR100 |
| INR600 | INR300 |
| INR900 | INR600 |
| INR1,000 | INR700 |
| INR1,200 | INR900 |
| INR1,500 | INR1,200 |
| INR3,000 | INR2,700 |

After the peak reaches INR300, the floor is `max(100, peak gross profit - 300)`.
It advances continuously between these examples, rather than waiting for the
next INR300 milestone. This keeps the giveback target within INR300. The stop
never falls after a retreat. The trigger price rounds upward to the contract
tick; modeled break-even after fees/slippage may tighten it further.

These amounts are positive gross profit, before charges. INR100 is not an
additional loss allowance. A stop trigger is not a guaranteed fill: gaps,
slippage, inadequate depth, stale quotes or broker failures can produce a worse
realized outcome. The holding deadline still exits the position.

## Integration and compatibility

- The fresh full-lot executable bid drives live/sandbox profit marks. LTP cannot
  inflate the earned floor. Kotak stop modifications retain durable intent,
  same-order verification and restart recovery.
- All-in initial risk, daily budget, consecutive-loss stop, drawdown pause,
  whole-lot admission and release checks remain in force.
- Explicit older recipes retain their original behavior, including v3's
  INR1,000-to-INR900 special floor. The v4 rule supersedes that special floor for
  new entries. Already protected positions cannot have their stops lowered.
- Earlier ML artifacts need qualification for the new recipe/source; changing
  defaults does not approve an old model for live execution.
- This change applies to managed scalping entries using this recipe. It does
  not rewrite arbitrary user-authored Flow exits or manually configured trades.

## Frozen historical comparison

Twenty replays used the same frozen signals, contracts, five development windows,
INR25,000 per independent window, 15-minute holding limit and 5-minute cooldown.
No training, parameter search or protected final-holdout replay was performed.
The previous v3 recipe reproduced every saved entry/exit identity and net P&L.

| Cost scenario | Previous v3 net P&L | New v4 net P&L | v4 trades | v4 win rate |
|---|---:|---:|---:|---:|
| Base | -INR2,555.90 | -INR2,466.07 | 37 | 32.43% |
| Stressed | -INR2,019.23 | -INR2,019.23 | 37 | 35.14% |

The base improvement is INR89.83; both scenarios remain loss-making. Costs can
change admission and exit paths, so the stress result is not evidence that
higher fees improve the same trades. This small exploratory sample cannot
establish a most profitable algorithm. Continuous trailing was selected because
it satisfies the requested giveback limit between milestones; it is not a new
signal model or a claim of predictive superiority.

Historical candles use observed opens/closes for ratcheting and conservative
stop-first handling. They cannot establish real executable depth or fills.
Full reports, input hashes, source hash and reproduction helper are under
`data/research/profit-lock300-comparison-2026-09-28/` and
`data/research/profit-lock300-verification-2026-09-28/`.

## Verification

- Broad regression run: 4,282 passed, 16 skipped and 1 expected failure; the only
  unexpected failure was a test expecting the former default artifact version.
  After updating that assertion and explicitly testing both recipe versions,
  all 98 affected backend tests passed, including ML artifact, bid pricing and
  broker stop/recovery coverage. No production fix was needed for that failure.
- All 61 affected frontend tests passed. TypeScript/Vite build and Ruff checks
  on changed Python modules/tests passed.
- Chrome UI check on an isolated research fixture confirmed the visible
  INR300-to-INR100, INR600-to-INR300, INR900-to-INR600 milestones, continuous
  INR300 giveback target, no fixed profit cap and fill-slippage explanation.
- Independent review found no production defect. Its version-parity test
  suggestion was implemented and passed. Twenty frozen replays completed with
  unchanged source/input fingerprints and no incomplete outcomes.
