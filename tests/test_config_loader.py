"""Unit tests for config loading, derived math, and validation."""
import copy
import datetime
import json
import pathlib

import pytest
import config_loader as cl

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXAMPLES = [ROOT / "config" / "config.example.json",
            ROOT / "config" / "examples" / "rivera_config.json"]


def _load(p):
    cfg, _ = cl.load_config(str(p))
    return cfg


# ---- shipped configs all parse and validate ------------------------------
@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_shipped_configs_valid(path):
    cfg = _load(path)
    assert cfg["household"]["name"]
    assert isinstance(cfg["household"]["state"], str)


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_configs_are_valid_json(path):
    json.loads(path.read_text())  # raises if malformed


# ---- derived math --------------------------------------------------------
def test_investable_excludes_529():
    cfg = {"accounts": {"spouse_a_401k_pretax": 100, "college_529_a": 50,
                        "college_529_b": 25, "cash_and_cds": 10}}
    assert cl.investable_total(cfg) == 110


def test_concentration_math():
    cfg = {"accounts": {"spouse_a_401k_pretax": 900},
           "employer_stock": {"holdings": {"x": 100}}}
    assert cl.employer_concentration_pct(cfg) == pytest.approx(11.11, abs=0.01)


def test_concentration_zero_investable_is_safe():
    cfg = {"accounts": {}, "employer_stock": {"holdings": {"x": 100}}}
    assert cl.employer_concentration_pct(cfg) == 0.0


def test_current_age():
    cfg = {"household": {"members": [{"id": "spouse_a", "birth_year": 1975}]}}
    assert cl.current_age(cfg, "spouse_a") == datetime.date.today().year - 1975


# ---- validation ----------------------------------------------------------
def _good():
    return copy.deepcopy(_load(ROOT / "config" / "examples" / "rivera_config.json"))


def test_validate_accepts_good_config():
    assert cl.validate_config(_good()) is not None


def test_load_config_validates_by_default():
    cfg = _good()
    del cfg["paths"]["model_xlsx"]
    # validate_config is invoked from load_config; bypass disk by calling directly
    with pytest.raises(cl.ConfigError):
        cl.validate_config(cfg)


def test_validate_can_be_disabled():
    # A structurally broken config still loads when validation is turned off.
    cfg, _ = cl.load_config(
        str(ROOT / "config" / "examples" / "rivera_config.json"), validate=False)
    assert cfg["household"]["name"]


def test_validate_accepts_one_member_single():
    # A single (one-member) household is valid and does NOT require the
    # spouse-B income/benefit keys.
    cfg = _good()
    cfg["household"]["filing_status"] = "single"
    cfg["household"]["members"] = cfg["household"]["members"][:1]
    del cfg["income"]["spouse_b_annual"]
    del cfg["social_security"]["spouse_b_monthly_benefit"]
    assert cl.validate_config(cfg) is not None


def test_validate_rejects_zero_members():
    cfg = _good()
    cfg["household"]["members"] = []
    with pytest.raises(cl.ConfigError) as e:
        cl.validate_config(cfg)
    assert "non-empty" in str(e.value)


def test_validate_mfj_requires_two_earners():
    cfg = _good()                       # rivera declares filing_status MFJ
    cfg["household"]["members"] = cfg["household"]["members"][:1]
    with pytest.raises(cl.ConfigError) as e:
        cl.validate_config(cfg)
    assert "requires 2 earner members" in str(e.value)


def test_validate_accepts_dependent_third_member():
    # A third member is a dependent: needs only id/display_name/birth_year and
    # bumps household size; it does not make the config invalid.
    cfg = _good()
    cfg["household"]["members"].append(
        {"id": "dependent_1", "display_name": "Kid", "birth_year": 2012})
    assert cl.validate_config(cfg) is not None


def test_validate_rejects_bad_filing_status():
    cfg = _good()
    cfg["household"]["filing_status"] = "jointish"
    with pytest.raises(cl.ConfigError) as e:
        cl.validate_config(cfg)
    assert "filing_status" in str(e.value)


def test_validate_rejects_missing_section():
    cfg = _good()
    del cfg["social_security"]
    with pytest.raises(cl.ConfigError) as e:
        cl.validate_config(cfg)
    assert "social_security" in str(e.value)


def test_validate_rejects_missing_required_key():
    cfg = _good()
    del cfg["assumptions"]["irmaa_tier1_magi_mfj"]
    with pytest.raises(cl.ConfigError) as e:
        cl.validate_config(cfg)
    assert "assumptions.irmaa_tier1_magi_mfj is required" in str(e.value)


def test_validate_rejects_nonnumeric_balance():
    cfg = _good()
    cfg["accounts"]["spouse_a_401k_pretax"] = "lots"
    with pytest.raises(cl.ConfigError) as e:
        cl.validate_config(cfg)
    assert "must be a number" in str(e.value)


def test_validate_collects_multiple_errors():
    cfg = _good()
    del cfg["paths"]["model_xlsx"]
    cfg["accounts"]["joint_brokerage"] = None
    with pytest.raises(cl.ConfigError) as e:
        cl.validate_config(cfg)
    msg = str(e.value)
    assert "paths.model_xlsx is required" in msg and "must be a number" in msg
