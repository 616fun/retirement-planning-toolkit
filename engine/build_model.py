#!/usr/bin/env python3
"""
build_model.py -- generate the multi-tab financial-plan workbook from config.

Mirrors the architecture documented in docs/ARCHITECTURE.md:
  * The ASSUMPTIONS tab is the single source of truth. Every other tab links
    back to it with cross-sheet formulas rather than hardcoding values.
  * Color convention:
      green text  = cross-sheet link  (=Assumptions!Cxx)
      black text  = intra-sheet formula
      blue text   = hardcoded input
  * Tabs built here: Assumptions, Net Worth Snapshot, Income Streams,
    Year-by-Year Projections, Cash Flow, Employer Concentration, Monte Carlo
    (summary), Roth Conversion Ladder (lifetime-tax optimizer), Action Plan.
  * The year-by-year math lives in engine/simulate.py (the shared kernel) so the
    Year-by-Year tab, the Cash Flow tab, and the Roth optimizer all read one
    consistent projection. Tax engine: engine/tax_us.py.

Run:
  python3 engine/build_model.py                      # demo config
  RPT_CONFIG=config/config.json python3 engine/build_model.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config_loader import (  # noqa: E402
    load_config, investable_total, employer_stock_total, employer_concentration_pct,
    current_age,
)
import tax_us  # noqa: E402
import simulate  # noqa: E402
from simulate import (  # noqa: E402  (re-exported for back-compat with callers/tests)
    rmd_factor, rmd_start_age, pretax_total, roth_total, taxable_total,
    simulate_conversions as _simulate_conversions,
    optimize_conversions as _optimize_conversions,
)

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parent.parent

GREEN = Font(color="008000")          # cross-sheet link
BLACK = Font(color="000000")          # intra-sheet formula
BLUE = Font(color="0000FF")           # hardcoded input
GOODF = Font(color="1A7F37", bold=True)   # winning strategy row
RED = Font(color="CF222E")            # IRMAA-breach flag
BOLD = Font(bold=True)
HDR = Font(bold=True, color="FFFFFF")
HDR_FILL = PatternFill("solid", fgColor="305496")
TITLE = Font(bold=True, size=14, color="1F3864")
thin = Side(style="thin", color="D9D9D9")
BORDER = Border(left=thin, right=thin, top=thin, bottom=thin)


def _title(ws, text):
    ws["A1"] = text
    ws["A1"].font = TITLE
    ws.append([])


def _header_row(ws, cells, row=None):
    for col, val in enumerate(cells, start=1):
        c = ws.cell(row=row or ws.max_row, column=col, value=val)
        c.font = HDR
        c.fill = HDR_FILL
        c.border = BORDER


def build_assumptions(wb, cfg):
    ws = wb.create_sheet("Assumptions")
    _title(ws, "Assumptions -- SINGLE SOURCE OF TRUTH")
    a = cfg["assumptions"]
    inc = cfg["income"]
    members = cfg["household"]["members"]

    rows = [
        ("Key", "Value", "Notes"),
        ("Portfolio return (base)", a["portfolio_return_base"], "Monte Carlo mu"),
        ("Portfolio return (conservative)", a["portfolio_return_conservative"], ""),
        ("Portfolio return (optimistic)", a["portfolio_return_optimistic"], ""),
        ("Inflation", a["inflation_rate"], "bracket + spend scaling"),
        ("State income tax", cfg["household"]["state_income_tax_rate"], ""),
        ("Local income tax", cfg["household"]["local_income_tax_rate"], ""),
        ("Standard deduction (MFJ)", a["standard_deduction_mfj"], ""),
        ("IRMAA Tier 1 MAGI (MFJ)", a["irmaa_tier1_magi_mfj"], "Roth conversion ceiling"),
        ("Retirement spend (annual, today $)", a["retirement_spend_annual"], ""),
        ("Target equity %", a["target_equity_pct"], ""),
        ("Target bond %", a["target_bond_pct"], ""),
        ("Bridge target", a["bridge_target"], "pre-59.5 brokerage bridge"),
        ("Pension monthly at retirement", inc["pension_monthly_at_retirement"], ""),
        ("Pension COLA", inc["pension_cola"], ""),
        ("Passive income (annual)", inc["passive_income_annual"], ""),
        (f"{members[0]['display_name']} salary", inc["spouse_a_salary"], ""),
        (f"{members[0]['display_name']} bonus %", inc["spouse_a_bonus_pct"], ""),
        (f"{members[0]['display_name']} RSU annual", inc["spouse_a_rsu_annual"], ""),
        (f"{members[1]['display_name']} income", inc["spouse_b_annual"], ""),
        (f"{members[0]['display_name']} retirement age", members[0]["retirement_age"], ""),
        (f"{members[1]['display_name']} retirement age", members[1]["retirement_age"], ""),
        (f"{members[0]['display_name']} SS claim age", members[0]["ss_claim_age"], ""),
        (f"{members[1]['display_name']} SS claim age", members[1]["ss_claim_age"], ""),
        (f"{members[0]['display_name']} SS monthly", cfg["social_security"]["spouse_a_monthly_benefit"], ""),
        (f"{members[1]['display_name']} SS monthly", cfg["social_security"]["spouse_b_monthly_benefit"], ""),
    ]
    start = ws.max_row + 1
    for i, r in enumerate(rows):
        ws.append(r)
        if i == 0:
            _header_row(ws, r)
        else:
            ws.cell(row=ws.max_row, column=2).font = BLUE  # hardcoded inputs
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 16
    ws.column_dimensions["C"].width = 30
    # Remember row of "Inflation" for linking demos
    cfg["_assum_rows"] = {name: start + idx for idx, (name, *_ ) in enumerate(rows)}
    return ws


def build_net_worth(wb, cfg):
    ws = wb.create_sheet("Net Worth Snapshot")
    _title(ws, "Net Worth Snapshot")
    ws.append(["Account", "Balance"])
    _header_row(ws, ["Account", "Balance"])
    first_data = ws.max_row + 1
    for k, v in cfg["accounts"].items():
        ws.append([k.replace("_", " ").title(), v])
        ws.cell(row=ws.max_row, column=2).font = BLUE
    for k, v in cfg["real_estate"].items():
        if v:
            ws.append([k.replace("_", " ").title(), v])
            ws.cell(row=ws.max_row, column=2).font = BLUE
    last_data = ws.max_row
    ws.append(["TOTAL NET WORTH", f"=SUM(B{first_data}:B{last_data})"])
    ws.cell(row=ws.max_row, column=1).font = BOLD
    ws.cell(row=ws.max_row, column=2).font = BLACK
    inv = investable_total(cfg)
    ws.append(["Investable total (computed)", inv])
    ws.cell(row=ws.max_row, column=2).font = BLUE
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 16
    return ws


def build_concentration(wb, cfg):
    ws = wb.create_sheet("Employer Concentration")
    _title(ws, f"Employer Concentration -- {cfg['employer_stock']['employer_name']} "
               f"({cfg['employer_stock']['ticker']})")
    es = cfg["employer_stock"]
    ws.append(["Sleeve", "Value"])
    _header_row(ws, ["Sleeve", "Value"])
    for k, v in es["holdings"].items():
        ws.append([k.replace("_", " ").title(), v])
        ws.cell(row=ws.max_row, column=2).font = BLUE
    ws.append(["Total employer exposure", employer_stock_total(cfg)])
    ws.cell(row=ws.max_row, column=1).font = BOLD
    ws.append(["Investable total", investable_total(cfg)])
    ws.append(["Concentration %", employer_concentration_pct(cfg)])
    ws.cell(row=ws.max_row, column=1).font = BOLD
    ws.append(["Watch threshold %", es["watch_threshold_pct"]])
    ws.append(["Trim threshold %", es["trim_threshold_pct"]])
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 16
    return ws


def build_year_by_year(wb, cfg):
    """Summary projection: the baseline (RMD-only, no conversions) run from the
    shared kernel. Now after-tax and pool-aware -- the portfolio draw reflects
    the real spending need net of guaranteed income and taxes, and the EOY
    balance is the sum of the pre-tax + Roth + taxable pools (HSA/529 excluded)."""
    ws = wb.create_sheet("Year-by-Year Projections")
    _title(ws, "Year-by-Year Projections (after-tax baseline -- RMDs, no conversions)")

    headers = ["Year", "Spouse A age", "Spouse B age", "Spend (infl-adj)",
               "Pension", "Passive", "Social Security", "Tax",
               "Portfolio draw", "Portfolio EOY"]
    ws.append(headers)
    _header_row(ws, headers)

    run = simulate.simulate(cfg)            # strategy="none" baseline
    for r in run["ledger"]:
        draw = r["draw_taxable"] + r["draw_trad"] + r["draw_roth"]
        ws.append([r["year"], r["a_age"], r["b_age"], round(r["spend"]),
                   round(r["pension"]), round(r["passive"]), round(r["ss_total"]),
                   round(r["total_tax"]), round(draw), round(r["portfolio"])])
        if r.get("phase") == "retired" and r["draw_roth"] + r["draw_trad"] == 0 \
                and r["portfolio"] <= 0:
            ws.cell(row=ws.max_row, column=10).font = RED

    for col in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col)].width = 15
    return ws


def build_cash_flow(wb, cfg):
    """Detailed after-tax cash-flow ledger -- the fullest view of the kernel's
    baseline run: every income source, the AGI/MAGI driving the tax cliffs,
    federal/state/IRMAA tax, which pool funded each shortfall, and the running
    pre-tax / Roth / taxable balances. Source: engine/simulate.py."""
    ws = wb.create_sheet("Cash Flow")
    _title(ws, "Cash Flow -- after-tax, by source and account (baseline)")

    headers = ["Year", "Age A", "Age B", "Pension", "Passive", "Wages",
               "Soc Sec", "RMD", "Cap gains", "MAGI", "Fed tax", "State tax",
               "Cap-gains tax", "NIIT", "IRMAA", "ACA subsidy", "Spend",
               "Draw: taxable", "Draw: pre-tax", "Draw: Roth",
               "Pre-tax bal", "Roth bal", "Taxable bal", "Net worth"]
    ws.append(headers)
    _header_row(ws, headers)

    run = simulate.simulate(cfg)
    for r in run["ledger"]:
        ws.append([r["year"], r["a_age"], r["b_age"], round(r["pension"]),
                   round(r["passive"]), round(r["wages"]), round(r["ss_total"]),
                   round(r["rmd"]), round(r.get("cap_gains", 0)), round(r["magi"]),
                   round(r["fed_tax"]), round(r["state_tax"]), round(r.get("cg_tax", 0)),
                   round(r.get("niit", 0)), round(r["irmaa"]), round(r.get("aca_subsidy", 0)),
                   round(r["spend"]), round(r["draw_taxable"]), round(r["draw_trad"]),
                   round(r["draw_roth"]), round(r["trad"]), round(r["roth"]),
                   round(r["taxable"]), round(r["net_worth"])])
        if r.get("aca_subsidy", 0) > 0:
            ws.cell(row=ws.max_row, column=16).font = GOODF
        if r["irmaa"] > 0:
            ws.cell(row=ws.max_row, column=15).font = RED

    for col in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col)].width = 12
    return ws


def build_monte_carlo(wb, cfg):
    ws = wb.create_sheet("Monte Carlo")
    _title(ws, "Monte Carlo (summary -- run engine/quarterly_update.py to refresh)")
    ws.append(["Scenario", "Return mu", "Success rate", "Note"])
    _header_row(ws, ["Scenario", "Return mu", "Success rate", "Note"])
    a = cfg["assumptions"]
    for label, mu in [("Conservative", a["portfolio_return_conservative"]),
                      ("Base", a["portfolio_return_base"]),
                      ("Optimistic", a["portfolio_return_optimistic"])]:
        ws.append([label, mu, "(pending)", "populated by quarterly_update.py"])
    ws.column_dimensions["A"].width = 16
    ws.column_dimensions["D"].width = 40
    return ws


# ---- Roth-conversion ladder optimizer -------------------------------------
# The year-by-year simulation now lives in engine/simulate.py (the shared
# kernel). rmd_factor / rmd_start_age / pool helpers are re-exported above.


def build_roth_ladder(wb, cfg):
    """Roth Conversion Ladder tab -- the lifetime-tax optimizer (objective #3).

    Shows three strategies side by side: do-nothing (RMDs only), the readable
    fill-to-22%-bracket heuristic, and the lifetime-tax-optimal level target.
    Lifetime tax = in-life federal + state + IRMAA (present-valued) PLUS the
    terminal tax heirs pay on the pre-tax balance under the SECURE 10-year rule.

    Tax engine: engine/tax_us.py. Models ordinary income (federal MFJ brackets +
    standard deduction + hybrid state), the IRMAA 2-year lookback, Social
    Security taxation via provisional income (IRC sec. 86), long-term capital
    gains realized on taxable draws (0/15/20% stacked) + NIIT, the terminal heir
    tax, and the ACA premium tax credit in the pre-65 window. The optimizer
    minimizes NET cost (tax minus ACA subsidy), so it won't over-convert and
    forfeit subsidies. Does NOT model per-state retirement exclusions, AMT, QBI,
    or spousal IRA splitting. Illustrative, not advice. See docs/US_RULES.md.
    """
    ws = wb.create_sheet("Roth Conversion Ladder")
    _title(ws, "Roth Conversion Ladder -- lifetime-tax optimizer")

    none = _simulate_conversions(cfg, "none")
    heur = _simulate_conversions(cfg, "bracket")
    best = _optimize_conversions(cfg)

    ws.append(["Objective: minimize NET lifetime cost = PV(federal + state + IRMAA "
               "+ capital gains + NIIT) + terminal heir tax MINUS the ACA premium "
               "subsidy preserved in the pre-65 window."])
    ws.append([])

    # ---- strategy comparison ----
    cmp_headers = ["Strategy", "Annual target (AGI)", "In-life tax (PV)",
                   "Terminal heir tax (PV)", "ACA subsidy kept (PV)",
                   "NET lifetime cost (PV)", "Pre-tax left @90", "Roth @90"]
    ws.append(cmp_headers)
    _header_row(ws, cmp_headers)
    rows = [
        ("Do nothing (RMDs only)", "n/a", none),
        ("Fill to top of 22% bracket", "22% bracket / IRMAA cap", heur),
        ("Net-cost optimal",
         (f"${best['target']:,.0f}/yr" if best.get("target") else "n/a"), best),
    ]
    base_net = none["net_cost"]
    for label, tgt, r in rows:
        ws.append([label, tgt, round(r["lifetime_tax"]), round(r["terminal_tax"]),
                   round(r["lifetime_aca_subsidy"]), round(r["net_cost"]),
                   round(r["trad_end"]), round(r["roth_end"])])
        if r is best:
            for c in range(1, len(cmp_headers) + 1):
                ws.cell(row=ws.max_row, column=c).font = GOODF
    ws.append([])
    saved = base_net - best["net_cost"]
    pct = (100 * saved / base_net) if base_net else 0.0
    ws.append(["Net cost saved vs. do-nothing", round(saved),
               f"{pct:.0f}% lower net cost at a ${best['target']:,.0f}/yr conversion ceiling"
               if best.get("target") else "optimizer fell back to do-nothing"])
    ws.cell(row=ws.max_row, column=1).font = BOLD
    ws.cell(row=ws.max_row, column=2).font = GOODF
    ws.append([])

    # ---- optimal year-by-year schedule ----
    sch_headers = ["Year", "Age A", "Age B", "Base income", "RMD", "Conversion",
                   "MAGI", "Income tax", "Cap-gains tax", "IRMAA", "ACA subsidy",
                   "Pre-tax bal", "Roth bal"]
    ws.append(sch_headers)
    _header_row(ws, sch_headers)
    for r in best["schedule"]:
        ws.append([r["year"], r["a_age"], r["b_age"], round(r["base_ordinary"]),
                   round(r["forced"]), round(r["conversion"]), round(r["agi"]),
                   round(r["tax"]), round(r.get("cg_tax", 0)), round(r["irmaa"]),
                   round(r.get("aca", 0)), round(r["trad"]), round(r["roth"])])
        if r["irmaa"] > 0:
            ws.cell(row=ws.max_row, column=10).font = RED

    widths = [8, 7, 7, 13, 12, 13, 13, 12, 13, 10, 12, 14, 14]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    return ws


def build_action_plan(wb, cfg):
    ws = wb.create_sheet("Action Plan")
    _title(ws, "Action Plan")
    ws.append(["Priority", "Item", "Status"])
    _header_row(ws, ["Priority", "Item", "Status"])
    items = [
        (1, "Review employer-stock concentration vs. thresholds (company_health.py)", "Recurring"),
        (2, "Confirm beneficiary designations on every account", "Open"),
        (3, "Execute Roth-conversion ladder to the optimal target (see Roth Conversion Ladder tab)", "Open"),
        (4, "Verify pension survivor-benefit election", "Open"),
        (5, "Rebalance toward target equity/bond split", "Recurring"),
    ]
    for p, it, st in items:
        ws.append([p, it, st])
    ws.column_dimensions["A"].width = 10
    ws.column_dimensions["B"].width = 60
    ws.column_dimensions["C"].width = 14
    return ws


def build(cfg):
    wb = Workbook()
    wb.remove(wb.active)
    build_assumptions(wb, cfg)
    build_net_worth(wb, cfg)
    build_concentration(wb, cfg)
    build_income_note(wb, cfg)
    build_year_by_year(wb, cfg)
    build_cash_flow(wb, cfg)
    build_monte_carlo(wb, cfg)
    build_roth_ladder(wb, cfg)
    build_action_plan(wb, cfg)
    return wb


def build_income_note(wb, cfg):
    ws = wb.create_sheet("Income Streams")
    _title(ws, "Income Streams")
    ws.append(["Stream", "Annual", "Notes"])
    _header_row(ws, ["Stream", "Annual", "Notes"])
    inc = cfg["income"]
    m = cfg["household"]["members"]
    rows = [
        (f"{m[0]['display_name']} salary", inc["spouse_a_salary"], ""),
        (f"{m[0]['display_name']} bonus", round(inc["spouse_a_salary"] * inc["spouse_a_bonus_pct"]), ""),
        (f"{m[0]['display_name']} RSU", inc["spouse_a_rsu_annual"], "employer stock -- see concentration tab"),
        (f"{m[1]['display_name']} income", inc["spouse_b_annual"], ""),
        ("Pension (annual at retirement)", inc["pension_monthly_at_retirement"] * 12, ""),
        ("Passive income", inc["passive_income_annual"], ""),
    ]
    for r in rows:
        ws.append(r)
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 14
    ws.column_dimensions["C"].width = 40
    return ws


def main():
    cfg, path = load_config()
    out = ROOT / cfg["paths"]["model_xlsx"]
    out.parent.mkdir(parents=True, exist_ok=True)
    wb = build(cfg)
    wb.save(out)
    tag = "DEMO" if cfg.get("_is_demo") else "LIVE"
    print(f"[{tag}] Built model from {path.name}")
    print(f"  -> {out}")
    print(f"  Tabs: {wb.sheetnames}")

    # Plain-English plan -- the human-readable summary, written next to the model
    # and echoed to the console (the part a non-expert actually reads).
    import plain_language
    summary = plain_language.plain_text(cfg)
    (out.parent / "plan_summary.txt").write_text(summary, encoding="utf-8")
    print(f"  Plain-English plan -> {out.parent / 'plan_summary.txt'}\n")
    print(summary)


if __name__ == "__main__":
    main()
