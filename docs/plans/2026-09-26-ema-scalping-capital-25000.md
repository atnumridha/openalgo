# EMA scalping capital amendment — user requested INR25,000

Registered after reviewing the original INR10,000 study, before examining results with the new capital filter. This is a follow-up development comparison, not a new independent holdout.

- Keep every signal, source date, contract-selection rule, 1:2 index bracket, holding time, cost and execution assumption in `2026-09-26-ema-scalping-evaluation.md` unchanged.
- Increase the initial capital assumption to INR25,000, with the same 20% cash buffer: one-lot premium plus entry charges must fit INR20,000.
- Rerun all twelve registered variants and the main-variant option audit. Compare with the original INR8,000 available-premium subset. Do not choose different signals or tune parameters after viewing returns.
- Keep existing live capital/configuration and risk allowances unchanged. INR1,000 first-trade loss budget, another INR1,000 shared by later trades, INR2,000 daily cap were not increased by this user request.
- This counterfactual option audit still does not implement a portfolio, guarantee a premium loss cap from an underlying-index stop, or prove a net 1:2 payoff. Explicitly disclose losses exceeding the intended per-trade budget. Raising research capital does not authorize live activation.
- Correct two review findings without changing trades: retain unresolved index attempts in option-availability denominators; report day-block confidence intervals as unavailable where there are fewer than two complete five-day blocks (fewer than ten represented days).
