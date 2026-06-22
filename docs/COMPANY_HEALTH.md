# Company Health & RSU Decisions

When a large share of your net worth rides on one employer — paycheck, bonus,
401(k) match in company stock, vesting RSUs, and often a pension — that company's
health is a **retirement-planning input**, not a side hobby. `engine/company_health.py`
turns public data on your configured ticker into a few decision-oriented signals.

## What it pulls (free, no API keys)
| Source | What it gives you |
|---|---|
| Yahoo Finance (`yfinance`) | Price, YTD / 1-yr return, forward P/E, dividend yield, analyst consensus target + implied upside |
| SEC EDGAR (`edgartools`) | Form 4 open-market insider buys/sells (sentiment), 8-K material events, Form 144 planned sales (overhang) |
| Your config | Employer-stock exposure as a % of investable assets vs. your watch/trim thresholds |

## The four signals
1. **Valuation & momentum** — is the stock cheap/expensive and trending up or down?
2. **Insider sentiment** — executives rarely buy their own stock unless they're
   optimistic; clustered C-suite selling is worth watching.
3. **Event risk** — recent 8-Ks and a spike in Form 144 planned sales can flag
   overhang before it shows up in the price.
4. **Concentration verdict** — `OK` / `WATCH` / `TRIM` based on your thresholds,
   with a concrete dollar figure to trim if you're over.

## How it informs RSU decisions
Each time RSUs vest you choose: hold or diversify. The monitor gives you a
repeatable basis for that call —

- **TRIM verdict** → sell vesting RSUs first (highest basis, least tax friction)
  to get exposure back under your trim threshold.
- **WATCH verdict** → direct new vests into diversified funds rather than holding.
- **OK verdict** → holding the vest is within tolerance.

Configure it in `config.json`:
```json
"employer_stock": {
  "employer_name": "Your Employer",
  "ticker": "TICKER",
  "watch_threshold_pct": 5.0,
  "trim_threshold_pct": 7.0,
  "holdings": { "employer_stock_in_401k": 0, "unvested_rsu_value": 0, "vested_shares_value": 0 }
}
```

SEC EDGAR requires a contact identity string (`"Your Name you@example.com"`).
Set it as `employer_stock.sec_identity` (or `sec_identity` at the top level).

## Run it
```bash
python3 engine/company_health.py                 # uses your config ticker
python3 engine/company_health.py --ticker MSFT   # any public company
python3 engine/company_health.py --days 30 --json health.json
```

> Monitoring aid only — not a buy/sell recommendation. See `DISCLAIMER.md`.
