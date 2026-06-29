#!/usr/bin/env python3
"""
plain_language.py -- the human face of the planner.

The engine is fiduciary-grade but speaks in jargon (IRMAA, NIIT, RMD, basis,
"net-cost optimal"). The people this is for are normal working Americans, not
accountants. This module turns the engine's output into a short, plain-English
plan written at roughly an 8th-grade reading level: can you retire, when, the
one or two moves that help most, and the few things to watch -- in everyday
words, with round numbers and a clear "do this."

Two things keep it honest:
  * GLOSSARY -- every scary term has a one-line plain explanation, and the rule
    is to lead with the plain words and put the jargon in parentheses.
  * readability_grade() -- a Flesch-Kincaid score so "approachable" is testable,
    not a vibe. The test suite fails if the summary drifts above ~9th grade.

This is plain wording, not dumbed-down math -- the numbers come straight from
engine/simulate.py. Illustrative, not financial advice.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import simulate  # noqa: E402
from config_loader import current_age  # noqa: E402


# Plain-English explanations. Lead with these words; keep the jargon in (parens).
GLOSSARY = {
    "401k": "a retirement account from your job that you put money in before taxes",
    "traditional ira": "a retirement account you fund before taxes",
    "roth": "a retirement account where the money grows tax-free and you owe no tax when you take it out",
    "pre-tax savings": "money in a 401(k) or traditional IRA that you have not paid tax on yet",
    "roth conversion": "moving money from a pre-tax account into a Roth account; you pay some tax now so it can grow tax-free",
    "rmd": "the minimum the government makes you take out of pre-tax accounts each year, starting at age 73 to 75",
    "irmaa": "a higher Medicare premium you pay in years your income is high",
    "aca subsidy": "a discount on health insurance you can get before age 65 if you keep your income low enough",
    "brokerage": "a regular investment account with money you have already paid tax on",
    "capital gains": "the tax you owe on the growth when you sell investments in a regular account",
    "social security": "the monthly check the government pays you in retirement",
    "pension": "a monthly check some employers pay you in retirement",
}


def explain(term):
    """Plain one-liner for a term (empty string if we have no entry)."""
    return GLOSSARY.get(term.strip().lower(), "")


# ---- reading level (Flesch-Kincaid grade) ---------------------------------

def _count_syllables(word):
    word = "".join(c for c in word.lower() if c.isalpha())
    if not word:
        return 0
    vowels = "aeiouy"
    count, prev_vowel = 0, False
    for c in word:
        is_vowel = c in vowels
        if is_vowel and not prev_vowel:
            count += 1
        prev_vowel = is_vowel
    if word.endswith("e") and count > 1:        # silent trailing 'e'
        count -= 1
    return max(1, count)


def readability_grade(text):
    """Flesch-Kincaid grade level of `text` (lower = easier). ~8 is 8th grade."""
    import re
    sentences = [s for s in re.split(r"[.!?]+", text) if s.strip()]
    words = re.findall(r"[A-Za-z']+", text)
    if not sentences or not words:
        return 0.0
    syllables = sum(_count_syllables(w) for w in words)
    wps = len(words) / len(sentences)
    spw = syllables / len(words)
    return 0.39 * wps + 11.8 * spw - 15.59


# ---- the plain-English plan ----------------------------------------------

def _money(x):
    """Round money to a friendly figure -- no false precision."""
    x = float(x)
    if abs(x) >= 1_000_000:
        return f"${x / 1_000_000:.1f} million"
    if abs(x) >= 10_000:
        return f"${round(x, -3):,.0f}"      # nearest thousand
    return f"${round(x, -2):,.0f}"          # nearest hundred


def plan_summary(cfg):
    """Build the plain-English plan as a structured dict (so the dashboard, a
    text file, and tests can all use it) plus a ready-to-read `narrative`."""
    none = simulate.simulate(cfg, strategy="none")
    best = simulate.optimize_conversions(cfg)
    return _build_plan(cfg, none, best)


def _build_plan(cfg, none, best):
    members = cfg["household"]["members"]
    name_a = members[0].get("display_name", "you")
    retire_age = members[0]["retirement_age"]
    monthly_spend = cfg["assumptions"]["retirement_spend_annual"] / 12.0

    # Verdict: does the plan last to age 90 at the planned spending?
    if not none["insolvent"]:
        verdict, color = "You are on track to retire comfortably.", "green"
    elif not best.get("insolvent", True):
        verdict, color = "You are close -- a few smart moves make it work.", "yellow"
    else:
        verdict, color = "You are not quite there yet -- let's close the gap.", "red"

    saves = max(0.0, none["net_cost"] - best["net_cost"])
    convert = best.get("target") or 0

    actions = []
    if convert and saves > 1000:
        actions.append(
            f"Each year after you retire, move about {_money(convert)} from your "
            f"pre-tax savings (your 401(k) and traditional IRA) into a Roth account. "
            f"You pay some tax now, but it grows tax-free -- saving about "
            f"{_money(saves)} over your life. Ask your brokerage for a 'Roth conversion.'")
    actions.append(
        "Keep no more than a small slice of your savings in your employer's stock, "
        "so one company can't sink your plan.")
    actions.append(
        "Check that the right people are listed to inherit each account.")

    watch = [
        "Health insurance before age 65 can be pricey. Some years you can keep your "
        "income lower to get a discount (an ACA subsidy).",
        "Starting around age 73 to 75, the government makes you pull money from "
        "pre-tax accounts (an RMD). Moving money out earlier lowers that future tax bill.",
        "Prices rise over time, so your spending will too. This plan already counts "
        "on that.",
    ]

    narrative = _render_narrative(name_a, verdict, retire_age, monthly_spend,
                                  actions, watch)
    return {
        "headline": verdict, "color": color, "retire_age": retire_age,
        "monthly_spend": monthly_spend, "convert_per_year": convert,
        "lifetime_savings": saves, "actions": actions, "watch": watch,
        "narrative": narrative,
    }


def _render_narrative(name, verdict, retire_age, monthly_spend, actions, watch):
    lines = [verdict,
             f"The plan has you stop working at age {retire_age}. It is built to cover "
             f"about {_money(monthly_spend)} a month, and to keep up as prices rise.",
             "", "The moves that help most:"]
    for i, a in enumerate(actions, 1):
        lines.append(f"{i}. {a}")
    lines += ["", "A few things to watch:"]
    for i, w in enumerate(watch, 1):
        lines.append(f"{i}. {w}")
    lines += ["", "This is a guide to help you plan, not formal financial advice. "
              "Your real numbers may differ."]
    return "\n".join(lines)


def _mc_scenario(cfg, label, mu, strategy, target):
    """One Monte Carlo regime (cold / normal / hot market) for the dashboard
    toggle -- a success rate + percentile outcomes + plain framing."""
    m = simulate.monte_carlo(cfg, n_sims=500, strategy=strategy, target=target, mu=mu)
    if m["success_rate"] >= 85:
        color, msg = "green", "Your plan holds up well in this market."
    elif m["success_rate"] >= 70:
        color, msg = "yellow", "Usually works, but this market could make it tight."
    else:
        color, msg = "red", "In many of these futures the money runs short."
    m["label"] = label
    m["sub"] = f"if returns average about {mu * 100:.1f}% a year"
    m["color"], m["message"] = color, msg
    return m


def _strategy_row(r):
    """Headline figures for one drawdown strategy (do-nothing or optimal)."""
    return {
        "target": r.get("target"),
        "lifetime_tax": r["lifetime_tax"], "terminal_tax": r["terminal_tax"],
        "aca_kept": r["lifetime_aca_subsidy"], "net_cost": r["net_cost"],
        "pretax_end": r["trad_end"], "roth_end": r["roth_end"],
        "money_lasts": not r["insolvent"],
    }


def full_report(cfg):
    """Everything the interface needs to show its work -- the plain plan PLUS
    the numbers behind it: do-nothing vs. the recommended plan, the year-by-year
    cash flow, and the assumptions used. All JSON-serializable so it can be
    rendered in the browser. This is the 'trust but verify' layer."""
    none = simulate.simulate(cfg, strategy="none")
    best = simulate.optimize_conversions(cfg)
    plan = _build_plan(cfg, none, best)

    # Year-by-year cash flow of the RECOMMENDED plan (the trajectory we advise).
    series = [{
        "year": r["year"], "age": r["a_age"], "phase": r["phase"],
        "income": r["pension"] + r["passive"] + r["ss_total"] + r["wages"],
        "conversion": r.get("conversion", 0.0), "spend": r["spend"],
        "tax": r["total_tax"], "pretax": r["trad"], "roth": r["roth"],
        "taxable": r["taxable"], "net_worth": r["net_worth"],
    } for r in best["ledger"]]

    a = cfg["assumptions"]
    hh = cfg["household"]
    assumptions = {
        "return_pct": round(a["portfolio_return_base"] * 100, 1),
        "inflation_pct": round(a["inflation_rate"] * 100, 1),
        "state_tax_pct": round(hh.get("state_income_tax_rate", 0) * 100, 2),
        "retire_age": hh["members"][0]["retirement_age"],
        "ss_claim_age": hh["members"][0]["ss_claim_age"],
        "planned_to_age": 90,
        "monthly_spend": a["retirement_spend_annual"] / 12.0,
    }

    # Monte Carlo: run the RECOMMENDED plan through random markets, under three
    # return regimes (cold / normal / hot) so people see the full range.
    mc_strategy = "optimal" if best.get("target") is not None else "none"
    mc = {
        "default": "normal",
        "scenarios": {
            "bad": _mc_scenario(cfg, "Bad market", a["portfolio_return_conservative"],
                                mc_strategy, best.get("target")),
            "normal": _mc_scenario(cfg, "Normal market", a["portfolio_return_base"],
                                   mc_strategy, best.get("target")),
            "good": _mc_scenario(cfg, "Good market", a["portfolio_return_optimistic"],
                                 mc_strategy, best.get("target")),
        },
    }

    return {
        "plan": plan,
        "comparison": {
            "do_nothing": _strategy_row(none),
            "recommended": _strategy_row(best),
            "lifetime_saved": max(0.0, none["net_cost"] - best["net_cost"]),
        },
        "series": series,
        "assumptions": assumptions,
        "monte_carlo": mc,
    }


def plain_text(cfg):
    """The full plain-English plan as one printable string."""
    p = plan_summary(cfg)
    return "YOUR RETIREMENT PLAN\n" + ("=" * 42) + "\n\n" + p["narrative"] + "\n"


if __name__ == "__main__":
    from config_loader import load_config
    cfg, _ = load_config()
    text = plain_text(cfg)
    print(text)
    print(f"[reading level: grade {readability_grade(text):.1f}]")
