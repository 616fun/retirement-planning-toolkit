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
WEB_ENGINE_FILES = ["config_loader.py", "tax_us.py", "simulate.py", "ss_claiming.py",
                    "plain_language.py"]


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


def test_web_engine_file_set_runs_full_report():
    # Simulate the Pyodide filesystem: copy ONLY the files the web loads into an
    # isolated dir and run full_report there. If full_report imports an engine
    # module the web page forgot to list, this fails (as it would in the browser).
    import shutil
    import tempfile
    import textwrap
    cfg_path = ROOT / "config" / "examples" / "rivera_config.json"
    with tempfile.TemporaryDirectory() as d:
        for f in WEB_ENGINE_FILES:
            shutil.copy(ROOT / "engine" / f, pathlib.Path(d) / f)
        code = textwrap.dedent(f"""
            import sys, json
            sys.path.insert(0, {d!r})
            import plain_language
            rep = plain_language.full_report(json.load(open({str(cfg_path)!r})))
            assert rep["ss_claiming"]["grid"], "ss_claiming missing"
            assert rep["plan"]["color"] in ("green", "yellow", "red")
        """)
        # cwd=d so only the copied engine files (not the repo's engine/) are importable.
        subprocess.run([sys.executable, "-c", code], check=True, cwd=d)


def test_web_page_and_its_engine_files_exist():
    page = ROOT / "web" / "index.html"
    assert page.exists()
    html = page.read_text()
    for f in WEB_ENGINE_FILES:
        assert (ROOT / "engine" / f).exists(), f"web references missing engine/{f}"
        assert f in html, f"web/index.html no longer lists engine/{f}"


def test_pages_deploy_scaffolding():
    # Root redirect sends Pages visitors to the app; .nojekyll serves files as-is.
    root = ROOT / "index.html"
    assert root.exists() and "web/" in root.read_text()
    assert (ROOT / ".nojekyll").exists()
