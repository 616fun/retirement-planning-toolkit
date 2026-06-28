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
  plain-English plan.
- **I2 (done):** a friendly "tell us about your money" intake wizard — plain
  questions (ages, savings buckets, income, spending, pre-65 health insurance)
  with sensible defaults and an *Advanced* section. It builds a full engine
  config behind the scenes and shows the personalized plan. Pyodide warms up in
  the background while you fill the form, so "See my plan" feels instant.
- **I3 (done):** a "Download my plan" button (saves the plain-English plan as a
  text file) + Print, and a GitHub Pages deploy. The repo root redirects to the
  app and `.nojekyll` serves the engine files as-is, so the planner is reachable
  at a public URL.
- **I4 (next):** put it in front of a few real people; let their reactions order
  the remaining capability work.

## Run it locally

From the repo root:

```bash
python3 -m http.server 8123
# then open http://localhost:8123/web/
```

Educational only — not financial advice.
