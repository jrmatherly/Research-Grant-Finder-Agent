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
- Keep every score explainable. A new signal adds a field to `ScoreBreakdown` in `models.py` and a line to the reasons. Add the new field last and give it a default value. `store.py` rebuilds `ScoreBreakdown` from saved rows by field name, and `scoring.py` fills it by position, so a renamed, removed, or reordered field breaks every saved row.
- `streamlit_app.py` repeats the thresholds 45 and 70 as score bin edges and repeats the level names in its metrics and charts. Change them together with `scoring.py`.
- Pass `today` to `MLRelevanceScorer.score` and to `is_current_nih_hhs_opportunity` in tests, so that a test does not depend on the date it runs.
