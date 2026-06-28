# Plain language — a design rule, not a nicety

The people this toolkit is for are **normal working Americans who want to retire
comfortably** — not accountants or financial planners. The engine is allowed to
be sophisticated; the **words a person reads must not be**. This is a standing
design rule for every current and future feature.

## The standard (and it's enforced)

1. **8th-grade reading level.** The plain-English plan is scored with a
   Flesch-Kincaid grade (`plain_language.readability_grade`) and a test fails if
   it drifts above ~grade 9. "Approachable" is measurable here, not a vibe — see
   `tests/test_plain_language.py::test_summary_reads_at_eighth_grade_or_easier`.
2. **No naked jargon.** Lead with the plain words; put the technical term in
   parentheses for the curious — *"a higher Medicare premium in high-income years
   (IRMAA)."* Never the reverse.
3. **Headline first.** The first thing a person sees answers the only question
   that matters: *can I retire comfortably?* — in big plain words with a
   traffic-light color (green / yellow / red). Detail lives behind that.
4. **Round, honest numbers.** "about $1,800/month" and "$3.3 million," not
   "$1,847.33." No false precision.
5. **Tell them what to do.** Every finding ends in an action — *"Each year, move
   about $15,000 from your 401(k) into a Roth. Ask your brokerage for a 'Roth
   conversion.'"* — not just analysis.

The technical tabs (Cash Flow, Roth Conversion Ladder, etc.) stay precise for
people who want them. The **plain-English plan** (`engine/plain_language.py`,
written to `plan_summary.txt` and shown at the top of the dashboard) is the face
of the product.

## Glossary

The one-line plain explanation for each term the toolkit might surface. Source of
truth: `GLOSSARY` in `engine/plain_language.py`.

| Term | In plain words |
|---|---|
| 401(k) / traditional IRA | A retirement account you put money in **before** taxes. |
| Pre-tax savings | Money in a 401(k) or traditional IRA you haven't paid tax on yet. |
| Roth | A retirement account where money grows **tax-free** and you owe no tax taking it out. |
| Roth conversion | Moving money from a pre-tax account into a Roth — you pay some tax now so it grows tax-free. |
| RMD | The minimum the government makes you take out of pre-tax accounts each year, starting at age 73–75. |
| IRMAA | A higher Medicare premium you pay in years your income is high. |
| ACA subsidy | A discount on health insurance before age 65 if you keep your income low enough. |
| Brokerage | A regular investment account with money you've already paid tax on. |
| Capital gains | The tax on the growth when you sell investments in a regular account. |
| Social Security | The monthly check the government pays you in retirement. |
| Pension | A monthly check some employers pay you in retirement. |

## For contributors

When you add a feature that surfaces a new number or term to the user:
- add its plain explanation to `GLOSSARY` and this table;
- route any user-facing wording through the plain-language layer;
- keep the plan summary under the reading-level budget (the test will tell you).
