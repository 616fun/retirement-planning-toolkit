#!/usr/bin/env python3
"""
tax_us.py -- a small US personal income-tax engine for retirement planning.

Computes federal ordinary-income tax (MFJ), the IRMAA Medicare surcharge cascade
(the 2-year-lookback Part B + Part D premium add-on), and state + local tax.
Brackets and the standard deduction index forward from a base year by an
inflation rate, so the engine works across a multi-decade projection. It exists
to price Roth conversions: every marginal dollar converted is ordinary income
this year, and the engine reports what that dollar (and the IRMAA cliff it may
trip two years later) actually costs.

Scope / honesty -- this is the hybrid design (see docs/US_RULES.md):
  * FEDERAL is modelled in full: progressive MFJ brackets (2026 OBBBA), the
    standard deduction, and the IRMAA Tier 0-5 cascade (2026 CMS figures).
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
STANDARD_DEDUCTION_MFJ = 32200          # 2026 OBBBA (config can override)
SS_TAXABLE_FRACTION = 0.85              # share of Social Security taxed federally

# IRMAA 2026 MFJ cascade: (MAGI floor, ANNUAL surcharge PER PERSON, Part B + D).
# Surcharge applies two calendar years after the MAGI is earned, and only once a
# spouse is enrolled in Medicare (age 65+). CMS-verified 2026 figures.
IRMAA_MFJ = [
    (0,       0.0),
    (218000,  1143.0),
    (274000,  2867.0),
    (342000,  4587.0),
    (410000,  6306.0),
    (750000,  6879.0),
]
MEDICARE_AGE = 65
IRMAA_LOOKBACK_YEARS = 2

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


def federal_tax(agi, year=BASE_YEAR, infl=0.02, std_deduction=STANDARD_DEDUCTION_MFJ):
    """Federal ordinary-income tax (MFJ) after the standard deduction.

    `agi` is adjusted gross income (pension + taxable IRA/401k withdrawals +
    Roth conversions + wages + passive + 85% of Social Security). The standard
    deduction indexes forward unless a fixed figure is passed.
    """
    taxable = max(0.0, agi - std_deduction * _f(year, infl))
    return _bracket_tax(taxable, FEDERAL_BRACKETS_MFJ, year, infl)


def irmaa_annual(magi, year=BASE_YEAR, infl=0.02, n_enrolled=2):
    """Total ANNUAL IRMAA surcharge for the household (Part B + D, all enrollees).

    `n_enrolled` is the number of spouses currently on Medicare (0, 1, or 2).
    Tier floors index forward with inflation. Returns 0 when no one is enrolled.
    """
    if n_enrolled <= 0 or magi <= 0:
        return 0.0
    per_person = 0.0
    for floor, surcharge in IRMAA_MFJ:
        if magi >= floor * _f(year, infl):
            per_person = surcharge * _f(year, infl)
        else:
            break
    return per_person * n_enrolled


def irmaa_tier1_magi(year=BASE_YEAR, infl=0.02):
    """The MAGI floor at which the first IRMAA surcharge bites (indexed)."""
    return IRMAA_MFJ[1][0] * _f(year, infl)


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
              magi=None, n_medicare=0, ss_income=0.0):
    """Combined federal + state/local income tax + IRMAA surcharge for the year.

    `agi`         -- ordinary income (pre-standard-deduction).
    `magi`        -- income that drives IRMAA (defaults to agi; pass the
                     2-years-prior MAGI to model the real lookback).
    `n_medicare`  -- spouses enrolled in Medicare this year (drives IRMAA).
    `ss_income`   -- Social Security dollars in agi, excluded from the state base.
    """
    if std_deduction is None:
        std_deduction = cfg["assumptions"].get("standard_deduction_mfj", STANDARD_DEDUCTION_MFJ)
    if magi is None:
        magi = agi
    fed = federal_tax(agi, year, infl, std_deduction)
    st = state_tax(agi, cfg, year, infl, ss_income=ss_income)
    irmaa = irmaa_annual(magi, year, infl, n_enrolled=n_medicare)
    return fed + st + irmaa


def marginal_rate(agi, cfg, year=BASE_YEAR, infl=0.02, step=100.0):
    """Approximate combined federal + state marginal rate at an income level
    (IRMAA excluded -- it is a step function, not a marginal rate)."""
    base = (federal_tax(agi, year, infl) + state_tax(agi, cfg, year, infl))
    up = (federal_tax(agi + step, year, infl) + state_tax(agi + step, cfg, year, infl))
    return (up - base) / step


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
