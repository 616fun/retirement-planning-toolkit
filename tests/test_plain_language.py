"""Tests for the plain-English layer -- including an enforced reading level."""
import copy
import pathlib

import pytest
import config_loader as cl
import plain_language as pl

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _cfg():
    cfg, _ = cl.load_config(str(ROOT / "config" / "examples" / "rivera_config.json"))
    return cfg


# ---- reading level (the measurable "approachable" standard) ---------------
def test_summary_reads_at_eighth_grade_or_easier():
    text = pl.plain_text(_cfg())
    grade = pl.readability_grade(text)
    # 8th grade is the US median; allow a little slack for unavoidable finance
    # words ("retire", "account"). If this fails, the wording got too complex.
    assert grade <= 9.0, f"plan summary reads at grade {grade:.1f} (target <= 9)"


def test_readability_grade_orders_simple_below_complex():
    simple = "The cat sat on the mat. It was a good day."
    complex_ = ("Notwithstanding the aforementioned considerations, the actuarial "
                "implications necessitate comprehensive recalibration.")
    assert pl.readability_grade(simple) < pl.readability_grade(complex_)


def test_syllable_counter_is_sane():
    assert pl._count_syllables("cat") == 1
    assert pl._count_syllables("retire") == 2
    assert pl._count_syllables("") == 0


# ---- money formatting (no false precision) -------------------------------
def test_money_is_rounded_and_friendly():
    assert pl._money(170000) == "$170,000"
    assert pl._money(3257114) == "$3.3 million"
    assert pl._money(1840) == "$1,800"


# ---- glossary ------------------------------------------------------------
def test_glossary_covers_the_scary_terms():
    for term in ("roth conversion", "irmaa", "rmd", "aca subsidy", "capital gains"):
        assert pl.explain(term)                      # non-empty plain explanation
    assert pl.explain("nonexistent term") == ""


# ---- plan summary structure ----------------------------------------------
def test_plan_summary_has_human_fields():
    p = pl.plan_summary(_cfg())
    assert p["color"] in ("green", "yellow", "red")
    assert p["headline"] and isinstance(p["headline"], str)
    assert p["retire_age"] == 57
    assert p["actions"] and p["watch"]
    assert "Roth" in " ".join(p["actions"])          # the headline move is named
    assert isinstance(p["narrative"], str) and len(p["narrative"]) > 100


def test_demo_household_is_on_track():
    p = pl.plan_summary(_cfg())
    assert p["color"] == "green"
    assert "on track" in p["headline"].lower()


def test_struggling_household_is_flagged_not_green():
    # Tiny savings, high spend -> the plan should not say "on track".
    cfg = copy.deepcopy(_cfg())
    for k in list(cfg["accounts"]):
        cfg["accounts"][k] = 0
    cfg["accounts"]["spouse_a_trad_ira"] = 50000
    cfg["assumptions"]["retirement_spend_annual"] = 150000
    p = pl.plan_summary(cfg)
    assert p["color"] in ("yellow", "red")


def test_full_report_exposes_the_evidence():
    r = pl.full_report(_cfg())
    # the plain plan is still there...
    assert r["plan"]["color"] in ("green", "yellow", "red")
    # ...plus the numbers behind it: do-nothing vs recommended, and the saving
    c = r["comparison"]
    assert c["do_nothing"]["net_cost"] >= c["recommended"]["net_cost"]
    assert c["lifetime_saved"] == pytest.approx(
        max(0.0, c["do_nothing"]["net_cost"] - c["recommended"]["net_cost"]))
    # year-by-year series covers the plan and carries real per-year numbers
    assert len(r["series"]) > 20
    retired = [row for row in r["series"] if row["phase"] == "retired"]
    assert retired and all("net_worth" in row and "tax" in row for row in retired)
    # assumptions are echoed back for transparency
    for k in ("return_pct", "inflation_pct", "state_tax_pct", "planned_to_age"):
        assert k in r["assumptions"]


def test_full_report_monte_carlo_three_regimes():
    mc = pl.full_report(_cfg())["monte_carlo"]
    sc = mc["scenarios"]
    assert set(sc) == {"bad", "normal", "good"} and mc["default"] == "normal"
    for k in sc:
        assert 0.0 <= sc[k]["success_rate"] <= 100.0
        assert sc[k]["color"] in ("green", "yellow", "red")
        assert sc[k]["message"] and sc[k]["n_sims"] > 0 and sc[k]["label"]
    # a good market never does worse than a normal one, which never beats... down
    assert (sc["good"]["success_rate"] >= sc["normal"]["success_rate"]
            >= sc["bad"]["success_rate"])
    # each scenario carries its own savings band for the chart
    for k in sc:
        assert sc[k]["band"] and all(b["p10"] <= b["p50"] <= b["p90"] for b in sc[k]["band"])


def test_full_report_reflects_inputs():
    # A higher assumed return shows up in the echoed assumptions (transparency).
    base = _cfg()
    base["assumptions"]["portfolio_return_base"] = 0.06
    assert pl.full_report(base)["assumptions"]["return_pct"] == 6.0


def test_narrative_avoids_bare_jargon():
    # Scary acronyms, if present, must travel with a plain explanation nearby.
    text = pl.plain_text(_cfg()).lower()
    if "irmaa" in text:
        assert "medicare" in text
    if "rmd" in text:
        assert "government makes you" in text or "minimum" in text
