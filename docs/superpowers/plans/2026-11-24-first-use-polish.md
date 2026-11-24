# First-Use Polish (0.3.3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A researcher who has just installed Grant Matcher sees the tour button and the two controls they use most, sets up a model without guessing, takes the tour without an alert sound, and learns about a new release with its notes when the app opens.

**Architecture:** Eight tasks in four independent areas, built in order. Tasks 1 and 2 reshape the sidebar and move the Database box into Settings. Task 3 changes the tour's script and data. Tasks 4 and 5 change the Model section. Tasks 6 and 7 change the macOS updater and the update feed. Task 8 is the release. Each area was prototyped on 2026-11-24, and its findings file holds the code that ran.

**Tech Stack:** Python 3.11 to 3.15, Streamlit 1.59 or later (1.67.0 in `uv.lock`), pytest with `streamlit.testing.v1.AppTest`, uv, driver.js 1.14.0 vendored and unchanged, PyInstaller, pywebview 6.2.1, Sparkle 2.10.1, bash. No new dependency.

**Spec:** Appendix A of this file, and the six findings files in `docs/superpowers/specs/2026-11-24-first-use-polish/`. Appendix A holds the owner's reports and decisions. Each findings file holds what was measured for one area, with a diff of its prototype. Where this plan and a findings file disagree, this plan wins, because the owner made decisions after the research.

## Global Constraints

- Run every command from `NIH Extractor/`. The tests fail from the repository root.
- The test command is `uv run --locked pytest -q -W error::DeprecationWarning`. The count before this plan is 911.
- Add no dependency. `pyproject.toml` and `uv.lock` change only in Task 8, for the version.
- The Streamlit floor stays 1.59. Use no call that 1.59.0 lacks.
- The three files in `nih_grant_matcher/ui/vendor/` do not change. `tests/test_tour.py` pins them by checksum.
- Match the dense style of the existing code. Do not reformat a line you are not changing. The repository has no formatter.
- `tests/test_streamlit_app_static.py` asserts literal lines of `streamlit_app.py`. Run it after every edit of that file.
- Scoring is not touched. The golden score file must not change.
- Copy follows the existing pages: plain sentences, no exclamation marks, and a control's name as it is written on the page.
- No message may claim to know a key's plan or tier. No provider reports it.
- Make no call to a model provider with a real key. Tests use the `post` fixture.
- Never copy or open the owner's `NIH Extractor/data/grants.sqlite3`. A browser check runs with a scratch folder as the working directory.
- Never open the frozen app's own window, and never run `macos/rehearse-update.sh`. Both write to the owner's real preferences. To try a build, run `HOME=<scratch> "<app>/Contents/MacOS/Grant Matcher" --serve <port>` and open `http://127.0.0.1:<port>`.
- A dev server keeps old modules after an edit. Restart it before each browser check.
- Push, pull request, merge and tag each need the owner's word. This is a fork. Push only to `jrmatherly/Research-Grant-Finder-Agent`.

## Review Focus

1. **A score filter that the user can no longer see.** A user raises Minimum score shown and the Display section is collapsed, or they leave the view and come back. Rows are hidden with no visible cause. The sidebar must say which scores are shown. Test in Task 1.
2. **Rows from the wrong database.** A user changes the Database path in Settings while rows are loaded. Find keeps the old database's rows until Load Saved Results, which is now inside a collapsed section. Find must show the new database's rows. Test in Task 2.
3. **The launch check fails.** The Mac is offline, or Sparkle raises. The app must still open, and Check for Updates must still work. Test in Task 6.
4. **A quota answer that waiting cannot fix.** A free-tier key calls a model with a limit of zero. A real draft must not wait and retry it. Test in Task 5.
5. **A text model that the name pattern hides.** The list is trimmed by a pattern on model names. A user must be able to tell that models were left out, and how many. Test in Task 4.

---

### Task 1: The Find sidebar shows Keyword and Run Search, and tucks the rest away

**Files:**
- Modify: `NIH Extractor/streamlit_app.py` (the `with st.sidebar:` block of the Find view)
- Test: `NIH Extractor/tests/test_streamlit_app_run.py`
- Modify: `docs/dashboard.md` (lines 11, 16, 22, 39, 57, 65, 127)

**Interfaces:**
- Produces: three sidebar sections drawn with `st.expander`, collapsed by default, with these labels and keys: `"Source and rows"` / `find_source_rows`, `"Display"` / `find_display`, `"Export"` / `find_export`. Task 3 names the first label in a tour step.
- Produces: `tour_button()` is the first thing under the View radio in the Find view.
- Every widget key in the Find sidebar stays as it is. Task 3's tour steps point at `view` and `find_run`.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_find_sidebar_keeps_keyword_and_run_search_in_view_and_tucks_the_rest_away(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    assert [(e.label, e.proto.expanded) for e in app.sidebar.expander] == [("Source and rows", False), ("Display", False), ("Export", False)]
    assert [b.label for b in app.sidebar.button][:2] == ["Show me around", "Run Search"]
    # `app.sidebar.button` also lists a button inside a section, so this is what keeps Keyword and Run Search out of one.
    assert ([b.label for e in app.sidebar.expander for b in e.button], [t.label for e in app.sidebar.expander for t in e.text_input]) == (["Load Saved Results", "Export Current View"], ["Excel output"])
    # A collapsed section still runs its controls, so a search and the load on opening have their values.
    assert (app.sidebar.selectbox(key="find_source").value, app.sidebar.slider(key="find_rows").value, app.sidebar.slider(key="find_max_saved").value) == ("nih-guide", 500, 500)


def test_the_sidebar_says_which_scores_are_shown_while_a_minimum_is_set(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    assert not [c for c in app.sidebar.caption if "Showing scores" in c.value]
    app.sidebar.slider(key="find_min_score").set_value(35.0).run(timeout=30)
    assert "Showing scores of 35 and up." in [c.value for c in app.sidebar.caption]
    # The line is outside the sections, so a collapsed Display does not hide it.
    assert not [c for e in app.sidebar.expander for c in e.caption]
    app.sidebar.radio[0].set_value("Profile").run(timeout=30)
    app.sidebar.radio[0].set_value("Find").run(timeout=30)
    assert "Showing scores of 35 and up." in [c.value for c in app.sidebar.caption]
```

- [ ] **Step 2: Run them and see them fail**

Run: `uv run --locked pytest -q tests/test_streamlit_app_run.py -k "tucks_the_rest_away or which_scores_are_shown"`
Expected: 2 failed. The first fails on the empty list of sections.

- [ ] **Step 3: Reshape the sidebar**

The diff that ran is in `docs/superpowers/specs/2026-11-24-first-use-polish/0.3.3-sidebar.md` under "Diff of the prototype against HEAD". Take its `streamlit_app.py` hunk for the sections and the tour button, and leave its Database lines for Task 2.

- In the Find view, call `tour_button()` first, under the View radio and above the Database box, which Task 2 removes. Remove the call and the divider at the bottom.
- Keep `st.header("Run Search")`, the Keyword box and the Run Search button outside any section, in that order with the section between them: Keyword, then `with st.expander("Source and rows", key="find_source_rows"):` holding Source and Rows per source, then the button.
- Replace the Display header and divider with `with st.expander("Display", key="find_display"):` around its two sliders and Load Saved Results. Do the same for Export with `key="find_export"`.
- Under the Display section, outside it, draw `st.caption(f"Showing scores of {min_score:g} and up.")` when `min_score > 0`.

A section's body runs while it is collapsed, so every variable the rest of the script reads stays bound. That was measured (Appendix A).

- [ ] **Step 4: Run the tests, the static test, then the suite**

Run: `uv run --locked pytest -q -W error::DeprecationWarning`
Expected: every test passes. The static test asserts the "Rows per source" line as a substring, so the deeper indent keeps it passing.

- [ ] **Step 5: Update `docs/dashboard.md`**

- Line 11: the sidebar starts with **View**. In the Find view it holds **Show me around**, the **Keyword** box and **Run Search**, and three sections that open when selected: **Source and rows**, **Display**, and **Export**.
- Line 16: **Show me around** is at the top of the sidebar, under **View**.
- Line 22: say that **Source** is under **Source and rows**.
- Lines 39, 57 and 65: say once that **Load Saved Results** and the two sliders are under **Display**.
- Line 64, the **Minimum score shown** row: add that while a minimum is set, the sidebar says `Showing scores of 35 and up.` under **Display**.
- Line 127: say that **Export Current View** is under **Export**.
- Add one sentence: a section closes again when you leave the view, and its values are kept.

- [ ] **Step 6: Commit**

```bash
git add streamlit_app.py tests/test_streamlit_app_run.py ../docs/dashboard.md
git commit -m "feat: keep Keyword and Run Search in view and tuck the rest of the Find sidebar away"
```

---

### Task 2: The Database box moves into Settings

**Files:**
- Modify: `NIH Extractor/streamlit_app.py` (the top of the sidebar, the Settings route, the session state for results)
- Modify: `NIH Extractor/nih_grant_matcher/ui/settings_page.py`
- Modify: `NIH Extractor/nih_grant_matcher/ui/apply_page.py` (`database_error`)
- Test: `NIH Extractor/tests/test_streamlit_app_run.py`
- Modify: `docs/dashboard.md` (lines 11, 33, 253)

**Interfaces:**
- Consumes: the sidebar of Task 1.
- Produces: `settings_page(db_path: str, default_db: str) -> None`. It draws `st.text_input("Database", value=default_db, key="db_path", persist_state="session", help="The file that holds your results, your profile, your applications and your settings.")` first under its header.
- Produces: every view reads the path with `os.path.expanduser(st.session_state.get("db_path", DEFAULT_DB))` at the top of the sidebar block.
- Produces: the session key `find_db`, the database the loaded rows came from.

- [ ] **Step 1: Write the failing tests**

`_rows(path, *titles)` below is a new helper beside `_model`. It saves one scored opportunity for each title with `OpportunityStore(path).upsert_many`, as `test_a_clicked_row_is_the_one_details_shows` does. It numbers them from 1 with `_opp(n, title)`, so the first title of any database is `PA-1`.

```python
def test_the_database_box_is_under_settings_and_every_view_reads_it(tmp_path, monkeypatch) -> None:
    _rows(tmp_path / "data" / "grants.sqlite3", "Machine learning for imaging")
    _rows(tmp_path / "data" / "second.sqlite3", "Mitochondria in cardiac muscle")
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    assert not [t for t in app.sidebar.text_input if t.label == "Database"]
    assert not [c for c in app.sidebar.caption if c.value.startswith("Database:")]
    assert app.selectbox(key="find_opportunity").value == "PA-1 | Machine learning for imaging"
    # Decision 1: no view names the default database, and Settings never draws the line, since the box is on the page.
    app.sidebar.radio[0].set_value("Profile").run(timeout=30)
    assert not [c for c in app.sidebar.caption if c.value.startswith("Database:")]
    app.sidebar.radio[0].set_value("Settings").run(timeout=30)
    app.text_input(key="db_path").set_value("data/second.sqlite3").run(timeout=30)
    assert not [c for c in app.sidebar.caption if c.value.startswith("Database:")]
    assert "These settings, except the API key, are saved in `data/second.sqlite3`, the file named under Database above." in [c.value for c in app.caption]
    app.sidebar.radio[0].set_value("Find").run(timeout=30)
    assert not app.exception
    # The rows of the first database must not stay on the page once another is open.
    assert app.selectbox(key="find_opportunity").value == "PA-1 | Mitochondria in cardiac muscle"
    assert "Database: `data/second.sqlite3`. Change it under Settings." in [c.value for c in app.sidebar.caption]
```

- [ ] **Step 2: Run it and see it fail**

Run: `uv run --locked pytest -q tests/test_streamlit_app_run.py -k "under_settings_and_every_view"`
Expected: FAIL on the first assertion, because the box is in the sidebar.

- [ ] **Step 3: Move the box and read the path from session state**

Take the `settings_page.py`, `apply_page.py` and Database hunks of the diff in `0.3.3-sidebar.md`.

- In `streamlit_app.py`, replace the sidebar's Database box with the read of session state named under Interfaces. Keep the comment's reason for `expanduser`.
- Under the tour button, draw the indicator in every view but Settings, only when the typed path is not `DEFAULT_DB`: `st.caption(f"Database: {f'`{db_path}`' if '`' not in db_path else escape_markdown(db_path)}. Change it under Settings.")`.
- Pass `DEFAULT_DB` to `settings_page`.
- Change the Settings caption's ending to "the file named under Database above."
- Change `database_error` to say "Check the Database path under Settings, and that no other program has the file open."

- [ ] **Step 4: Clear loaded rows when the database changes**

Directly after the `if "scored_items" not in st.session_state:` block at module level (lines 141 and 142 at HEAD), add the lines below. With the rows empty, the load on opening reads the new database.

```python
if st.session_state.get("find_db", db_path) != db_path:
    st.session_state["scored_items"] = []
st.session_state["find_db"] = db_path
```

- [ ] **Step 5: Move the nine tests that reach the box by position**

`app.sidebar.text_input[0]` is on nine lines of `tests/test_streamlit_app_run.py`. Without a change, eleven cases fail, and three pass for the wrong reason, because the first sidebar text box in the Find view is now Keyword. Change every one of the nine lines, as the `tests/test_streamlit_app_run.py` hunks of the diff in `0.3.3-sidebar.md` do.

- Outside Settings, set the key and run: `app.session_state["db_path"] = "notes.txt"` then `app.run(timeout=30)`.
- Inside Settings, use the key: `app.text_input(key="db_path").set_value("data/second.sqlite3").run(timeout=30)`.
- The help assertion switches to Settings first, then reads `app.text_input(key="db_path").help`.
- Two asserted sentences change with the copy of Step 3.

- [ ] **Step 6: Run the suite**

Run: `uv run --locked pytest -q -W error::DeprecationWarning`
Expected: every test passes. Run `grep -n "sidebar.text_input\[0\]" tests/*.py` and expect no line.

- [ ] **Step 7: Update `docs/dashboard.md`**

The line numbers are those of HEAD, and Task 1 Step 5 has added lines since. Find each line by its text.

- Line 11: the sidebar no longer holds the Database path.
- Line 33: delete the **Database** row from the Run a search table. The page has no section on Settings, so add `## Use another database` after `## Come back later`. It says that the **Database** box is the first control under **Settings**, what the file holds, that a leading `~` means the home folder, and that the default is `data/grants.sqlite3`.
- Line 253: "Correct the **Database** path under **Settings**".
- In the new section, add: when another database is open, the sidebar names it. Reloading the page returns to the default database.

- [ ] **Step 8: Commit**

```bash
git add streamlit_app.py nih_grant_matcher/ui/settings_page.py nih_grant_matcher/ui/apply_page.py tests/test_streamlit_app_run.py ../docs/dashboard.md
git commit -m "feat: move the Database path into Settings and name another database in the sidebar"
```

---

### Task 3: The tour is quiet, points at the tab bar, and follows the theme

**Files:**
- Modify: `NIH Extractor/nih_grant_matcher/ui/tour.py`
- Test: `NIH Extractor/tests/test_tour.py`

**Interfaces:**
- Consumes: the section label "Source and rows" of Task 1.
- Produces: `TOUR_STEPS: tuple[tuple[str, str, str, str], ...]`, each `(key, part, title, text)`. `part` is a CSS selector inside the keyed container, and `""` for a step that lights the whole container.
- Produces: `THEME: str`, the stylesheet rules that `styles()` appends.

- [ ] **Step 1: Change the tests that unpack three fields, and add five tests**

In `tests/test_tour.py`, three tests unpack `(key, title, text)`: `test_every_step_points_at_a_key_the_find_view_draws`, `test_show_me_around_starts_the_tour_once_for_each_press` and `test_the_tour_waits_for_a_press_and_is_sent_its_words`. Give each the fourth field, and compare `(s["key"], s["part"], s["title"], s["text"])` in the last. Then add:

```python
def test_the_details_step_lights_the_tab_bar_and_not_the_table_under_it() -> None:
    assert {key: part for key, part, _, _ in tour.TOUR_STEPS if part} == {"find_tabs": '[role="tablist"]'}
    assert "'.st-key-' + s.key + (s.part ? ' ' + s.part : '')" in tour.script()

def test_the_tour_keys_do_not_reach_macos_which_would_play_the_alert_sound() -> None:
    script = tour.script()
    # The listener goes on after drive(), because driver.js ignores a key whose keydown was prevented before its own listener ran.
    assert script.index(".drive();") < script.index("window.addEventListener('keydown', quiet)")
    assert "onDestroyed: () => window.removeEventListener('keydown', quiet)" in script

def test_the_popover_takes_the_colours_of_the_app() -> None:
    assert ".driver-popover{background-color:var(--gm-tour-bg,#fff);color:var(--gm-tour-fg,#2d2d2d)" in tour.styles()
    assert "setProperty('--gm-tour-bg', c.backgroundColor)" in tour.script()

def test_a_click_outside_the_popover_still_closes_the_tour() -> None:
    # The owner chose to keep driver.js's default. The vendored file names the option too, so the glue is what is searched.
    assert "overlayClickBehavior" not in tour.GLUE and "overlayClickBehavior:`close`" in tour.script()

def test_the_run_search_step_names_the_section_that_holds_source() -> None:
    assert "under Source and rows." in tour.TOUR_STEPS[1][3]
```

- [ ] **Step 2: Run them and see them fail**

Run: `uv run --locked pytest -q tests/test_tour.py`
Expected: the three changed tests fail on the unpacking, and the first three new tests and the last fail. The overlay test passes now, because 0.3.2 does not set the option. It is there to fail if the option is added.

- [ ] **Step 3: Change `tour.py`**

Take the diff at the end of `docs/superpowers/specs/2026-11-24-first-use-polish/0.3.3-tour.md`, with two changes: leave `overlayClickBehavior: 'none', ` out of the `lib.driver` call, and give step 2 the text below, since the diff keeps the old sentence. Cut out of the file, the diff applies to HEAD with `git apply`.

- `TOUR_STEPS` gains the `part` field. Only the `find_tabs` step has one, `[role="tablist"]`.
- Step 2's text becomes: "Run Search fetches and ranks the opportunities of the source chosen under Source and rows. A keyword narrows the search, and an empty keyword fetches everything that is open."
- In the script, one `target` helper builds the selector for both the step filter and the step's `element`.
- Before the tour starts, the script copies the computed background and text colour of `.stApp` into `--gm-tour-bg` and `--gm-tour-fg` on the document element.
- The script defines `quiet`, a `keydown` listener that calls `preventDefault()` for Escape, ArrowLeft and ArrowRight. It passes `onDestroyed` to remove it, calls `.drive()`, and only then adds it to `window`.
- `THEME` holds the ten rules of the findings file, and `styles()` appends it after the overlay rule. Each side of the arrow is coloured by its own rule, because one rule for all four sides would paint the three that driver.js makes transparent.
- `tour_button()` sends `part` with each step.

- [ ] **Step 4: Run the suite**

Run: `uv run --locked pytest -q -W error::DeprecationWarning`
Expected: every test passes, and the checksum test still passes because the vendored files did not change.

- [ ] **Step 5: Check it in Chrome, then count the alert path in a WebKit window**

Serve the dashboard from a scratch folder. Take the tour once before any search, press Run Search, and confirm each line:

- The tour shows three steps before a search and six after.
- Step 5 lights the tab bar alone, and its popover is below the tabs and clear of the sidebar.
- Escape, ArrowLeft and ArrowRight still drive the tour.
- After the tour ends by Done, the close button, Escape and a click on the overlay, a probe `keydown` for Escape comes back with `defaultPrevented` false. The overlay route is new to check, since the owner keeps it. The probe is `const e = new KeyboardEvent('keydown', {key: 'Escape', bubbles: true, cancelable: true}); window.dispatchEvent(e); e.defaultPrevented`. Without `cancelable` it is always false. Run it once while the tour is open and see `true`, so that the probe is known to work.
- In the dark theme and the light theme the popover has the app's colours.
- The console shows no error.

Then save the check script in the appendix of `0.3.3-tour.md` to a scratch folder as `check.py`. From `NIH Extractor/`, run `uv run --locked --group macos python -I <scratch>/check.py nih_grant_matcher/ui/vendor naked`, and again with `quiet`. pywebview is in the `macos` group only. Each run opens a pywebview window for about 25 seconds and shows a `python3.13` icon in the Dock, so tell the owner first. Expected, in the JSON line each run prints: `"noResponderFor": 1` for each of the four keys in the `naked` mode, and `0` in the `quiet` mode. The last entry, `after_end_ArrowRight`, is `1` in both modes, which shows that the listener was removed.

- [ ] **Step 6: Commit**

```bash
git add nih_grant_matcher/ui/tour.py tests/test_tour.py
git commit -m "fix: stop the tour's keys from sounding the alert, light the tab bar, and follow the theme"
```

---

### Task 4: The Model section links to each provider's key page and lists models that write text

**Files:**
- Modify: `NIH Extractor/nih_grant_matcher/llm.py` (`Provider`, `PROVIDERS`, `list_models`, a new `writes_text`)
- Modify: `NIH Extractor/nih_grant_matcher/ui/apply_page.py` (`model_settings`, `_list_models`)
- Test: `NIH Extractor/tests/test_llm.py`, `NIH Extractor/tests/test_streamlit_app_run.py`
- Modify: `docs/dashboard.md` (the three paragraphs under `### Choose a model`)

**Interfaces:**
- Produces: `Provider` gains three fields after `default_model`: `key_page: str = ""`, `key_url: str = ""`, `key_note: str = ""`.
- Produces: `writes_text(provider: Provider, names: list[str]) -> list[str]` in `llm.py`. It returns `names` without those that `NOT_TEXT[provider.name]` matches, and all of them for a provider with no pattern.
- Produces: `NOT_TEXT: dict[str, str]`, a regular expression for `openai` and one for `gemini`.
- `list_models` keeps its signature. It leaves out a Claude model that is not `active`, sorts the OpenAI wire newest first, and applies no name pattern. The command line prints that list.

- [ ] **Step 1: Confirm the three key pages and the two default models before writing them**

Confirm each address and each model id on the provider's public documentation on the day you build. The key pages themselves sit behind a sign-in. Do not sign in. The values below were read by a research agent on 2026-11-24 and not opened by the author of this plan.

| Provider | `key_page` | `key_url` | `default_model` |
| --- | --- | --- | --- |
| claude | API keys page of the Claude Console | `https://platform.claude.com/settings/keys` | `claude-opus-5-5` (unchanged) |
| openai | API keys page of the OpenAI platform | `https://platform.openai.com/api-keys` | `gpt-6.2-astra` |
| gemini | API Keys page of Google AI Studio | `https://aistudio.google.com/apikey` | `gemini-4-hydrogen` |
| compatible | none | none | none |

If a page has moved, use the address you opened. If you cannot confirm a default model's id on its provider's models page, leave that provider's default empty and say so in your report.

- [ ] **Step 2: Write the failing tests**

In `tests/test_llm.py`, add `writes_text` to the import from `nih_grant_matcher.llm` on line 5, then add:

```python
@pytest.mark.parametrize("name, reply, names", [
    ("claude", {"data": [{"id": "claude-opus-5-5", "type": "model", "lifecycle": "active"}, {"id": "claude-opus-4-5", "type": "model", "lifecycle": "deprecated"}], "has_more": False}, ["claude-opus-5-5"]),
    ("openai", {"object": "list", "data": [{"id": "model-id-0", "object": "model", "created": 1686935002}, {"id": "gpt-6.2-astra", "object": "model", "created": 1790000000}]}, ["gpt-6.2-astra", "model-id-0"])])
def test_a_list_leaves_out_a_deprecated_model_and_puts_the_newest_first(name, reply, names, post) -> None:
    post.reply(reply)
    assert list_models(PROVIDERS[name], PROVIDERS[name].base_url, "k") == names

@pytest.mark.parametrize("name, listed, kept", [
    ("openai", ["text-embedding-3-small", "gpt-5.5-pro", "gpt-6.2-astra", "whisper-1"], ["gpt-6.2-astra"]),
    ("gemini", ["gemini-4-hydrogen", "gemini-2.5-flash-preview-tts", "gemma-4-31b-it"], ["gemini-4-hydrogen", "gemma-4-31b-it"]),
    ("claude", ["claude-opus-5-5"], ["claude-opus-5-5"]),
    ("compatible", ["nomic-embed-text", "llama9"], ["nomic-embed-text", "llama9"])])
def test_only_models_that_write_text_are_offered(name, listed, kept) -> None:
    assert writes_text(PROVIDERS[name], listed) == kept
```

In `tests/test_streamlit_app_run.py`, in the style of the Model section tests that use `post` and `_apply_view`:

```python
def test_the_model_section_links_the_key_page_and_says_how_many_models_it_left_out(tmp_path, monkeypatch, post) -> None:
    from nih_grant_matcher import keys
    monkeypatch.setenv("GEMINI_API_KEY", "g-key-test-1234")
    monkeypatch.setattr(keys, "PLATFORM", "linux")
    _r21_database(tmp_path, start=True)
    app = _apply_view(tmp_path, monkeypatch)
    for name, url in (("claude", "https://platform.claude.com/settings/keys"), ("openai", "https://platform.openai.com/api-keys"), ("gemini", "https://aistudio.google.com/apikey")):
        app.selectbox(key="apply_llm_provider").set_value(name).run(timeout=30)
        assert any(f"]({url})." in c.value for c in app.caption), name
    post.reply({"models": [{"name": "models/gemini-4-hydrogen", "supportedGenerationMethods": ["generateContent"]}, {"name": "models/gemini-2.5-flash-preview-tts", "supportedGenerationMethods": ["generateContent"]}]})
    app.button(key="apply_llm_list_button").click().run(timeout=30)
    assert any("lists 1 model that writes text and 1 that does not, which is left out." in s.value.replace("\\", "") for s in app.success)
    # The count alone would pass a build that stores the whole list.
    assert app.selectbox(key="apply_llm_model").options == ["gemini-4-hydrogen"]
    app.selectbox(key="apply_llm_provider").set_value("compatible").run(timeout=30)
    assert any("needs no key" in c.value for c in app.caption)
```

- [ ] **Step 3: Run them and see them fail**

Run: `uv run --locked pytest -q tests/test_llm.py tests/test_streamlit_app_run.py -k "deprecated_model or write_text or key_page"`
Expected: pytest stops at a collection error for `tests/test_llm.py`, because `writes_text` cannot be imported, and runs nothing. To see the other two fail on their own, run them before adding the import: the list test fails on its assertion for both cases, and the dashboard test fails with `AssertionError: claude`.

- [ ] **Step 4: Change `llm.py`**

The code that ran is in `docs/superpowers/specs/2026-11-24-first-use-polish/0.3.3-models.md`, sections A and B. This plan differs from it in one way: the name filter is its own function, so that `list_models` still returns the whole list.

- Add the three `Provider` fields, and fill them from the table of Step 1 and the `key_note` strings of section A.
- `NOT_TEXT` takes the two patterns of section B. Keep the comment in the `shortcut:` form, which says the limit and when to add a family.
- `list_models` keeps only Anthropic models whose `lifecycle` is `active`, with a missing field read as `active`. It sorts the OpenAI wire's models by `created`, newest first, with a missing date read as 0.
- `writes_text` applies the pattern.

- [ ] **Step 5: Change `apply_page.py`**

- Under the caption that says where the key is saved, draw one caption from the provider's fields: `Create a key on the [<key_page>](<key_url>).` when it has a page, then `key_note`. The page and its address are constants, so they are drawn as a link without `escape_markdown`. No provider or user text goes in that caption.
- `_list_models` stores `writes_text(provider, found)` and returns a sentence that counts both: "`<host>` lists 1 model that writes text and 1 that does not, which is left out." With none left out it ends after "writes text." Use "models" and "write" for any count but one.

- [ ] **Step 6: Run the suite**

Run: `uv run --locked pytest -q -W error::DeprecationWarning`
Expected: every test passes. `tests/test_llm.py` holds a list sample for Claude with no `lifecycle` field, which stays listed.

- [ ] **Step 7: Update `docs/dashboard.md`**

In "Choose a model", say that the section links to the page where the provider gives out a key, that the list holds the models that write text and says how many it left out, and that `uv run python -m nih_grant_matcher models` prints the list without the name filter.

- [ ] **Step 8: Commit**

```bash
git add nih_grant_matcher/llm.py nih_grant_matcher/ui/apply_page.py tests/test_llm.py tests/test_streamlit_app_run.py ../docs/dashboard.md
git commit -m "feat: link each provider's key page and list the models that write text"
```

---

### Task 5: Test connection answers within a minute and says what a failure means

**Files:**
- Modify: `NIH Extractor/nih_grant_matcher/llm.py` (`HINTS`, `_http_error`, `HttpModel.complete`)
- Modify: `NIH Extractor/nih_grant_matcher/models.py:70` (the `Model` protocol)
- Modify: `NIH Extractor/nih_grant_matcher/ui/apply_page.py` (`model_settings`, `_test_connection`)
- Test: `NIH Extractor/tests/test_llm.py`, `NIH Extractor/tests/test_streamlit_app_run.py`
- Modify: `docs/dashboard.md` (the "Choose a model" section)

**Interfaces:**
- Consumes: the Gemini `default_model` of Task 4. Only the dashboard test depends on it.
- Produces: `complete(self, system: str, user: str, max_tokens: int = 16000, probe: bool = False) -> Completion` on `HttpModel` and on the `Model` protocol. A probe makes one try with a 60 second socket timeout and does not retry.
- Produces: `HINTS: dict[str, str]` in `llm.py`, with the keys `auth`, `quota`, `rate`, `overload` and `missing`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_llm.py`, take two tests of section E of `0.3.3-models.md`: `test_a_failed_test_says_what_it_means_for_the_key` (five cases) and `test_a_429_with_a_limit_above_zero_is_still_a_rate_limit`. Two of the five expected phrases change with the sentences of Step 3: "did not accept the key" becomes "refused this request", and "does not offer this model" becomes "did not find this model". The first block below is the dashboard test, for `tests/test_streamlit_app_run.py`. The second holds the Review Focus 4 test and the test of a failed model list, for `tests/test_llm.py`.

```python
def test_test_connection_makes_one_try_and_explains_a_busy_provider(tmp_path, monkeypatch, post) -> None:
    from nih_grant_matcher import keys
    monkeypatch.setenv("GEMINI_API_KEY", "g-key-test-1234")
    monkeypatch.setattr(keys, "PLATFORM", "linux")
    _r21_database(tmp_path, start=True)
    app = _apply_view(tmp_path, monkeypatch)
    app.selectbox(key="apply_llm_provider").set_value("gemini").run(timeout=30)
    app.checkbox(key="apply_llm_consent_generativelanguage.googleapis.com").check().run(timeout=30)
    busy = {"error": {"code": "service_unavailable", "message": "gemini-4-hydrogen is currently experiencing high demand."}}
    post.fail(503, busy)
    post.fail(503, busy)
    app.button(key="apply_llm_test_button").click().run(timeout=30)
    assert not app.exception and post.calls == 1 and post.slept == []
    assert any("says nothing about your key" in e.value for e in app.error)
```

This test needs a model to be chosen. Task 4 gives Gemini a default. If Task 4 left that default empty, set the model after the provider is chosen, because choosing a provider clears `llm.model`: after the `apply_llm_provider` line, open `OpportunityStore(tmp_path / "data" / "grants.sqlite3")`, call `set_setting("llm.model", "gemini-4-hydrogen")`, close it, and call `app.run(timeout=30)`.

```python
def test_a_draft_does_not_wait_and_retry_a_quota_of_zero(post) -> None:
    post.fail(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded for metric: generate_content_free_tier_requests, limit: 0, model: gemini-4-argon"}})
    with pytest.raises(ModelError) as failed:
        model("gemini").complete("s", "u")
    assert (failed.value.kind, post.calls, post.slept) == ("quota", 1, [])

def test_a_model_list_that_fails_is_not_told_to_list_the_models(post) -> None:
    post.fail(404, {"error": {"message": "Not Found"}})
    with pytest.raises(ModelError) as failed:
        list_models(PROVIDERS["compatible"], "http://localhost:11434", None)
    assert "did not find this model" not in str(failed.value)
```

- [ ] **Step 2: Run them and see them fail**

Run: `uv run --locked pytest -q tests/test_llm.py tests/test_streamlit_app_run.py -k "what_it_means or limit_above_zero or quota_of_zero or one_try or fails_is_not_told"`
Expected: the five `what_it_means` cases fail with a TypeError on `probe`. The quota test fails with `('other', 2, [2.0])`: the kind was `rate`, and the retry found the fake's queue empty. The dashboard test fails with `post.calls == 2`. `limit_above_zero` and the model list test pass now and must still pass after. The model list test is there to fail if the 404 sentence reaches a list.

- [ ] **Step 3: Change `llm.py` and `models.py`**

The code that ran is in sections D and E of `0.3.3-models.md`.

- `HINTS` takes the five sentences of section D, with two changes (decision 15). The first sentence of `auth` becomes "The provider refused this request, most often because of the key." The first sentence of `missing` becomes "The provider did not find this model. Its name may be wrong or retired, or this key may not be allowed to use it."
- In `_http_error`, move the `message =` line above the `kind` line first, since the quota test below reads the message. A 429 whose message holds `limit: 0` as whole words is a quota error. A 404 takes the `missing` sentence, unless the Claude workspace hint applies.
- The `missing` sentence is for a request that names a model. `_http_error` skips it when `(exc.url or "").split("?")[0].endswith("/models")`, so a failed model list gets the provider's words alone. The sentence is added after `_redact`, joined to the provider's words with a period. Added before, a short key would be redacted out of the sentence's own words, which the prototype found.
- `HttpModel.complete` gains `probe`. A probe sends once with a timeout of 60. Anything else retries as today, including the second attempt in the 400 branch.
- The `Model` protocol gains the same argument.

- [ ] **Step 4: Change `apply_page.py`**

- `_test_connection` calls `complete("Answer in one word.", "Say hello.", max_tokens=64, probe=True)`.
- Draw Test connection as a plain button, not a callback, so that a spinner shows while the request waits:

```python
        # Not a callback, so that the spinner shows while the request waits. Its notice is drawn here, since the notices above were drawn before the click was read.
        if st.button("Test connection", key="apply_llm_test_button", disabled=not agreed, help="Sends one short request, which the provider may charge for."):
            with st.spinner(f"Waiting for {escape_markdown(host)} to answer, for up to a minute."):
                _act(db_path, _test_connection)
            show_notices()
```

- [ ] **Step 5: Run the suite**

Run: `uv run --locked pytest -q -W error::DeprecationWarning`
Expected: every test passes. The retry tests in `tests/test_llm.py` keep their waits, because only a probe skips the retry. No fake needs the `probe` argument for the suite to pass. To keep them in step with the protocol, add `probe: bool = False` to `FakeModel.complete` at `tests/helpers.py:98` and `probe=False` to `SavedMeanwhile.complete` at `tests/test_streamlit_app_run.py:1576`.

- [ ] **Step 6: Update `docs/dashboard.md`**

In "Choose a model", say that **Test connection** makes one request and waits up to a minute, that a busy provider says nothing about the key, and that the app cannot know a key's plan.

- [ ] **Step 7: Commit**

```bash
git add nih_grant_matcher/llm.py nih_grant_matcher/models.py nih_grant_matcher/ui/apply_page.py tests ../docs/dashboard.md
git commit -m "feat: make Test connection one short try that says what a failure means"
```

---

### Task 6: The app checks for an update each time it opens

**Files:**
- Modify: `NIH Extractor/macos/launcher.py:89-95` (`start_updater`)
- Test: `NIH Extractor/tests/test_macos_launcher.py`
- Modify: `docs/macos-app.md:11`

**Interfaces:**
- Produces: `start_updater` keeps the controller in `UPDATER`, then asks its updater for a background check when automatic checks are on.

- [ ] **Step 1: Write the failing tests**

Take `test_the_updater_checks_at_launch_only_while_automatic_checks_are_on` from section A of `docs/superpowers/specs/2026-11-24-first-use-polish/0.3.3-updates.md` as it is. Add this one for Review Focus 3:

```python
def test_a_launch_check_that_fails_leaves_the_app_open_and_the_menu_item_working(monkeypatch, tmp_path) -> None:
    launcher = _load(monkeypatch)
    def offline():
        raise RuntimeError("no network")
    checks = []
    controller = types.SimpleNamespace(checkForUpdates_=checks.append, updater=lambda: types.SimpleNamespace(automaticallyChecksForUpdates=lambda: True, checkForUpdatesInBackground=offline))
    monkeypatch.setattr(launcher, "sparkle_class", lambda framework: types.SimpleNamespace(alloc=lambda: types.SimpleNamespace(initWithStartingUpdater_updaterDelegate_userDriverDelegate_=lambda *args: controller)))
    tools = types.ModuleType("PyObjCTools")
    tools.AppHelper = types.SimpleNamespace(callAfter=lambda function, *args: function(*args))
    monkeypatch.setitem(sys.modules, "PyObjCTools", tools)
    monkeypatch.setattr(launcher, "alert", lambda message: pytest.fail(message))
    log = tmp_path / "server.log"
    launcher.start_updater(tmp_path / "Sparkle.framework", log)
    # The menu item is pressed, since keeping the controller is only the means.
    launcher.check_for_updates()
    assert launcher.UPDATER == [controller] and checks == [None] and "no network" in log.read_text()
```

Give the fake controller of the existing test at line 340 an updater whose automatic checks are off: `updater=lambda: types.SimpleNamespace(automaticallyChecksForUpdates=lambda: False)`. Without it that test would write to the log and still pass. Add `and not (tmp_path / "server.log").exists()` to its assertion, so that a start with no check is pinned to write nothing.

- [ ] **Step 2: Run them and see them fail**

Run: `uv run --locked pytest -q tests/test_macos_launcher.py -k "at_launch or leaves_the_app_open"`
Expected: the case with automatic checks on fails with an empty list, and the second test fails because the log does not exist.

- [ ] **Step 3: Add the check to `start_updater`**

After the controller is appended to `UPDATER`, and inside the same `try`: take `UPDATER[0].updater()`, and call its `checkForUpdatesInBackground()` when its `automaticallyChecksForUpdates()` is true. Sparkle's header allows this call right after the updater starts and only while automatic checks are on. The controller is kept first, so the menu item works when the check raises. A check that raises is logged under the same heading as a failed start, "updater did not start". The traceback names `checkForUpdatesInBackground`, which tells the two apart. A second `try` for a truer heading is more code than the case earns.

- [ ] **Step 4: Run the suite**

Run: `uv run --locked pytest -q -W error::DeprecationWarning`
Expected: every test passes.

- [ ] **Step 5: Update `docs/macos-app.md`**

Line 11 becomes: "The app checks for a new release each time it opens, and once a day while it stays open, and shows what changed before it offers to install it."

- [ ] **Step 6: Commit**

```bash
git add macos/launcher.py tests/test_macos_launcher.py ../docs/macos-app.md
git commit -m "feat: check for an update each time the app opens"
```

---

### Task 7: The update window shows the release notes

**Files:**
- Modify: `NIH Extractor/macos/make-appcast.sh`
- Modify: `NIH Extractor/macos/rehearse-update.sh:73` and `:98`
- Test: `NIH Extractor/tests/test_macos_appcast.py`
- Modify: `docs/macos-app.md` (lines 75 and 119), `AGENTS.md` (the CI section's line on `macos-release.yml`)

**Interfaces:**
- Produces: `make-appcast.sh` reads the notes from the file named by `RELEASE_NOTES`, or from `macos/release-notes/<version>.md` beside the script. It exits 1 before it signs when the file is missing or zero bytes long. A file of blank lines passes the script, and Task 8's test is what refuses it for a released version.
- Produces: the path `NIH Extractor/macos/release-notes/<version>.md` that the script reads. Git keeps no empty folder, so Task 8 creates the folder with its first file.

- [ ] **Step 1: Give the test helper notes, and write the failing tests**

`_run` in `tests/test_macos_appcast.py` gains `notes: str = "- A fix."`. It writes the text to `tmp_path / "notes.md"` and sets `RELEASE_NOTES` to that path in the script's environment. Four of the six existing tests need a feed and would fail without it. The two that test a missing key and a missing disk image stop earlier and would still pass. Then add the two tests of section E of `0.3.3-updates.md` as they are: `test_appcast_carries_the_release_notes_exactly` and `test_no_appcast_without_release_notes`.

- [ ] **Step 2: Run them and see them fail**

Run: `uv run --locked pytest -q tests/test_macos_appcast.py`
Expected: the two new tests fail. The six existing tests pass, since the script ignores the new variable.

- [ ] **Step 3: Change `make-appcast.sh`**

Take the script lines of section D of `0.3.3-updates.md`.

- After the check that `sign_update` exists, resolve the notes file as `${RELEASE_NOTES:-$(dirname "$0")/release-notes/$version.md}`, test it with `[ -s ]`, fail with a message that names its path when the test fails, and read it. The new test asserts that the path is in the message.
- Keep `sparkle:format="markdown"` on `<description>`. Start `$notes` right after `<![CDATA[` with no indent, and put the blank line and the link line at column 0 inside the heredoc. Section D shows the two fragments with an elision between them.
- Split any `]]>` in the notes across two CDATA sections with `notes=${notes//]]>/]]]]><![CDATA[>}`. Nothing else needs escaping inside CDATA.
- The description holds the notes, a blank line, and the line `[This release on GitHub](https://github.com/jrmatherly/Research-Grant-Finder-Agent/releases/tag/v$version)`. That line keeps `test_appcast_links_the_release_notes` passing.

- [ ] **Step 4: Keep the rehearsal script working**

`rehearse-update.sh` calls `make-appcast.sh` at line 73 and would now fail there. Before that line, write a short notes file into its work folder, and pass its path as `RELEASE_NOTES` on line 73. Change the instruction at line 98: the update window now opens by itself when the feed offers 0.0.2, so say "If no window opens, choose Check for Updates…". The `--stop-feed` mode still needs the menu item, because a failed launch check shows nothing. Do not run the script.

- [ ] **Step 5: Run the suite and check the scripts**

Run: `uv run --locked pytest -q -W error::DeprecationWarning`
Expected: every test passes.

Run: `bash -n macos/make-appcast.sh && bash -n macos/rehearse-update.sh`
Expected: no output.

- [ ] **Step 6: Update the docs**

- `docs/macos-app.md:119`, the release steps: add that the pull request which sets the version also adds `NIH Extractor/macos/release-notes/X.Y.Z.md`, the text that the update window shows, written for a researcher, with headings, lists, bold and links only.
- `docs/macos-app.md:75`: the update window opens by itself. `Check for Updates…` is needed only when no window opens, as in `--stop-feed`.
- `docs/macos-app.md:104`: add that the workflow also stops before it builds when `NIH Extractor/macos/release-notes/<version>.md` is missing, because the test suite runs first.
- `AGENTS.md`, the `macos-release.yml` line: a release needs `NIH Extractor/macos/release-notes/<version>.md`, and a test fails without it.

- [ ] **Step 7: Commit**

```bash
git add macos/make-appcast.sh macos/rehearse-update.sh tests/test_macos_appcast.py ../docs/macos-app.md ../AGENTS.md
git commit -m "feat: show the release notes in the update window"
```

---

### Task 8: Release 0.3.3

**Files:**
- Create: `NIH Extractor/macos/release-notes/0.3.3.md`
- Modify: `NIH Extractor/pyproject.toml:3`, `NIH Extractor/nih_grant_matcher/__init__.py:2`, `NIH Extractor/uv.lock`
- Test: `NIH Extractor/tests/test_macos_appcast.py`

**Interfaces:**
- Consumes: the notes folder of Task 7.

- [ ] **Step 1: Write the failing test**

```python
def test_the_version_in_pyproject_has_release_notes() -> None:
    import tomllib
    version = tomllib.loads((SCRIPT.parent.parent / "pyproject.toml").read_text())["project"]["version"]
    assert (SCRIPT.parent / "release-notes" / f"{version}.md").read_text().strip()
```

Run: `uv run --locked pytest -q tests/test_macos_appcast.py -k has_release_notes`
Expected: FAIL, because no notes file exists.

- [ ] **Step 2: Write the notes and set the version**

Create `macos/release-notes/0.3.3.md` with this text. The owner edits it in the pull request.

```markdown
## What is new in 0.3.3

- The sidebar is shorter. **Keyword** and **Run Search** stay in view, and **Source and rows**, **Display** and **Export** open when you select them.
- **Show me around** is at the top of the sidebar, under **View**.
- The **Database** path moved to **Settings**.
- The tour no longer plays the alert sound when you press Escape or an arrow key. Its Details step points at the tabs, and it follows the light or dark theme.
- The **Model** section links to the page where each provider gives out an API key, and its list holds the models that can write text.
- **Test connection** answers within a minute and says what a failure means.
- Grant Matcher checks for a new release each time it opens, and this window shows what changed.
```

Set `0.3.3` in `pyproject.toml` and `__version__`, then run `uv lock`. `git diff --stat` shows the lock file with one changed line.

- [ ] **Step 3: Run the suite and build the app**

Run: `uv run --locked pytest -q -W error::DeprecationWarning`
Expected: every test passes.

Run: `macos/build.sh` with `CODESIGN_IDENTITY` and the notary variables unset.
Expected: exit 0, "Smoke test passed" and "valid on disk".

- [ ] **Step 4: Check the built app in a browser**

Serve the build with a scratch home folder (Global Constraints) and confirm each line:

- The Find sidebar shows Show me around, Keyword and Run Search, with three collapsed sections.
- After a search, the tour shows six steps, and step 5 lights the tab bar.
- Settings shows the Database box above the Model section. A second database set there is the one Find, Apply and Profile use, and the sidebar names it.
- Choosing a provider shows the link to its key page.
- With the compatible provider and no server running, Test connection shows a spinner and then a message, within a minute.

- [ ] **Step 5: Commit, and stop for the owner**

```bash
git add macos/release-notes/0.3.3.md pyproject.toml nih_grant_matcher/__init__.py uv.lock tests/test_macos_appcast.py
git commit -m "chore: release 0.3.3"
```

Push, the pull request, the merge and the tag `v0.3.3` each wait for the owner's word. Read the `🏗️ build Grant Matcher ad hoc` check before merging. The steps after the merge are in `docs/macos-app.md` under the secrets table.

- [ ] **Step 6: After the release, the owner's check**

Only the owner can do these, in his installed app after it updates:

- The update window opened by itself when the app was opened, and it showed the notes of Step 2.
- In the tour, Escape and the arrow keys make no sound.
- A click on the link to a provider's key page opens the browser.
- Test connection with his own key shows the spinner and a plain result.

---

## Appendix A. Spec: the reports, what was measured, and the decisions

### What the owner reported (2026-11-24, in the released 0.3.2 app)

He updated from 0.3.1 to 0.3.2 inside the app, which proved the in-app update, and tested the window by hand.

1. An update check should run at every launch, as well as from the menu item.
2. The update window showed one line and a link, with room for the notes.
3. Show me around is at the bottom of the sidebar, where a new user may not find it.
4. The sidebar always shows every control. Keyword and Run Search should stay in view, with Source and Rows per source collapsed. Display and Export should be collapsed. The Database box should move into Settings.
5. In the tour, Escape and the left and right arrow keys work, and each plays the system alert sound.
6. The Model section should give help and a link for getting an API key from the chosen provider.
7. The model list was long and held models that cannot write text.
8. Test connection on two Gemini models dimmed the window for a long time and then showed a 503. His key's project is on Google's free tier, and he asked how the app can tell what a key's tier allows.

Passed in the same test: Next, Previous, Done, the close button, a click on the popover's text with no freeze, the lit control not responding, the four views, and the help text.

### Decisions

| # | Decision | Whose | Why |
| --- | --- | --- | --- |
| 1 | The other views name the open database only when it is not `data/grants.sqlite3`. | Owner | Most users never change it. |
| 2 | The Database box moves into Settings. This reverses decision 2 of Appendix A in `2026-11-24-first-run-guidance.md`. | Owner | His request. |
| 3 | A click outside the popover still closes the tour. | Owner | It is the quickest way out. |
| 4 | The update notes come from a file per version, written for researchers. | Owner | Generated notes are pull request titles. |
| 5 | The model list is trimmed to models that write text. | Owner | Two providers give no field for it, so the trim is a pattern on names. |
| 6 | Test connection makes one try with a limit of 60 seconds. | Owner | A user is waiting on it, and can press again. |
| 7 | The sidebar says "Showing scores of 35 and up." while a minimum is set. | Author | A collapsed Display section hides an active filter. A label that changes was the other way, and it resets an unkeyed section. |
| 8 | Loaded rows are cleared when the database changes. | Author | The button that reloads them is now inside a collapsed section. |
| 9 | The filter is a function of its own, and the message counts what it left out. | Author | A pattern can hide a model that writes text, and the user must be able to tell. The command line still prints every model. |
| 10 | OpenAI and Gemini get a default model. | Author | The Model box was empty until the list was fetched. A default goes stale when a provider retires the model, and Test connection then says the model is not offered. |
| 11 | The key link is a Markdown link in a caption, not a button. | Author | It adds no widget, so the static test does not move. |
| 12 | The hint sentences are added where the error is built, so a draft gets them too. | Author | The same failure reads the same everywhere. |
| 13 | The popover takes the app's colours, and step 5 lights the tab bar. | Author | Seen in the owner's screenshots. He did not object when shown. |
| 14 | The GitHub release body stays generated. | Author | It serves developers, and the window serves researchers. |
| 15 | Two hint sentences are hedged, and a failed model list gets no hint. A 403 reads "refused this request, most often because of the key", and a 404 reads "did not find this model. Its name may be wrong or retired, or this key may not be allowed to use it". | Author | Found in the review of 2026-11-24. A 403 can be a region and a 404 can be a retired model, so the research's sentences stated one cause as fact. The second also claimed to know what a key is allowed, which the Global Constraints rule out. |

The owner can still veto the author's decisions.

### What was measured (2026-11-24)

Each line was run by a research agent on a scratch copy of `38e9439`. The findings file named has the method.

- **Sidebar** (`0.3.3-sidebar.md`). A collapsed section in the sidebar still runs its controls, and their values survive a collapse, a rerun and a change of view. An opened section stays open across reruns of the same view and closes when the view changes. A section with a key keeps its state when its label changes, on 1.67.0. The Database box drawn only in Settings, with a key that persists, gave every view the second database. A page reload returns to the default database, as before. The tour showed three and six steps. `AppTest` finds a keyed widget inside a collapsed section. The prototype's suite passed with 911 tests.
- **Tour** (`0.3.3-tour.md`). In a pywebview 6.2.1 window, real key events for Escape and the arrows reached `-[NSWindow noResponderFor:]` once each, which is the path that ends in the alert sound. With the listener they reached it zero times, and the keys still drove the tour. A listener added before `drive()`, or in the capture phase, broke the keys. `.st-key-find_tabs [role="tablist"]` matched one element 40 pixels tall, and the popover moved from over the sidebar to below the tabs. The popover's text contrast was 15.2 in the dark theme and 13.7 in the light theme.
- **Models** (`0.3.3-models.md`). The name patterns were run over the providers' published model lists, and the ids kept and dropped are listed there. A hint added before the redaction was mangled by a short key. One request today can take two tries of up to 600 seconds each. The prototype's suite passed.
- **Updates** (`0.3.3-updates.md`). PyObjC finds the three selectors on the bundled Sparkle 2.10.1. The call on an updater that has not started returns without an error. Notes that hold `& < ]]> $HOME` and backticks came back exactly, under bash 5.3 and bash 3.2. The 0.3.2 feed's description is the one line the owner saw.

### Read in official sources by a research agent, not opened by the author

- Sparkle's header allows `checkForUpdatesInBackground` right after the updater starts, only while automatic checks are on. A background check does not offer a version the user skipped. With no update or no network it shows nothing.
- Sparkle 2.9 and later draw Markdown notes in a text view, with no scripts and no remote loads. The signature in the feed covers the disk image only.
- No provider's model list says which models a key may use. Google's consumer plans are separate from its API tiers. A 503 is the provider's capacity. `gemini-4-argon` has no free tier, and `gemini-4-hydrogen` has one (`gemini-tiers.md`).
- The three key pages and the two default model ids of Task 4. Task 4 Step 1 opens them again.

### Not proven

- The alert sound itself. The count of the AppKit path was taken on a small page, not on the app, and nobody listened. Task 8 Step 6 is the first time.
- An update from 0.3.2 to 0.3.3 with the launch check and the notes. The rehearsal script was not run, because it writes to the owner's preferences.
- A section's behaviour on the Streamlit 1.59.0 frontend. Its `key` argument exists there, and the page was not run.
- What a free-tier key receives for a model with no free tier when the provider is not busy. The quota hint rests on forum reports of a `limit: 0` message.
- The spinner and the key link in a browser and in the Mac app. Both were checked with `AppTest`.
- The new sidebar in the light theme and at a phone's width.
- The screenshots in `images/` show the old sidebar. No task retakes them.

### Known limits

- A section closes when the user leaves the view and comes back. Its values are kept.
- A page reload returns to the default database.
- The indicator compares the typed path, so another spelling of the default path shows it.
- In the dark theme the popover's arrow is faint against the overlay.
- The table's hover toolbar sits inside the lit tab bar on step 5.
- With Remind Me Later, the update window returns at each launch until the user installs or skips.
- An empty Database box makes the sidebar say "Database: ``. Change it under Settings." Settings shows the error that the database could not be opened.
- The name patterns match anywhere in a model's id, so an id that holds a dropped word, such as `live`, is left out. The count in the message is how a user can tell, and it goes at the next rerun.
- The command line's list leaves out a deprecated Claude model, as the dashboard's does.

### Review of 2026-11-24

Four agents each built one area in a scratch copy of `805a64d`, from the findings diffs and this plan, and ran the suite. The plan then went green in every area but the tour, where one test could never pass. The corrections are in the tasks above. What the review measured, beyond the lines under "What was measured":

- Tasks 1 and 2 pass on Streamlit 1.67.0 and on 1.59.0 (914 tests), Python side only.
- Tasks 4 and 5 pass together (926 tests). Tasks 6, 7 and 8 pass together (917 tests). No run held all eight tasks.
- `macos-release.yml` needs no change. It runs `macos/make-appcast.sh` from `NIH Extractor/`, and the default notes path resolved there in the scratch copy.
- The app and the Docker image do not ship the notes folder.

Written in the review and not run: the hedged hint sentences and the `/models` skip of Task 5, the menu item press in Task 6's test, and the step 2 test of Task 3.
