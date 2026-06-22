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
    Year-by-Year Projections, Employer Concentration, Monte Carlo (summary),
    Roth Conversion (scaffold), Action Plan.

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

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parent.parent

GREEN = Font(color="008000")          # cross-sheet link
BLACK = Font(color="000000")          # intra-sheet formula
BLUE = Font(color="0000FF")           # hardcoded input
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
    ws = wb.create_sheet("Year-by-Year Projections")
    _title(ws, "Year-by-Year Projections (simplified)")
    members = cfg["household"]["members"]
    a = cfg["assumptions"]
    spend0 = a["retirement_spend_annual"]
    infl = a["inflation_rate"]
    ret = a["portfolio_return_base"]
    pension = cfg["income"]["pension_monthly_at_retirement"] * 12
    passive = cfg["income"]["passive_income_annual"]
    ss_a = cfg["social_security"]["spouse_a_monthly_benefit"] * 12
    ss_b = cfg["social_security"]["spouse_b_monthly_benefit"] * 12

    headers = ["Year", "Spouse A age", "Spouse B age", "Spend (infl-adj)",
               "Pension", "Passive", "Social Security", "Portfolio draw", "Portfolio EOY"]
    ws.append(headers)
    _header_row(ws, headers)

    import datetime
    base_year = datetime.date.today().year
    a_age0 = current_age(cfg, "spouse_a")
    b_age0 = current_age(cfg, "spouse_b")
    a_ret_age = members[0]["retirement_age"]
    a_ss_age = members[0]["ss_claim_age"]
    b_ss_age = members[1]["ss_claim_age"]
    portfolio = investable_total(cfg)

    for n in range(0, 36):
        year = base_year + n
        a_age = a_age0 + n
        b_age = b_age0 + n
        retired = a_age >= a_ret_age
        spend = spend0 * ((1 + infl) ** n) if retired else 0
        pen = pension * ((1 + cfg["income"]["pension_cola"]) ** max(0, a_age - a_ret_age)) if retired else 0
        pas = passive if retired else 0
        ss = (ss_a if a_age >= a_ss_age else 0) + (ss_b if b_age >= b_ss_age else 0)
        # grow then draw
        portfolio *= (1 + ret)
        draw = 0
        if retired:
            need = spend - pen - pas - ss
            draw = max(0, need)
            portfolio -= draw
        ws.append([year, a_age, b_age, round(spend), round(pen), round(pas),
                   round(ss), round(draw), round(portfolio)])

    for col in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col)].width = 15
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


def build_action_plan(wb, cfg):
    ws = wb.create_sheet("Action Plan")
    _title(ws, "Action Plan")
    ws.append(["Priority", "Item", "Status"])
    _header_row(ws, ["Priority", "Item", "Status"])
    items = [
        (1, "Review employer-stock concentration vs. thresholds (company_health.py)", "Recurring"),
        (2, "Confirm beneficiary designations on every account", "Open"),
        (3, "Map Roth-conversion headroom under IRMAA Tier 1", "Open"),
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
    build_monte_carlo(wb, cfg)
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


if __name__ == "__main__":
    main()
