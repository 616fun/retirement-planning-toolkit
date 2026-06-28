"""Guards that keep the in-browser (Pyodide) plan path working.

The web app loads engine/*.py unchanged and runs plain_language.plan_summary in
the browser. That only works if the plan path stays pure-Python (no openpyxl /
numpy C-heavy deps) and accepts a plain parsed-JSON config dict. These tests
lock both, so a future change can't silently break the web MVP.
"""
import json
import pathlib
import subprocess
import sys

import plain_language as pl

ROOT = pathlib.Path(__file__).resolve().parent.parent

# The exact files web/index.html writes into the Pyodide filesystem.
WEB_ENGINE_FILES = ["config_loader.py", "tax_us.py", "simulate.py", "plain_language.py"]


def test_plan_path_is_pure_python():
    # In a FRESH interpreter, importing the plan path must not pull openpyxl or
    # numpy (they'd bloat / break the browser load).
    code = ("import sys; sys.path.insert(0, 'engine'); import plain_language; "
            "assert 'openpyxl' not in sys.modules, 'openpyxl leaked'; "
            "assert 'numpy' not in sys.modules, 'numpy leaked'; "
            "assert 'build_model' not in sys.modules, 'build_model leaked'")
    subprocess.run([sys.executable, "-c", code], check=True, cwd=ROOT)


def test_plan_summary_accepts_parsed_json_dict():
    # The browser hands the engine a JSON.parse'd config (not via load_config).
    cfg = json.loads((ROOT / "config" / "examples" / "rivera_config.json").read_text())
    p = pl.plan_summary(cfg)
    assert p["color"] in ("green", "yellow", "red")
    assert p["actions"] and p["watch"]


def test_web_page_and_its_engine_files_exist():
    page = ROOT / "web" / "index.html"
    assert page.exists()
    html = page.read_text()
    for f in WEB_ENGINE_FILES:
        assert (ROOT / "engine" / f).exists(), f"web references missing engine/{f}"
        assert f in html, f"web/index.html no longer lists engine/{f}"
