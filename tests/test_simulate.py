"""Unit tests for the shared simulation kernel (engine/simulate.py)."""
import pathlib

import pytest
import config_loader as cl
import simulate as sim
import build_model as bm

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _cfg():
    cfg, _ = cl.load_config(str(ROOT / "config" / "examples" / "rivera_config.json"))
    return cfg


# ---- characterization: the kernel reproduces the pre-refactor Roth results ---
# These figures were snapshotted from _simulate_conversions BEFORE the kernel
# extraction. They lock the refactor: the optimizer must not drift.
def test_reproduces_do_nothing_baseline():
    r = sim.simulate(_cfg(), strategy="none")
    assert r["total_tax"] == pytest.approx(3737720.8781, abs=0.01)
    assert r["lifetime_tax"] == pytest.approx(1839605.2437, abs=0.01)
    assert r["terminal_tax"] == pytest.approx(1898115.6344, abs=0.01)
    assert r["trad_end"] == pytest.approx(16784868.8280, abs=0.1)


def test_reproduces_bracket_heuristic():
    r = sim.simulate(_cfg(), strategy="bracket")
    assert r["total_tax"] == pytest.approx(553484.0816, abs=0.01)
    assert r["roth_end"] == pytest.approx(16974630.4653, abs=0.1)


def test_reproduces_optimizer():
    best = bm._optimize_conversions(_cfg())
    assert best["target"] == 150000.0
    assert best["total_tax"] == pytest.approx(510606.7191, abs=0.01)
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


# ---- pool helpers --------------------------------------------------------
def test_pool_helpers_partition_the_accounts():
    cfg = _cfg()
    # Pre-tax + Roth + taxable should equal investable minus HSA and 529s.
    inv = cl.investable_total(cfg)
    pools = sim.pretax_total(cfg) + sim.roth_total(cfg) + sim.taxable_total(cfg)
    hsa = cfg["accounts"].get("hsa", 0)
    assert pools == pytest.approx(inv - hsa)
