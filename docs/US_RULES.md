# US tax rules encoded in `engine/tax_us.py`

This documents the figures and modelling choices behind the federal tax engine
and the Roth-conversion ladder optimizer. **Illustrative, not tax advice — verify
against the IRS and your state.** All bracket/threshold figures index forward from
the base year by the configured inflation rate.

**Compiled:** June 2026 (base tax year 2026).
**Convention:** Every figure table carries a *Source* column and the tax year it
applies to. Authorities: the **IRS** (federal brackets, standard deduction, RMD
tables) and **CMS** (IRMAA). Statute is cited where a rule originates in an Act
(SECURE 2.0, OBBBA).

> **Sourcing note.** The dollar figures below are the 2026 values the engine
> ships with, taken from the planning model they were built for. Tax-year dollar
> amounts (bracket edges, the standard deduction, and especially the IRMAA
> surcharge dollars) are released annually and should be confirmed against the
> primary IRS/CMS publication for the year you run. Figures that warrant an
> independent check before you rely on them are flagged **⚠ VERIFY**. The
> primary-source URLs are listed at the bottom. The engine indexes these forward
> by your `inflation_rate`, which is an approximation of the real annual IRS/CMS
> indexation — another reason the **relative** strategy comparison is more robust
> than any absolute tax figure.

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

`FEDERAL_BRACKETS_MFJ`, taxable income (AGI − standard deduction). The seven-rate
structure (10/12/22/24/32/35/37%) was made **permanent** by the One Big Beautiful
Bill Act (OBBBA, P.L. 119-21, 2025); the dollar edges are the IRS annual
inflation-adjusted figures.

| Rate | Bracket top (taxable) | Applies to | Source |
|---|---|---|---|
| 10% | $24,800 | 2026 | IRS annual inflation adjustment ⚠ VERIFY |
| 12% | $100,800 | 2026 | IRS annual inflation adjustment ⚠ VERIFY |
| 22% | $211,400 | 2026 | IRS annual inflation adjustment ⚠ VERIFY |
| 24% | $403,550 | 2026 | IRS annual inflation adjustment ⚠ VERIFY |
| 32% | $512,450 | 2026 | IRS annual inflation adjustment ⚠ VERIFY |
| 35% | $768,700 | 2026 | IRS annual inflation adjustment ⚠ VERIFY |
| 37% | above | 2026 | rate permanent (OBBBA, P.L. 119-21) |

- **Standard deduction (MFJ):** **$32,200** for 2026 (IRS annual inflation
  adjustment; the increased base was set by OBBBA) — ⚠ VERIFY against the IRS
  Rev. Proc. for the year. Config `assumptions.standard_deduction_mfj` is
  authoritative at runtime.
- **Social Security:** modelled as **85% taxable** federally — the statutory cap
  (IRC §86) that applies to higher-income households. The engine does not model
  the lower 0%/50% inclusion tiers.

> ⚠ **VERIFY the bracket edges and standard deduction each year.** The IRS
> publishes the inflation-adjusted figures in a Revenue Procedure in the autumn
> before the tax year (e.g. the 2026 figures in a late-2025 Rev. Proc.). Confirm
> against that document before relying on absolute tax numbers.

## IRMAA — Medicare premium surcharge, MFJ 2026 (CMS)

`IRMAA_MFJ`, **annual** surcharge **per person** (Part B + Part D combined). CMS
sets the MAGI tier floors and the per-tier premium add-ons annually (usually a
November release for the following year).

| MAGI floor (MFJ) | Surcharge / person / yr | Applies to | Source |
|---|---|---|---|
| ≤ $218,000 | $0 | 2026 | CMS IRMAA release |
| $218,000 | $1,143 | 2026 | CMS IRMAA release ⚠ VERIFY |
| $274,000 | $2,867 | 2026 | CMS IRMAA release ⚠ VERIFY |
| $342,000 | $4,587 | 2026 | CMS IRMAA release ⚠ VERIFY |
| $410,000 | $6,306 | 2026 | CMS IRMAA release ⚠ VERIFY |
| > $750,000 | $6,879 | 2026 | CMS IRMAA release ⚠ VERIFY |

- **2-year lookback:** the surcharge in a given year is set by MAGI from **two
  calendar years prior** (`IRMAA_LOOKBACK_YEARS = 2`), and only once a spouse is
  enrolled in Medicare at **65** (`MEDICARE_AGE`). The optimizer applies both.
- The `$218,000` Tier-1 floor is the conversion ceiling the fill-to-bracket
  heuristic respects in the Medicare-lookback window.

> ⚠ **VERIFY the surcharge dollars and tier floors each year.** The per-person
> amounts above bundle the Part B and Part D add-ons; CMS publishes them
> separately and they move every year with the Part B premium. The top tier
> ($750k+) floor is fixed by statute and not indexed. Confirm against the CMS
> release for the applicable year — IRMAA is the single most material cliff in a
> conversion plan, so a stale figure here matters more than a stale bracket edge.

## RMDs — IRS Uniform Lifetime Table (2022+)

`_RMD_DIVISOR` in `build_model.py`. RMD = pre-tax balance ÷ divisor.

| Item | Value | Source |
|---|---|---|
| Divisor table | Uniform Lifetime Table, ages 73–100+ | IRS Pub. 590-B, Appendix B (final regs effective 2022) |
| Required beginning age, born 1951–1959 | 73 | SECURE 2.0 Act of 2022, §107 |
| Required beginning age, born 1960 or later | **75** | SECURE 2.0 Act of 2022, §107 |

- These divisors are stable (last revised for 2022) and not inflation-indexed, so
  no ⚠ VERIFY flag — but confirm the start age if a member's birth year sits on
  the 1959/1960 boundary.
- RMDs are modelled on the **pooled** pre-tax balance using spouse A's age — a
  simplification; in reality each spouse's RMD is computed on their own IRAs.

## The optimizer's objective

Total lifetime tax (what we minimize) =

> **PV**( Σ yearly [ federal + state/local + IRMAA ] ) **+** PV( terminal tax )

where the **terminal tax** is what heirs pay on the pre-tax balance still
standing at age 90, drawn down under the SECURE Act 10-year rule (SECURE Act of
2019, §401 — non-eligible designated beneficiaries) at `HEIR_MARGINAL_RATE`
(24% — an **assumption**, not a sourced figure: a planning rate for early-career
heirs). Roth dollars pass tax-free. Present-valuing at the inflation rate is what trades "pay
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

## Sources & primary references

Confirm dollar figures against these before relying on absolute tax numbers.
Each year's IRS Revenue Procedure and CMS IRMAA release supersede the values
shipped here.

| Topic | Primary source |
|---|---|
| Federal brackets + standard deduction (annual $ figures) | IRS annual inflation-adjustment Revenue Procedure — <https://www.irs.gov/newsroom> (search "inflation adjustments" for the tax year) |
| Bracket-rate permanence | One Big Beautiful Bill Act (OBBBA), P.L. 119-21 (2025) |
| Taxation of Social Security benefits (≤85%) | IRC §86; IRS Pub. 915 — <https://www.irs.gov/pub/irs-pdf/p915.pdf> |
| IRMAA tiers + Part B/D surcharges | CMS annual Medicare Part B/D premium release — <https://www.cms.gov/newsroom> (and Medicare.gov IRMAA pages) |
| RMD Uniform Lifetime Table | IRS Pub. 590-B, Appendix B — <https://www.irs.gov/pub/irs-pdf/p590b.pdf> |
| RMD beginning ages (73 / 75) | SECURE 2.0 Act of 2022, §107 (Div. T, Consolidated Appropriations Act 2023, P.L. 117-328) |
| Inherited-IRA 10-year rule | SECURE Act of 2019, §401 |

**⚠ VERIFY** tags above mark figures that are released annually and most warrant
an independent check: the IRMAA surcharge dollars and tier floors, and the
federal bracket edges + standard deduction for the run year.
