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
    assert r["total_tax"] == pytest.approx(3747670.76, abs=1.0)
    assert r["trad_end"] == pytest.approx(16967559.47, abs=1.0)


def test_snapshot_bracket_heuristic():
    r = sim.simulate(_cfg(), strategy="bracket")
    assert r["total_tax"] == pytest.approx(532642.70, abs=1.0)
    assert r["roth_end"] == pytest.approx(16565762.12, abs=1.0)


def test_snapshot_optimizer():
    best = bm._optimize_conversions(_cfg())
    assert best["target"] == 170000.0
    assert best["net_cost"] == pytest.approx(490748.62, abs=1.0)
    assert len(best["schedule"]) == 34


def test_wrapper_matches_kernel():
    # build_model._simulate_conversions must be a faithful pass-through.
    a = bm._simulate_conversions(_cfg(), "optimal", target=150000.0)
    b = sim.simulate(_cfg(), strategy="optimal", target=150000.0)
    assert a["total_tax"] == pytest.approx(b["total_tax"])
    assert len(a["schedule"]) == len(b["schedule"])


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
    assert r["total_tax"] == pytest.approx(3747670.76, abs=1.0)
