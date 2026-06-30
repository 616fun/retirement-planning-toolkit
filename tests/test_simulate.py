"""Unit tests for the shared simulation kernel (engine/simulate.py)."""
import copy
import pathlib

import pytest
import config_loader as cl
import simulate as sim
import build_model as bm

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _cfg():
    cfg, _ = cl.load_config(str(ROOT / "config" / "examples" / "rivera_config.json"))
    return cfg


# ---- characterization: Phase 1 snapshot (locks the tax model) -------------
# Snapshotted from the demo after Phase 1 (SS provisional income, capital gains
# on taxable draws, NIIT, ACA). Re-snapshot deliberately if the model changes.
def test_snapshot_do_nothing_baseline():
    r = sim.simulate(_cfg(), strategy="none")
    assert r["total_tax"] == pytest.approx(3748450.76, abs=1.0)
    assert r["trad_end"] == pytest.approx(16967559.47, abs=1.0)


def test_snapshot_bracket_heuristic():
    r = sim.simulate(_cfg(), strategy="bracket")
    assert r["total_tax"] == pytest.approx(532660.70, abs=1.0)
    assert r["roth_end"] == pytest.approx(16565604.39, abs=1.0)


def test_snapshot_optimizer():
    best = bm._optimize_conversions(_cfg())
    assert best["target"] == 170000.0
    assert best["net_cost"] == pytest.approx(490751.82, abs=1.0)
    assert len(best["schedule"]) == 34


def test_wrapper_matches_kernel():
    # build_model._simulate_conversions must be a faithful pass-through.
    a = bm._simulate_conversions(_cfg(), "optimal", target=150000.0)
    b = sim.simulate(_cfg(), strategy="optimal", target=150000.0)
    assert a["total_tax"] == pytest.approx(b["total_tax"])
    assert len(a["schedule"]) == len(b["schedule"])


# ---- single-filer support ------------------------------------------------
def _single_cfg():
    cfg, _ = cl.load_config(str(ROOT / "config" / "examples" / "avery_single_config.json"))
    return cfg


def test_single_config_simulates_end_to_end():
    r = sim.simulate(_single_cfg(), strategy="none")
    assert r["ledger"]                       # produced a full ledger
    assert r["ledger"][-1]["a_age"] == 90    # ran to the horizon
    assert not r["insolvent"]


def test_single_taxes_more_than_mfj_at_equal_income():
    # Hold spouse A's income fixed and vary ONLY the filing status: zero out
    # spouse B in the MFJ run, then drop the member entirely for the single run.
    base = _cfg()
    base["income"]["spouse_b_annual"] = 0
    base["social_security"]["spouse_b_monthly_benefit"] = 0
    mfj = sim.simulate(copy.deepcopy(base), strategy="none")

    single = copy.deepcopy(base)
    single["household"]["members"] = single["household"]["members"][:1]
    del single["income"]["spouse_b_annual"]
    del single["social_security"]["spouse_b_monthly_benefit"]
    single_run = sim.simulate(single, strategy="none")

    # Tighter single brackets + smaller standard deduction -> strictly more tax.
    assert single_run["lifetime_tax"] > mfj["lifetime_tax"]


def test_single_household_has_one_medicare_enrollee_max():
    # IRMAA is driven by at most one enrollee for a single filer; the schedule's
    # surcharge must never reflect a phantom second spouse.
    r = sim.simulate(_single_cfg(), strategy="bracket")
    # Sanity: a one-member run still builds a schedule and stays finite.
    assert r["schedule"]
    assert all(row["irmaa"] >= 0 for row in r["schedule"])


def test_single_build_model_tabs_do_not_crash():
    # The xlsx assumption + income tabs reference members[1]; for a single
    # household they must skip the spouse-B rows rather than IndexError.
    import openpyxl
    cfg = _single_cfg()
    wb = openpyxl.Workbook()
    bm.build_assumptions(wb, cfg)
    bm.build_income_note(wb, cfg)
    # Spouse A's name appears; the (absent) spouse B's display name must not.
    text = "\n".join(str(c.value) for ws in wb.worksheets for row in ws.iter_rows()
                     for c in row if c.value is not None)
    assert "Avery" in text


# ---- withdrawal sequencing (Phase 2b) ------------------------------------
def test_withdrawal_order_defaults_and_fills_missing():
    assert sim.withdrawal_order({}) == ["taxable", "pretax", "roth"]
    # A partial order keeps the requested lead and appends the rest.
    assert sim.withdrawal_order({"withdrawal_order": ["roth"]}) == ["roth", "taxable", "pretax"]
    assert sim.withdrawal_order({"withdrawal_order": ["pretax", "taxable"]}) == \
        ["pretax", "taxable", "roth"]
    # Unknown bucket names are ignored, not stranded.
    assert sim.withdrawal_order({"withdrawal_order": ["bogus", "roth"]}) == \
        ["roth", "taxable", "pretax"]


def _first_drawing_row(r):
    """The first ledger row that pulls anything from the portfolio."""
    for row in r["ledger"]:
        if row["draw_taxable"] + row["draw_trad"] + row["draw_roth"] > 1:
            return row
    return None


def test_withdrawal_order_changes_which_bucket_is_hit_first():
    # Over a long horizon with growth, cumulative draws are non-monotonic (a
    # pool left untouched keeps compounding). The order's effect is clearest on
    # the FIRST year money is pulled: that bucket is decided purely by the order.
    base = _cfg()
    base["assumptions"]["retirement_spend_annual"] = 220000   # force real draws

    default = _first_drawing_row(sim.simulate(copy.deepcopy(base), strategy="none"))
    assert default["draw_taxable"] > 0 and default["draw_roth"] == 0   # taxable first

    rf_cfg = copy.deepcopy(base); rf_cfg["withdrawal_order"] = ["roth", "pretax", "taxable"]
    rf = _first_drawing_row(sim.simulate(rf_cfg, strategy="none"))
    assert rf["draw_roth"] > 0 and rf["draw_taxable"] == 0             # Roth first

    pt_cfg = copy.deepcopy(base); pt_cfg["withdrawal_order"] = ["pretax", "taxable", "roth"]
    pt = _first_drawing_row(sim.simulate(pt_cfg, strategy="none"))
    assert pt["draw_trad"] > 0 and pt["draw_roth"] == 0               # pre-tax first


def test_withdrawal_order_keeps_plan_solvent():
    # Reordering the buckets shifts WHERE money comes from; a solvent default
    # plan stays solvent under an alternative order.
    base = _cfg()
    base["assumptions"]["retirement_spend_annual"] = 200000
    a = sim.simulate(copy.deepcopy(base), strategy="none")
    b_cfg = copy.deepcopy(base); b_cfg["withdrawal_order"] = ["pretax", "taxable", "roth"]
    b = sim.simulate(b_cfg, strategy="none")
    assert not a["insolvent"] and not b["insolvent"]


def test_invalid_withdrawal_order_rejected():
    cfg = _cfg()
    cfg["withdrawal_order"] = ["roth", "bonds"]
    with pytest.raises(cl.ConfigError) as e:
        cl.validate_config(cfg)
    assert "withdrawal_order" in str(e.value)


# ---- ledger contract -----------------------------------------------------
def test_ledger_covers_every_year_to_horizon():
    cfg = _cfg()
    r = sim.simulate(cfg)
    a_age0 = sim.current_age(cfg, "spouse_a")
    horizon = 90 - a_age0
    assert len(r["ledger"]) == horizon + 1          # year 0..horizon inclusive
    assert r["ledger"][0]["a_age"] == a_age0
    assert r["ledger"][-1]["a_age"] == 90


def test_ledger_has_working_then_retired_phases():
    cfg = _cfg()
    r = sim.simulate(cfg)
    phases = [row["phase"] for row in r["ledger"]]
    assert "working" in phases and "retired" in phases
    # working years never carry spend or tax; retired years carry spend.
    for row in r["ledger"]:
        if row["phase"] == "working":
            assert row["spend"] == 0 and row["total_tax"] == 0
    assert any(row["spend"] > 0 for row in r["ledger"] if row["phase"] == "retired")


def test_schedule_is_retirement_subset_of_ledger():
    r = sim.simulate(_cfg(), strategy="optimal", target=150000.0)
    retired_rows = [row for row in r["ledger"] if row["phase"] == "retired"]
    assert len(r["schedule"]) == len(retired_rows)


def test_balances_never_negative():
    r = sim.simulate(_cfg(), strategy="optimal", target=150000.0)
    for row in r["ledger"]:
        assert row["trad"] >= -1e-6
        assert row["roth"] >= -1e-6
        assert row["taxable"] >= -1e-6


# ---- return-path parametrization (the Monte Carlo hook) ------------------
def test_constant_returns_arg_matches_default():
    cfg = _cfg()
    base = cfg["assumptions"]["portfolio_return_base"]
    default = sim.simulate(cfg, strategy="none")
    explicit = sim.simulate(cfg, strategy="none", returns=base)
    assert default["total_tax"] == pytest.approx(explicit["total_tax"])


def test_higher_returns_leave_more_pretax_and_more_terminal_tax():
    cfg = _cfg()
    lo = sim.simulate(cfg, strategy="none", returns=0.03)
    hi = sim.simulate(cfg, strategy="none", returns=0.09)
    assert hi["trad_end"] > lo["trad_end"]
    assert hi["terminal_tax"] > lo["terminal_tax"]


def test_callable_return_path_is_accepted():
    cfg = _cfg()
    r = sim.simulate(cfg, strategy="none", returns=lambda n: 0.05)
    assert r["total_tax"] > 0
    assert len(r["ledger"]) > 0


# ---- Monte Carlo (pure-stdlib; runs in the browser) ----------------------
def test_monte_carlo_shape_and_determinism():
    cfg = _cfg()
    m1 = sim.monte_carlo(cfg, n_sims=200, strategy="optimal", target=170000.0)
    m2 = sim.monte_carlo(cfg, n_sims=200, strategy="optimal", target=170000.0)
    assert 0.0 <= m1["success_rate"] <= 100.0
    assert m1["success_rate"] == m2["success_rate"]          # fixed seed -> reproducible
    assert m1["end_low"] <= m1["end_median"] <= m1["end_high"]


def test_monte_carlo_uses_no_numpy():
    # MC must stay pure-Python so it runs in the browser (Pyodide) deps-free.
    import subprocess, sys
    code = ("import sys; sys.path.insert(0,'engine'); import json, simulate; "
            "cfg=json.load(open('config/examples/rivera_config.json')); "
            "simulate.monte_carlo(cfg, n_sims=50); "
            "assert 'numpy' not in sys.modules, 'numpy leaked into MC'")
    subprocess.run([sys.executable, "-c", code], check=True, cwd=ROOT)


def test_record_false_skips_ledger_but_keeps_summary():
    cfg = _cfg()
    full = sim.simulate(cfg, strategy="none")
    light = sim.simulate(cfg, strategy="none", record=False)
    assert light["ledger"] == [] and light["schedule"] == []
    assert light["net_cost"] == pytest.approx(full["net_cost"])   # summary unchanged
    assert light["trad_end"] == pytest.approx(full["trad_end"])


def test_monte_carlo_band_is_ordered_per_year():
    cfg = _cfg()
    m = sim.monte_carlo(cfg, n_sims=200, strategy="optimal", target=170000.0, bands=True)
    assert "band" in m and len(m["band"]) > 20
    first, last = m["band"][0], m["band"][-1]
    assert first["age"] < last["age"]
    for row in m["band"]:                              # p10 <= p50 <= p90 every year
        assert row["p10"] <= row["p50"] <= row["p90"]


def test_trace_length_matches_horizon():
    cfg = _cfg()
    r = sim.simulate(cfg, strategy="none", trace=True, record=False)
    horizon = 90 - sim.current_age(cfg, "spouse_a")
    assert len(r["trace"]) == horizon + 1


def test_monte_carlo_mu_override():
    # A cold-market mean (lower mu) never beats a hot-market mean.
    cfg = _cfg()
    lo = sim.monte_carlo(cfg, n_sims=300, mu=0.03)
    hi = sim.monte_carlo(cfg, n_sims=300, mu=0.10)
    assert hi["success_rate"] >= lo["success_rate"]


def test_worse_returns_lower_success():
    # A household on the edge: higher volatility / lower return -> lower success.
    cfg = _cfg()
    cfg["assumptions"]["retirement_spend_annual"] = 180000   # stress it
    hi = sim.monte_carlo(cfg, n_sims=300, strategy="none", sigma=0.08)
    lo = sim.monte_carlo(cfg, n_sims=300, strategy="none", sigma=0.20)
    assert lo["success_rate"] <= hi["success_rate"]


# ---- pool helpers --------------------------------------------------------
def test_pool_helpers_partition_the_accounts():
    cfg = _cfg()
    # Pre-tax + Roth + taxable should equal investable minus HSA and 529s.
    inv = cl.investable_total(cfg)
    pools = sim.pretax_total(cfg) + sim.roth_total(cfg) + sim.taxable_total(cfg)
    hsa = cfg["accounts"].get("hsa", 0)
    assert pools == pytest.approx(inv - hsa)


# ---- spending model: smile + lumpy expenses (Phase 2a) -------------------
SMILE = {"phases": [{"until_age": 75, "multiplier": 1.0},
                    {"until_age": 85, "multiplier": 0.85},
                    {"until_age": 999, "multiplier": 0.95}]}


def test_spending_multiplier_flat_without_config():
    assert sim.spending_multiplier({}, 70) == 1.0


def test_spending_multiplier_follows_phases():
    cfg = {"spending": SMILE}
    assert sim.spending_multiplier(cfg, 70) == 1.0      # go-go
    assert sim.spending_multiplier(cfg, 80) == 0.85     # slow-go
    assert sim.spending_multiplier(cfg, 90) == 0.95     # no-go


def test_lumpy_expense_hits_the_right_year_inflation_adjusted():
    cfg = {"spending": {"lumpy": [{"year": 2034, "amount": 40000}]}}
    assert sim.lumpy_expense(cfg, 2033, 1.1) == 0.0
    assert sim.lumpy_expense(cfg, 2034, 1.0) == pytest.approx(40000)
    assert sim.lumpy_expense(cfg, 2034, 1.2) == pytest.approx(48000)   # inflated


def test_smile_lowers_midretirement_spend_in_ledger():
    flat = _cfg()
    smiled = copy.deepcopy(flat)
    smiled["spending"] = SMILE
    fr = {r["a_age"]: r["spend"] for r in sim.simulate(flat)["ledger"]}
    sr = {r["a_age"]: r["spend"] for r in sim.simulate(smiled)["ledger"]}
    assert sr[80] < fr[80]                       # slow-go years spend less
    assert sr[70] == pytest.approx(fr[70])       # go-go unchanged


def test_lumpy_expense_spikes_one_year_of_spend():
    base = _cfg()
    lumped = copy.deepcopy(base)
    lumped["spending"] = {"lumpy": [{"year": 2034, "amount": 50000}]}
    b = {r["year"]: r["spend"] for r in sim.simulate(base)["ledger"]}
    L = {r["year"]: r["spend"] for r in sim.simulate(lumped)["ledger"]}
    assert L[2034] > b[2034]                      # spike in the lumpy year
    assert L[2035] == pytest.approx(b[2035])      # neighbours unchanged


def test_no_spending_block_preserves_baseline():
    # Backward compatibility: absent spending block == flat (snapshot intact).
    assert "spending" not in _cfg()
    r = sim.simulate(_cfg(), strategy="none")
    assert r["total_tax"] == pytest.approx(3748450.76, abs=1.0)
