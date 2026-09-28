# Reproduce the frozen-signal comparison

From the implementation worktree, run:

```sh
PYTHONDONTWRITEBYTECODE=1 /Users/atanumridha/Documents/AlgoTrading/openalgo/.venv/bin/python data/research/risk-profit-verification-2026-09-28/run_comparison.py
```

The default input root is the immutable primary checkout at `/Users/atanumridha/Documents/AlgoTrading/openalgo`; `--primary` changes it. The default output is this worktree's `data/research/risk-profit-comparison-2026-09-28`; `--output` can select a new directory. A rerun deterministically replaces only the helper's named reports, README and manifest in that output directory. Original datasets, models, earlier reports and sealed final sessions are never written.

Run after implementation changes settle. The helper records source fingerprints at start and finish, checks immutable input hashes again at the end, and marks `rerun_required_source_changed` when implementation files changed during the run. A final release comparison must also match the final implementation hash.

The process disables dotenv before importing application modules and directs all database and log paths into its own temporary directory. It invokes pure replay only; it does not invoke fitting, qualification, broker actions or pytest.

Thirty reports compare five independent development windows, three variants and two fixed fee scenarios. The old-profit-v2 baseline must reproduce every saved trade entry/exit identity and net result plus the known aggregate totals. New-policy reports independently audit all-in entry caps, the fixed daily baseline and nonrefilling daily allowance. A synthetic check proves the ATR input excludes the current bar; runtime overlay assertions preserve the baseline stop floor.

The 2ATR variant exists only as a process-local research overlay. It uses the ten true ranges from eleven contiguous, already-completed option minute bars, resets each session and excludes the current bar even when evaluating its close. It activates after gross profit reaches 600 at an observed open/close, then only tightens the production-v3 stop. Full approximation details and limitations are saved with results. If no trade activates it, equality of results says nothing about its usefulness.
