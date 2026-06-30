"""Unit tests for the Social Security claim-age optimizer (engine/ss_claiming.py)."""
import copy
import pathlib

import pytest
import config_loader as cl
import ss_claiming as ss

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _cfg(name="rivera_config.json"):
    cfg, _ = cl.load_config(str(ROOT / "config" / "examples" / name))
    return cfg


# ---- Full Retirement Age ---------------------------------------------------
def test_full_retirement_age_by_birth_year():
    assert ss.full_retirement_age(1976) == 67.0      # 1960+
    assert ss.full_retirement_age(1960) == 67.0
    assert ss.full_retirement_age(1954) == 66.0
    assert ss.full_retirement_age(1958) == pytest.approx(66 + 8 / 12.0)  # 66 + 8 months
    assert ss.full_retirement_age(1937) == 65.0


# ---- SSA reduction / credit schedule --------------------------------------
def test_claim_factor_anchor_points():
    # The canonical SSA figures for an FRA of 67.
    assert ss.claim_factor(67, 67) == 1.0
    assert ss.claim_factor(62, 67) == pytest.approx(0.70)    # 30% reduction
    assert ss.claim_factor(70, 67) == pytest.approx(1.24)    # 24% delayed credit
    assert ss.claim_factor(66, 67) == pytest.approx(1 - 5 / 9 / 100 * 12)  # 1 yr early


def test_claim_factor_is_monotonic_in_age():
    prev = -1.0
    for age in range(62, 71):
        f = ss.claim_factor(age, 67)
        assert f > prev
        prev = f


def test_credits_stop_accruing_at_70():
    # No extra credit past 70 (the schedule caps there).
    assert ss.claim_factor(71, 67) == ss.claim_factor(70, 67)


def test_pia_round_trip():
    fra = 67
    for claim in (62, 65, 67, 69, 70):
        pia = ss.pia_from_benefit(2000.0, claim, fra)
        assert ss.benefit_at_claim(pia, claim, fra) == pytest.approx(2000.0)


# ---- the optimizer ---------------------------------------------------------
def test_optimizer_returns_valid_recommendation():
    best = ss.optimize_ss_claim_ages(_cfg())
    assert 62 <= best["a_claim"] <= 70 and 62 <= best["b_claim"] <= 70
    assert best["grid"]                                   # full grid returned
    assert best["a_fra"] == 67.0
    # The optimizer never recommends a combination worse than the configured one.
    assert best["gain_vs_configured"] >= 0
    assert best["pv"] >= best["baseline_pv"]


def test_optimizer_maximizes_pv_over_the_grid():
    best = ss.optimize_ss_claim_ages(_cfg())
    solvent = [g for g in best["grid"] if not g["insolvent"]]
    assert best["pv"] == max(g["pv"] for g in solvent)


def test_single_household_only_sweeps_one_claim_age():
    best = ss.optimize_ss_claim_ages(_cfg("avery_single_config.json"))
    assert best["one_earner"] is True
    # Spouse B is not modelled: its claim age never varies off the configured value.
    assert {g["b_claim"] for g in best["grid"]} == {best["configured"]["b_claim"]}
    assert len(best["grid"]) == 9                         # ages 62..70 for the one earner


def test_optimizer_recommendation_is_solvent_when_possible():
    best = ss.optimize_ss_claim_ages(_cfg())
    assert any(not g["insolvent"] for g in best["grid"])
    rec = next(g for g in best["grid"]
               if g["a_claim"] == best["a_claim"] and g["b_claim"] == best["b_claim"])
    assert not rec["insolvent"]                           # never recommend a bust plan


def test_optimizer_falls_back_to_configured_when_nothing_solvent():
    # Unsolvable household (no assets, very high spend) -> keep the status quo.
    cfg = _cfg()
    cfg["accounts"] = {k: 0 for k in cfg["accounts"]}
    cfg["assumptions"]["retirement_spend_annual"] = 200000
    best = ss.optimize_ss_claim_ages(cfg)
    assert all(g["insolvent"] for g in best["grid"])
    assert (best["a_claim"], best["b_claim"]) == \
        (best["configured"]["a_claim"], best["configured"]["b_claim"])
