# Web app (interface MVP)

A browser front-end so a **normal person can use the planner without installing
anything or running Python** — they open a page, and the plan appears.

## How it works

`index.html` loads [Pyodide](https://pyodide.org) (CPython compiled to
WebAssembly), fetches the engine's `engine/*.py` files **unchanged**, and runs
`plain_language.plan_summary()` right in the browser. So:

- **Your numbers never leave your device** — the math runs client-side, there is
  no server and nothing is uploaded.
- **One source of truth** — it runs the real engine, not a re-implementation, so
  the web app and the spreadsheet can never disagree.
- **Free to host** — it's static files (works on GitHub Pages).

The plan path is pure Python (no `numpy`/`openpyxl`), which is what makes the
in-browser load fast and dependency-free. `tests/test_web_ready.py` guards that.

## Status

- **I1 (done):** proof of concept — the engine runs in-browser and renders the
  plain-English plan from a **demo** config.
- **I2 (next):** a friendly "tell us about your money" intake wizard that builds
  the config from a person's own answers (plain questions, sensible defaults).
- **I3 (next):** result page polish + GitHub Pages deploy.

## Run it locally

From the repo root:

```bash
python3 -m http.server 8123
# then open http://localhost:8123/web/
```

Educational only — not financial advice.
