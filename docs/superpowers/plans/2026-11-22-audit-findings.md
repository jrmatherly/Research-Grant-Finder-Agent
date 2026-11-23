# Audit Findings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A researcher sees every open NIH Guide notice, ranked without the AI/AN false match, with dates labelled as what they are, and the tool fails cleanly when a service or a record misbehaves.

**Architecture:** Eight small changes on one branch, one commit each, in the order that keeps every commit green. The dead command goes first, so that later tasks build on less code. Each code task starts with a test that fails on `main` at `b4a11f3`. All eight tasks were run once in a throwaway worktree on 2026-11-22. Each test failed before its change and passed after it, and every expected count and output below comes from that run.

**Tech Stack:** Python 3.11+, standard library only in the package, Streamlit and pandas in the dashboard, pytest, uv.

**Spec:** Appendix A of this file. It lists the 13 audit findings with the evidence for each. No separate spec exists.

## Global Constraints

- Run every command from `NIH Extractor/` unless the step names the repository root. The tests fail from the root.
- Run every `git` command from the repository root. The paths in the commit steps are relative to the root.
- The test command is `uv run --locked pytest -q`. CI adds `-W error::DeprecationWarning`. Run that form before the push.
- Add no dependency. `pyproject.toml` and `uv.lock` do not change.
- Do not reformat a line that a task does not name. The repository has no formatter config.
- Do not edit `nih_grant_matcher/term_rarity.json` or any file under `data/`, `outputs/`, or `digests/`.
- Do not rename, remove, or reorder a field of `ScoreBreakdown`. Saved rows rebuild it by field name.
- `tests/test_streamlit_app_static.py` asserts literal strings in `streamlit_app.py`. Run that file after every dashboard edit.
- Work on the branch `fix/audit-findings`. Do not commit to `main`.
- Push and open pull requests on `jrmatherly/Research-Grant-Finder-Agent` only. Ask the owner once, in Task 8, for the push and the pull request together.
- Before each commit, run `/simplify`, then `/code-review` on that commit's diff.
- Every `git commit` command below takes one more argument, `-m "Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>"`, after its first `-m`.
- Each task ends with the full suite green. Do not start a task while the suite is red.
- Tasks 1, 3, and 4 change product behavior that the owner decides. The owner asked for a plan that covers every recommendation. To drop one of the three, skip its task. No other task depends on it. The expected test counts then differ by the tests that the skipped task adds or removes.
- Line numbers are those of `main` at `b4a11f3`. An earlier task can move them, so find each edit by the text that the step quotes.

## Review Focus

1. A source holds more rows than the limit. Grants.gov held 633 on 2026-11-22, and the NIH Guide can grow past 500. A run would drop the rest without a word. The run says that a source reached the limit. Pinned by `test_run_says_when_it_reaches_the_limit` in Task 2.
2. A notice that names AI/AN people and also uses AI methods. The AI match must survive. Pinned by `test_ai_matches_beside_ai_an` in Task 3.
3. A run with `--source both` where the two sources together pass the limit and neither reaches it. The run must not report a limit. Pinned by the `--source both` case of `test_run_says_when_it_reaches_the_limit` in Task 2.
4. A score of exactly 100. `pd.cut` with `right=False` drops it from the chart, which is why Task 5 does not use that option. Pinned by `test_score_bin_edges_follow_the_levels` in Task 5.
5. Text that holds an encoded comparison such as `p&lt;0.05`. Decoding before the tag strip would delete everything from `<` to the next `>`. Pinned by `test_clean_text_decodes_entities_after_it_strips_tags` in Task 7.

---

### Task 1: Remove the `backfill-xml` command (finding 9)

The command fails with a certificate error, and no code reads the file that it downloads.

**Files:**
- Modify: `nih_grant_matcher/clients.py:2,4,6,21,38-39,72-89`
- Modify: `nih_grant_matcher/config.py:7`
- Modify: `nih_grant_matcher/cli.py:2,5,39-40,55-56,112-124`
- Modify: `tests/test_cli.py:1-2,8,96-103,111-123`
- Modify: `tests/test_clients.py:104-109`
- Modify: `../README.md:432`

**Interfaces:**
- Consumes: nothing.
- Produces: `cli.main` no longer accepts `backfill-xml`. `clients.GrantsGovXmlClient`, `clients._get_bytes`, and `config.GRANTSGOV_XML_EXTRACT_URL` no longer exist.

- [ ] **Step 0: Create the branch, from the repository root**

Run: `git switch -c fix/audit-findings main`
Expected: `Switched to a new branch 'fix/audit-findings'`. `git rev-parse --short main` prints `b4a11f3` or a later commit that adds only this plan and the handoff.

- [ ] **Step 1: Delete the tests of the removed code**

Delete `test_backfill_xml_reports_a_failed_download`, `test_backfill_xml_reports_a_certificate_error`, and `test_xml_extract_url_is_resolved_against_the_page` from `tests/test_cli.py`. Delete `test_download_removes_a_file_that_is_not_a_zip` from `tests/test_clients.py`. Remove the imports that only those tests used: `ssl`, `urllib.error`, and `GrantsGovXmlClient` in `tests/test_cli.py`. Keep `test_read_does_not_retry_a_certificate_error`. `_read` still fails fast on a certificate error.

- [ ] **Step 2: Delete the code**

In `clients.py`, delete the class `GrantsGovXmlClient` and the function `_get_bytes`. Remove `re` and `zipfile` from the import on line 2, the `Path` import on line 4, and `GRANTSGOV_XML_EXTRACT_URL` from the import on line 6. Shorten the comment on line 21 to `# A certificate that fails once fails every time.` In `config.py`, delete `GRANTSGOV_XML_EXTRACT_URL`. In `cli.py`, delete the `backfill-xml` parser, its branch in `main`, and `_backfill_xml`. Reduce the import on line 2 to `import argparse, json, sys`. Remove `ApiError` and `GrantsGovXmlClient` from line 5. Only `_backfill_xml` used `ApiError`, and an unused import fails the check in Step 4. Task 6 imports it again.

- [ ] **Step 3: Delete the README row**

Delete the `backfill-xml` row from the command table in `README.md`.

- [ ] **Step 4: Verify**

Run: `uv run --locked pytest -q`
Expected: 96 passed.

Run: `uv run python -m nih_grant_matcher backfill-xml`
Expected: exit code 2 and `invalid choice: 'backfill-xml'`.

Run: `uvx ruff check --select F --no-cache .`
Expected: `All checks passed!` An unused import fails this check.

Run from the repository root: `grep -rn "backfill\|GrantsGovXml\|XML_EXTRACT" --include='*.py' --include='*.md' . | grep -v "docs/superpowers\|\.remember\|\.venv"`
Expected: no output.

- [ ] **Step 5: Commit, from the repository root**

```bash
git add -A "NIH Extractor" README.md
git commit -m "refactor: remove the backfill-xml command, which fails and feeds nothing"
```

---

### Task 2: Fetch every active notice by default (findings 1 and 8)

The NIH Guide held 371 active notices on 2026-11-22. A default run reads the newest 250 and showed 25 of the 41 Medium matches.

The new default of 500 also applies to the Grants.gov source, which makes one request for each row and held 633 rows on 2026-11-22. A default Grants.gov run therefore takes about twice as long as before and reports that it reached the limit. Step 5 measures the time and corrects the guide.

**Files:**
- Modify: `nih_grant_matcher/config.py:47`
- Modify: `nih_grant_matcher/workflow.py:17-53`
- Modify: `nih_grant_matcher/cli.py:22` and `_run`
- Modify: `streamlit_app.py:108,141`
- Modify: `../docs/docker.md:36`
- Test: `tests/test_clients.py`, `tests/test_cli.py`, `tests/test_streamlit_app_static.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `MatcherConfig().rows == 500`. The `run` command's `--limit` defaults to 500. `workflow.fetch_score_opportunities(config, source, keyword) -> tuple[list[ScoredOpportunity], int, bool]`. The third value, `capped`, is true when one source returned `config.rows` rows or more. `RunSummary` gains the field `capped: bool = False`, placed last. `run` prints one line to standard error when `capped` is true.

- [ ] **Step 1: Write the failing tests**

In `tests/test_clients.py`:

```python
def test_nih_guide_default_run_reads_every_page(monkeypatch) -> None:
    import json, urllib.parse
    from nih_grant_matcher.agents import NihGuideIngestionAgent
    from nih_grant_matcher.config import MatcherConfig
    offsets = []
    def fake_read(request, timeout, attempts=3):
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)
        start, size = int(query["from"][0]), int(query["perpage"][0])
        offsets.append((start, size))
        hits = [{"_source": {"rowid": str(n), "docnum": f"PAR-27-{n:03d}", "title": "Notice", "type": "active"}} for n in range(start, min(start + size, 371))]
        return json.dumps({"data": {"hits": {"hits": hits}}}).encode()
    monkeypatch.setattr(clients, "_read", fake_read)
    monkeypatch.setattr(clients.time, "sleep", lambda seconds: None)
    opportunities = NihGuideIngestionAgent(clients.NihGuideClient(), MatcherConfig()).ingest()
    assert len({opportunity.source_id for opportunity in opportunities}) == 371
    assert offsets == [(0, 100), (100, 100), (200, 100), (300, 100)]
```

In `tests/test_cli.py`:

```python
def test_run_says_when_it_reaches_the_limit(sources, tmp_path, capsys) -> None:
    db = tmp_path / "g.sqlite3"
    assert cli.main(["--db", str(db), "run", "--limit", "2", "--out", str(tmp_path / "d.md")]) == 0
    assert "A source returned 2 rows" in capsys.readouterr().err
    # Each source returns 2 rows. Together they pass a limit of 3, but neither source reaches it.
    assert cli.main(["--db", str(db), "run", "--source", "both", "--limit", "3", "--out", str(tmp_path / "d.md")]) == 0
    assert capsys.readouterr().err == ""
    assert cli.main(["--db", str(db), "run", "--out", str(tmp_path / "d.md")]) == 0
    assert capsys.readouterr().err == ""
    assert cli.build_parser().parse_args(["run"]).limit == 500
```

In `tests/test_streamlit_app_static.py`:

```python
def test_streamlit_app_reads_500_rows_by_default_and_warns_at_the_limit() -> None:
    app_text = Path("streamlit_app.py").read_text(encoding="utf-8")

    assert 'limit = st.slider("Rows per source", min_value=25, max_value=1000, value=500, step=25)' in app_text
    assert "if summary.capped:" in app_text
```

- [ ] **Step 2: Run the tests to verify that they fail**

Run: `uv run --locked pytest -q tests/test_clients.py::test_nih_guide_default_run_reads_every_page tests/test_cli.py::test_run_says_when_it_reaches_the_limit tests/test_streamlit_app_static.py`
Expected: 3 failed, 3 passed. The first failure reports 250 sources where the test expects 371.

- [ ] **Step 3: Raise the defaults**

Set `rows: int = 500` in `MatcherConfig`. Set `default=500` on `--limit` in `cli.py`. Replace the slider line in `streamlit_app.py` with the line that the static test names.

- [ ] **Step 4: Say when a source reaches the limit**

The count that a run reports is the sum over its sources, so compare each source's own count to the limit. In `workflow.fetch_score_opportunities`, set `capped` to true when the NIH Guide list or the Grants.gov list holds `config.rows` rows or more, and return it as the third value. Add `capped: bool = False` as the last field of `RunSummary`, and pass it from `run_and_save`. Both callers unpack three values: `cli._run` and `workflow.run_and_save`.

In `cli._run`, when `capped` is true, print to standard error:

```text
A source returned {args.limit} rows, which is the --limit, and may hold more. Raise --limit and run again.
```

In `streamlit_app.py`, after the `st.success` call on line 141, under `if summary.capped:`, call `st.warning("A source reached the row limit and may hold more. Raise Rows per source and run again.")`.

- [ ] **Step 5: Correct the timing sentence in the Docker guide**

Run: `time uv run python -m nih_grant_matcher --db "$(mktemp -d)/g.sqlite3" run --source grants.gov --out "$(mktemp -d)/d.md"`

`docs/docker.md:36` says "so 250 rows take about two minutes". Replace the row count with the `Fetched` count that the command prints, and the duration with the measured time, rounded to the minute.

- [ ] **Step 6: Run the suite**

Run: `uv run --locked pytest -q`
Expected: 99 passed.

- [ ] **Step 7: Commit, from the repository root**

```bash
git add -A "NIH Extractor" docs/docker.md
git commit -m "fix: read up to 500 notices by default and say when a run reaches the limit"
```

---

### Task 3: Stop "AI/AN" from matching as "AI" (finding 2)

On 2026-11-22, 4 of the 8 AI matches were AI/AN only. Each scored Medium and scores Watchlist without the match.

**Files:**
- Modify: `nih_grant_matcher/scoring.py:9`
- Test: `tests/test_scoring.py`

**Interfaces:**
- Consumes: the `_nih(title, description)` helper in `tests/test_scoring.py`.
- Produces: `AI_WORD_RE` does not match "AI" when "/AN" or "/ANs" follows it.

- [ ] **Step 1: Write the failing tests**

```python
def test_ai_an_is_not_artificial_intelligence() -> None:
    scored = MLRelevanceScorer().score(_nih("Substance use prevention in AI/AN communities", "Community research with American Indian and Alaska Native (AI / ANs) youth."), today=date(2026, 7, 6))
    assert "AI" not in scored.matched_terms
    assert scored.classification == "Watchlist"

@pytest.mark.parametrize("title", ["AI tools for AI/AN health", "AI/ML methods for imaging", "PRIMED-AI coordination", "AI/Analytics core"])
def test_ai_matches_beside_ai_an(title: str) -> None:
    assert "AI" in MLRelevanceScorer().score(_nih(title, ""), today=date(2026, 7, 6)).matched_terms
```

- [ ] **Step 2: Run the tests to verify that they fail**

Run: `uv run --locked pytest -q tests/test_scoring.py -k "ai_an"`
Expected: 1 failed, 4 passed. The first test reports `'AI' not in ('AI',)`.

- [ ] **Step 3: Narrow the pattern**

Set the pattern to `r"\bai\b(?!\s*/\s*ans?\b)"` and keep `re.IGNORECASE`. Put a one-line comment above it that names AI/AN as American Indian and Alaska Native.

- [ ] **Step 4: Run the suite**

Run: `uv run --locked pytest -q`
Expected: 104 passed.

- [ ] **Step 5: Commit, from the repository root**

```bash
git add -A "NIH Extractor"
git commit -m "fix: do not score AI/AN as an artificial intelligence match"
```

---

### Task 4: Label the date as an expiration, not a deadline (finding 3)

The NIH Guide date is `expdate`, the day the notice expires. The due-date field reads "Multiple dates, see announcement." on 219 of 371 records.

**Files:**
- Modify: `nih_grant_matcher/digest.py:13`
- Modify: `nih_grant_matcher/excel.py:9`
- Modify: `nih_grant_matcher/scoring.py:117`
- Modify: `streamlit_app.py:179,185,193,219,222,236`
- Modify: `../README.md:198-200,241,253,269,346` and the sentence under the command table
- Test: `tests/test_cli.py`, `tests/test_excel.py`, `tests/test_streamlit_app_run.py`

**Interfaces:**
- Consumes: the `sources` fixture and `CLOSE` in `tests/test_cli.py`.
- Produces: user-facing text only. `Opportunity.close_date`, `ScoreBreakdown.urgency_score`, the frame column key `"Close Date"`, and `_deadline_score` keep their names.

- [ ] **Step 1: Write the failing tests**

In `tests/test_cli.py`:

```python
def test_digest_calls_the_date_an_expiration(sources, tmp_path) -> None:
    out = tmp_path / "d.md"
    cli.main(["--db", str(tmp_path / "g.sqlite3"), "run", "--out", str(out)])
    digest = out.read_text(encoding="utf-8")
    assert f"- Expires: {CLOSE.isoformat()}" in digest
    assert f"  - Open until {CLOSE.isoformat()}" in digest
    assert "eadline" not in digest

def test_digest_replaces_a_saved_deadline_reason(tmp_path) -> None:
    from dataclasses import replace
    from nih_grant_matcher.models import Opportunity
    from nih_grant_matcher.scoring import MLRelevanceScorer
    from nih_grant_matcher.store import OpportunityStore
    saved = MLRelevanceScorer().score(Opportunity(source_id="nih-guide:5", opportunity_number="RFA-OLD", title="Machine learning for health", agency_code="NIH", agency_name="National Institutes of Health", status="active", close_date=CLOSE))
    db, out = tmp_path / "g.sqlite3", tmp_path / "d.md"
    store = OpportunityStore(db)
    try:
        store.upsert_scored(replace(saved, reasons=(f"Deadline is still active: {CLOSE.isoformat()}",)))
    finally:
        store.close()
    assert cli.main(["--db", str(db), "digest", "--out", str(out)]) == 0
    assert "eadline" not in out.read_text(encoding="utf-8")
```

In `tests/test_excel.py`:

```python
def test_excel_header_calls_the_date_an_expiration() -> None:
    from nih_grant_matcher.excel import HEADERS
    assert "Expires" in HEADERS and "Close Date" not in HEADERS
```

In `tests/test_streamlit_app_run.py`, add one line at the end of `test_dashboard_renders_saved_open_results`:

```python
    assert [metric.label for metric in app.metric][:4] == ["Visible Opportunities", "High Matches", "Median Score", "Next Expiration"]
```

- [ ] **Step 2: Run the tests to verify that they fail**

Run: `uv run --locked pytest -q tests/test_cli.py tests/test_excel.py tests/test_streamlit_app_run.py`
Expected: 4 failed. The other tests in the three files pass.

- [ ] **Step 3: Change the text**

| File | Old text | New text |
| --- | --- | --- |
| `digest.py:13` | `- Deadline:` | `- Expires:` |
| `excel.py:9` | `"Close Date"` | `"Expires"` |
| `scoring.py:117` | `Deadline is still active: {date}` | `Open until {date}` |
| `streamlit_app.py:179` | `"Next Deadline"` | `"Next Expiration"` |
| `streamlit_app.py:185` | `drop(columns=["Source ID"]` | `drop(columns=["Source ID", "Close Month"]` |
| `streamlit_app.py:193` | `DateColumn("Close Date"` | `DateColumn("Expires"` |
| `streamlit_app.py:219` | `"Deadlines by Month"` | `"Expirations by Month"` |
| `streamlit_app.py:222` | `"No deadline dates in the current view."` | `"No expiration dates in the current view."` |
| `streamlit_app.py:236` | `d4.metric("Deadline"` | `d4.metric("Expires"` |

On line 193, change the label only. The dictionary key `"Close Date"` stays, because it names the frame column. The change on line 185 takes the helper column `Close Month` out of the Results table. The month chart still reads it from the frame.

After the metric row that ends on line 179, add `st.caption("For an NIH Guide notice, Expires is the day the notice expires, and application due dates are in the announcement. For a Grants.gov row, Expires is the closing date.")`. Grants.gov fills the same field from its `closeDate`, which is a real closing date.

- [ ] **Step 4: Change the README**

| Line | New text |
| --- | --- |
| 198 | `### 5. Expiration Awareness` |
| 200 | `An opportunity that expires soon ranks a little higher. The date shown is the day the notice expires. Application due dates are in the announcement.` |
| 241 | `* Monitor upcoming expiration dates` |
| 253 | `* **Next Expiration**` |
| 269 | `* Open and expiration dates` |
| 346 | `* Expiration-aware prioritization` |
| The sentence under the command table | Replace `whose deadline has passed` with `whose expiration date has passed`. |

Leave the "Long-Term Vision" and "Responsible Use" sections as they are. They speak of real deadlines.

- [ ] **Step 5: Run the suite**

Run: `uv run --locked pytest -q`
Expected: 107 passed.

- [ ] **Step 6: Commit, from the repository root**

```bash
git add -A "NIH Extractor" README.md
git commit -m "fix: label the notice date as an expiration, not a deadline"
```

---

### Task 5: Put threshold scores in the bin that matches their level (finding 4)

A score of 35.0 is Medium and the chart counts it under "25-35". A score of 70.0 is High and the chart counts it under "35-70".

**Files:**
- Modify: `nih_grant_matcher/scoring.py`
- Modify: `streamlit_app.py:9-12,209-216`
- Modify: `tests/test_streamlit_app_static.py:19-24`
- Modify: `../.claude/rules/scoring.md` (the line about score bin edges)
- Test: `tests/test_scoring.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `score_bin(score: float) -> str` at module level in `nih_grant_matcher/scoring.py`. It returns one of `"0-25"`, `"25-35"`, `"35-70"`, `"70-100"`. Each bin includes its lower edge, and `"70-100"` includes 100.

- [ ] **Step 1: Write the failing test**

In `tests/test_scoring.py`:

```python
def test_score_bin_edges_follow_the_levels() -> None:
    from nih_grant_matcher.scoring import score_bin
    assert [score_bin(score) for score in (0, 24.9, 25, 34.9, 35, 69.9, 70, 100)] == ["0-25", "0-25", "25-35", "25-35", "35-70", "35-70", "70-100", "70-100"]
    assert (MLRelevanceScorer._classification(35.0), MLRelevanceScorer._classification(70.0)) == ("Medium", "High")
```

In `tests/test_streamlit_app_static.py`, replace the last two assertions of `test_streamlit_score_bins_use_string_labels` with:

```python
    assert 'filtered["Score"].map(score_bin)' in app_text
```

- [ ] **Step 2: Run the tests to verify that they fail**

Run: `uv run --locked pytest -q tests/test_scoring.py::test_score_bin_edges_follow_the_levels tests/test_streamlit_app_static.py`
Expected: 2 failed. The first reports `cannot import name 'score_bin'`.

- [ ] **Step 3: Implement `score_bin` and use it in the dashboard**

Write `score_bin` as a module-level function directly above `class MLRelevanceScorer`, so that the 35 and 70 edges sit in the file that holds `_classification`. In `streamlit_app.py`, import `score_bin` from `nih_grant_matcher.scoring`. Keep the line `score_labels = ["0-25", "25-35", "35-70", "70-100"]`. Replace the `pd.cut` call and the line after it with `score_counts = filtered["Score"].map(score_bin).value_counts().reindex(score_labels, fill_value=0)`.

- [ ] **Step 4: Correct the scoring rule file**

In `.claude/rules/scoring.md`, the fourth rule says that `streamlit_app.py` repeats the thresholds 35 and 70 as score bin edges. Rewrite it to say that `score_bin` in `scoring.py` holds the bin edges, that `streamlit_app.py` repeats the bin labels and the level names, and that all of them change together.

- [ ] **Step 5: Run the suite**

Run: `uv run --locked pytest -q`
Expected: 108 passed.

- [ ] **Step 6: Commit, from the repository root**

```bash
git add -A "NIH Extractor" .claude/rules/scoring.md
git commit -m "fix: count a threshold score in the chart bin of its level"
```

---

### Task 6: Report a failed request in one line (finding 5)

`run` and `reporter-context` print a traceback when a service does not answer. The dashboard already reports the same failure in one line.

**Files:**
- Modify: `nih_grant_matcher/cli.py` (`main`)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `clients.ApiError`.
- Produces: `cli.main` returns 1 and prints `Request failed: {error}` to standard error when a command raises `ApiError`.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.parametrize("argv, target", [(["run"], (NihGuideClient, "search")), (["reporter-context", "--term", "x"], (NihReporterClient, "search_projects"))])
def test_a_failed_request_exits_1_with_one_line(monkeypatch, tmp_path, capsys, argv, target) -> None:
    from nih_grant_matcher.clients import ApiError
    def fail(self, *args, **kwargs):
        raise ApiError("https://example.invalid/data failed after 3 attempt(s): HTTP Error 503")
    monkeypatch.setattr(*target, fail)
    assert cli.main(["--db", str(tmp_path / "g.sqlite3"), *argv]) == 1
    assert capsys.readouterr().err == "Request failed: https://example.invalid/data failed after 3 attempt(s): HTTP Error 503\n"
    assert not (tmp_path / "g.sqlite3").exists()
```

- [ ] **Step 2: Run the test to verify that it fails**

Run: `uv run --locked pytest -q tests/test_cli.py::test_a_failed_request_exits_1_with_one_line`
Expected: 2 failed with an uncaught `ApiError`.

- [ ] **Step 3: Catch `ApiError` in `main`**

Import `ApiError` from `.clients` again. Wrap the command dispatch in `main` in one `try`. Catch `ApiError` only. Any other exception is a bug and keeps its traceback.

- [ ] **Step 4: Run the suite**

Run: `uv run --locked pytest -q`
Expected: 110 passed.

- [ ] **Step 5: Commit, from the repository root**

```bash
git add -A "NIH Extractor"
git commit -m "fix: report a failed request from the command line in one line"
```

---

### Task 7: Decode HTML entities and keep the Excel file valid (findings 6 and 7)

On 2026-11-22, 36 of 371 records showed `&nbsp;` or `&rsquo;` in a title or summary. A title that holds a control character produces an Excel sheet that does not parse.

**Files:**
- Modify: `nih_grant_matcher/normalizer.py:1-10`
- Modify: `nih_grant_matcher/excel.py:54-63`
- Test: `tests/test_normalizer.py`, `tests/test_excel.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `normalizer._clean_text` returns text with HTML entities decoded. `excel._cell` writes no character that XML 1.0 forbids.

- [ ] **Step 1: Write the failing tests**

In `tests/test_normalizer.py`:

```python
def test_clean_text_decodes_entities_after_it_strips_tags() -> None:
    from nih_grant_matcher.normalizer import _clean_text
    assert _clean_text("Alzheimer&rsquo;s&nbsp;disease <b>data</b> p&lt;0.05") == "Alzheimer’s disease data p<0.05"

def test_nih_guide_title_loses_its_nonbreaking_space() -> None:
    from nih_grant_matcher.normalizer import normalize_nih_guide
    assert normalize_nih_guide({"rowid": "1", "docnum": "PAR-27-001", "title": "Machine&nbsp;learning for imaging", "type": "active"}).title == "Machine learning for imaging"
```

In `tests/test_excel.py`:

```python
def test_write_excel_drops_characters_that_xml_forbids(tmp_path) -> None:
    import xml.etree.ElementTree as ET
    scored = MLRelevanceScorer().score(Opportunity(source_id="x2", opportunity_number="RFA-X2", title="Bad\x08title & <more>", agency_code="NCI", agency_name="NIH NCI", status="active"), today=date(2026, 7, 6))
    output = write_excel([scored], tmp_path / "results.xlsx", min_score=0)
    root = ET.fromstring(zipfile.ZipFile(output).read("xl/worksheets/sheet1.xml"))
    assert "Badtitle & <more>" in [cell.text for cell in root.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")]
```

- [ ] **Step 2: Run the tests to verify that they fail**

Run: `uv run --locked pytest -q tests/test_normalizer.py tests/test_excel.py`
Expected: 3 failed. The Excel test reports `ParseError: not well-formed (invalid token)`.

- [ ] **Step 3: Decode entities in `_clean_text`**

Use `html.unescape` from the standard library. Strip the tags first, decode second, and collapse whitespace last. The whitespace pattern `\s+` already matches the non-breaking space that `&nbsp;` decodes to.

`_clean_text` also cleans Grants.gov attachment names and addresses. `html.unescape` follows HTML and decodes a few old entity names that lack a semicolon, so an address such as `x?a=1&copy=3` would become `x?a=1©=3`. No code displays or follows an attachment value, and none of the 371 live notices held such text, so the plan accepts this limit.

- [ ] **Step 4: Drop forbidden characters in `_cell`**

Before `html.escape`, remove every character that matches `[\x00-\x08\x0b\x0c\x0e-\x1f]`.

- [ ] **Step 5: Run the suite**

Run: `uv run --locked pytest -q`
Expected: 113 passed.

A decoded title changes its similarity score. On live data the largest change was 1.4 points, and no notice changed level. A saved row keeps its old text until the next `run` fetches the notice again.

- [ ] **Step 6: Commit, from the repository root**

```bash
git add -A "NIH Extractor"
git commit -m "fix: decode HTML entities and keep forbidden characters out of the Excel file"
```

---

### Task 8: Document the weekly rebuild limit, verify live, and open the pull request (findings 10 and 11)

**Files:**
- Modify: `../docs/docker.md:125`

**Interfaces:**
- Consumes: the branch with Tasks 1 to 7.
- Produces: one pull request on the fork, ready for the owner to merge.

- [ ] **Step 1: Add the rebuild limit to the Docker guide**

After the sentence "`latest` is normally rebuilt every week with Debian's security fixes." add: "GitHub turns the weekly rebuild off after 60 days without activity in the repository. To turn it on again, open the repository's Actions tab, select the Docker image workflow, and select Enable workflow."

GitHub states the 60-day rule on its page "Disabling and enabling a workflow".

- [ ] **Step 2: Run the suite as CI runs it, and the linters**

Run: `uv run --locked pytest -q -W error::DeprecationWarning`
Expected: 113 passed.

Run from the repository root: `actionlint && mise x zizmor@1.32.0 -- zizmor .github/workflows`
Expected: no findings. No workflow changed, so this run confirms the baseline.

- [ ] **Step 3: Run the command line against the live NIH Guide**

```bash
OUT="$(mktemp -d)"
uv run python -m nih_grant_matcher --db "$OUT/g.sqlite3" run --out "$OUT/d.md"
grep -c "^- Deadline\|Deadline is still active\|&nbsp;\|&rsquo;" "$OUT/d.md"
grep -B1 -A8 -E "PAR-25-441|PAR-24-236|PAR-24-235|PAR-24-260" "$OUT/d.md" | grep -E "Score|Matched terms"
uv run python -m nih_grant_matcher --db "$OUT/g.sqlite3" excel --out "$OUT/r.xlsx"
uv run python -c "import sys, zipfile, xml.etree.ElementTree as ET; ET.fromstring(zipfile.ZipFile(sys.argv[1]).read('xl/worksheets/sheet1.xml')); print('sheet parses')" "$OUT/r.xlsx"
```

Expected: `Fetched N` with N above 250 and no line about the `--limit`. N was 371 on 2026-11-22. The first `grep` prints `0`. The second prints one `- Score:` line with `(Watchlist)` for each of the four notices that is still open, and no `- Matched terms:` line that names `AI`. On 2026-11-22 all four were open and scored 15.5 to 21.8. The last command prints `sheet parses`.

- [ ] **Step 4: Check the dashboard in a browser**

Run: `uv run streamlit run streamlit_app.py --server.port 8502`

Drive `http://localhost:8502` with the `chrome-devtools-mcp:chrome-devtools` skill. Port 8501 may hold the owner's container. Select **Run Search**, then check each line:

- The success message reports more than 250 fetched records, and no row-limit warning shows.
- The fourth metric reads **Next Expiration**, and the caption under the metrics names the announcement as the place for due dates.
- The **Results** table has a column named **Expires**, no column named **Close Month**, and no `&nbsp;` in a title.
- The **Visuals** tab shows **Expirations by Month**, and the score chart shows the four bins in order.
- **Export Current View** writes a file that the command in Step 3 parses.

Stop the server and close every page that the check opened.

- [ ] **Step 5: Commit and ask the owner once for the push and the pull request**

```bash
git add docs/docker.md
git commit -m "docs: say when GitHub turns the weekly rebuild off"
```

On the owner's yes, push `fix/audit-findings` to `origin` and open the pull request against `jrmatherly/Research-Grant-Finder-Agent` `main`. The pull request changes files in the image's `paths` list, so both workflows run. Require `✅ Required checks passed` and a green `🐳 Docker image` run.

- [ ] **Step 6: Check Renovate after Monday 07:00 Eastern (finding 11)**

Run: `gh pr list --repo jrmatherly/Research-Grant-Finder-Agent --state all --author app/renovate`

Expected: a pull request newer than number 2. If the list shows number 2 only, tell the owner that Renovate has opened nothing, and that the Renovate app's access to this repository is the first place to look, under the owner's GitHub Applications settings. Do not change `renovate.json` on a guess.

---

## Appendix A. The audit findings

Each finding was reproduced on `main` at `b4a11f3` on 2026-11-22, against live NIH Guide data where the evidence says so.

| # | Finding | Evidence | Task |
| --- | --- | --- | --- |
| 1 | A default run misses open opportunities. | 371 active notices. The default reads 250 and showed 25 of 41 Medium matches and 6 of 6 High. Grants.gov held 633 rows. | 2 |
| 2 | "AI/AN" scores as "AI". | 4 of 8 AI matches were AI/AN only. They scored 41.5 to 48.1 and score 15.4 to 21.8 without the match. | 3 |
| 3 | "Deadline" is the notice's expiration date. | `normalizer.py:99` maps `expdate` to `close_date`. The due-date field is free text on 229 records. | 4 |
| 4 | The score chart puts threshold scores in the wrong bin. | `pd.cut` put 35.0 in "25-35" and 70.0 in "35-70". | 5 |
| 5 | The command line prints a traceback when a service fails. | `cli.main(["run"])` raised an uncaught `ApiError`. | 6 |
| 6 | A control character corrupts the Excel file. | A title with `\x08` gave a sheet that fails XML parsing. No live record held one. | 7 |
| 7 | HTML entities stay in the text. | 36 of 371 records. Scores moved by 1.4 at most. | 7 |
| 8 | NIH Guide paging has no test. | `clients.py` lines 96 to 135 were uncovered. | 2 |
| 9 | `backfill-xml` fails, and nothing reads its output. | The command failed with the certificate error that the README documents. | 1 |
| 10 | The weekly rebuild can stop without notice. | GitHub disables scheduled workflows in a public repository after 60 days without activity. | 8 |
| 11 | Renovate may not be running. | Its onboarding pull request 2 was closed automatically, and it has opened nothing since. | 8 |
| 12 | The NIH Guide address is an unbranded AWS gateway. | It answered on 2026-11-22. Nothing warns when it moves. | None |
| 13 | Trivy results do not reach the Security tab. | The code-scanning API returns "no analysis found". | None |

## Appendix B. Findings with no task, and alternatives rejected

- **Finding 12 has no task.** When the address stops answering, a failed search names it in the dashboard and, after Task 6, on the command line. One case stays quiet. If the address answers with a different shape, `clients.py:125-129` reads the reply as an empty list, and the run reports `Fetched 0` with exit code 0. A user who sees zero rows from an unfiltered search can tell that something is wrong, so the plan adds no check. A scheduled canary would add a workflow to maintain for the same signal.
- **Finding 13 has no task.** The upload needs the `security-events: write` permission and one more pinned action. The owner listed it as an open choice and has not picked it.
- **`pd.cut(..., right=False)` for finding 4.** It drops a score of exactly 100 from the chart. A test run on 2026-11-22 confirmed that.
- **The `lard` field for finding 3.** It holds an ISO date on 239 of 371 records and may be the last due date. Its meaning is not confirmed, so the plan relabels the date and adds no new one.
- **Removing the row cap for finding 1.** A cap bounds the Grants.gov source, which makes one request per row. Task 2 keeps the cap, raises it, and reports when a run reaches it.
- **The j-mode multi-PR plan skeleton.** It requires ten live lanes and a performance gate per pull request. The owner rejected it for this repository on 2026-11-22 as out of proportion. This plan takes its ordering rules from j-mode: remove before adding, a failing test before each fix, and one verifiable commit per task.
- **Housekeeping, outside this plan.** The container `nih-grant-matcher` still runs on port 8501. `docker rm -f nih-grant-matcher` removes it. `ReviewFeedbackAgent` and `MatcherConfig.min_digest_score` are unused upstream code and stay.
