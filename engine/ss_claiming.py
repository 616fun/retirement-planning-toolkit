#!/usr/bin/env python3
"""
ss_claiming.py -- Social Security claim-age actuarial adjustments + optimizer.

The kernel (simulate.py) takes each spouse's benefit as a fixed monthly amount AT
THE CONFIGURED claim age. To *optimize* the claim age we first recover the Primary
Insurance Amount (PIA -- the benefit at Full Retirement Age) from that input via
the SSA reduction/credit schedule, then re-price the benefit at each candidate
claim age. So no new config is required: you give the benefit you expect at your
planned claim age, and the optimizer explores the alternatives off the same PIA.

Objective: maximize the present value (today's dollars) of cumulative Social
Security benefits received to the planning horizon -- the classic breakeven
framework. Later claiming buys a larger, COLA'd, longevity-hedged benefit; the
optimizer weighs that against the years of foregone early benefits. Each candidate
runs through the full kernel, so the SS income, its taxation, and solvency stay
consistent with the rest of the plan.

SSA schedule (encoded below):
  * Full Retirement Age: 67 for those born 1960+ (graded down to 65 for pre-1938).
  * Early claiming: benefit reduced 5/9 of 1% per month for the first 36 months
    before FRA, then 5/12 of 1% per month beyond that (so claiming at 62 with an
    FRA of 67 yields 70% of PIA).
  * Delayed retirement credits: +2/3 of 1% per month after FRA, accruing only to
    age 70 (so 124% of PIA at 70 with an FRA of 67).
"""

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import simulate  # noqa: E402


def full_retirement_age(birth_year):
    """SSA Full Retirement Age (in years) by birth year."""
    if birth_year <= 1937:
        return 65.0
    if birth_year <= 1942:
        return 65 + (birth_year - 1937) * 2 / 12.0
    if birth_year <= 1954:
        return 66.0
    if birth_year <= 1959:
        return 66 + (birth_year - 1954) * 2 / 12.0
    return 67.0


def claim_factor(claim_age, fra):
    """Benefit as a fraction of PIA when first claimed at `claim_age` (SSA rules).

    < FRA reduces the benefit; > FRA adds delayed-retirement credits that stop
    accruing at 70. Returns 1.0 exactly at FRA."""
    months = round((claim_age - fra) * 12)
    if months == 0:
        return 1.0
    if months < 0:                      # claimed early -> reduction
        early = -months
        reduction = (5.0 / 9.0 / 100.0) * min(36, early) \
            + (5.0 / 12.0 / 100.0) * max(0, early - 36)
        return max(0.0, 1.0 - reduction)
    cap = round((70 - fra) * 12)         # credits accrue only to age 70
    return 1.0 + (2.0 / 3.0 / 100.0) * min(months, cap)


def benefit_at_claim(pia, claim_age, fra):
    """Monthly benefit when PIA is claimed at `claim_age`."""
    return pia * claim_factor(claim_age, fra)


def pia_from_benefit(benefit, claim_age, fra):
    """Recover PIA (benefit at FRA) from a benefit quoted at `claim_age`."""
    f = claim_factor(claim_age, fra)
    return benefit / f if f > 0 else benefit


def _ss_present_value(cfg):
    """Today's-dollar PV of all SS benefits received over the projection."""
    r = simulate.simulate(cfg, strategy="none")
    infl = cfg["assumptions"]["inflation_rate"]
    pv = 0.0
    base_age = simulate.current_age(cfg, "spouse_a")
    for row in r["ledger"]:
        n = row["a_age"] - base_age
        pv += row.get("ss_total", 0.0) / ((1 + infl) ** n)
    return pv, r


def _with_claim_ages(cfg, a_claim, b_claim, a_pia, b_pia, a_fra, b_fra, one_earner):
    """A config clone with the candidate claim ages and PIA-scaled benefits."""
    c = copy.deepcopy(cfg)
    c["household"]["members"][0]["ss_claim_age"] = a_claim
    c["social_security"]["spouse_a_monthly_benefit"] = benefit_at_claim(a_pia, a_claim, a_fra)
    if not one_earner:
        c["household"]["members"][1]["ss_claim_age"] = b_claim
        c["social_security"]["spouse_b_monthly_benefit"] = benefit_at_claim(b_pia, b_claim, b_fra)
    return c


def optimize_ss_claim_ages(cfg, ages=range(62, 71)):
    """Grid-search each spouse's SS claim age to maximize the present value of
    lifetime benefits, requiring the plan to stay solvent.

    Returns a dict with the recommended `a_claim`/`b_claim`, the `pv` at that
    choice, the `baseline` PV at the configured claim ages, and the full `grid`
    (one row per combination) for trust-but-verify inspection. Never recommends a
    combination worse than the configured one."""
    import tax_us
    members = cfg["household"]["members"]
    one_earner = tax_us.resolve_filing_status(cfg) != "mfj"

    a_fra = full_retirement_age(members[0]["birth_year"])
    a_cfg_claim = members[0]["ss_claim_age"]
    a_pia = pia_from_benefit(cfg["social_security"]["spouse_a_monthly_benefit"],
                             a_cfg_claim, a_fra)
    if one_earner:
        b_fra = a_fra
        b_cfg_claim, b_pia = a_cfg_claim, 0.0
        b_ages = [a_cfg_claim]            # spouse B is not modelled
    else:
        b_fra = full_retirement_age(members[1]["birth_year"])
        b_cfg_claim = members[1]["ss_claim_age"]
        b_pia = pia_from_benefit(cfg["social_security"]["spouse_b_monthly_benefit"],
                                 b_cfg_claim, b_fra)
        b_ages = list(ages)

    baseline_pv, _ = _ss_present_value(cfg)
    grid, best = [], None
    for a_claim in ages:
        for b_claim in b_ages:
            cand = _with_claim_ages(cfg, a_claim, b_claim, a_pia, b_pia,
                                    a_fra, b_fra, one_earner)
            pv, r = _ss_present_value(cand)
            row = {"a_claim": a_claim, "b_claim": b_claim,
                   "pv": round(pv), "insolvent": r["insolvent"]}
            grid.append(row)
            if r["insolvent"]:
                continue
            if best is None or pv > best["pv_raw"]:
                best = {"a_claim": a_claim, "b_claim": b_claim,
                        "pv_raw": pv, "estate_end": r["estate_end"]}

    if best is None:                       # nothing solvent: keep the status quo
        best = {"a_claim": a_cfg_claim, "b_claim": b_cfg_claim,
                "pv_raw": baseline_pv, "estate_end": None}
    return {
        "a_claim": best["a_claim"], "b_claim": best["b_claim"],
        "a_fra": a_fra, "b_fra": b_fra,
        "pv": round(best["pv_raw"]), "baseline_pv": round(baseline_pv),
        "gain_vs_configured": round(best["pv_raw"] - baseline_pv),
        "configured": {"a_claim": a_cfg_claim, "b_claim": b_cfg_claim},
        "one_earner": one_earner, "grid": grid,
    }


if __name__ == "__main__":
    from config_loader import load_config
    cfg, _ = load_config()
    best = optimize_ss_claim_ages(cfg)
    print(f"Recommended claim ages: A={best['a_claim']} B={best['b_claim']} "
          f"(FRA A={best['a_fra']:.2f} B={best['b_fra']:.2f})")
    print(f"  Lifetime SS PV: ${best['pv']:,} "
          f"(${best['gain_vs_configured']:,} vs configured "
          f"{best['configured']})")
