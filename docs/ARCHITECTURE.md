# Architecture

The toolkit is deliberately **config-driven**: there is no personal data in any
script. Everything flows from one JSON config, so pointing the whole system at a
different household is a one-file swap.

```
config/config.json  ─┐
                     ├─►  engine/config_loader.py  (single load point + derived math)
                     │
                     ├─►  engine/build_model.py        → model/financial_plan.xlsx
                     ├─►  engine/company_health.py      → live ticker health + RSU verdict
                     ├─►  engine/quarterly_update.py    → rebuild + Monte Carlo + dashboard
                     └─►  engine/refresh_dashboard.py   → dashboard/dashboard.html
```

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
| Year-by-Year Projections | Spend, income floor, portfolio draw, EOY balance to age ~90 |
| Monte Carlo | 3-scenario success rates (populated by quarterly_update.py) |
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
