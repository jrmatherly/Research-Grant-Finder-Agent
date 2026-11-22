---
paths:
  - "**/nih_grant_matcher/scoring.py"
  - "**/nih_grant_matcher/config.py"
  - "**/nih_grant_matcher/filters.py"
---

# Scoring rules

- The keyword weights, the example sentences, and the classification thresholds are product behavior. The README documents the High, Medium, and Watchlist levels. Do not change a weight or a threshold as a side effect of another task.
- A change to a weight, a threshold, or a filter needs a matching case in `tests/test_scoring.py` or `tests/test_filters.py`.
- Keep every score explainable. A new signal adds a field to `ScoreBreakdown` in `models.py` and a line to the reasons. Give the new field a default value, because `store.py` rebuilds `ScoreBreakdown` from rows that were saved without it.
- Pass `today` to `MLRelevanceScorer.score` and to `is_current_nih_hhs_opportunity` in tests, so that a test does not depend on the date it runs.
