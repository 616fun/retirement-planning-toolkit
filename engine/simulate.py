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
import random
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


# The three tax buckets, in the default decumulation order (taxable first lets
# the tax-advantaged pools keep compounding; Roth last preserves the tax-free
# pool longest). cfg["withdrawal_order"] may reorder them.
WITHDRAWAL_BUCKETS = ("taxable", "pretax", "roth")


def withdrawal_order(cfg):
    """Resolve the decumulation bucket order from config, defaulting to
    taxable -> pre-tax -> Roth. Unknown names are ignored and any of the three
    buckets the config omits are appended (so no money is ever stranded)."""
    requested = cfg.get("withdrawal_order") or list(WITHDRAWAL_BUCKETS)
    ordered = [b for b in requested if b in WITHDRAWAL_BUCKETS]
    return ordered + [b for b in WITHDRAWAL_BUCKETS if b not in ordered]


# ---- spending model: the retirement "smile" + lumpy one-time expenses ------

def spending_multiplier(cfg, age):
    """Real-spending multiplier at `age` from cfg["spending"]["phases"] -- the
    retirement smile (e.g. go-go 1.0 to ~75, slow-go 0.85 to ~85, no-go 0.95 as
    healthcare rises). Each phase applies up to its `until_age` (exclusive);
    absent config => 1.0 (flat spending, the prior behavior)."""
    phases = cfg.get("spending", {}).get("phases")
    if not phases:
        return 1.0
    for ph in phases:
        if age < ph.get("until_age", 999):
            return float(ph.get("multiplier", 1.0))
    return float(phases[-1].get("multiplier", 1.0))


def lumpy_expense(cfg, year, idx):
    """One-time expenses scheduled for `year` from cfg["spending"]["lumpy"].
    Amounts are in today's dollars and inflated to the year by `idx`."""
    total = 0.0
    for item in cfg.get("spending", {}).get("lumpy", []):
        if item.get("year") == year:
            total += float(item.get("amount", 0)) * idx
    return total


def guardrail_params(cfg):
    """Guyton-Klinger dynamic-spending guardrails from cfg["spending"]["guardrails"],
    or None when not enabled. Returns the upper/lower withdrawal-rate bands and the
    cut/raise step. Defaults are the classic 20% bands with a 10% adjustment."""
    g = cfg.get("spending", {}).get("guardrails")
    if not g or not g.get("enabled"):
        return None
    return {
        "upper": float(g.get("upper", 0.20)),   # cut when rate is >20% above the start
        "lower": float(g.get("lower", 0.20)),   # raise when >20% below the start
        "cut": float(g.get("cut", 0.10)),       # spending cut size
        "raise": float(g.get("raise", 0.10)),   # spending raise size
    }


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


def simulate(cfg, *, returns=None, strategy="none", target=None, horizon=None,
             record=True, trace=False):
    """Run the household projection and return {ledger, schedule, summary...}.

    returns   -- nominal return path (see _return_at); None = config base rate.
    record    -- when False, skip building the per-year ledger/schedule rows
                 (the summary fields are still computed). Monte Carlo passes
                 False so thousands of runs stay fast.
    trace     -- when True, also return `trace`: the net worth at the end of each
                 year (one float/year -- cheap even with record=False). Monte
                 Carlo uses this to build the percentile band of outcomes.
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

    # Filing status: explicit household.filing_status wins, else inferred from
    # the member count (>=2 -> MFJ, else single). Single and head-of-household
    # are both one-earner households; only MFJ has a second earner.
    status = tax_us.resolve_filing_status(cfg)
    one_earner = status != "mfj"

    infl = a["inflation_rate"]
    base_ret = a["portfolio_return_base"]
    # Standard deduction: an explicit `standard_deduction` override wins; else the
    # MFJ config key (for a couple) or the status default (single/HOH/MFJ).
    std0 = a.get("standard_deduction")
    if std0 is None:
        std0 = a.get("standard_deduction_mfj") if status == "mfj" else None
    if std0 is None:
        std0 = tax_us.standard_deduction(status)
    spend0 = a["retirement_spend_annual"]
    base_year = datetime.date.today().year

    a_age0 = current_age(cfg, "spouse_a")
    a_ret = m[0]["retirement_age"]
    a_ss = m[0]["ss_claim_age"]
    a_rmd_start = rmd_start_age(m[0]["birth_year"])
    # Spouse B drivers are neutral for a one-earner household (no second income,
    # SS, or Medicare enrollee); b_age tracks spouse A only as an unused column.
    if one_earner:
        b_age0, b_ret, b_ss = a_age0, 0, 999
    else:
        b_age0 = current_age(cfg, "spouse_b")
        b_ret, b_ss = m[1]["retirement_age"], m[1]["ss_claim_age"]

    trad = pretax_total(cfg)
    roth = roth_total(cfg)
    taxable = taxable_total(cfg)
    re_total = real_estate_total(cfg)

    # Cost basis for the taxable pool -> capital gains realized on draws. Use an
    # explicit basis if configured, else infer it from an assumed unrealized-gain
    # fraction (default 50% of the pool is embedded gain).
    gain_pct = a.get("taxable_unrealized_gain_pct", 0.5)
    taxable_basis = float(cfg["accounts"].get("taxable_cost_basis",
                                              taxable * (1.0 - gain_pct)))

    # ACA premium-tax-credit inputs (pre-65 marketplace coverage). Feature is off
    # unless a benchmark premium is configured under cfg["healthcare"].
    hc = cfg.get("healthcare", {})
    aca_benchmark0 = float(hc.get("aca_benchmark_premium_annual", 0) or 0)
    # ACA/FPL household size defaults to the number of listed members (earners +
    # any dependents); set healthcare.aca_household_size to override.
    aca_hh_size = int(hc.get("aca_household_size", len(m)) or len(m))
    aca_enhanced = bool(a.get("aca_enhanced_subsidies", False))

    pension_m, cola = inc["pension_monthly_at_retirement"], inc["pension_cola"]
    passive0 = inc["passive_income_annual"]
    b_salary0 = 0.0 if one_earner else inc["spouse_b_annual"]
    ss_a0 = cfg["social_security"]["spouse_a_monthly_benefit"] * 12
    ss_b0 = 0.0 if one_earner else cfg["social_security"]["spouse_b_monthly_benefit"] * 12

    if horizon is None:
        horizon = max(1, 90 - a_age0)
    lifetime_tax, lifetime_aca, insolvent = 0.0, 0.0, False
    ledger, schedule = [], []
    trace_out = [] if trace else None        # net worth per year (for the MC band)
    magi_history = {}                        # year_index -> MAGI, for IRMAA lookback

    # Decumulation order across the three tax buckets. Default taxable ->
    # pre-tax -> Roth (the conventional "let Roth compound longest" sequence);
    # cfg["withdrawal_order"] overrides it. Any bucket the config omits is
    # appended so the plan can always reach every dollar.
    draw_order = withdrawal_order(cfg)

    # Draw `amount` across the pools in `draw_order`, realizing proportional
    # capital gains on the taxable slice and amortizing basis. Mutates the pools
    # and the per-year draw/gain accumulators in place.
    draw_taxable = draw_trad = draw_roth = realized_gain = 0.0

    # Guyton-Klinger guardrails: ratchet real spending down/up as the current
    # withdrawal rate drifts above/below its starting level (None = off).
    gr = guardrail_params(cfg)
    guard_factor = 1.0
    guard_rate0 = None

    def _pull(amount):
        nonlocal taxable, taxable_basis, trad, roth
        nonlocal draw_taxable, draw_trad, draw_roth, realized_gain, insolvent
        short = amount
        if short <= 0:
            return
        for bucket in draw_order:
            if short <= 0:
                break
            if bucket == "taxable" and taxable > 0:
                take = min(taxable, short)
                gfrac = max(0.0, (taxable - taxable_basis) / taxable)
                realized_gain += take * gfrac
                taxable_basis -= take * (1.0 - gfrac)
                taxable -= take; short -= take; draw_taxable += take
            elif bucket == "pretax" and trad > 0:
                take = min(trad, short); trad -= take; short -= take; draw_trad += take
            elif bucket == "roth" and roth > 0:
                take = min(roth, short); roth -= take; short -= take; draw_roth += take
        if short > 1.0:
            insolvent = True

    for n in range(0, horizon + 1):
        year = base_year + n
        a_age, b_age = a_age0 + n, b_age0 + n
        r = _return_at(returns, n, base_ret)
        trad *= (1 + r); roth *= (1 + r); taxable *= (1 + r)

        if a_age < a_ret:
            # Still working -- pools grow; no draws, conversions, or retirement
            # tax modelled. A minimal ledger row preserves the accumulation
            # runway for the projection tabs.
            if record:
                ledger.append(_working_row(year, a_age, b_age, trad, roth, taxable, re_total))
            if trace:
                trace_out.append((trad, roth, taxable))
            continue

        idx = (1 + infl) ** n
        std = std0 * idx
        # Spending = inflation-adjusted base x the retirement-smile multiplier,
        # plus any lumpy one-time expenses scheduled for the year.
        recurring = spend0 * idx * spending_multiplier(cfg, a_age)
        # Guyton-Klinger guardrails adjust the recurring slice based on how the
        # current withdrawal rate compares to the rate at the start of retirement.
        if gr is not None:
            portfolio = trad + roth + taxable
            if portfolio > 0:
                if guard_rate0 is None:
                    guard_rate0 = recurring / portfolio          # anchor at retirement
                else:
                    cur_rate = recurring * guard_factor / portfolio
                    if cur_rate > guard_rate0 * (1 + gr["upper"]):
                        guard_factor *= (1 - gr["cut"])          # capital-preservation cut
                    elif cur_rate < guard_rate0 * (1 - gr["lower"]):
                        guard_factor *= (1 + gr["raise"])        # prosperity raise
        spend = recurring * guard_factor + lumpy_expense(cfg, year, idx)
        pension = pension_m * 12 * ((1 + cola) ** max(0, a_age - a_ret))
        passive = passive0 * idx
        b_work = b_salary0 * idx if b_age < b_ret else 0.0
        ss_a = ss_a0 * idx if a_age >= a_ss else 0.0
        ss_b = ss_b0 * idx if b_age >= b_ss else 0.0
        ss_total = ss_a + ss_b

        forced = min(trad * rmd_factor(a_age) if a_age >= a_rmd_start else 0.0, trad)
        non_ss = pension + passive + b_work + forced     # non-SS ordinary income

        # ---- choose the conversion amount (fills ordinary income to a ceiling) ----
        irmaa_ceiling = tax_us.irmaa_tier1_magi(year, infl, status=status)
        if strategy == "none":
            conversion = 0.0
        elif strategy == "bracket":
            bracket_top_taxable = tax_us.FEDERAL_BRACKETS[status][2][1] * idx
            ceiling_agi = bracket_top_taxable + std
            if (a_age >= tax_us.MEDICARE_AGE - tax_us.IRMAA_LOOKBACK_YEARS
                    or (not one_earner and b_age >= tax_us.MEDICARE_AGE - tax_us.IRMAA_LOOKBACK_YEARS)):
                ceiling_agi = min(ceiling_agi, irmaa_ceiling)
            conversion = max(0.0, min(ceiling_agi - non_ss, trad - forced))
        else:  # optimal -- fill to a level real target (today's $ AGI)
            ceiling_agi = target * idx
            conversion = max(0.0, min(ceiling_agi - non_ss, trad - forced))

        trad -= conversion
        roth += conversion

        # ---- Social Security taxed via provisional income (IRC sec. 86) ----
        non_ss_ord = non_ss + conversion
        ss_taxable = tax_us.ss_taxable_amount(ss_total, non_ss_ord, status=status)
        ordinary_agi = non_ss_ord + ss_taxable
        ordinary_taxable = max(0.0, ordinary_agi - std)

        # ---- ordinary income tax (fed + state) + the 2-yr-lookback IRMAA ----
        n_medicare = (1 if a_age >= tax_us.MEDICARE_AGE else 0) + \
                     (0 if one_earner else (1 if b_age >= tax_us.MEDICARE_AGE else 0))
        fed = tax_us.federal_tax(ordinary_agi, year, infl, std0, status=status)
        st = tax_us.state_tax(ordinary_agi, cfg, year, infl, ss_income=ss_taxable)
        magi_look = magi_history.get(n - tax_us.IRMAA_LOOKBACK_YEARS, ordinary_agi)
        irmaa = tax_us.irmaa_annual(magi_look, year, infl, n_enrolled=n_medicare, status=status)

        # ---- fund spending; realize capital gains on the taxable draws ----
        draw_taxable = draw_trad = draw_roth = realized_gain = 0.0
        income_cash = pension + passive + ss_total + b_work + forced
        net = income_cash - (fed + st + irmaa)
        if net >= spend:
            surplus = net - spend
            taxable += surplus; taxable_basis += surplus   # after-tax cash = basis
        else:
            _pull(spend - net)
        # capital-gains + NIIT on the gains realized while funding the shortfall
        cg_tax = tax_us.capital_gains_tax(ordinary_taxable, realized_gain, year, infl, status=status)
        magi = ordinary_agi + realized_gain
        niit_tax = tax_us.niit(realized_gain, magi, status=status)
        if cg_tax + niit_tax > 0:
            _pull(cg_tax + niit_tax)        # 2nd-pass draw to cover investment tax
        year_tax = fed + st + irmaa + cg_tax + niit_tax
        magi_history[n] = magi
        lifetime_tax += year_tax / ((1 + infl) ** n)   # present value, today's $

        # ---- ACA premium tax credit (pre-65 marketplace years) ----
        aca = 0.0
        if aca_benchmark0 > 0 and min(a_age, b_age) < tax_us.MEDICARE_AGE:
            aca = tax_us.aca_subsidy(magi, aca_hh_size, aca_benchmark0 * idx,
                                     year, infl, enhanced=aca_enhanced)
        lifetime_aca += aca / ((1 + infl) ** n)

        if record:
            # Backward-compatible schedule row (exact keys the Roth tab reads) + extras.
            schedule.append({
                "year": year, "a_age": a_age, "b_age": b_age,
                "base_ordinary": non_ss + ss_taxable, "forced": forced, "conversion": conversion,
                "agi": magi, "tax": fed + st, "irmaa": irmaa, "magi_look": magi_look,
                "cg_tax": cg_tax, "niit": niit_tax, "aca": aca,
                "trad": trad, "roth": roth,
                "over": irmaa > 0,
            })
            # Rich ledger row (income, taxes, draws, balances) for the projection tabs.
            ledger.append({
                "year": year, "a_age": a_age, "b_age": b_age, "phase": "retired",
                "pension": pension, "passive": passive, "wages": b_work,
                "ss_total": ss_total, "ss_taxable": ss_taxable, "rmd": forced,
                "conversion": conversion, "agi": ordinary_agi, "magi": magi,
                "cap_gains": realized_gain, "fed_tax": fed, "state_tax": st,
                "cg_tax": cg_tax, "niit": niit_tax, "irmaa": irmaa, "aca_subsidy": aca,
                "total_tax": year_tax, "spend": spend,
                "draw_taxable": draw_taxable, "draw_trad": draw_trad, "draw_roth": draw_roth,
                "trad": trad, "roth": roth, "taxable": taxable,
                "portfolio": trad + roth + taxable, "net_worth": trad + roth + taxable + re_total,
            })
        if trace:
            trace_out.append((trad, roth, taxable))

    # ---- terminal tax: pre-tax balance left to heirs (SECURE 10-year rule) ----
    terminal_tax = (trad * tax_us.HEIR_MARGINAL_RATE) / ((1 + infl) ** horizon)
    total_tax = lifetime_tax + terminal_tax
    # Net lifetime cost = taxes paid MINUS ACA subsidy preserved. This is what
    # the optimizer minimizes, so it won't over-convert in the 55-65 window and
    # forfeit premium tax credits.
    net_cost = total_tax - lifetime_aca
    estate = trad + roth + taxable
    return {
        "strategy": strategy, "target": target,
        "lifetime_tax": lifetime_tax, "terminal_tax": terminal_tax, "total_tax": total_tax,
        "lifetime_aca_subsidy": lifetime_aca, "net_cost": net_cost,
        "trad_end": trad, "roth_end": roth, "taxable_end": taxable, "estate_end": estate,
        "insolvent": insolvent, "ledger": ledger, "schedule": schedule, "trace": trace_out,
    }


# ---- Roth-conversion optimizer (engine core; no spreadsheet dependency) ----

def simulate_conversions(cfg, strategy, target=None):
    """Run the deterministic (base-return) projection under a conversion policy.

      "none"    -- RMDs only (do-nothing baseline)
      "bracket" -- fill to the top of the 22% bracket, IRMAA-capped in the
                   Medicare lookback window (the readable heuristic)
      "optimal" -- fill ordinary income to a level real `target` (today's $)
    """
    return simulate(cfg, strategy=strategy, target=target)


def optimize_conversions(cfg):
    """Grid-search the level real conversion target (today's $ AGI ceiling) that
    minimizes NET lifetime cost -- taxes (incl. terminal heir tax + IRMAA) minus
    the ACA premium subsidy preserved -- subject to the plan staying solvent.
    Using net cost (not tax alone) keeps the optimizer from over-converting in
    the pre-65 window and forfeiting ACA premium tax credits."""
    best = None
    for t in range(0, 400001, 5000):
        r = simulate(cfg, strategy="optimal", target=float(t))
        if r["insolvent"]:
            continue
        if best is None or r["net_cost"] < best["net_cost"]:
            best = r
    if best is None:  # nothing solvent -- fall back to the do-nothing baseline
        best = simulate(cfg, strategy="none")
    return best


def monte_carlo(cfg, *, n_sims=500, strategy="none", target=None, mu=None,
                sigma=0.12, seed=12345, bands=False):
    """Run the plan through `n_sims` random market futures and report how often
    the money lasts to the horizon. Each year's return is drawn from a normal
    distribution around the mean `mu` (default: the config's base return) with
    std dev `sigma`. Pass a lower/higher `mu` to model a cold/hot market regime.
    Uses the stdlib `random` only -- no numpy -- so it runs in the browser.
    Deterministic for a given seed, so results are reproducible.

    Returns success_rate (% of futures where the plan stays solvent to age 90)
    plus the 10th / 50th / 90th percentile ending estate. When `bands` is True,
    also returns `band`: the 10th / 50th / 90th percentile of net worth at EACH
    year -- the fan chart of outcomes."""
    a = cfg["assumptions"]
    if mu is None:
        mu = a["portfolio_return_base"]
    rng = random.Random(seed)
    a_age0 = current_age(cfg, "spouse_a")
    horizon = max(1, 90 - a_age0)
    successes, ends, traces = 0, [], []
    for _ in range(n_sims):
        path = [rng.gauss(mu, sigma) for _ in range(horizon + 1)]
        r = simulate(cfg, returns=path, strategy=strategy, target=target,
                     record=False, trace=bands)
        if not r["insolvent"]:
            successes += 1
        ends.append(r["estate_end"])
        if bands:
            traces.append(r["trace"])
    ends.sort()

    def pctile(col, p):
        return col[min(len(col) - 1, int(p / 100.0 * len(col)))] if col else 0.0

    out = {
        "n_sims": n_sims,
        "success_rate": round(100.0 * successes / n_sims, 1),
        "end_low": pctile(ends, 10), "end_median": pctile(ends, 50),
        "end_high": pctile(ends, 90),
    }
    if bands and traces:
        re_total = real_estate_total(cfg)
        band = []
        for n in range(len(traces[0])):
            pre = sorted(t[n][0] for t in traces)
            rot = sorted(t[n][1] for t in traces)
            txb = sorted(t[n][2] for t in traces)
            nw = sorted(t[n][0] + t[n][1] + t[n][2] + re_total for t in traces)
            pre_m, rot_m, txb_m = pctile(pre, 50), pctile(rot, 50), pctile(txb, 50)
            # p50 is the SUM of pool medians (= the account-stack total), so the
            # net-worth center line and the account chart agree exactly; p10/p90
            # are the net-worth range across futures.
            band.append({"age": a_age0 + n,
                         "p10": round(pctile(nw, 10)),
                         "p50": round(pre_m + rot_m + txb_m + re_total),
                         "p90": round(pctile(nw, 90)),
                         "pretax": round(pre_m), "roth": round(rot_m), "taxable": round(txb_m)})
        out["band"] = band
    return out


def _working_row(year, a_age, b_age, trad, roth, taxable, re_total):
    """A minimal pre-retirement ledger row (pools growing, no spend/tax)."""
    return {
        "year": year, "a_age": a_age, "b_age": b_age, "phase": "working",
        "pension": 0.0, "passive": 0.0, "wages": 0.0, "ss_total": 0.0,
        "ss_taxable": 0.0, "rmd": 0.0, "conversion": 0.0, "agi": 0.0, "magi": 0.0,
        "cap_gains": 0.0, "fed_tax": 0.0, "state_tax": 0.0, "cg_tax": 0.0,
        "niit": 0.0, "irmaa": 0.0, "aca_subsidy": 0.0, "total_tax": 0.0,
        "spend": 0.0, "draw_taxable": 0.0, "draw_trad": 0.0, "draw_roth": 0.0,
        "trad": trad, "roth": roth, "taxable": taxable,
        "portfolio": trad + roth + taxable, "net_worth": trad + roth + taxable + re_total,
    }
