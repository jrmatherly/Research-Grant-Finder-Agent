---
paths:
  - "**/nih_grant_matcher/scoring.py"
  - "**/nih_grant_matcher/config.py"
  - "**/nih_grant_matcher/filters.py"
  - "**/nih_grant_matcher/models.py"
  - "**/nih_grant_matcher/store.py"
---

# Scoring rules

- The keyword weights, the example sentences, and the classification thresholds are product behavior. The README documents the High, Medium, and Watchlist levels. Do not change a weight or a threshold as a side effect of another task.
- A change to a weight, a threshold, or a filter needs a matching case in `tests/test_scoring.py` or `tests/test_filters.py`.
- Keep every score explainable. A new signal adds a field to `ScoreBreakdown` in `models.py` and a line to the reasons. Add the new field last and give it a default value. `store.py` rebuilds `ScoreBreakdown` from saved rows by field name, so a renamed or removed field breaks every saved row. `scoring.py` fills it by position, so a reordered field puts new scores in the wrong fields with no error.
- `streamlit_app.py` repeats the thresholds 35 and 70 as score bin edges and repeats the level names in its metrics and charts. Change them together with `scoring.py`.
- Similarity weights words with `nih_grant_matcher/term_rarity.json`. Do not edit that file by hand. `python -m nih_grant_matcher rarity-table` rebuilds it from live data, and every score shifts after a rebuild, so rebuild it only as its own change.
- `workflow.rescore_saved` scores the open saved rows again before every read (dashboard, digest, Excel, and the end of `run`). A new read path calls it first.
- A keyword whose matched form differs from its name, such as `data coordination` for "data coordinating", gets a pattern in `KEYWORD_PATTERNS` in `config.py`. The name is what the user reads under Matched Terms.
- Pass `today` to `MLRelevanceScorer.score` and to `is_current_nih_hhs_opportunity` in tests, so that a test does not depend on the date it runs.
