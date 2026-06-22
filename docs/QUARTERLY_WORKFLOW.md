# Quarterly Workflow

A repeatable rhythm to keep the plan current.

## Each quarter
1. Copy `templates/quarterly_input_TEMPLATE.json` → `quarterly_input_Q#_YYYY.json`.
2. Fill in new account balances from your statements (leave `null` to keep prior).
3. Update `employer_stock_holdings` so the concentration check stays accurate.
4. Run the pipeline:
   ```bash
   RPT_CONFIG=config/config.json \
   python3 engine/quarterly_update.py --input quarterly_input_Q3_2026.json
   ```
   This rebuilds the workbook, runs a 10,000-path Monte Carlo across three return
   scenarios, stamps the success rates into the model, and refreshes the dashboard.
5. Run the company-health check and review the RSU/concentration verdict:
   ```bash
   python3 engine/company_health.py
   ```
6. Skim the dashboard (`dashboard/dashboard.html`) and update your knowledge base
   if anything material changed.

## Annually
- Refresh tax brackets, contribution limits, and IRMAA thresholds in `config.json`.
- Re-verify Social Security estimates and pension survivor election.
- Full re-read of the knowledge base; reset its "Last reviewed" date.

## Safety
- `config/config.json` and all `quarterly_input_Q*.json` files are git-ignored.
- Never commit statements or anything with real balances. The `.gitignore` is set
  up to block them, but check `git status` before every commit.
