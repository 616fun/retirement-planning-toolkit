# [Your Name] — Retirement Planning Knowledge Base

> This is the heart of the toolkit. It's a structured brief you keep beside your
> numbers so an AI assistant (or future you) instantly has the full context to
> reason about your plan. Fill in the brackets, delete what doesn't apply, add
> what's missing. Keep it in sync with your config and spreadsheet.
>
> **Do not commit a filled-in copy to a public repo** — this file holds personal
> data. Keep your real version local (it's git-ignored as `CLAUDE.md` or
> `knowledge_base.md`).

**Last reviewed**: [date] | **Source of truth for figures**: `model/financial_plan.xlsx`

---

## 1. Identity & Household
- Names / ages / birth years: [...]
- Location & relevant tax jurisdiction: [state, county, flat vs. graduated tax]
- Dependents (kids in college, parents, etc.): [...]
- Target retirement age(s) and date(s): [...]

## 2. Goals & Vision
- Target retirement spend (annual, today's dollars): [...]
- Bridge strategy for the pre-59½ gap, if retiring early: [...]
- Education funding goals (529s): [...]
- Estate / legacy goals: [...]
- Explicit non-goals / things you will NOT do: [...]

## 3. Financial Snapshot (approximate — defer to the spreadsheet)
- Investable total and rough split (traditional / Roth / taxable): [...]
- Real estate: [...]
- Income floor in retirement (pension, Social Security, passive): [...]
- Current household income: [...]

## 4. Employer Stock & Concentration
- Employer, ticker, and why it matters (salary + RSUs + 401(k) + pension all tied to it?): [...]
- Current concentration % and your watch/trim thresholds: [...]
- RSU vesting schedule and your default action on vest (hold vs. diversify): [...]
- See `engine/company_health.py` — this section is what those signals inform.

## 5. Core Strategy
- Asset allocation target (e.g., 65/35 glide path): [...]
- Account-location strategy (what goes where for tax efficiency): [...]
- Roth conversion plan and the bracket/IRMAA ceiling you're managing to: [...]
- Withdrawal sequencing: [...]

## 6. Tax Profile
- Filing status, bracket, state specifics: [...]
- Key constraints you watch (IRMAA, SALT, contribution limits): [...]

## 7. Estate Planning Status
- Wills / POA / healthcare directives: [done? pending?]
- Trust status and beneficiary audit: [...]

## 8. Open Loops & Unresolved Questions
- [Decisions you keep circling back to — list them so they don't get lost.]

## 9. Communication Preferences (how you want the AI to respond)
- Tone, format (tables vs. prose), level of detail, expert persona to adopt: [...]

## 10. Maintenance Protocol
- When numbers change → update config + this file + rerun quarterly_update.py.
- Review cadence (e.g., quarterly + annual full review): [...]
