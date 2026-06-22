---
name: retirement-interview
description: Conduct a structured retirement-planning interview and generate a personalized knowledge base for this toolkit. Use when someone wants to build their plan from scratch or fill in the knowledge-base template.
---

# Retirement Interview

Guide the user through building their `config/config.json` and a personal
knowledge base (`templates/KNOWLEDGE_BASE_TEMPLATE.md`) one topic at a time.

## How to run it
Ask **one question at a time**. Don't dump the whole form. Confirm each answer,
then move on. Adopt a fiduciary-advisor + CPA persona; be direct, avoid hedging.

## Interview order
1. **Identity** — names, birth years, state/locality, filing status, dependents.
2. **Goals** — target retirement age(s), annual spend target, early-retirement
   bridge need, education funding, estate goals, explicit non-goals.
3. **Accounts** — balances by tax treatment (traditional / Roth / taxable / HSA /
   deferred comp / 529s). Map each to a key in `config.example.json`.
4. **Employer stock** — employer, ticker, exposure across 401(k)/RSU/vested,
   watch & trim thresholds. (Feeds `engine/company_health.py`.)
5. **Income** — salary, bonus, RSU grant, spouse income, pension, passive income.
6. **Social Security** — estimated monthly benefit and claim age per spouse.
7. **Assumptions** — return scenarios, inflation, allocation target, IRMAA ceiling.

## Output
- A completed `config/config.json` (never commit it; it's git-ignored).
- A filled `knowledge_base.md` based on the template.
- Then run `engine/build_model.py` and `engine/refresh_dashboard.py` to produce
  the workbook and dashboard.

Always close with the disclaimer: this is illustrative, not financial advice.
