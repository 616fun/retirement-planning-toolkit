#!/usr/bin/env python3
"""
simulate.py -- the unified annual simulation kernel.

ONE year-by-year projection that every consumer reads from. Given a config, a
return path, and a conversion policy, `simulate()` walks from today to the
planning horizon and emits a full per-year **ledger** (income sources, the AGI
and the MAGI that drive every tax cliff, federal/state/IRMAA tax, account-level
withdrawals, and balances) plus a **summary** (present-valued lifetime tax, the
terminal heir tax, ending balances, solvency).

Before this module the toolkit had three independent year loops -- the
Year-by-Year tab, the Monte Carlo, and the Roth optimizer -- each re-deriving
ages, income, growth, and (inconsistently) taxes. They could drift and disagree.
Now they are thin callers of this kernel:

    Year-by-Year tab  = simulate(cfg)                      # one deterministic run
    Cash Flow tab     = simulate(cfg)                      # detailed view of the same run
    Roth optimizer    = simulate(cfg, strategy=..., target=...)  # compare policies

The retirement-year math is a faithful generalization of the original
`_simulate_conversions`, so the Roth-ladder results are reproduced exactly; the
only new degree of freedom is `returns`, which lets the (future) Monte Carlo
feed a stochastic path through the same engine.

Tax engine: engine/tax_us.py. See docs/US_RULES.md for the modelling scope.
"""

import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tax_us  # noqa: E402
from config_loader import current_age  # noqa: E402


# IRS Uniform Lifetime Table (2022+) -- required-minimum-distribution divisors.
# RMD = pre-tax balance / divisor. Ages below the start age have no RMD.
_RMD_DIVISOR = {
    73: 26.5, 74: 25.5, 75: 24.6, 76: 23.7, 77: 22.9, 78: 22.0, 79: 21.1,
    80: 20.2, 81: 19.4, 82: 18.5, 83: 17.7, 84: 16.8, 85: 16.0, 86: 15.2,
    87: 14.4, 88: 13.7, 89: 12.9, 90: 12.2, 91: 11.5, 92: 10.8, 93: 10.1,
    94: 9.5, 95: 8.9, 96: 8.4, 97: 7.8, 98: 7.3, 99: 6.8, 100: 6.4,
}


def rmd_start_age(birth_year):
    """SECURE 2.0 required-beginning-age: 73 (1951-59) or 75 (1960+)."""
    if birth_year >= 1960:
        return 75
    if birth_year >= 1951:
        return 73
    return 72


def rmd_factor(age):
    """Fraction of the pre-tax balance that must be withdrawn at `age` (0 before
    the start age). Clamped to the oldest tabulated divisor."""
    if age < 73:
        return 0.0
    div = _RMD_DIVISOR.get(age, _RMD_DIVISOR[100])
    return 1.0 / div


# ---- pool helpers: the three tax buckets the engine decumulates ------------

def pretax_total(cfg):
    """Tax-deferred (traditional 401k + traditional IRA) across both spouses."""
    a = cfg["accounts"]
    return float(a.get("spouse_a_401k_pretax", 0) + a.get("spouse_a_trad_ira", 0)
                 + a.get("spouse_b_401k_pretax", 0) + a.get("spouse_b_trad_ira", 0))


def roth_total(cfg):
    """Tax-free (Roth 401k + Roth IRA) across both spouses."""
    a = cfg["accounts"]
    return float(a.get("spouse_a_401k_roth", 0) + a.get("spouse_a_roth_ira", 0)
                 + a.get("spouse_b_401k_roth", 0) + a.get("spouse_b_roth_ira", 0))


def taxable_total(cfg):
    """Taxable pool that funds spending shortfalls and the conversion tax
    (brokerage + cash/CDs + deferred comp). HSA and 529s are excluded -- they
    are earmarked (medical / education) and are not general spendable assets."""
    a = cfg["accounts"]
    return float(a.get("joint_brokerage", 0) + a.get("cash_and_cds", 0)
                 + a.get("deferred_comp", 0))


def real_estate_total(cfg):
    return float(sum(v for v in cfg.get("real_estate", {}).values()
                     if isinstance(v, (int, float))))


def _return_at(returns, n, default):
    """Resolve the nominal return for year index n from `returns`, which may be
    None (use the config base rate), a constant float, a callable(n)->rate, or a
    sequence (last value repeats past its end)."""
    if returns is None:
        return default
    if callable(returns):
        return returns(n)
    if isinstance(returns, (int, float)):
        return float(returns)
    return float(returns[n] if n < len(returns) else returns[-1])


def simulate(cfg, *, returns=None, strategy="none", target=None, horizon=None):
    """Run the household projection and return {ledger, schedule, summary...}.

    returns   -- nominal return path (see _return_at); None = config base rate.
    strategy  -- conversion policy: "none" (RMDs only), "bracket" (fill to top of
                 the 22% bracket, IRMAA-capped in the Medicare window), or
                 "optimal" (fill ordinary income to a level real `target`).
    target    -- today's-dollar AGI ceiling for the "optimal" policy.
    horizon   -- years to project (default: to spouse A age 90).

    Returns a dict with:
      ledger    -- one row per projected year (working + retired), for the
                   Year-by-Year and Cash Flow tabs.
      schedule  -- the retirement-year subset, with the exact keys the Roth tab
                   consumes (backward-compatible).
      lifetime_tax / terminal_tax / total_tax -- present-valued, today's $.
      trad_end / roth_end / taxable_end / estate_end / insolvent.
    """
    a = cfg["assumptions"]
    m = cfg["household"]["members"]
    inc = cfg["income"]

    infl = a["inflation_rate"]
    base_ret = a["portfolio_return_base"]
    std0 = a.get("standard_deduction_mfj", tax_us.STANDARD_DEDUCTION_MFJ)
    spend0 = a["retirement_spend_annual"]
    base_year = datetime.date.today().year

    a_age0, b_age0 = current_age(cfg, "spouse_a"), current_age(cfg, "spouse_b")
    a_ret = m[0]["retirement_age"]
    b_ret = m[1]["retirement_age"]
    a_ss, b_ss = m[0]["ss_claim_age"], m[1]["ss_claim_age"]
    a_rmd_start = rmd_start_age(m[0]["birth_year"])

    trad = pretax_total(cfg)
    roth = roth_total(cfg)
    taxable = taxable_total(cfg)
    re_total = real_estate_total(cfg)

    pension_m, cola = inc["pension_monthly_at_retirement"], inc["pension_cola"]
    passive0 = inc["passive_income_annual"]
    b_salary0 = inc["spouse_b_annual"]
    ss_a0 = cfg["social_security"]["spouse_a_monthly_benefit"] * 12
    ss_b0 = cfg["social_security"]["spouse_b_monthly_benefit"] * 12

    if horizon is None:
        horizon = max(1, 90 - a_age0)
    lifetime_tax, insolvent = 0.0, False
    ledger, schedule = [], []
    magi_history = {}                        # year_index -> AGI, for IRMAA lookback

    for n in range(0, horizon + 1):
        year = base_year + n
        a_age, b_age = a_age0 + n, b_age0 + n
        r = _return_at(returns, n, base_ret)
        trad *= (1 + r); roth *= (1 + r); taxable *= (1 + r)

        if a_age < a_ret:
            # Still working -- pools grow; no draws, conversions, or retirement
            # tax modelled. A minimal ledger row preserves the accumulation
            # runway for the projection tabs.
            ledger.append(_working_row(year, a_age, b_age, trad, roth, taxable, re_total))
            continue

        idx = (1 + infl) ** n
        std = std0 * idx
        spend = spend0 * idx
        pension = pension_m * 12 * ((1 + cola) ** max(0, a_age - a_ret))
        passive = passive0 * idx
        b_work = b_salary0 * idx if b_age < b_ret else 0.0
        ss_a = ss_a0 * idx if a_age >= a_ss else 0.0
        ss_b = ss_b0 * idx if b_age >= b_ss else 0.0
        ss_total = ss_a + ss_b
        ss_taxable = tax_us.SS_TAXABLE_FRACTION * ss_total

        forced = min(trad * rmd_factor(a_age) if a_age >= a_rmd_start else 0.0, trad)
        base_ordinary = pension + passive + b_work + ss_taxable + forced

        # ---- choose the conversion amount ----
        irmaa_ceiling = tax_us.irmaa_tier1_magi(year, infl)
        if strategy == "none":
            conversion = 0.0
        elif strategy == "bracket":
            bracket_top_taxable = tax_us.FEDERAL_BRACKETS_MFJ[2][1] * idx
            ceiling_agi = bracket_top_taxable + std
            if (a_age >= tax_us.MEDICARE_AGE - tax_us.IRMAA_LOOKBACK_YEARS
                    or b_age >= tax_us.MEDICARE_AGE - tax_us.IRMAA_LOOKBACK_YEARS):
                ceiling_agi = min(ceiling_agi, irmaa_ceiling)
            conversion = max(0.0, min(ceiling_agi - base_ordinary, trad - forced))
        else:  # optimal -- fill to a level real target (today's $ AGI)
            ceiling_agi = target * idx
            conversion = max(0.0, min(ceiling_agi - base_ordinary, trad - forced))

        trad -= conversion
        roth += conversion
        agi = base_ordinary + conversion

        # ---- tax: IRMAA keys off MAGI from two years prior, once on Medicare ----
        n_medicare = (1 if a_age >= tax_us.MEDICARE_AGE else 0) + \
                     (1 if b_age >= tax_us.MEDICARE_AGE else 0)
        magi_look = magi_history.get(n - tax_us.IRMAA_LOOKBACK_YEARS, agi)
        magi_history[n] = agi
        fed = tax_us.federal_tax(agi, year, infl, std0)
        st = tax_us.state_tax(agi, cfg, year, infl, ss_income=ss_taxable)
        irmaa = tax_us.irmaa_annual(magi_look, year, infl, n_enrolled=n_medicare)
        year_tax = fed + st + irmaa
        lifetime_tax += year_tax / ((1 + infl) ** n)   # present value, today's $

        # ---- fund spending; conversion tax is embedded in year_tax ----
        income_cash = pension + passive + ss_total + b_work + forced
        net = income_cash - year_tax
        draw_taxable = draw_trad = draw_roth = 0.0
        if net >= spend:
            taxable += (net - spend)
        else:
            short = spend - net
            draw_taxable = min(taxable, short); taxable -= draw_taxable; short -= draw_taxable
            if short > 0:
                draw_trad = min(trad, short); trad -= draw_trad; short -= draw_trad
            if short > 0:
                draw_roth = min(roth, short); roth -= draw_roth; short -= draw_roth
            if short > 1.0:
                insolvent = True

        # Backward-compatible schedule row (exact keys the Roth tab reads).
        schedule.append({
            "year": year, "a_age": a_age, "b_age": b_age,
            "base_ordinary": base_ordinary, "forced": forced, "conversion": conversion,
            "agi": agi, "tax": fed + st, "irmaa": irmaa, "magi_look": magi_look,
            "trad": trad, "roth": roth,
            "over": irmaa > 0,
        })
        # Rich ledger row (income, taxes, draws, balances) for the projection tabs.
        ledger.append({
            "year": year, "a_age": a_age, "b_age": b_age, "phase": "retired",
            "pension": pension, "passive": passive, "wages": b_work,
            "ss_total": ss_total, "ss_taxable": ss_taxable, "rmd": forced,
            "conversion": conversion, "agi": agi, "magi": magi_look,
            "fed_tax": fed, "state_tax": st, "irmaa": irmaa, "total_tax": year_tax,
            "spend": spend, "draw_taxable": draw_taxable, "draw_trad": draw_trad,
            "draw_roth": draw_roth, "trad": trad, "roth": roth, "taxable": taxable,
            "portfolio": trad + roth + taxable, "net_worth": trad + roth + taxable + re_total,
        })

    # ---- terminal tax: pre-tax balance left to heirs (SECURE 10-year rule) ----
    terminal_tax = (trad * tax_us.HEIR_MARGINAL_RATE) / ((1 + infl) ** horizon)
    total_tax = lifetime_tax + terminal_tax
    estate = trad + roth + taxable
    return {
        "strategy": strategy, "target": target,
        "lifetime_tax": lifetime_tax, "terminal_tax": terminal_tax, "total_tax": total_tax,
        "trad_end": trad, "roth_end": roth, "taxable_end": taxable, "estate_end": estate,
        "insolvent": insolvent, "ledger": ledger, "schedule": schedule,
    }


def _working_row(year, a_age, b_age, trad, roth, taxable, re_total):
    """A minimal pre-retirement ledger row (pools growing, no spend/tax)."""
    return {
        "year": year, "a_age": a_age, "b_age": b_age, "phase": "working",
        "pension": 0.0, "passive": 0.0, "wages": 0.0, "ss_total": 0.0,
        "ss_taxable": 0.0, "rmd": 0.0, "conversion": 0.0, "agi": 0.0, "magi": 0.0,
        "fed_tax": 0.0, "state_tax": 0.0, "irmaa": 0.0, "total_tax": 0.0,
        "spend": 0.0, "draw_taxable": 0.0, "draw_trad": 0.0, "draw_roth": 0.0,
        "trad": trad, "roth": roth, "taxable": taxable,
        "portfolio": trad + roth + taxable, "net_worth": trad + roth + taxable + re_total,
    }
