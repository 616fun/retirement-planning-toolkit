"""Unit tests for the US tax engine (federal brackets, IRMAA, hybrid state)."""
import pytest
import tax_us


# A flat-tax (Indiana-like) household, and a no-income-tax one.
FLAT = {"household": {"state_income_tax_rate": 0.03, "local_income_tax_rate": 0.0},
        "assumptions": {"standard_deduction_mfj": tax_us.STANDARD_DEDUCTION_MFJ}}
NOTAX = {"household": {"state_income_tax_rate": 0.0, "local_income_tax_rate": 0.0},
         "assumptions": {"standard_deduction_mfj": tax_us.STANDARD_DEDUCTION_MFJ}}


# ---- federal brackets ----------------------------------------------------
def test_zero_and_below_deduction_is_zero():
    assert tax_us.federal_tax(0) == 0.0
    assert tax_us.federal_tax(tax_us.STANDARD_DEDUCTION_MFJ) == 0.0


def test_federal_is_monotonic_and_progressive():
    prev = -1.0
    last_avg = 0.0
    for agi in (40000, 80000, 150000, 250000, 500000, 900000):
        t = tax_us.federal_tax(agi)
        assert t > prev                      # strictly increasing
        avg = t / agi
        assert avg >= last_avg - 1e-9        # average rate never falls
        last_avg = avg
        prev = t


def test_known_bracket_math():
    # AGI 200k, std deduction 32.2k -> taxable 167.8k.
    # 10%*24,800 + 12%*76,000 + 22%*67,000 = 2,480 + 9,120 + 14,740 = 26,340.
    assert tax_us.federal_tax(200000) == pytest.approx(26340, abs=1)


def test_marginal_rate_climbs_with_income():
    assert tax_us.marginal_rate(60000, FLAT) == pytest.approx(0.15, abs=0.005)   # 12% + 3%
    assert tax_us.marginal_rate(200000, FLAT) == pytest.approx(0.25, abs=0.005)  # 22% + 3%
    assert tax_us.marginal_rate(250000, FLAT) == pytest.approx(0.27, abs=0.005)  # 24% + 3%


def test_standard_deduction_reduces_tax():
    small = tax_us.federal_tax(120000, std_deduction=10000)
    large = tax_us.federal_tax(120000, std_deduction=40000)
    assert large < small


def test_inflation_indexing_lowers_future_real_tax():
    # Same nominal AGI taxed in a later year (brackets indexed up) -> less tax.
    now = tax_us.federal_tax(200000, year=2026)
    later = tax_us.federal_tax(200000, year=2046, infl=0.02)
    assert later < now


# ---- IRMAA ---------------------------------------------------------------
def test_irmaa_zero_below_threshold_and_when_unenrolled():
    assert tax_us.irmaa_annual(200000, n_enrolled=2) == 0.0          # under Tier 1
    assert tax_us.irmaa_annual(500000, n_enrolled=0) == 0.0          # nobody on Medicare


def test_irmaa_tiers_step_up():
    t1 = tax_us.irmaa_annual(230000, n_enrolled=2)
    t2 = tax_us.irmaa_annual(300000, n_enrolled=2)
    t4 = tax_us.irmaa_annual(420000, n_enrolled=2)
    assert t1 == pytest.approx(2 * 1143)
    assert t2 == pytest.approx(2 * 2867)
    assert t4 == pytest.approx(2 * 6306)
    assert t1 < t2 < t4


def test_irmaa_scales_with_enrollees():
    one = tax_us.irmaa_annual(300000, n_enrolled=1)
    two = tax_us.irmaa_annual(300000, n_enrolled=2)
    assert two == pytest.approx(2 * one)


def test_irmaa_tier1_floor_indexes_up():
    assert tax_us.irmaa_tier1_magi(2046, infl=0.02) > tax_us.irmaa_tier1_magi(2026)


# ---- hybrid state --------------------------------------------------------
def test_flat_state_applies_combined_rate():
    # State base excludes Social Security; 3% + 0% local on 100k ordinary.
    assert tax_us.state_tax(100000, FLAT) == pytest.approx(3000)


def test_no_tax_state_is_zero():
    assert tax_us.state_tax(300000, NOTAX) == 0.0


def test_state_excludes_social_security():
    full = tax_us.state_tax(100000, FLAT, ss_income=0)
    less = tax_us.state_tax(100000, FLAT, ss_income=40000)
    assert less < full
    assert less == pytest.approx(0.03 * 60000)


def test_optional_progressive_state_brackets():
    cfg = {"household": {"state_income_tax_rate": 0.05, "local_income_tax_rate": 0.0,
                         "state_brackets": [[0.02, 50000], [0.05, 100000], [0.07, None]]},
           "assumptions": {}}
    # 2%*50,000 + 5%*50,000 + 7%*50,000 = 1,000 + 2,500 + 3,500 = 7,000 on 150k.
    assert tax_us.state_tax(150000, cfg) == pytest.approx(7000)
    # Progressive path ignores the flat state_income_tax_rate entirely.
    assert tax_us.state_tax(150000, cfg) != pytest.approx(0.05 * 150000)


# ---- combined ------------------------------------------------------------
def test_total_tax_sums_components():
    agi = 300000
    expect = (tax_us.federal_tax(agi)
              + tax_us.state_tax(agi, FLAT)
              + tax_us.irmaa_annual(agi, n_enrolled=2))
    assert tax_us.total_tax(agi, FLAT, magi=agi, n_medicare=2) == pytest.approx(expect)
