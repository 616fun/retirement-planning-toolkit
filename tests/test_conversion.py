"""Unit tests for the Roth-conversion ladder optimizer and RMD logic."""
import copy
import pathlib

import openpyxl
import pytest
import config_loader as cl
import build_model as bm

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _cfg():
    cfg, _ = cl.load_config(str(ROOT / "config" / "examples" / "rivera_config.json"))
    return cfg


# ---- RMD table -----------------------------------------------------------
def test_rmd_start_age_by_birth_year():
    assert bm.rmd_start_age(1976) == 75      # born 1960+
    assert bm.rmd_start_age(1955) == 73      # born 1951-59
    assert bm.rmd_start_age(1945) == 72


def test_rmd_factor_zero_before_start_then_climbs():
    assert bm.rmd_factor(70) == 0.0
    assert bm.rmd_factor(72) == 0.0          # table begins at 73
    assert bm.rmd_factor(75) == pytest.approx(1 / 24.6, abs=1e-6)
    assert bm.rmd_factor(90) == pytest.approx(1 / 12.2, abs=1e-6)
    assert bm.rmd_factor(130) == pytest.approx(1 / 6.4, abs=1e-6)   # clamps to oldest


# ---- simulation invariants ----------------------------------------------
def test_simulation_invariants():
    r = bm._simulate_conversions(_cfg(), "optimal", target=150000.0)
    assert r["lifetime_tax"] > 0
    assert all(row["trad"] >= -1e-6 for row in r["schedule"])     # never goes negative
    assert all(row["conversion"] >= -1e-6 for row in r["schedule"])
    assert r["terminal_tax"] >= 0


def test_conversions_move_pretax_into_roth():
    none = bm._simulate_conversions(_cfg(), "none")
    opt = bm._simulate_conversions(_cfg(), "optimal", target=150000.0)
    # Converting shrinks the pre-tax balance at the horizon and grows Roth.
    assert opt["trad_end"] < none["trad_end"]
    assert opt["roth_end"] > none["roth_end"]


# ---- optimizer -----------------------------------------------------------
def test_optimal_beats_do_nothing():
    best = bm._optimize_conversions(_cfg())
    none = bm._simulate_conversions(_cfg(), "none")
    assert best["total_tax"] <= none["total_tax"]
    assert best["target"] is not None
    assert not best["insolvent"]


def test_heuristic_is_competitive_with_optimal():
    # The fill-to-bracket heuristic should land near (never far below) optimal.
    heur = bm._simulate_conversions(_cfg(), "bracket")
    best = bm._optimize_conversions(_cfg())
    assert best["total_tax"] <= heur["total_tax"] + 1.0       # optimal is the floor
    assert heur["total_tax"] <= 1.5 * best["total_tax"]       # heuristic within 50%


def test_optimizer_is_deterministic():
    a = bm._optimize_conversions(_cfg())
    b = bm._optimize_conversions(_cfg())
    assert a["target"] == b["target"]
    assert a["total_tax"] == pytest.approx(b["total_tax"])


def test_no_income_tax_state_costs_less_than_taxed_state():
    base = _cfg()
    notax = copy.deepcopy(base)
    notax["household"]["state_income_tax_rate"] = 0.0
    notax["household"]["local_income_tax_rate"] = 0.0
    taxed = copy.deepcopy(base)
    taxed["household"]["state_income_tax_rate"] = 0.05
    taxed["household"]["local_income_tax_rate"] = 0.0
    assert (bm._simulate_conversions(notax, "optimal", target=150000.0)["lifetime_tax"]
            < bm._simulate_conversions(taxed, "optimal", target=150000.0)["lifetime_tax"])


# ---- workbook tab --------------------------------------------------------
def test_ladder_tab_present_and_populated(tmp_path):
    wb = bm.build(_cfg())
    assert "Roth Conversion Ladder" in wb.sheetnames
    out = tmp_path / "plan.xlsx"
    wb.save(out)
    ws = openpyxl.load_workbook(out)["Roth Conversion Ladder"]
    cells = [c.value for row in ws.iter_rows() for c in row]
    assert any(isinstance(v, str) and "Lifetime-tax optimal" in v for v in cells)
    assert any(isinstance(v, str) and "Do nothing" in v for v in cells)
