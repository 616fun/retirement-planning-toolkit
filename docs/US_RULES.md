# US tax rules encoded in `engine/tax_us.py`

This documents the figures and modelling choices behind the federal tax engine
and the Roth-conversion ladder optimizer. **Illustrative, not tax advice — verify
against the IRS and your state.** All bracket/threshold figures index forward from
the base year by the configured inflation rate.

## The hybrid state-tax design (why we don't encode 50 states)

US state tax is a far larger and more idiosyncratic surface than the federal
system: 9 states levy no income tax, ~11 are flat, and ~31 (plus DC) are
progressive — each with its **own** retirement-income rules (whether Social
Security is taxed, pension/age exclusions, AGI add-backs). Encoding all of that
accurately, and re-indexing it every year, is a maintenance trap that produces
confident-but-wrong numbers. A Roth-conversion decision is dominated by the
**federal** marginal rate and the **IRMAA** cliff; state tax is a near-flat
additive layer on top. So the engine is deliberately hybrid:

| Layer | How it's modelled |
|---|---|
| **Federal** | Full — progressive MFJ brackets, standard deduction, IRMAA cascade |
| **State (default)** | A flat effective rate: `household.state_income_tax_rate` + `household.local_income_tax_rate` |
| **State (optional)** | Supply `household.state_brackets` to model a progressive state precisely |

The flat default is **exactly right** for the 9 no-income-tax states (set the
rate to 0) and the flat-tax states (e.g. Indiana ≈ 3.0%), and a defensible
marginal approximation everywhere else. **Fold any state retirement break (SS
exclusion, pension exclusion, age deduction) into your effective rate.**

### Optional progressive state brackets

Add to the `household` block (bounds are upper-edges; last is `null` for the
open top bracket; rates index with inflation):

```json
"household": {
  "state_income_tax_rate": 0.0,
  "local_income_tax_rate": 0.0,
  "state_brackets": [[0.02, 50000], [0.05, 100000], [0.07, null]]
}
```

When `state_brackets` is present it **replaces** the flat `state_income_tax_rate`
(the local rate is still applied on top). Social Security is excluded from the
state base by default.

## Federal — MFJ, 2026 (OBBBA)

`FEDERAL_BRACKETS_MFJ`, taxable income (AGI − standard deduction):

| Rate | Bracket top (taxable) |
|---|---|
| 10% | $24,800 |
| 12% | $100,800 |
| 22% | $211,400 |
| 24% | $403,550 |
| 32% | $512,450 |
| 35% | $768,700 |
| 37% | above |

- **Standard deduction (MFJ):** $32,200 (config `assumptions.standard_deduction_mfj` is authoritative).
- **Social Security:** modelled as **85% taxable** federally (the cap that applies to higher-income households).

## IRMAA — Medicare premium surcharge, MFJ 2026 (CMS)

`IRMAA_MFJ`, **annual** surcharge **per person** (Part B + Part D combined):

| MAGI floor (MFJ) | Surcharge / person / yr |
|---|---|
| ≤ $218,000 | $0 |
| $218,000 | $1,143 |
| $274,000 | $2,867 |
| $342,000 | $4,587 |
| $410,000 | $6,306 |
| > $750,000 | $6,879 |

- **2-year lookback:** the surcharge in a given year is set by MAGI from **two
  calendar years prior** (`IRMAA_LOOKBACK_YEARS = 2`), and only once a spouse is
  enrolled in Medicare at **65** (`MEDICARE_AGE`). The optimizer applies both.
- The `$218,000` Tier-1 floor is the conversion ceiling the fill-to-bracket
  heuristic respects in the Medicare-lookback window.

## RMDs — IRS Uniform Lifetime Table (2022+)

`_RMD_DIVISOR` in `build_model.py`. RMD = pre-tax balance ÷ divisor.

- **Required beginning age (SECURE 2.0):** 73 for those born 1951–1959, **75 for
  those born 1960 or later** (`rmd_start_age`).
- RMDs are modelled on the **pooled** pre-tax balance using spouse A's age — a
  simplification; in reality each spouse's RMD is computed on their own IRAs.

## The optimizer's objective

Total lifetime tax (what we minimize) =

> **PV**( Σ yearly [ federal + state/local + IRMAA ] ) **+** PV( terminal tax )

where the **terminal tax** is what heirs pay on the pre-tax balance still
standing at age 90, drawn down under the SECURE Act 10-year rule at
`HEIR_MARGINAL_RATE` (24% — a planning figure for early-career heirs). Roth
dollars pass tax-free. Present-valuing at the inflation rate is what trades "pay
tax now at known rates" against "defer and face RMD-driven tax, IRMAA, and heir
tax later" — producing an **interior** optimum rather than "convert everything
immediately."

Three strategies are compared in the **Roth Conversion Ladder** tab:

1. **Do nothing** — RMDs only (baseline).
2. **Fill to top of 22% bracket** — the readable heuristic, capped at the IRMAA
   Tier-1 line inside the Medicare lookback window.
3. **Lifetime-tax optimal** — grid-searches the level real AGI ceiling that
   minimizes total lifetime tax, subject to solvency.

## Not modelled (by design)

NIIT (3.8%), capital-gains preferential rates, AMT, the QBI deduction,
per-state retirement-income exclusions, and spousal IRA splitting. These are
either second-order for a conversion decision or state-idiosyncratic. Keep them
in mind when reading the absolute tax figures — the **relative** comparison
between strategies is the robust output.
