# First-Run Guidance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A researcher who opens Grant Matcher for the first time can see where each thing is: a clicked row opens in Details, the model is set up under Settings before any application exists, each empty screen says what to do next, and a "Show me around" tour points at the controls of the Find view.

**Architecture:** Four changes, built in the order of the tasks. Tasks 1 and 2 stand alone. Task 4 names the Settings view of Task 2 and uses the keys of Tasks 1 and 3, so it comes after them. The Results table reports the clicked cell, and a callback sets the Details selector. A new Settings view draws the Model panel that Apply already has, from the same function. The tour is one page component (`st.components.v2`) that runs driver.js 1.14.0 in the app's own document and targets widgets by their `st-key-<key>` class. driver.js is vendored as two files inside the package, with its licence, and a test pins their checksums.

**Tech Stack:** Python 3.11 to 3.15, Streamlit 1.59 or later (1.67.0 in `uv.lock`), pandas, pytest with `streamlit.testing.v1.AppTest`, uv, PyInstaller for the macOS app. driver.js 1.14.0 (MIT, no dependencies) as vendored files. No new Python package.

**Spec:** Appendix A of this file. It holds the two reports from the owner, what was measured on 2026-11-24, and the owner's decisions.

## Global Constraints

- Run every command from `NIH Extractor/`. The tests fail from the repository root.
- The test command is `uv run --locked pytest -q -W error::DeprecationWarning`.
- Add no Python dependency. `pyproject.toml` and `uv.lock` change only in Task 6, for the version.
- Match the dense style of the existing code. Do not reformat a line you are not changing. Do not re-indent the Find view's tab blocks.
- `tests/test_streamlit_app_static.py` asserts literal lines of `streamlit_app.py`. Run it after every edit of that file.
- Scoring is not touched. The golden score file must not change.
- The app runs offline apart from its own API calls. The tour loads nothing from a network at run time.
- The vendored files are byte-for-byte the files of the npm tarball `driver.js-1.14.0.tgz`, whose registry integrity is `sha512-BnCFuNU8QO2rrYiDra43Ortx6D6chqMvEMF1q3fWQfsC3xNyCX4T1P1vZDTXTxGdtcXh2v5r11hxSpNLF3DJVw==`.
- Never copy or open the owner's `NIH Extractor/data/grants.sqlite3`. A browser check runs with a scratch folder as the working directory.
- Push, pull request, merge and tag each need the owner's word. This is a fork. Push only to `jrmatherly/Research-Grant-Finder-Agent`.
- Every widget a tour step points at keeps the key named in Task 4. A renamed key silently drops its step.
- Copy follows the existing pages: plain sentences, no exclamation marks, and a control's name as it is written on the page.

## Review Focus

1. **Settings is the first view a new user opens, so no database file exists yet.** Opening Settings creates an empty file. The Find view must then show its "Run a search" line, not an error. Test in Task 2.
2. **A clicked cell whose row is no longer in the list.** A filter narrows the table after a click, and Streamlit keeps the old selection. The Details selector must stay as it was. Test in Task 1.
3. **The tour is started before any search.** The table, the filters and the tabs are not on the page. The tour must run with the steps that are, and never show a step that points at nothing. Test in Task 4 (the step filter) and its browser check in Step 7.
4. **A provider chosen in Settings before any application exists** must be the one Apply shows once the first application is started. Test in Task 2.
5. **A vendored file that was edited, or copied from another driver.js version.** Renovate does not see these files, so a test must fail on any byte that differs. Test in Task 4.

---

### Task 1: A clicked row opens in Details

**Files:**
- Create: `NIH Extractor/nih_grant_matcher/ui/find_page.py`
- Modify: `NIH Extractor/streamlit_app.py:221-232` (the `st.dataframe` call) and `:257-259` (the options list)
- Test: `NIH Extractor/tests/test_find_page.py`
- Modify: `docs/dashboard.md` (the "Results tab" and "Details tab" sections)

**Interfaces:**
- Produces: `picked_option(selection: Mapping[str, Any] | None, options: Sequence[str]) -> str | None` in `nih_grant_matcher/ui/find_page.py`. `selection` is the value Streamlit keeps under the table's key, shaped `{"selection": {"cells": [(row, column_name)], "rows": [], "columns": []}}`.
- Produces: the table has `key="find_table"` and the tabs have `key="find_tabs"`. Task 4 points tour steps at both.

- [ ] **Step 1: Write the failing tests**

```python
from nih_grant_matcher.ui.find_page import picked_option

OPTIONS = ["PAR-1 | One", "PAR-2 | Two", "PAR-3 | Three"]

def _cells(*cells):
    return {"selection": {"cells": list(cells), "rows": [], "columns": []}}

def test_a_clicked_cell_picks_the_option_of_its_row() -> None:
    assert picked_option(_cells((2, "Title")), OPTIONS) == "PAR-3 | Three"

def test_no_clicked_cell_picks_nothing() -> None:
    assert picked_option(_cells(), OPTIONS) is None
    assert picked_option(None, OPTIONS) is None
    assert picked_option({}, OPTIONS) is None

def test_a_cell_of_a_row_that_a_filter_removed_picks_nothing() -> None:
    assert picked_option(_cells((3, "Title")), OPTIONS) is None
    assert picked_option(_cells((0, "Title")), []) is None
```

- [ ] **Step 2: Run them and see them fail**

Run: `uv run --locked pytest -q tests/test_find_page.py`
Expected: FAIL, `No module named 'nih_grant_matcher.ui.find_page'`.

- [ ] **Step 3: Implement `picked_option` in `nih_grant_matcher/ui/find_page.py`**

It reads the first cell's row and returns `options[row]`, or `None` when there is no cell or the row is outside `options`. It imports nothing from Streamlit.

- [ ] **Step 4: Run the tests and see them pass**

Run: `uv run --locked pytest -q tests/test_find_page.py`
Expected: 3 passed.

- [ ] **Step 5: Wire the table in `streamlit_app.py`**

- Move the line that builds `options` (now inside `with tab_detail:`) to just above `st.tabs`, and make it a list once: `options = (filtered["Opportunity Number"].fillna("") + " | " + filtered["Title"].fillna("")).tolist()`. Replace the two later `options.tolist()` calls with `options`.
- Give the tabs a key: `st.tabs(["Results", "Visuals", "Details"], key="find_tabs")`. A key alone adds the CSS class and tracks no state.
- Add to the `st.dataframe` call: `key="find_table", on_select=_pick_row, selection_mode="single-cell"`.
- Define `_pick_row` above the tabs. `st.dataframe` takes no `args`, so the callback closes over `options`:

```python
def _pick_row(options: list[str] = options) -> None:
    picked = picked_option(st.session_state.get("find_table"), options)
    if picked is not None:
        st.session_state["find_opportunity"] = picked
```

- Under the table, add `st.caption("Select a row, then open Details to read it.")`.

The row in the selection is the row's position in the frame that was passed, also after the user sorts a column. That was measured (Appendix A).

- [ ] **Step 6: Add a dashboard test in `tests/test_streamlit_app_run.py`**

`AppTest` has no call that clicks a table cell, so the test hands the table the state a click sends. It reaches `app._tree.get_widget_states`, which is not a public name. That was measured to work on Streamlit 1.67.0 (Appendix A). If a later Streamlit renames it, keep the test and change how it injects the state.

```python
def test_a_clicked_row_is_the_one_details_shows(tmp_path, monkeypatch) -> None:
    import json
    store = OpportunityStore(tmp_path / "data" / "grants.sqlite3")
    try:
        store.upsert_many([MLRelevanceScorer().score(_opp(1, "Machine learning for imaging")), MLRelevanceScorer().score(_opp(2, "Mitochondria in cardiac muscle"))])
    finally:
        store.close()
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    assert app.selectbox(key="find_opportunity").value == "PA-1 | Machine learning for imaging"
    assert "Select a row, then open Details to read it." in " ".join(c.value for c in app.caption)
    table, states = app.dataframe[0], app._tree.get_widget_states
    def clicked():
        sent = states()
        widget = sent.widgets.add()
        widget.id, widget.string_value = table.proto.id, json.dumps({"selection": {"rows": [], "columns": [], "cells": [[1, "Title"]]}})
        return sent
    app._tree.get_widget_states = clicked
    app.run(timeout=30)
    assert not app.exception
    assert app.selectbox(key="find_opportunity").value == "PA-2 | Mitochondria in cardiac muscle"
```

It fails without Step 5's wiring, on the caption. Stash the edit of `streamlit_app.py` to see that, then restore it and see the test pass.

- [ ] **Step 7: Run the whole suite**

Run: `uv run --locked pytest -q -W error::DeprecationWarning`
Expected: every test passes, and the count is the earlier count plus 4 (873 before this plan).

- [ ] **Step 8: Update `docs/dashboard.md`**

In "Results tab", after the first paragraph, add: "Select any cell of a row to choose that row for the **Details** tab." In "Details tab", replace step 2 with: "Under **Opportunity**, the row you selected in the table is chosen. Choose another row there if you want one."

- [ ] **Step 9: Commit**

```bash
git add nih_grant_matcher/ui/find_page.py streamlit_app.py tests/test_find_page.py tests/test_streamlit_app_run.py ../docs/dashboard.md
git commit -m "feat: open the row selected in the results table under Details"
```

---

### Task 2: A Settings view for the model

**Files:**
- Create: `NIH Extractor/nih_grant_matcher/ui/settings_page.py`
- Modify: `NIH Extractor/nih_grant_matcher/llm.py:21` (`WORKSPACE_HINT`)
- Modify: `NIH Extractor/nih_grant_matcher/ui/apply_page.py:20` (`HOW_TO_START`), `:212` (the call), `:236-238` (the function's name and signature)
- Modify: `NIH Extractor/streamlit_app.py:16-18` (imports), `:112` (the View list), `:149-154` (the view routing)
- Test: `NIH Extractor/tests/test_streamlit_app_run.py`
- Modify: `docs/dashboard.md` ("The layout", "Choose a model"), `docs/macos-app.md:63`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `model_settings(store: OpportunityStore, db_path: str, expanded: bool | None = None) -> None` in `apply_page.py`, the old `_model_settings` made public. `expanded=None` keeps today's rule (open until a model and a consent are saved). `expanded=True` forces it open.
- Produces: `settings_page(db_path: str) -> None` in `settings_page.py`.
- Produces: the sidebar's View radio lists `["Find", "Apply", "Profile", "Settings"]` under the existing key `view`.

- [ ] **Step 1: Write the failing tests in `tests/test_streamlit_app_run.py`**

```python
def test_settings_shows_the_model_panel_before_any_database_exists(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    app.sidebar.radio[0].set_value("Settings").run(timeout=30)
    assert not app.exception
    assert app.selectbox(key="apply_llm_provider").value is None
    app.sidebar.radio[0].set_value("Find").run(timeout=30)
    assert not app.exception
    assert "Run a search or load saved results to populate the dashboard." in " ".join(i.value for i in app.info)

def test_a_provider_chosen_in_settings_is_the_one_apply_shows(tmp_path, monkeypatch) -> None:
    _r21_database(tmp_path, start=True)
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    app.sidebar.radio[0].set_value("Settings").run(timeout=30)
    app.selectbox(key="apply_llm_provider").set_value("compatible").run(timeout=30)
    assert not app.exception
    store = OpportunityStore(tmp_path / "data" / "grants.sqlite3")
    try:
        assert store.setting("llm.provider") == "compatible"
    finally:
        store.close()
    app.sidebar.radio[0].set_value("Apply").run(timeout=30)
    assert app.selectbox(key="apply_llm_provider").value == "compatible"
    assert app.text_input(key="apply_llm_base_url").value == "http://localhost:11434/v1"

def test_settings_says_so_when_the_database_folder_cannot_be_made(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "notes.txt").write_text("x")
    app = AppTest.from_file(str(APP)).run(timeout=30)
    app.sidebar.text_input[0].set_value("notes.txt/sub/grants.sqlite3")
    app.sidebar.radio[0].set_value("Settings").run(timeout=30)
    assert not app.exception
    assert "Not a directory" in " ".join(e.value for e in app.error)

def test_the_empty_apply_view_points_to_settings(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    app.sidebar.radio[0].set_value("Apply").run(timeout=30)
    assert "A model is optional, and you set one up under Settings." in " ".join(i.value for i in app.info)
```

`_r21_database(tmp_path, start=True)` saves one R21 opportunity and starts an application for it.

- [ ] **Step 2: Run them and see them fail**

Run: `uv run --locked pytest -q tests/test_streamlit_app_run.py -k "settings"`
Expected: 4 failed. Three fail with `ValueError: 'Settings' is not in list`, and the last on the missing sentence.

- [ ] **Step 3: Make the panel public and add the view**

- In `apply_page.py`, rename `_model_settings` to `model_settings` and add the `expanded` parameter. The expander's value is `expanded` when it is not `None`, and today's expression otherwise. Update the one caller and the one comment that names "the Model expander".
- Change `HOW_TO_START` to: `"No application yet. To start one, open an opportunity under Details in the Find view and choose Start application. A model is optional, and you set one up under Settings."`
- In `llm.py`, `WORKSPACE_HINT` ends "Set it as the Workspace ID in the Model section of the Apply view, or with models --workspace." Change "in the Model section of the Apply view" to "in the Model section, under Settings or in the Apply view". Run `grep -rn "Model section of the Apply view" tests` and update any test that quotes the old words.
- Create `settings_page(db_path)`. It draws `st.header("Settings")`, a container that calls `show_notices()`, opens `OpportunityStore(db_path)`, calls `model_settings(store, db_path, expanded=True)`, and closes the store in a `finally`. It shows `st.error(escape_markdown(str(exc)))` for `sqlite3.Error`, `ValueError` and `OSError`. `OSError` is needed here and not in `apply_page`, because Settings opens a store whose folder may not exist, and the store creates that folder (`store.py:47`). Opening the store creates the file and its folder, which is intended here.
- In `streamlit_app.py`, add "Settings" to the radio and route it like the other two views, with `st.stop()` after it.

- [ ] **Step 4: Run the four tests, then the suite**

Run: `uv run --locked pytest -q -W error::DeprecationWarning`
Expected: every test passes. No existing test needs a change: the one that reads `HOW_TO_START` checks the words "choose Start application", which stay.

- [ ] **Step 5: Update `docs/dashboard.md`**

- "The layout": **View** switches between **Find**, **Apply**, **Profile**, and **Settings**.
- `docs/macos-app.md` line 63 says "A key you save in the Apply view's **Model** section". Change it to "A key you save in the **Model** section, under Settings or in the Apply view,".
- "Choose a model": the first sentence becomes "The **Model** section sets the model that will help you write. It is under **Settings**, where you can set it up before you start an application, and at the top of the Apply view." The rest of the section stays.

- [ ] **Step 6: Commit**

```bash
git add nih_grant_matcher/ui/settings_page.py nih_grant_matcher/ui/apply_page.py nih_grant_matcher/llm.py streamlit_app.py tests/test_streamlit_app_run.py ../docs/dashboard.md ../docs/macos-app.md
git commit -m "feat: add a Settings view that sets up the model before any application exists"
```

---

### Task 3: Help on the Find view's controls

**Files:**
- Modify: `NIH Extractor/streamlit_app.py:113-129` (the sidebar controls)
- Test: `NIH Extractor/tests/test_streamlit_app_run.py`

**Interfaces:**
- Produces: the Run Search button has `key="find_run"`. Task 4 points a tour step at it.

- [ ] **Step 1: Write the failing test**

```python
def test_the_find_controls_explain_themselves(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    assert app.sidebar.selectbox(key="find_source").help == "nih-guide searches the NIH Guide. grants.gov searches Grants.gov for NIH opportunities, one request for each row. both searches the two and keeps one row for each opportunity number."
    assert app.sidebar.slider(key="find_min_score").help == "Hides the rows that score lower. It changes what is shown, not what is saved."
    assert app.sidebar.slider(key="find_max_saved").help == "The most saved rows that Load Saved Results reads from the database."
    assert app.sidebar.text_input[0].help == "The file that holds your results, your profile, your applications and your settings."
```

- [ ] **Step 2: Run it and see it fail**

Run: `uv run --locked pytest -q tests/test_streamlit_app_run.py -k explain_themselves`
Expected: FAIL on the first `help` assertion, which is an empty string.

- [ ] **Step 3: Add the four `help=` values and the key**

Add each `help=` string above to its control. Add `key="find_run"` to the Run Search button. A static test asserts the "Rows per source" line as written, so that control gets no `help=`.

- [ ] **Step 4: Run the suite**

Run: `uv run --locked pytest -q -W error::DeprecationWarning`
Expected: every test passes.

- [ ] **Step 5: Commit**

```bash
git add streamlit_app.py tests/test_streamlit_app_run.py
git commit -m "feat: say what each Find control does"
```

---

### Task 4: The tour

**Files:**
- Create: `NIH Extractor/nih_grant_matcher/ui/vendor/driver.js.iife.js`, `driver.css`, `driver.js.LICENSE` (copied from the tarball, unchanged)
- Create: `NIH Extractor/nih_grant_matcher/ui/tour.py`
- Modify: `NIH Extractor/streamlit_app.py` (the sidebar block of the Find view, after the Export group, and the empty line at `:192`)
- Modify: `docs/dashboard.md:248`
- Test: `NIH Extractor/tests/test_tour.py`

**Interfaces:**
- Consumes: the keys `view`, `find_run`, `find_classes`, `find_table`, `find_tabs` (Tasks 1 and 3, and existing code), and the Settings view of Task 2, which the first step names.
- Produces: `TOUR_STEPS: tuple[tuple[str, str, str], ...]`, each `(key, title, text)`, with `""` as the key of a step that points at nothing.
- Produces: `tour_button() -> None`, which draws the button and mounts the component. Call it once, in the sidebar.
- Produces: `VENDOR: Path`, the folder of the three vendored files. Task 5 reads it.

- [ ] **Step 1: Vendor the files**

```bash
mkdir -p /tmp/driver-js && cd /tmp/driver-js && npm pack driver.js@1.14.0 --silent && tar xzf driver.js-1.14.0.tgz
openssl dgst -sha512 -binary driver.js-1.14.0.tgz | base64
```

Expected: the base64 text equals the integrity value in Global Constraints, without the `sha512-` prefix. Then copy `package/dist/driver.js.iife.js`, `package/dist/driver.css` and `package/license` (as `driver.js.LICENSE`) into `nih_grant_matcher/ui/vendor/`. Do not edit them.

- [ ] **Step 2: Write the failing tests in `tests/test_tour.py`**

```python
import hashlib
from pathlib import Path
from streamlit.testing.v1 import AppTest
from nih_grant_matcher.ui import tour

APP = Path(__file__).resolve().parents[1] / "streamlit_app.py"
PINS = {"driver.js.iife.js": "9ef0eb2b57694145f881c225e61c988df73c03da36f3b2b176de744c17cf1e0d", "driver.css": "9b47907a54c7629054ff09e5fbb7bcd139d672f69efd39df47862f337a3f9a9e", "driver.js.LICENSE": "ec3ce3a08736fefd6a03a6d5b52b0705e6919fe06de9d7bd3fb63dcfb492d76d"}

def test_the_vendored_files_are_those_of_driver_js_1_14_0() -> None:
    assert {name: hashlib.sha256((tour.VENDOR / name).read_bytes()).hexdigest() for name in PINS} == PINS

def test_streamlit_reads_the_script_and_the_styles_as_content_not_as_paths() -> None:
    # Streamlit takes a one-line string that holds a slash for a file path, and the vendored files are one line each.
    from streamlit.components.v2.component_path_utils import ComponentPathUtils
    assert ComponentPathUtils.looks_like_inline_content(tour.script())
    assert ComponentPathUtils.looks_like_inline_content(tour.styles())

def test_the_styles_put_the_overlay_above_the_sidebar() -> None:
    assert ".driver-overlay{z-index:1000000!important}" in tour.styles()

def test_every_step_points_at_a_key_the_find_view_draws() -> None:
    text = APP.read_text(encoding="utf-8")
    keys = [key for key, _, _ in tour.TOUR_STEPS if key]
    assert keys == ["view", "find_run", "find_classes", "find_table", "find_tabs"]
    assert all(f'key="{key}"' in text for key in keys)
    assert tour.TOUR_STEPS[-1][0] == ""

def test_the_script_skips_a_step_whose_control_is_not_on_the_page() -> None:
    assert "getClientRects().length" in tour.script()

def test_show_me_around_starts_the_tour_once_for_each_press(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    assert "tour_nonce" not in app.session_state
    app.sidebar.button(key="tour_start").click().run(timeout=30)
    assert not app.exception
    assert app.session_state["tour_nonce"] == 1
    app.sidebar.button(key="tour_start").click().run(timeout=30)
    assert app.session_state["tour_nonce"] == 2

def test_the_empty_find_view_points_to_the_tour(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    assert [i.value for i in app.info] == ["Run a search or load saved results to populate the dashboard. New here? Select Show me around in the sidebar."]
```

- [ ] **Step 3: Run them and see them fail**

Run: `uv run --locked pytest -q tests/test_tour.py`
Expected: an import error, `cannot import name 'tour'`.

- [ ] **Step 4: Implement `nih_grant_matcher/ui/tour.py`**

- `VENDOR = Path(__file__).parent / "vendor"`.
- `TOUR_STEPS`, with this copy:

| Key | Title | Text |
| --- | --- | --- |
| `view` | Four views | Find ranks NIH opportunities. Apply holds the applications you write. Profile sets what the ranking looks for. Settings sets up a model to help you write. |
| `find_run` | Run a search | Choose a source, add a keyword if you want one, and select Run Search. Leave the keyword empty to see everything that is open. |
| `find_classes` | Narrow the results | Classification, and the two filters beside it, hide rows that are already loaded. They do not search again. |
| `find_table` | The results | The highest score is first. Select a row to choose it for the Details tab. |
| `find_tabs` | Details | Details shows why one opportunity matched, and Start application begins an application for it. |
| (none) | That is the tour | Select Show me around in the sidebar to see it again. |

- `styles() -> str` returns a comment line, a newline, the text of `driver.css`, and `.driver-overlay{z-index:1000000!important}`. Streamlit's sidebar has a z-index of 999991 and driver.js puts its overlay at 10000, so without the rule the sidebar is never dimmed and a sidebar control is never lit.
- `script() -> str` returns the wrapper below around the text of `driver.js.iife.js`. The vendored file assigns to `this.driver`, and `this` is undefined at the top of a module, so it runs inside a function called on an empty object.

```python
GLUE = """
export default function(component) {
  const { data } = component;
  if (!data.nonce || window.__grantMatcherTour === data.nonce) return;
  window.__grantMatcherTour = data.nonce;
  const shown = step => { if (!step.key) return true; const e = document.querySelector('.st-key-' + step.key); return !!e && e.getClientRects().length > 0; };
  const steps = data.steps.filter(shown).map(s => ({ element: s.key ? '.st-key-' + s.key : undefined, popover: { title: s.title, description: s.text } }));
  lib.driver({ showProgress: true, steps }).drive();
}
"""

def script() -> str:
    return "const lib = (function(){" + (VENDOR / "driver.js.iife.js").read_text(encoding="utf-8") + "; return this.driver.js; }).call({});\n" + GLUE
```

- `tour_button()` draws `st.button("Show me around", key="tour_start", on_click=_start, width="stretch")`, where `_start` adds 1 to `st.session_state["tour_nonce"]`. It then mounts the component with `data={"nonce": st.session_state.get("tour_nonce", 0), "steps": [{"key": k, "title": t, "text": x} for k, t, x in TOUR_STEPS]}` and `key="tour"`. The component is registered once at import with `st.components.v2.component("grant_matcher_tour", js=script(), css=styles(), isolate_styles=False)`. `isolate_styles=False` is required, because driver.js adds its popover to the page body, outside any shadow root.

The nonce is why a rerun does not restart the tour: the script returns unless the nonce is new. A page reload starts a new session with no nonce, so the tour never starts by itself.

- [ ] **Step 5: Call `tour_button()` in `streamlit_app.py`**

In the `if view == "Find":` sidebar block, after the Export group, add `st.divider()` and `tour_button()`. Change the empty line (`streamlit_app.py:192`) to `st.info("Run a search or load saved results to populate the dashboard. New here? Select Show me around in the sidebar.")`. `docs/dashboard.md:248` quotes that line in the troubleshooting table, so add the new sentence there too. It is mounted before the main area is drawn. That order was measured to work, because the controls of the earlier run are still on the page when the script runs (Appendix A).

- [ ] **Step 6: Run the suite**

Run: `uv run --locked pytest -q -W error::DeprecationWarning`
Expected: every test passes.

- [ ] **Step 7: Check it in a browser**

```bash
mkdir -p /tmp/gm-tour && cd /tmp/gm-tour && uv run --project "<repo>/NIH Extractor" streamlit run "<repo>/NIH Extractor/streamlit_app.py" --server.port 8770 --server.headless true --server.address 127.0.0.1
```

Open `http://127.0.0.1:8770` and confirm each line:

- Before a search, **Show me around** shows 3 steps: Four views, Run a search, That is the tour.
- After **Run Search**, it shows 6 steps, and the lit control matches each title.
- On a sidebar step the rest of the sidebar is dimmed and the control is lit.
- Escape, the close button and the last step's Done each end the tour and leave no overlay.
- Selecting a table row during or after the tour does not start it again.
- The browser console shows no error from the component, before and after a tour.
- In the dark theme and the light theme the popover text is readable.

Record what you saw in the pull request, with one screenshot of a sidebar step and one of the table step.

- [ ] **Step 8: Commit**

```bash
git add nih_grant_matcher/ui/vendor nih_grant_matcher/ui/tour.py streamlit_app.py tests/test_tour.py ../docs/dashboard.md
git commit -m "feat: add a Show me around tour of the Find view, with driver.js 1.14.0 vendored"
```

---

### Task 5: Ship the vendored files in the macOS app, and record them

**Files:**
- Modify: `NIH Extractor/macos/grant_matcher.spec:17-51` (`licence_files` and `datas`)
- Modify: `NIH Extractor/macos/build.sh:78-79` (the checks after the build)
- Modify: `NIH Extractor/tests/test_macos_launcher.py`
- Modify: `docs/macos-app.md` ("Licences and the icon"), `docs/dashboard.md` (a "Take the tour" paragraph under "The layout"), `AGENTS.md` (Conventions), `renovate.json:7` (the description)

**Interfaces:**
- Consumes: `VENDOR` and the three file names from Task 4.

- [ ] **Step 1: Write the failing test in `tests/test_macos_launcher.py`**

The file already reads `build.sh` as text through `LAUNCHER.parent`.

```python
def test_the_app_carries_the_vendored_tour_files_and_their_licence() -> None:
    spec = (LAUNCHER.parent / "grant_matcher.spec").read_text(encoding="utf-8")
    assert 'os.path.join("nih_grant_matcher", "ui", "vendor")' in spec
    assert 'os.path.join("licenses", "driver.js")' in spec
    build = (LAUNCHER.parent / "build.sh").read_text(encoding="utf-8")
    assert 'test -s "$app/Contents/Resources/nih_grant_matcher/ui/vendor/driver.js.iife.js"' in build
    assert 'test -s "$app/Contents/Resources/nih_grant_matcher/ui/vendor/driver.css"' in build
    assert 'test -s "$app/Contents/Resources/licenses/driver.js/driver.js.LICENSE"' in build
```

- [ ] **Step 2: Run it and see it fail**

Run: `uv run --locked pytest -q tests/test_macos_launcher.py -k vendored`
Expected: FAIL on the first assertion.

- [ ] **Step 3: Change the spec and the build script**

- In `grant_matcher.spec`, add four tuples to the `datas=` expression of `Analysis`, beside the `term_rarity.json` tuple and for the same reason (`collect_submodules` gathers code only). Name each file, with no glob, so that a stray file in the folder is not shipped: each of the three vendored files into `os.path.join("nih_grant_matcher", "ui", "vendor")`, and `driver.js.LICENSE` a second time into `os.path.join("licenses", "driver.js")`, where the app keeps every licence text.
- In `build.sh`, add the three `test -s` lines beside the existing check of Streamlit's `NOTICES`.

- [ ] **Step 4: Run the suite, then build**

Run: `uv run --locked pytest -q -W error::DeprecationWarning`
Expected: every test passes.

Run: `macos/build.sh` with the signing variables unset.
Expected: exit 0, "Grant Matcher.app: valid on disk", and the three new checks pass. In the 0.3.1 build, `term_rarity.json` is at `Contents/Resources/nih_grant_matcher/`, and `Contents/Frameworks/nih_grant_matcher` is a link to that folder, which is how `Path(__file__).parent` finds a data file.

- [ ] **Step 5: Check the tour in the built app**

```bash
HOME=/tmp/gm-home "macos/dist/Grant Matcher.app/Contents/MacOS/Grant Matcher" --serve 8771
```

Open `http://127.0.0.1:8771` (the server refuses `localhost`) and repeat the first four lines of Task 4 Step 7. Then open the app's own window once (`open "macos/dist/Grant Matcher.app"` uses the owner's real data folder, so ask the owner to do this or to agree to it) and run the tour there, because the window is a WebKit view and every earlier check ran in Chrome.

- [ ] **Step 6: Update the docs**

- `docs/macos-app.md`, "Licences and the icon": add that the tour uses driver.js 1.14.0 (MIT), that its two files and its licence are in `NIH Extractor/nih_grant_matcher/ui/vendor/`, copied unchanged from the npm tarball, that `tests/test_tour.py` pins their checksums, and that moving to a newer driver.js means copying the three files again, updating the pins, and repeating the browser check.
- `docs/dashboard.md`: under "The layout", add "**Show me around**, at the bottom of the sidebar in the Find view, points at each part of the page in turn. Press Escape to leave it."
- `AGENTS.md`, Conventions: add one line. "`nih_grant_matcher/ui/vendor/` holds driver.js 1.14.0, copied by hand and pinned by `tests/test_tour.py`. Renovate does not move it, and it is the only JavaScript in the package."
- `renovate.json`: its `description` lists what the repository pins. Add one sentence to it: "The driver.js files in nih_grant_matcher/ui/vendor are copied by hand and are not moved." Run `npx --yes renovate-config-validator renovate.json` if it is on hand, and otherwise `python3 -m json.tool renovate.json`.
- The Docker image copies the whole package and `.dockerignore` re-includes `nih_grant_matcher`, so neither changes. Confirm with `docker build -t gm-tour-check -f Dockerfile .` and `docker run --rm gm-tour-check python -c "from nih_grant_matcher.ui import tour; print(len(tour.script()))"`, which prints a number above 47000.

- [ ] **Step 7: Commit**

```bash
git add macos/grant_matcher.spec macos/build.sh tests/test_macos_launcher.py ../docs/macos-app.md ../docs/dashboard.md ../AGENTS.md ../renovate.json
git commit -m "build: ship the tour's vendored files and licence in the macOS app"
```

---

### Task 6: Release 0.3.2

**Files:**
- Modify: `NIH Extractor/pyproject.toml:3`, `NIH Extractor/nih_grant_matcher/__init__.py:2`, `NIH Extractor/uv.lock`

- [ ] **Step 1: Bump the version**

Set `0.3.2` in `pyproject.toml` and `__version__`, then run `uv lock`. `git diff --stat` shows three files and no dependency moved.

- [ ] **Step 2: Run the suite**

Run: `uv run --locked pytest -q -W error::DeprecationWarning`
Expected: every test passes.

- [ ] **Step 3: Commit, and stop for the owner**

```bash
git add pyproject.toml nih_grant_matcher/__init__.py uv.lock
git commit -m "chore: release 0.3.2"
```

Push, the pull request, the merge and the tag `v0.3.2` each wait for the owner's word. The steps after the merge are in `docs/macos-app.md` under the secrets table. Read the `🏗️ build Grant Matcher ad hoc` check on the pull request before merging, since this change adds files to what the app bundles.

---

## Appendix A. Spec: the reports, what was measured, and the decisions

### What the owner reported (2026-11-24, in the released 0.3.1 app)

1. After a search, selecting a row and then the Details tab shows the first row, whatever was selected.
2. No place in the app sets the model provider, its base URL or its API key.

He then asked for a Settings section in place of drawing the Model panel in an empty Apply view, with Apply still showing the panel once an application exists. He chose the vendored spotlight tour over native help alone and over the `streamlit-tour` package.

### What was measured

In the installed 0.3.1 app, run with a scratch home folder:

- A click on a cell of row 3 (PAR-26-040) and then on Details showed row 1 (RFA-LM-28-001). The table was a display table with no selection, and the Details selector starts at its first option.
- The Apply view with no application showed one line, "No application yet", and no Model panel.

In scratch Streamlit 1.67.0 pages, in Chrome:

- `st.dataframe(..., on_select=<callable>, selection_mode="single-cell")` reports the clicked cell. After the user sorted by a column, the reported row was still the row's position in the frame that was passed: the first row shown was PAR-2, and the callback picked PAR-2.
- A selection's rerun did not restart a running or finished tour.
- A `st.components.v2` component runs in the page's own document, not in an iframe, and found keyed widgets by `.st-key-<key>` in the sidebar and the main area. A keyed `st.dataframe` and a keyed `st.tabs` both carry the class.
- driver.js 1.14.0, wrapped as in Task 4, ran a six-step tour and skipped a step whose key was not on the page. It left no overlay behind.
- Passing the minified `driver.css` as `css=` raised "must be declared in pyproject.toml with asset_dir to use file-backed css". Streamlit reads a one-line string that holds a slash as a path. A leading comment line fixed it.
- Without the z-index rule, the sidebar stayed bright and its control was not lit. With `.driver-overlay{z-index:1000000!important}` the sidebar dimmed and the control was lit. Streamlit's sidebar is at 999991 and its header at 999990.
- The component mounted in the sidebar, before a main area that took 1.5 seconds to draw, still found all five keyed targets when the button was pressed.
- `AppTest` runs a page that mounts a v2 component without an exception, and lists it as an unknown element. A component registered when its module is imported still mounts in a second and a third `AppTest` in the same process.
- Streamlit 1.59.0, the floor in `pyproject.toml`, already has `selection_mode="single-cell"`, a `key` on `st.tabs`, `st.components.v2.component` with `isolate_styles`, and `width` on `st.button`. So the floor does not move.
- In the 0.3.1 app built on this Mac, `term_rarity.json` is at `Contents/Resources/nih_grant_matcher/`, and `Contents/Frameworks/nih_grant_matcher` is a link to that folder.

From the registries and the tarball:

- driver.js 1.14.0 is MIT with no dependencies. The tarball's sha512 equals the registry's integrity value. `dist/driver.js.iife.js` is 47,077 bytes and `dist/driver.css` is 7,539 bytes. The script holds no URL apart from the SVG namespace.

### Found by a review of this plan (2026-11-24)

A reviewer built Tasks 1 to 4 as first written in a scratch copy and ran the plan's tests and the suite there (883 passed). The author ran its two reproduced findings again before changing the plan.

- Settings raised an uncaught `NotADirectoryError` for a Database path under a file, because the store makes the folder. Task 2 now catches `OSError` and tests it.
- A table click can be tested: a widget state injected through `app._tree.get_widget_states` moved the Details selector from PA-1 to PA-2 on a two-row database. Task 1's dashboard test now does that. The first draft only read the source text.
- Each new test failed before its change for the stated reason, and no existing test broke.
- Stale words were found in `llm.py:21`, `docs/macos-app.md:63` and `docs/dashboard.md:248`, and each now has a step.

### Read by a research agent, not re-checked

- Streamlit has no built-in tour, and its issue tracker holds no request for one. (The absence of a tour call in 1.67.0 was measured.)
- Streamlit's documentation recommends `st-key-<key>` for targeting an element and says the HTML around it is not guaranteed between versions.
- Intro.js and Shepherd.js are AGPL with a paid commercial licence.
- A Nielsen Norman Group test of four mobile apps with 70 participants found no gain in task success from a tutorial, and their guidance favours help the user asks for. That is why the tour starts only from a button and never by itself.

### Decisions

| # | Decision | Why |
| --- | --- | --- |
| 1 | A click sets the Details selector and stays on Results. | A click that changes the tab gets in the way of copying a cell or scrolling. The owner did not object when this was proposed. |
| 2 | Settings holds the Model panel only. The Database box stays in the sidebar. | Every view reads the database path. |
| 3 | Settings creates the database file when it is opened. | The settings live in that file, and Find handles an empty file. |
| 4 | The tour covers the Find view only and never starts by itself. | It needs no "seen" record, which would have to live in a database that a new install does not have yet. Its last step names the other views. |
| 5 | driver.js is vendored, not installed. | The owner chose this. It adds no Python package, works offline and survives freezing as two data files. |
| 6 | The vendored files are pinned by checksum in a test. | Renovate does not see them, so a silent edit or a wrong copy must fail a test. |

### Not proven by this plan's research

- Nothing ran in the frozen macOS app or in its WebKit window. Task 5 Step 5 is the first time.
- The screenshots in `images/` that `docs/dashboard.md` shows predate the fourth view and the tour button. No task retakes them.
- The tour's look in the light theme. Task 4 Step 7 checks it.
- Keyboard and screen-reader use of the tour. driver.js documents keyboard control, and it was not tried.
