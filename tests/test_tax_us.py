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
    assert t1 == pytest.approx(2 * 1148)   # 2026 CMS
    assert t2 == pytest.approx(2 * 2885)
    assert t4 == pytest.approx(2 * 6356)
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


# ---- Social Security taxation (IRC sec. 86) ------------------------------
def test_ss_taxable_tiers():
    ss = 40000
    assert tax_us.ss_taxable_amount(ss, 0) == 0.0               # all under base 1
    assert tax_us.ss_taxable_amount(ss, 30000) == pytest.approx(11100, abs=1)
    assert tax_us.ss_taxable_amount(ss, 200000) == pytest.approx(0.85 * ss, abs=1)


def test_ss_taxable_is_monotonic_and_capped():
    ss, prev = 50000, -1.0
    for other in (0, 20000, 40000, 60000, 100000):
        v = tax_us.ss_taxable_amount(ss, other)
        assert v >= prev and v <= 0.85 * ss + 1e-6
        prev = v


def test_ss_thresholds_are_not_indexed():
    assert tax_us.SS_PI_BASE1_MFJ == 32000.0 and tax_us.SS_PI_BASE2_MFJ == 44000.0


# ---- capital gains (stacked on ordinary taxable income) ------------------
def test_zero_gain_is_zero():
    assert tax_us.capital_gains_tax(50000, 0) == 0.0


def test_gain_in_zero_bracket_when_income_low():
    assert tax_us.capital_gains_tax(0, 50000) == 0.0           # whole gain at 0%


def test_gain_crosses_into_15_and_20():
    assert tax_us.capital_gains_tax(650000, 100000) == pytest.approx(20000, abs=5)
    t = tax_us.capital_gains_tax(90000, 100000)               # straddles 0%/15%
    assert 0 < t < 15000


# ---- NIIT ----------------------------------------------------------------
def test_niit_below_threshold_is_zero():
    assert tax_us.niit(80000, 200000) == 0.0


def test_niit_is_lesser_of_nii_and_excess():
    assert tax_us.niit(80000, 300000) == pytest.approx(0.038 * 50000)   # excess binds
    assert tax_us.niit(20000, 500000) == pytest.approx(0.038 * 20000)   # NII binds


# ---- ACA premium tax credit ----------------------------------------------
def test_aca_off_without_benchmark():
    assert tax_us.aca_subsidy(40000, 2, 0) == 0.0


def test_aca_subsidy_falls_as_income_rises():
    assert tax_us.aca_subsidy(40000, 2, 18000) > tax_us.aca_subsidy(70000, 2, 18000) > 0


def test_aca_cliff_under_current_law():
    fpl = tax_us.federal_poverty_level(2)
    assert tax_us.aca_subsidy(4.0 * fpl - 500, 2, 18000, enhanced=False) > 0
    assert tax_us.aca_subsidy(4.0 * fpl + 500, 2, 18000, enhanced=False) == 0.0  # cliff


def test_aca_enhanced_has_no_cliff():
    fpl = tax_us.federal_poverty_level(2)
    assert tax_us.aca_subsidy(4.0 * fpl + 5000, 2, 18000, enhanced=True) > 0.0


# ---- single filer (filing-status switch) ---------------------------------
def test_normalize_status_and_defaults():
    assert tax_us.normalize_status("single") == "single"
    assert tax_us.normalize_status("MFJ") == "mfj"
    assert tax_us.normalize_status(None) == "mfj"          # default
    assert tax_us.normalize_status("married") == "mfj"
    assert tax_us.standard_deduction("single") == tax_us.STANDARD_DEDUCTION_SINGLE
    assert tax_us.standard_deduction() == tax_us.STANDARD_DEDUCTION_MFJ


def test_single_pays_more_federal_than_mfj():
    # Tighter brackets + smaller standard deduction -> strictly more tax.
    for agi in (60000, 120000, 250000, 500000):
        assert tax_us.federal_tax(agi, status="single") > tax_us.federal_tax(agi)


def test_single_known_bracket_math():
    # AGI 100k, single std 16.1k -> taxable 83.9k.
    # 10%*12,400 + 12%*38,000 + 22%*33,500 = 1,240 + 4,560 + 7,370 = 13,170.
    assert tax_us.federal_tax(100000, status="single") == pytest.approx(13170, abs=1)


def test_single_irmaa_floor_is_lower():
    # $120k MAGI: no surcharge for MFJ (floor $218k) but Tier 1 for single ($109k).
    assert tax_us.irmaa_annual(120000, n_enrolled=1) == 0.0
    assert tax_us.irmaa_annual(120000, n_enrolled=1, status="single") == pytest.approx(1148)
    assert tax_us.irmaa_tier1_magi(status="single") == pytest.approx(109000)


def test_single_ss_thresholds_bite_earlier():
    full = tax_us.ss_taxable_amount(40000, 30000)                  # MFJ bases 32k/44k
    more = tax_us.ss_taxable_amount(40000, 30000, status="single")  # single bases 25k/34k
    assert more > full
    assert tax_us.SS_PI_BASE1_SINGLE == 25000.0 and tax_us.SS_PI_BASE2_SINGLE == 34000.0


def test_single_niit_threshold_is_200k():
    assert tax_us.niit(50000, 220000) == 0.0                            # under MFJ $250k
    assert tax_us.niit(50000, 220000, status="single") == pytest.approx(0.038 * 20000)


def test_single_ltcg_zero_bracket_is_smaller():
    # A $60k gain on zero ordinary income is all 0% for MFJ but spills into 15%
    # for single (0% top ~$49.5k).
    assert tax_us.capital_gains_tax(0, 60000) == 0.0
    assert tax_us.capital_gains_tax(0, 60000, status="single") > 0.0


# ---- head of household ----------------------------------------------------
def test_normalize_status_hoh():
    assert tax_us.normalize_status("hoh") == "hoh"
    assert tax_us.normalize_status("head_of_household") == "hoh"
    assert tax_us.normalize_status("Head-of-Household") == "hoh"
    assert tax_us.standard_deduction("hoh") == 24150


def test_hoh_federal_sits_between_mfj_and_single():
    # More favorable than single, less than MFJ, at a middling income.
    for agi in (90000, 120000, 180000):
        mfj = tax_us.federal_tax(agi)
        hoh = tax_us.federal_tax(agi, status="hoh")
        single = tax_us.federal_tax(agi, status="single")
        assert mfj < hoh < single


def test_hoh_shares_single_irmaa_ss_niit():
    # HOH has no separate IRMAA / SS §86 / NIIT tier -- it uses the single amounts.
    assert tax_us.irmaa_annual(120000, n_enrolled=1, status="hoh") == \
        tax_us.irmaa_annual(120000, n_enrolled=1, status="single")
    assert tax_us.ss_taxable_amount(40000, 30000, status="hoh") == \
        tax_us.ss_taxable_amount(40000, 30000, status="single")
    assert tax_us.niit(50000, 220000, status="hoh") == \
        tax_us.niit(50000, 220000, status="single")


def test_hoh_has_its_own_ltcg_breakpoints():
    # A $60k gain on no ordinary income: 0% for HOH (top $66,200) but taxed for
    # single (top $49,450).
    assert tax_us.capital_gains_tax(0, 60000, status="hoh") == 0.0
    assert tax_us.capital_gains_tax(0, 60000, status="single") > 0.0
    assert [e for _, e in tax_us.CAP_GAINS_BRACKETS_HOH] == [66200, 579600, None]


def test_resolve_filing_status():
    mk = lambda n, fs=None: {"household": {"members": [{}] * n, **({"filing_status": fs} if fs else {})}}
    assert tax_us.resolve_filing_status(mk(2)) == "mfj"       # inferred
    assert tax_us.resolve_filing_status(mk(1)) == "single"    # inferred
    assert tax_us.resolve_filing_status(mk(1, "hoh")) == "hoh"          # declared wins
    assert tax_us.resolve_filing_status(mk(2, "single")) == "single"    # declared wins


# ---- verified 2026 constants (drift guard for the annual re-verification) --
# These lock the figures confirmed/corrected on 2026-06-30 against Rev. Proc.
# 2025-32 and the CMS 2026 IRMAA fact sheet (see docs/US_RULES.md verification
# log). If a value here changes, re-confirm it against the primary source and
# bump the log rather than just editing the number.
def test_verified_2026_federal_and_std_deduction():
    assert [b[1] for b in tax_us.FEDERAL_BRACKETS_MFJ] == \
        [24800, 100800, 211400, 403550, 512450, 768700, None]
    assert [b[1] for b in tax_us.FEDERAL_BRACKETS_SINGLE] == \
        [12400, 50400, 105700, 201775, 256225, 640600, None]
    assert tax_us.STANDARD_DEDUCTION_MFJ == 32200
    assert tax_us.STANDARD_DEDUCTION_SINGLE == 16100


def test_verified_2026_irmaa():
    assert [f for f, _ in tax_us.IRMAA_MFJ] == [0, 218000, 274000, 342000, 410000, 750000]
    assert [f for f, _ in tax_us.IRMAA_SINGLE] == [0, 109000, 137000, 171000, 205000, 500000]
    # Per-person annual surcharge dollars are identical across filing status.
    assert [s for _, s in tax_us.IRMAA_MFJ] == [0.0, 1148.0, 2885.0, 4620.0, 6356.0, 6936.0]
    assert [s for _, s in tax_us.IRMAA_SINGLE] == [s for _, s in tax_us.IRMAA_MFJ]


def test_verified_2026_ltcg_and_fpl():
    assert [e for _, e in tax_us.CAP_GAINS_BRACKETS_MFJ] == [98900, 613700, None]
    assert [e for _, e in tax_us.CAP_GAINS_BRACKETS_SINGLE] == [49450, 545500, None]
    assert tax_us.FPL_BASE_1PERSON == 15650.0
    assert tax_us.FPL_PER_ADDL_PERSON == 5500.0
