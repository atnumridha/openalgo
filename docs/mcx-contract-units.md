# MCX contract money units

Verified 28 September 2026 for the Kotak master schema used by this deployment.
Broker quantities are unchanged. Monetary value is `quote × quantity × factor`.
The quantity multiplier is applied once to premiums, price-stop risk, realized
and unrealized P&L, modeled turnover fees and profit floors. Price triggers stay
in exchange quotation units; order and depth quantities stay in physical units.

| Contract | Kotak master lot quantity | Quote basis | Rupees per one-point move per lot | Factor |
| --- | ---: | --- | ---: | ---: |
| GOLDM | 100 grams | per 10 grams | 10 | 0.1 |
| CRUDEOILM | 10 barrels | per barrel | 10 | 1 |
| SILVERM | 5 kilograms | per kilogram | 5 | 1 |
| NATGASMINI | 250 MMBtu | per MMBtu | 250 | 1 |

Official MCX option specifications:
[GOLDM](https://www.mcxindia.com/docs/default-source/options/gold-mini-%28100-grams%29-options-march-2026-contract-onwardsb02f614857fb64e3bdfdff00007acb35.pdf),
[CRUDEOILM](https://www.mcxindia.com/docs/default-source/products/contract-specification/crudeoil-mini-options/crude-oil-mini-%2810-barrels%29-options-march-2026-contract-onwards.pdf),
[SILVERM](https://www.mcxindia.com/docs/default-source/options/silver-mini-%285-kilograms%29-options-february-2026-contract-onwards7826ba40-8dcd-490c-8354-f68798ca6f63.pdf),
[NATGASMINI](https://www.mcxindia.com/docs/default-source/products/contract-specification/natural-gas-mini-option/natural-gas-mini-%28250-mmbtu%29-options-march-2026-contract-onwards.pdf).

The PDFs describe the underlying quotation basis. The GOLDM option-premium
factor is additionally inferred from the official
[MCX turnover table](https://www.mcxindia.com/market-data/most-active-puts-calls)
for 25 September 2026: GOLDM 150000 PE had 2,643,784 lots, notional turnover
39,691,017.53 lakh and premium turnover 34,255.51 lakh.
`(notional - premium) × 100000 / (volume × strike) = 10.000000509` quote units
per contract. MCX's [turnover definition](https://beta.mcxindia.com/market-operations/trading-surveillance/reports/disclosure-of-open-interest-and-turnover-for-various-categories-of-market-participants)
uses strike plus premium for option notional turnover. This corroborates ten
quote units per 100-gram contract. The
[Dhan GOLDM options page](https://dhan.co/commodity/gold-mini-options-summary/)
independently displays a market lot of ten quote units.

[Kotak quantity guidance](https://www.kotakneo.com/support/facing-issue-with-order-quantity-lot-size-what-do-i-do/)
states that order quantity equals contracts times the master lot size. Never
replace Kotak's physical order quantity with monetary quantity.

Only these four roots are admitted by the managed capital policy. Unsupported
MCX symbols, inconsistent master lots, missing valuation metadata or conflicting
snapshot multipliers remain blocked. Contract discovery alone is not admission.
The additive migration is limited to Kotak `mcx_fo` rows with validated lots.
Re-downloads preserve the verified factor. A future contract-unit change requires
new verification and regression tests; a changed lot must not silently trade.

Example: one GOLDM option lot at 100 costs ₹1,000 before charges; a 30-point
stop represents ₹300 gross risk. At price 130 the gross profit is ₹300 and the
profit stop protects ₹100 (stop price 110); at 160 it protects ₹300 (130);
at 190 it protects ₹600 (160). Exchange ticks and actual fills can change realized
amounts. The ₹300 trade risk, ₹2,000 daily limit, loss-streak stop, mode authorization,
spread/depth checks and broker protective-order checks remain in force.
