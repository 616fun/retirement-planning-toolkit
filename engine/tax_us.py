#!/usr/bin/env python3
"""
tax_us.py -- a small US personal income-tax engine for retirement planning.

Computes federal ordinary-income tax (MFJ or single), the IRMAA surcharge cascade
(the 2-year-lookback Part B + Part D premium add-on), and state + local tax.
Brackets and the standard deduction index forward from a base year by an
inflation rate, so the engine works across a multi-decade projection. It exists
to price Roth conversions: every marginal dollar converted is ordinary income
this year, and the engine reports what that dollar (and the IRMAA cliff it may
trip two years later) actually costs.

Scope / honesty -- this is the hybrid design (see docs/US_RULES.md):
  * FEDERAL is modelled in full: progressive brackets (2026 OBBBA, MFJ or
    single per the household size), the standard deduction, and the IRMAA Tier
    0-5 cascade (2026 CMS figures). Filing status flows from the kernel: a
    one-member household is taxed as single, two as MFJ.
  * STATE is modelled as a FLAT effective rate by default (the
    household.state_income_tax_rate + local_income_tax_rate inputs). This is
    exactly right for the 9 no-income-tax states (rate 0) and the ~11 flat-tax
    states (e.g. Indiana ~3.0%), and a defensible marginal approximation
    elsewhere. Power users who live in a progressive-bracket state can supply an
    optional household.state_brackets array to model it precisely.
  * NOT modelled (by deliberate design -- they are state-idiosyncratic and would
    rot annually): per-state retirement-income exclusions (Social Security
    taxability, pension exclusions, age deductions), AGI add-backs, the NIIT,
    capital-gains preferential rates, AMT, and the QBI deduction. Fold any
    state retirement break into your effective state rate. Social Security is
    treated as 85% taxable federally (the cap for higher-income households) and
    is excluded from state taxable income by default.

This is illustrative, not tax advice. Verify against the IRS and your state.
"""

BASE_YEAR = 2026

# (marginal_rate, upper_bound_of_bracket) ascending; last bound is None (open).
# MFJ 2026 OBBBA-adjusted -- mirrors the household plan's Assumptions rows 50-57.
FEDERAL_BRACKETS_MFJ = [
    (0.10, 24800),
    (0.12, 100800),
    (0.22, 211400),
    (0.24, 403550),
    (0.32, 512450),
    (0.35, 768700),
    (0.37, None),
]
# SINGLE 2026 (Rev. Proc. 2025-32, verified 2026-06-30) -- the lower five edges
# are exactly half the MFJ figure; only the 35% top diverges ($640,600 vs $768,700).
FEDERAL_BRACKETS_SINGLE = [
    (0.10, 12400),
    (0.12, 50400),
    (0.22, 105700),
    (0.24, 201775),
    (0.32, 256225),
    (0.35, 640600),
    (0.37, None),
]
STANDARD_DEDUCTION_MFJ = 32200          # 2026 OBBBA (config can override)
STANDARD_DEDUCTION_SINGLE = 16100       # 2026 OBBBA -- half of MFJ (config can override)
SS_TAXABLE_FRACTION = 0.85              # share of Social Security taxed federally

# IRMAA 2026 MFJ cascade: (MAGI floor, ANNUAL surcharge PER PERSON, Part B + D).
# Surcharge applies two calendar years after the MAGI is earned, and only once a
# spouse is enrolled in Medicare (age 65+). CMS-verified 2026 figures.
# 2026 CMS-verified (fact sheet released 2025-11-14). Annual = 12 x (monthly
# Part B IRMAA add-on + monthly Part D IRMAA add-on), per person. Part B standard
# premium $202.90; Part B add-ons run $81.20/$202.90/$324.64/$446.38/$486.96 and
# Part D add-ons $14.50/$37.50/$60.40/$83.30/$91.00 across the five tiers.
IRMAA_MFJ = [
    (0,       0.0),
    (218000,  1148.0),
    (274000,  2885.0),
    (342000,  4620.0),
    (410000,  6356.0),
    (750000,  6936.0),
]
# SINGLE 2026: same per-person surcharge dollars (IRMAA is per enrollee, not per
# return); only the MAGI floors differ -- half of MFJ for the first four tiers,
# top tier at $500k (vs MFJ $750k). CMS-verified 2026.
IRMAA_SINGLE = [
    (0,       0.0),
    (109000,  1148.0),
    (137000,  2885.0),
    (171000,  4620.0),
    (205000,  6356.0),
    (500000,  6936.0),
]
MEDICARE_AGE = 65
IRMAA_LOOKBACK_YEARS = 2

# Filing-status selector tables. Default everywhere is "mfj" (backward
# compatible); the kernel passes "single" for a one-member household.
FEDERAL_BRACKETS = {"mfj": FEDERAL_BRACKETS_MFJ, "single": FEDERAL_BRACKETS_SINGLE}
_STD_DEDUCTION = {"mfj": STANDARD_DEDUCTION_MFJ, "single": STANDARD_DEDUCTION_SINGLE}
_IRMAA = {"mfj": IRMAA_MFJ, "single": IRMAA_SINGLE}


def normalize_status(status):
    """Map a free-form filing-status string to 'mfj' or 'single' (default mfj)."""
    s = str(status or "mfj").strip().lower()
    if s in ("single", "s", "individual", "just_me", "1"):
        return "single"
    return "mfj"


def standard_deduction(status="mfj"):
    """Default standard deduction for a filing status (config may override)."""
    return _STD_DEDUCTION[normalize_status(status)]

# Terminal (estate) assumption: pre-tax dollars left to heirs are drawn down
# under the SECURE Act 10-year rule and taxed at the heirs' marginal rate. Sons
# are early-career engineers -> a 24% bracket is a reasonable planning figure.
HEIR_MARGINAL_RATE = 0.24


def _f(year, infl):
    """Inflation index factor from the base year."""
    return (1 + infl) ** (year - BASE_YEAR)


def _bracket_tax(taxable, brackets, year, infl):
    """Progressive tax on `taxable`, with bracket bounds indexed to `year`."""
    if taxable <= 0:
        return 0.0
    tax, lo = 0.0, 0.0
    for rate, upper in brackets:
        hi = float("inf") if upper is None else upper * _f(year, infl)
        if taxable > lo:
            tax += rate * (min(taxable, hi) - lo)
        lo = hi
        if taxable <= lo:
            break
    return tax


def federal_tax(agi, year=BASE_YEAR, infl=0.02, std_deduction=None, status="mfj"):
    """Federal ordinary-income tax after the standard deduction.

    `agi` is adjusted gross income (pension + taxable IRA/401k withdrawals +
    Roth conversions + wages + passive + taxable Social Security). `status` is
    'mfj' (default) or 'single' and selects the bracket schedule. The standard
    deduction indexes forward; if not passed it defaults to the status default.
    """
    status = normalize_status(status)
    if std_deduction is None:
        std_deduction = _STD_DEDUCTION[status]
    taxable = max(0.0, agi - std_deduction * _f(year, infl))
    return _bracket_tax(taxable, FEDERAL_BRACKETS[status], year, infl)


def irmaa_annual(magi, year=BASE_YEAR, infl=0.02, n_enrolled=2, status="mfj"):
    """Total ANNUAL IRMAA surcharge for the household (Part B + D, all enrollees).

    `n_enrolled` is the number of people currently on Medicare (0, 1, or 2).
    `status` selects the MFJ or single MAGI floors (the per-person surcharge
    dollars are identical). Tier floors index forward with inflation.
    """
    if n_enrolled <= 0 or magi <= 0:
        return 0.0
    per_person = 0.0
    for floor, surcharge in _IRMAA[normalize_status(status)]:
        if magi >= floor * _f(year, infl):
            per_person = surcharge * _f(year, infl)
        else:
            break
    return per_person * n_enrolled


def irmaa_tier1_magi(year=BASE_YEAR, infl=0.02, status="mfj"):
    """The MAGI floor at which the first IRMAA surcharge bites (indexed)."""
    return _IRMAA[normalize_status(status)][1][0] * _f(year, infl)


def state_tax(ordinary_income, cfg, year=BASE_YEAR, infl=0.02, ss_income=0.0):
    """State + local income tax (the hybrid model).

    If household.state_brackets is present, tax progressively against it
    (bounds index with inflation). Otherwise apply the flat
    state_income_tax_rate + local_income_tax_rate to ordinary income. Social
    Security is excluded from the state base by default (most states do not tax
    it); fold any other state retirement break into your effective rate.
    """
    hh = cfg["household"]
    base = max(0.0, ordinary_income - ss_income)
    brackets = hh.get("state_brackets")
    if brackets:
        # Optional precise mode: [[rate, upper], ...] with last upper = null.
        norm = [(r, (None if u is None else u)) for r, u in brackets]
        prog = _bracket_tax(base, norm, year, infl)
        local = hh.get("local_income_tax_rate", 0.0) * base
        return prog + local
    rate = hh.get("state_income_tax_rate", 0.0) + hh.get("local_income_tax_rate", 0.0)
    return rate * base


def total_tax(agi, cfg, year=BASE_YEAR, infl=0.02, std_deduction=None,
              magi=None, n_medicare=0, ss_income=0.0, status="mfj"):
    """Combined federal + state/local income tax + IRMAA surcharge for the year.

    `agi`         -- ordinary income (pre-standard-deduction).
    `magi`        -- income that drives IRMAA (defaults to agi; pass the
                     2-years-prior MAGI to model the real lookback).
    `n_medicare`  -- people enrolled in Medicare this year (drives IRMAA).
    `ss_income`   -- Social Security dollars in agi, excluded from the state base.
    `status`      -- 'mfj' (default) or 'single'.
    """
    status = normalize_status(status)
    if std_deduction is None:
        std_deduction = cfg["assumptions"].get("standard_deduction_mfj", _STD_DEDUCTION[status])
    if magi is None:
        magi = agi
    fed = federal_tax(agi, year, infl, std_deduction, status=status)
    st = state_tax(agi, cfg, year, infl, ss_income=ss_income)
    irmaa = irmaa_annual(magi, year, infl, n_enrolled=n_medicare, status=status)
    return fed + st + irmaa


def marginal_rate(agi, cfg, year=BASE_YEAR, infl=0.02, step=100.0, status="mfj"):
    """Approximate combined federal + state marginal rate at an income level
    (IRMAA excluded -- it is a step function, not a marginal rate)."""
    base = (federal_tax(agi, year, infl, status=status) + state_tax(agi, cfg, year, infl))
    up = (federal_tax(agi + step, year, infl, status=status) + state_tax(agi + step, cfg, year, infl))
    return (up - base) / step


# ============================================================================
# Phase 1 -- capital gains, NIIT, Social Security taxation, and ACA subsidies.
# These all read off the same MAGI the kernel computes once per year.
# ============================================================================

# ---- Social Security taxation (IRC sec. 86) -------------------------------
# Provisional-income thresholds are STATUTORY and NOT inflation-indexed (frozen
# since 1993) -- so across a multi-decade plan a rising share of SS becomes
# taxable (the "tax torpedo"). Do NOT index these.
SS_PI_BASE1_MFJ = 32000.0
SS_PI_BASE2_MFJ = 44000.0
SS_PI_BASE1_SINGLE = 25000.0
SS_PI_BASE2_SINGLE = 34000.0
_SS_PI = {"mfj": (SS_PI_BASE1_MFJ, SS_PI_BASE2_MFJ),
          "single": (SS_PI_BASE1_SINGLE, SS_PI_BASE2_SINGLE)}


def ss_taxable_amount(ss_total, other_income, status="mfj"):
    """Taxable portion of Social Security (IRC sec. 86). `other_income` is
    AGI excluding SS (pension + IRA/conversions + wages + capital gains + ...).
    Replaces the flat 85% assumption with the real 0/50/85% provisional tiers.
    `status` selects the MFJ ($32k/$44k) or single ($25k/$34k) base amounts."""
    if ss_total <= 0:
        return 0.0
    base1, base2 = _SS_PI[normalize_status(status)]
    pi = other_income + 0.5 * ss_total
    if pi <= base1:
        return 0.0
    if pi <= base2:
        return min(0.5 * ss_total, 0.5 * (pi - base1))
    lower_band = min(0.5 * ss_total, 0.5 * (base2 - base1))
    return min(0.85 * ss_total, 0.85 * (pi - base2) + lower_band)


# ---- Long-term capital gains (stacked on top of ordinary taxable income) ---
# MFJ breakpoints are taxable-income thresholds; the gain fills the 0/15/20%
# bands ABOVE ordinary taxable income. Breakpoints index with inflation.
# 2026 verified against Tax Foundation / IRS Rev. Proc. 2025-32 (taxable-income
# breakpoints where the gain starts being taxed at 15% / 20%).
CAP_GAINS_BRACKETS_MFJ = [(0.0, 98900), (0.15, 613700), (0.20, None)]
CAP_GAINS_BRACKETS_SINGLE = [(0.0, 49450), (0.15, 545500), (0.20, None)]
_CAP_GAINS = {"mfj": CAP_GAINS_BRACKETS_MFJ, "single": CAP_GAINS_BRACKETS_SINGLE}


def capital_gains_tax(ordinary_taxable, gain, year=BASE_YEAR, infl=0.02, status="mfj"):
    """LTCG tax: stack `gain` on top of `ordinary_taxable` and tax the slice in
    each 0/15/20% band at that band's rate. `status` selects the breakpoints."""
    if gain <= 0:
        return 0.0
    lo = max(0.0, ordinary_taxable)
    top = lo + gain
    tax, prev = 0.0, 0.0
    for rate, edge in _CAP_GAINS[normalize_status(status)]:
        hi = float("inf") if edge is None else edge * _f(year, infl)
        seg_lo, seg_hi = max(lo, prev), min(top, hi)
        if seg_hi > seg_lo:
            tax += rate * (seg_hi - seg_lo)
        prev = hi
        if top <= hi:
            break
    return tax


# ---- Net Investment Income Tax (NIIT) -------------------------------------
NIIT_RATE = 0.038
NIIT_THRESHOLD_MFJ = 250000.0     # statutory, NOT inflation-indexed
NIIT_THRESHOLD_SINGLE = 200000.0  # statutory, NOT inflation-indexed
_NIIT_THRESHOLD = {"mfj": NIIT_THRESHOLD_MFJ, "single": NIIT_THRESHOLD_SINGLE}


def niit(net_investment_income, magi, status="mfj"):
    """3.8% on the lesser of net investment income and MAGI over the threshold
    ($250k MFJ / $200k single)."""
    threshold = _NIIT_THRESHOLD[normalize_status(status)]
    if net_investment_income <= 0 or magi <= threshold:
        return 0.0
    return NIIT_RATE * min(net_investment_income, magi - threshold)


# ---- ACA premium tax credit -----------------------------------------------
# Federal Poverty Level (48 contiguous states; prior year's FPL applies to a
# coverage year). Updated annually -- indexed here ~ inflation.
# 2025 HHS poverty guidelines (48 contiguous states) -- the PRIOR-year FPL
# applies to a coverage year, so the 2025 figures govern 2026 ACA coverage.
FPL_BASE_1PERSON = 15650.0       # 2025 HHS, 1 person
FPL_PER_ADDL_PERSON = 5500.0     # 2025 HHS, each additional person
ACA_CLIFF_FPL = 4.00             # 400% FPL subsidy cliff (current law, post-2025)


def federal_poverty_level(household_size, year=BASE_YEAR, infl=0.02):
    base = FPL_BASE_1PERSON + FPL_PER_ADDL_PERSON * (max(1, household_size) - 1)
    return base * _f(year, infl)


def aca_applicable_pct(fpl_ratio, enhanced=False):
    """Share of MAGI the household is expected to contribute toward the
    benchmark plan, at a given % of FPL. Two regimes:
      enhanced=False -- current law (pre-ARPA): ~2.06% at 150% FPL rising to
                        ~9.83% at 400%, then the cliff (handled by caller).
      enhanced=True  -- ARPA/IRA: 0% at <=150% FPL rising to 8.5% at 400%, flat
                        above (no cliff)."""
    r = max(1.0, fpl_ratio)
    if enhanced:
        if r <= 1.5:
            return 0.0
        if r >= 4.0:
            return 0.085
        return 0.085 * (r - 1.5) / (4.0 - 1.5)
    if r < 1.5:
        return 0.0206
    if r >= 4.0:
        return 0.0983
    return 0.0206 + (0.0983 - 0.0206) * (r - 1.5) / (4.0 - 1.5)


def aca_subsidy(magi, household_size, benchmark_premium, year=BASE_YEAR,
                infl=0.02, enhanced=False):
    """Annual ACA premium tax credit. Returns 0 when no benchmark premium is
    supplied (feature off) or -- under current law -- when MAGI exceeds the 400%
    FPL cliff. Subsidy = benchmark premium minus the expected contribution."""
    if benchmark_premium <= 0 or magi <= 0:
        return 0.0
    fpl = federal_poverty_level(household_size, year, infl)
    ratio = magi / fpl if fpl > 0 else 0.0
    if not enhanced and ratio > ACA_CLIFF_FPL:
        return 0.0    # the subsidy cliff
    expected = aca_applicable_pct(ratio, enhanced=enhanced) * magi
    return max(0.0, benchmark_premium - expected)


if __name__ == "__main__":
    # Minimal self-check against a flat-tax (Indiana-like) household.
    demo = {"household": {"state_income_tax_rate": 0.03, "local_income_tax_rate": 0.0},
            "assumptions": {"standard_deduction_mfj": STANDARD_DEDUCTION_MFJ}}
    print("  MFJ federal + 3% flat state, std deduction applied:")
    for agi in (60000, 120000, 200000, 250000, 400000):
        ft = federal_tax(agi)
        tt = total_tax(agi, demo)
        print(f"  AGI ${agi:>7,}: fed ${ft:>8,.0f}  fed+state ${tt:>8,.0f}  "
              f"(marginal {100*marginal_rate(agi, demo):4.1f}%)")
    print("  IRMAA surcharge (both spouses enrolled), by MAGI:")
    for magi in (200000, 230000, 300000, 420000):
        print(f"  MAGI ${magi:>7,}: ${irmaa_annual(magi, n_enrolled=2):>7,.0f}/yr")
