# Architecture

The toolkit is deliberately **config-driven**: there is no personal data in any
script. Everything flows from one JSON config, so pointing the whole system at a
different household is a one-file swap.

```
config/config.json  ─┐
                     ├─►  engine/config_loader.py  (single load point + derived math)
                     │
                     ├─►  engine/simulate.py           (the shared year-by-year kernel)
                     │        ▲ used by build_model's Year-by-Year, Cash Flow,
                     │        │ and Roth-optimizer tabs; tax via engine/tax_us.py
                     ├─►  engine/build_model.py        → model/financial_plan.xlsx
                     ├─►  engine/company_health.py      → live ticker health + RSU verdict
                     ├─►  engine/quarterly_update.py    → rebuild + Monte Carlo + dashboard
                     └─►  engine/refresh_dashboard.py   → dashboard/dashboard.html
```

## The simulation kernel
`engine/simulate.py` is the **one** year-by-year projection. Given a config, a
return path, and a conversion policy, `simulate()` walks from today to the
horizon and emits a per-year **ledger** (income, AGI/MAGI, federal/state/IRMAA
tax, account-level withdrawals, balances) plus a **summary** (present-valued
lifetime tax, terminal heir tax, ending balances, solvency). The Year-by-Year
tab, the Cash Flow tab, and the Roth optimizer are all thin callers — so they
can never drift apart. (The Monte Carlo still uses its own vectorized path; it
migrates onto the kernel in a later phase.)

## Single source of truth
`config/config.json` holds identity, accounts, employer stock, income, Social
Security, and assumptions. Inside the **spreadsheet**, the `Assumptions` tab plays
the same role: every other tab links back to it with cross-sheet formulas instead
of hardcoding values. When you add a value, put it in `Assumptions` and link to it.

## Spreadsheet tabs (built by build_model.py)
| Tab | Purpose |
|---|---|
| Assumptions | Master inputs — returns, inflation, taxes, ages, SS, brackets |
| Net Worth Snapshot | All account balances + total + investable |
| Income Streams | Salary, bonus, RSU, pension, passive |
| Employer Concentration | Employer-stock exposure vs. watch/trim thresholds |
| Year-by-Year Projections | After-tax baseline (RMD-only) from the kernel — spend, income floor, tax, portfolio draw, EOY balance to age ~90 |
| Cash Flow | Detailed after-tax ledger from the kernel — every income source, AGI/MAGI, federal/state/IRMAA/cap-gains/NIIT tax, ACA subsidy, per-account withdrawals, and running pre-tax / Roth / taxable balances |
| Monte Carlo | 3-scenario success rates (populated by quarterly_update.py) |
| Roth Conversion Ladder | Lifetime-tax optimizer (`engine/tax_us.py`) — do-nothing vs. fill-to-bracket heuristic vs. optimal target, with a year-by-year schedule |
| Action Plan | Open items and recurring checks |

## Cell color convention
- **Green** text = cross-sheet link (`=Assumptions!C5`)
- **Black** text = intra-sheet formula
- **Blue** text = hardcoded input

## De-identification model
Because identity lives only in config and the git-ignored data files, sharing the
code is safe by construction. The `.gitignore` blocks `config/config.json`,
generated `model/` + `dashboard/` artifacts, statements, and anything matching
`*credentials*` or `.env`.
