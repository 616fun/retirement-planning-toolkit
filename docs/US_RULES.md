# US tax rules encoded in `engine/tax_us.py`

This documents the figures and modelling choices behind the federal tax engine
and the Roth-conversion ladder optimizer. **Illustrative, not tax advice — verify
against the IRS and your state.** All bracket/threshold figures index forward from
the base year by the configured inflation rate.

**Compiled:** June 2026 (base tax year 2026).
**Last verified:** 2026-06-30 — federal brackets, standard deductions, and IRMAA
MAGI floors (MFJ + single) confirmed against IRS Rev. Proc. 2025-32 and the CMS
2026 IRMAA fact sheet (released 2025-11-14); LTCG breakpoints, IRMAA surcharge
dollars, and the ACA FPL base were **corrected** in this pass (they were carrying
stale 2024–2025 values). ✓ marks a figure confirmed against its primary source
this cycle; ⚠ VERIFY marks one still to re-confirm next year.
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
| 10% | $24,800 | 2026 | Rev. Proc. 2025-32 ✓ |
| 12% | $100,800 | 2026 | Rev. Proc. 2025-32 ✓ |
| 22% | $211,400 | 2026 | Rev. Proc. 2025-32 ✓ |
| 24% | $403,550 | 2026 | Rev. Proc. 2025-32 ✓ |
| 32% | $512,450 | 2026 | Rev. Proc. 2025-32 ✓ |
| 35% | $768,700 | 2026 | Rev. Proc. 2025-32 ✓ |
| 37% | above | 2026 | rate permanent (OBBBA, P.L. 119-21) |

- **Standard deduction (MFJ):** **$32,200** for 2026 (IRS Rev. Proc. 2025-32;
  the increased base was set by OBBBA) — ✓ verified 2026-06-30. Config
  `assumptions.standard_deduction_mfj` is authoritative at runtime.
- **Social Security:** modelled as **85% taxable** federally — the statutory cap
  (IRC §86) that applies to higher-income households. The engine does not model
  the lower 0%/50% inclusion tiers.

> ⚠ **VERIFY the bracket edges and standard deduction each year.** The IRS
> publishes the inflation-adjusted figures in a Revenue Procedure in the autumn
> before the tax year (e.g. the 2026 figures in a late-2025 Rev. Proc.). Confirm
> against that document before relying on absolute tax numbers.

## Single filer (one-member household), 2026

The engine taxes a **one-member** household as **single** and a two-member
household as **MFJ** (`tax_us.normalize_status`; the kernel passes the status
through every tax call). All single figures below are the 2026 counterparts of
the MFJ tables above; ✓ = confirmed against Rev. Proc. 2025-32 / CMS 2026 on
2026-06-30.

| Item | Single value | Relationship to MFJ | Constant |
|---|---|---|---|
| 10% bracket top (taxable) | $12,400 | exactly ½ MFJ | `FEDERAL_BRACKETS_SINGLE` ✓ |
| 12% bracket top | $50,400 | exactly ½ MFJ | ✓ |
| 22% bracket top | $105,700 | exactly ½ MFJ | ✓ |
| 24% bracket top | $201,775 | exactly ½ MFJ | ✓ |
| 32% bracket top | $256,225 | exactly ½ MFJ | ✓ |
| 35% bracket top | $640,600 | **not** ½ MFJ (single top is lower) | ✓ |
| Standard deduction | $16,100 | exactly ½ MFJ | `STANDARD_DEDUCTION_SINGLE` ✓ |
| IRMAA Tier 1–4 floors | $109k / $137k / $171k / $205k | exactly ½ MFJ | `IRMAA_SINGLE` ✓ |
| IRMAA top floor | $500,000 | **not** ½ MFJ ($750k) | ✓ |
| IRMAA surcharge $/person | identical to MFJ | per-enrollee, status-independent | `IRMAA_SINGLE` |
| SS §86 provisional bases | $25,000 / $34,000 | statutory, not indexed | `SS_PI_BASE1/2_SINGLE` |
| LTCG 0% / 15% tops | $49,450 / $545,500 | 0% ≈ ½ MFJ; 15% not | `CAP_GAINS_BRACKETS_SINGLE` ✓ |
| NIIT threshold | $200,000 | statutory, not indexed | `NIIT_THRESHOLD_SINGLE` |
| ACA FPL household size | 1 | drives the FPL ratio | `federal_poverty_level(1)` |

- The IRS sets the lower five ordinary brackets and the standard deduction at
  **exactly half** the MFJ figure; the 35% top and the LTCG 15% top diverge (the
  single edge is lower), as do the top IRMAA floor and the §86/NIIT statutory
  bases. Re-verify the single column against the same Rev. Proc. / CMS release.

## Head of household (one-earner with a dependent), 2026

Set `household.filing_status: "hoh"` (or list a dependent member). HOH has its
own ordinary brackets, standard deduction, and LTCG breakpoints, but uses the
**single/unmarried** amounts for IRMAA floors, the SS §86 provisional bases, and
the NIIT threshold (the IRS gives HOH no separate tier for those). ✓ verified
2026-06-30 against Rev. Proc. 2025-32.

| Item | HOH value | Constant |
|---|---|---|
| 10% / 12% / 32% bracket tops | $17,700 / $67,450 / $256,200 | `FEDERAL_BRACKETS_HOH` ✓ |
| 22% / 24% / 35% bracket tops | $105,700 / $201,775 / $640,600 (= single) | `FEDERAL_BRACKETS_HOH` ✓ |
| Standard deduction | $24,150 | `STANDARD_DEDUCTION_HOH` ✓ |
| LTCG 0% / 15% tops | $66,200 / $579,600 | `CAP_GAINS_BRACKETS_HOH` ✓ |
| IRMAA floors / SS §86 bases / NIIT threshold | same as single | `_IRMAA`/`_SS_PI`/`_NIIT_THRESHOLD["hoh"]` |

**Household model.** Filing status comes from `household.filing_status` (else
inferred: ≥2 members → MFJ, else single). One-earner statuses (single, HOH) use
`members[0]` as the sole earner; MFJ uses `members[0]` + `members[1]`. Any further
members are **dependents** — they need only id / display_name / birth_year and
add to the default ACA household size (FPL), not to income or Social Security.

## IRMAA — Medicare premium surcharge, MFJ 2026 (CMS)

`IRMAA_MFJ`, **annual** surcharge **per person** (Part B + Part D combined). CMS
sets the MAGI tier floors and the per-tier premium add-ons annually (usually a
November release for the following year).

| MAGI floor (MFJ) | Surcharge / person / yr | Applies to | Source |
|---|---|---|---|
| ≤ $218,000 | $0 | 2026 | CMS 2026 IRMAA ✓ |
| $218,000 | $1,148 | 2026 | CMS 2026 IRMAA ✓ |
| $274,000 | $2,885 | 2026 | CMS 2026 IRMAA ✓ |
| $342,000 | $4,620 | 2026 | CMS 2026 IRMAA ✓ |
| $410,000 | $6,356 | 2026 | CMS 2026 IRMAA ✓ |
| > $750,000 | $6,936 | 2026 | CMS 2026 IRMAA ✓ |

- **Derivation (per person, annual = 12 × monthly add-ons):** Part B standard
  premium $202.90; the statutory IRMAA multipliers (1.4 / 2.0 / 2.6 / 3.2 / 3.4)
  give Part B add-ons of $81.20 / $202.90 / $324.64 / $446.38 / $486.96, and the
  CMS 2026 Part D add-ons are $14.50 / $37.50 / $60.40 / $83.30 / $91.00. Tier-1
  total $284.10/mo and tier-5 total $689.90/mo reconcile with the published CMS
  premium range.
- **2-year lookback:** the surcharge in a given year is set by MAGI from **two
  calendar years prior** (`IRMAA_LOOKBACK_YEARS = 2`), and only once a spouse is
  enrolled in Medicare at **65** (`MEDICARE_AGE`). The optimizer applies both.
- The `$218,000` Tier-1 floor is the conversion ceiling the fill-to-bracket
  heuristic respects in the Medicare-lookback window.

> ⚠ **RE-VERIFY the surcharge dollars each year.** The 2026 figures above are
> CMS-confirmed (fact sheet released 2025-11-14), but the per-person amounts move
> every year with the Part B premium and the Part D add-ons. The top tier ($750k
> MFJ / $500k single) floor is fixed by statute and not indexed. IRMAA is the
> single most material cliff in a conversion plan, so a stale figure here matters
> more than a stale bracket edge.

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

## Social Security taxation — provisional income (IRC §86)

Replaces the old flat-85% assumption with the real 0/50/85% inclusion tiers.
*Provisional income* = AGI-excluding-SS + ½·SS.

| Threshold (MFJ) | Value | Source |
|---|---|---|
| Base amount 1 | $32,000 | IRC §86; IRS Pub. 915 |
| Base amount 2 | $44,000 | IRC §86; IRS Pub. 915 |

- **These thresholds are statutory and NOT inflation-indexed** (frozen since
  1993), so over a multi-decade plan a rising share of SS becomes taxable — the
  "tax torpedo." The engine deliberately does **not** index them.

## Social Security claim-age optimization — `ss_claiming.py`

The engine takes each spouse's benefit as a fixed amount **at the configured
claim age**. The optimizer recovers the Primary Insurance Amount (benefit at Full
Retirement Age) from that input and re-prices the benefit at each candidate age,
so no new input is required.

| Rule | Value | Source |
|---|---|---|
| Full Retirement Age | 67 (born 1960+), graded to 65 (pre-1938) | SSA |
| Early-claim reduction | 5/9 of 1% per month, first 36 mo; 5/12 of 1% beyond | SSA — 62 → 70% of PIA at FRA 67 |
| Delayed-retirement credit | +2/3 of 1% per month, accrues only to age 70 | SSA — 70 → 124% of PIA at FRA 67 |

- **Objective:** maximize the present value (today's $) of cumulative lifetime
  benefits to the planning horizon (the breakeven framework — matches the classic
  "claim later if you expect to live past the breakeven age"). Each candidate runs
  through the full kernel, so SS taxation and solvency stay consistent; an
  insolvent combination is never recommended.
- **Not yet modelled:** spousal and survivor benefits (the optimizer treats each
  spouse's benefit independently), and a mortality-weighted objective (it uses a
  fixed horizon, not a survival curve). Both are roadmapped.

## Capital gains, NIIT — `tax_us.py`

Draws from the taxable brokerage realize proportional long-term gains (basis is
tracked); the gain stacks on top of ordinary taxable income through the 0/15/20%
bands.

| Item | Value (MFJ, 2026) | Source |
|---|---|---|
| LTCG 0% bracket top (taxable income) | $98,900 | Rev. Proc. 2025-32 ✓ (was stale $96,950) |
| LTCG 15% bracket top | $613,700 | Rev. Proc. 2025-32 ✓ (was stale $600,050) |
| LTCG 20% | above | statutory |
| NIIT rate | 3.8% | IRC §1411 |
| NIIT MAGI threshold (MFJ / single) | $250,000 / $200,000 | IRC §1411 — **not** inflation-indexed |

- Cost basis comes from `accounts.taxable_cost_basis`, else an assumed
  `assumptions.taxable_unrealized_gain_pct` (default 50%). The 0% LTCG bracket is
  a real early-retirement lever (gain harvesting) the engine now captures.
- NIIT here counts realized capital gains as the investment income; dividends and
  interest are not separately modelled.

## ACA premium tax credit — `tax_us.py`

Pre-65 marketplace subsidy, MAGI-driven. Enabled by setting
`healthcare.aca_benchmark_premium_annual` (your area's second-lowest-cost Silver
plan). The **`assumptions.aca_enhanced_subsidies` flag (default false)** models
current law — the **400% FPL subsidy cliff returns** after the ARPA/IRA enhanced
credits expire at the end of 2025; set it true for the 8.5%-cap, no-cliff regime.

| Item | Value | Source |
|---|---|---|
| Federal Poverty Level, 1 person | $15,650 | HHS 2025 guidelines ✓ (was stale 2024 $15,060) |
| FPL per additional person | $5,500 | HHS 2025 ✓ (was stale 2024 $5,380) |
| Subsidy cliff (current law) | 400% FPL | ACA / IRC §36B |
| Applicable-% schedule | ~2.0%→9.83% (current law) / 0%→8.5% (enhanced) | IRS Rev. Proc. (annual) ⚠ VERIFY |

- ⚠ **VERIFY the FPL table and applicable-percentage schedule each year** — both
  are released annually, and whether the enhanced subsidies are extended is a live
  legislative question. The applicable-% schedule here is a piecewise-linear
  approximation of the IRS table.
- **Why this matters most:** for an early retiree, ACA MAGI management is often a
  *harder* constraint than IRMAA, and capital gains alone (from funding spending)
  can blow through the cliff before any Roth conversion. The optimizer minimizes
  net cost (tax − subsidy) so it accounts for the tradeoff.

## The optimizer's objective

Net lifetime cost (what we minimize) =

> **PV**( Σ yearly [ federal + state/local + IRMAA + capital-gains + NIIT ] )
> **+** PV( terminal tax ) **−** PV( ACA subsidy preserved )

where the **terminal tax** is what heirs pay on the pre-tax balance still
standing at age 90, drawn down under the SECURE Act 10-year rule (SECURE Act of
2019, §401 — non-eligible designated beneficiaries) at `HEIR_MARGINAL_RATE`
(24% — an **assumption**, not a sourced figure: a planning rate for early-career
heirs). Roth dollars pass tax-free. Subtracting the ACA subsidy is the key
Phase 1 fix: it stops the optimizer from over-converting in the pre-65 window and
forfeiting premium tax credits. Present-valuing at inflation trades "pay tax now
at known rates" against "defer and face RMD-driven tax, IRMAA, lost ACA, and heir
tax later" — producing an **interior** optimum.

Three strategies are compared in the **Roth Conversion Ladder** tab:

1. **Do nothing** — RMDs only (baseline).
2. **Fill to top of 22% bracket** — the readable heuristic, capped at the IRMAA
   Tier-1 line inside the Medicare lookback window.
3. **Net-cost optimal** — grid-searches the level real AGI ceiling that minimizes
   net lifetime cost, subject to solvency.

> **Known limitation:** the optimizer searches a single *level* conversion
> target. The true ACA optimum is often time-varying (bunch conversions into one
> year, then stay under the cliff) — the level-target search only approximates
> this. A time-varying schedule is roadmapped for a later phase.

## Not modelled (by design)

AMT, the QBI deduction, the dividend/interest split of investment income,
per-state retirement-income exclusions, spousal IRA splitting, and time-varying
conversion schedules. These are either second-order for a conversion decision,
state-idiosyncratic, or roadmapped. Keep them in mind when reading the absolute
tax figures — the **relative** comparison between strategies is the robust output.

## Sources & primary references

Confirm dollar figures against these before relying on absolute tax numbers.
Each year's IRS Revenue Procedure and CMS IRMAA release supersede the values
shipped here.

| Topic | Primary source |
|---|---|
| Federal brackets + standard deduction (annual $ figures) | IRS Rev. Proc. 2025-32 (2026) — <https://www.irs.gov/pub/irs-drop/rp-25-32.pdf>; news summary <https://www.irs.gov/newsroom/irs-releases-tax-inflation-adjustments-for-tax-year-2026-including-amendments-from-the-one-big-beautiful-bill> |
| Bracket-rate permanence | One Big Beautiful Bill Act (OBBBA), P.L. 119-21 (2025) |
| Taxation of Social Security benefits (≤85%) | IRC §86; IRS Pub. 915 — <https://www.irs.gov/pub/irs-pdf/p915.pdf> |
| IRMAA tiers + Part B/D surcharges | CMS annual Medicare Part B/D premium release — <https://www.cms.gov/newsroom> (and Medicare.gov IRMAA pages) |
| RMD Uniform Lifetime Table | IRS Pub. 590-B, Appendix B — <https://www.irs.gov/pub/irs-pdf/p590b.pdf> |
| RMD beginning ages (73 / 75) | SECURE 2.0 Act of 2022, §107 (Div. T, Consolidated Appropriations Act 2023, P.L. 117-328) |
| Inherited-IRA 10-year rule | SECURE Act of 2019, §401 |
| Social Security provisional-income thresholds | IRC §86; IRS Pub. 915 — <https://www.irs.gov/pub/irs-pdf/p915.pdf> |
| Long-term capital-gains brackets (annual $ figures) | IRS annual inflation-adjustment Revenue Procedure |
| Net Investment Income Tax (3.8%, $250k MFJ) | IRC §1411; IRS Form 8960 instructions |
| ACA premium tax credit / applicable % | IRC §36B; IRS Rev. Proc. (annual) — <https://www.irs.gov/affordable-care-act> |
| Federal Poverty Level guidelines | HHS ASPE poverty guidelines — <https://aspe.hhs.gov/poverty-guidelines> |
| Enhanced-subsidy expiration (post-2025 cliff) | ARPA 2021 / IRA 2022 sunset — verify current legislative status |

**Verification log:**
- **2026-06-30** — full pass against Rev. Proc. 2025-32 and the CMS 2026 IRMAA
  fact sheet. Confirmed (✓): federal brackets + standard deduction (MFJ + single),
  IRMAA MAGI floors (MFJ + single). Corrected stale values: LTCG breakpoints
  (MFJ $96,950/$600,050 → $98,900/$613,700; single $48,475/$540,700 →
  $49,450/$545,500), IRMAA surcharge dollars (→ $1,148/$2,885/$4,620/$6,356/$6,936
  per person/yr), ACA FPL base (2024 $15,060/$5,380 → 2025 $15,650/$5,500).

**Re-verify next cycle:** the IRMAA surcharge dollars (move yearly with the Part B
premium), the federal bracket edges + standard deduction, the LTCG breakpoints,
and the FPL table + ACA applicable-% schedule — all released annually.
