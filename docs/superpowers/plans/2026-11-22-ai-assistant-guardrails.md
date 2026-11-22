# AI Assistant Guardrails Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** AI coding assistants that work in this repository follow its structure and standards, and a broken change cannot land unnoticed.

**Architecture:** Guidance goes in files that the model reads: one shared `AGENTS.md`, a `CLAUDE.md` that imports it, and two path-scoped rules. Enforcement goes in things that run without the model: permission deny rules and one `Stop` hook for Claude Code, and one CI job for everyone. The baseline is made green first, because every check after it measures against that baseline.

**Tech Stack:** Python 3.10+, pytest, bash, jq, uv (optional, for the stop hook), GitHub Actions, Claude Code project settings.

**Spec:** `docs/superpowers/specs/2026-11-22-ai-assistant-guardrails.md`

## Global Constraints

- Run every test command from `NIH Extractor/`. From the repository root, 3 tests fail.
- The test command is `uv run --no-project --with pytest pytest -q`. `pytest` is not on `PATH`.
- Add no runtime dependency. `pyproject.toml` and `requirements.txt` do not change.
- Do not reformat any line that a task does not name. The repository has no formatter config.
- `.claude/settings.json` puts hook events under a top-level `"hooks"` key.
- Work on the branch `chore/ai-assistant-guardrails`. Do not commit to `main`.
- Do not push and do not open a pull request without the operator's approval. Ask once, in Task 2, for the push and the pull request together.
- Every `git commit` command below takes one more argument, `-m "Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>"`, after its first `-m`.
- Each task ends with the full suite green. Do not start a task while the suite is red.
- Do not test instruction files from a Claude Code session scratchpad. Claude Code does not load `CLAUDE.md`, `AGENTS.md`, or `.claude/rules/` from a scratchpad directory.

## Review Focus

1. A test fixture at `NIH Extractor/tests/data/fixture.json`. An assistant can edit it, because each deny rule is anchored at `/NIH Extractor/` and names one generated directory. An unanchored rule such as `Edit(data/**)` would block the fixture. Pinned by `test_settings_denies_edits_to_generated_output` in Task 5.
2. A stop hook that already sent Claude back to work once. The hook exits with code 0 when `stop_hook_active` is true, so a failing suite cannot hold a turn open. Pinned by `test_stop_hook_exits_when_already_active` in Task 5.
3. A machine without `jq`, `uv`, or `git`. The hook exits with code 0 and blocks nothing. Pinned by `test_stop_hook_skips_when_tools_are_missing` in Task 5.
4. A new `.py` file that git does not track yet. The stop hook still runs the tests. No pytest case pins it, because a test that makes the hook run pytest would start pytest inside pytest. Task 5 Step 7 checks it by hand.
5. A script that writes into a generated directory, such as `python -m nih_grant_matcher run`. Nothing blocks it, and nothing should. The deny rules cover Claude's edit tools, not programs that Claude runs. The ignore rules from Task 1 keep that output out of commits. Task 1 Step 6 checks the ignore rules.

---

## File structure

| File | Task | Responsibility |
| --- | --- | --- |
| `NIH Extractor/streamlit_app.py` | 1 | One comment reworded, so that the static test passes |
| `.gitignore` | 1 | Ignores generated output and `CLAUDE.local.md` |
| `.github/workflows/tests.yml` | 2 | Runs the suite on every push to `main` and every pull request |
| `AGENTS.md` | 3 | The instructions every assistant reads |
| `CLAUDE.md` | 3 | Imports `AGENTS.md` for Claude Code |
| `.claude/rules/scoring.md` | 4 | Loads when an assistant opens the scoring files |
| `.claude/rules/streamlit.md` | 4 | Loads when an assistant opens the dashboard or its static test |
| `NIH Extractor/tests/test_claude_hooks.py` | 5 | Tests the stop hook and the settings file |
| `.claude/hooks/verify-on-stop.sh` | 5 | Runs the suite before Claude ends a turn that changed Python |
| `.claude/settings.json` | 5 | Denies edits to generated output and registers the stop hook |

---

### Task 1: Make the baseline green

**Files:**
- Modify: `NIH Extractor/streamlit_app.py:25`
- Modify: `.gitignore` (append at the end)
- Test: `NIH Extractor/tests/test_streamlit_app_static.py` (exists, unchanged)

**Interfaces:**
- Consumes: nothing.
- Produces: a suite that reports `13 passed`. Tasks 2 and 5 depend on that result.

- [ ] **Step 1: Create the branch and commit the spec and this plan**

```bash
git switch -c chore/ai-assistant-guardrails
git add docs/superpowers
git commit -m "docs: add the AI assistant guardrails spec and plan"
```

- [ ] **Step 2: Run the failing test**

Run from `NIH Extractor/`: `uv run --no-project --with pytest pytest -q tests/test_streamlit_app_static.py`
Expected: `1 failed, 2 passed`. The failing test is `test_streamlit_app_avoids_session_state_items_attribute`.

- [ ] **Step 3: Reword the comment at `NIH Extractor/streamlit_app.py:25`**

The test asserts that the source does not contain `st.session_state.items`. The comment contains it. Replace this line:

```python
    # Older versions accidentally used st.session_state.items, which resolves
```

with this line:

```python
    # Older versions accidentally used the items attribute of session state, which resolves
```

Change no other line in the file.

- [ ] **Step 4: Run the full suite**

Run from `NIH Extractor/`: `uv run --no-project --with pytest pytest -q`
Expected: `13 passed`.

- [ ] **Step 5: Append the ignore rules to `.gitignore`**

```gitignore

### Project ###
NIH Extractor/data/
NIH Extractor/digests/
NIH Extractor/outputs/
CLAUDE.local.md
```

- [ ] **Step 6: Check the ignore rules**

Run from the repository root: `git check-ignore "NIH Extractor/data/grants.sqlite3" "NIH Extractor/digests/latest.md" "NIH Extractor/outputs/x.xlsx" CLAUDE.local.md`
Expected: the command prints all four paths.

- [ ] **Step 7: Commit**

```bash
git add "NIH Extractor/streamlit_app.py" .gitignore
git commit -m "fix: make the test suite pass and ignore generated output"
```

---

### Task 2: Run the tests in CI

**Files:**
- Create: `.github/workflows/tests.yml`

**Interfaces:**
- Consumes: the green suite from Task 1.
- Produces: a check named `tests` on every pull request. Task 5 adds tests that this job runs. Two of those tests need `bash` and `jq` on the runner and skip without them.

- [ ] **Step 1: Create `.github/workflows/tests.yml`**

```yaml
name: tests
on:
  push:
    branches: [main]
  pull_request:
permissions:
  contents: read
jobs:
  pytest:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.10", "3.13"]
    defaults:
      run:
        working-directory: NIH Extractor
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with:
          python-version: ${{ matrix.python-version }}
      - run: python -m pip install pytest
      - run: python -m pytest -q
```

- [ ] **Step 2: Lint the workflow**

Run from the repository root: `actionlint .github/workflows/tests.yml`
Expected: no output, exit code 0.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/tests.yml
git commit -m "ci: run pytest on Python 3.10 and 3.13"
```

- [ ] **Step 4: Ask the operator to approve the push and the pull request**

Ask one question that covers both. State that the branch goes to `jrmatherly/Research-Grant-Finder-Agent` and that nothing goes to the upstream `Quazi-07` repository. Stop until the operator answers. If the operator declines, skip Steps 5 and 6, continue with Task 3, and leave the branch local.

- [ ] **Step 5: Push the branch and open the pull request**

```bash
git push -u origin chore/ai-assistant-guardrails
gh pr create --repo jrmatherly/Research-Grant-Finder-Agent --base main --title "Add AI assistant guardrails" --body "$(cat <<'EOF'
## Why

AI coding assistants that work in this repository should follow its structure and standards, and a broken change should not land unnoticed. Before this change the repository had no assistant instructions and no CI, and one test failed on main.

## What

- Fixes the failing test and ignores generated output.
- Adds a CI job that runs pytest on Python 3.10 and 3.13.
- Adds AGENTS.md, a CLAUDE.md that imports it, and two path-scoped rules.
- Adds Claude Code deny rules for generated output and a Stop hook that runs the tests.

The findings and the reasons are in docs/superpowers/specs/2026-11-22-ai-assistant-guardrails.md.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 6: Check that the job passes**

Run: `gh pr checks --repo jrmatherly/Research-Grant-Finder-Agent --watch`
Expected: `pytest (3.10)` and `pytest (3.13)` both pass. If no check appears, GitHub Actions is disabled on the fork. Tell the operator, who enables it under the repository's **Actions** settings, and run the command again.

---

### Task 3: Write the instruction files

**Files:**
- Create: `AGENTS.md`
- Create: `CLAUDE.md`

**Interfaces:**
- Consumes: nothing.
- Produces: `AGENTS.md`, which the rules in Task 4 assume an assistant has already read. The rules do not repeat its content.

Claude Code loads a `CLAUDE.md` at session start and loads the `AGENTS.md` that it imports. The spec records the test that showed both loads.

- [ ] **Step 1: Read the owner's decisions in the spec**

Decision 2 sets the wording of the dependency line below. If the operator changed that decision, use the operator's wording.

- [ ] **Step 2: Create `AGENTS.md`**

````markdown
# Research Grant Finder Agent

The Python package `nih_grant_matcher` and a Streamlit dashboard live in `NIH Extractor/`. The directory name has a space, so quote it in shell commands.

## Commands

Run every command from `NIH Extractor/`. Three tests open `streamlit_app.py` by relative path, and they fail from the repository root.

- Run all tests: `python -m pytest -q`. When pytest is not installed, use `uv run --no-project --with pytest pytest -q`.
- Run one test file: `python -m pytest -q tests/test_scoring.py`
- Run the dashboard: `streamlit run streamlit_app.py`
- Run the CLI: `python -m nih_grant_matcher run --source nih-guide`

## Conventions

- Scoring stays explainable and uses no LLM. Every score keeps its `reasons`, its `matched_terms`, and its `ScoreBreakdown`.
- Match the dense style of the existing code. Do not reformat a line that you are not changing. The repository has no formatter config, and a formatter rewrites nearly every file.
- Ask before adding a dependency. The package uses the standard library. Only the dashboard needs `streamlit` and `pandas`.

## Gotchas

- `_run` in `cli.py` repeats the pipeline in `fetch_score_opportunities` in `workflow.py`. Change both, or make `_run` call the workflow function.
- `NIH Extractor/data/`, `NIH Extractor/outputs/`, and `NIH Extractor/digests/` hold generated files. Change the code that writes them, not the files.
- `tests/test_streamlit_app_static.py` asserts literal strings in `streamlit_app.py`. A reworded line or comment in that file can fail a test.
````

- [ ] **Step 3: Create `CLAUDE.md`**

```markdown
@AGENTS.md
```

- [ ] **Step 4: Check the size and the commands**

Run from the repository root: `wc -l AGENTS.md`
Expected: fewer than 40 lines.

Run from `NIH Extractor/`: `python3 -m nih_grant_matcher run --help`
Expected: the help text lists `--source` with the choices `nih-guide`, `grants.gov`, and `both`.

- [ ] **Step 5: Commit**

```bash
git add AGENTS.md CLAUDE.md
git commit -m "docs: add AGENTS.md and import it from CLAUDE.md"
```

---

### Task 4: Add the path-scoped rules

**Files:**
- Create: `.claude/rules/scoring.md`
- Create: `.claude/rules/streamlit.md`

**Interfaces:**
- Consumes: `AGENTS.md` from Task 3.
- Produces: nothing that a later task uses.

A rule with a `paths` block loads when Claude reads a matching file. The spec records the test that showed it, for a pattern that starts with `**/` and for a pattern that contains the space in `NIH Extractor`.

- [ ] **Step 1: Create `.claude/rules/scoring.md`**

```markdown
---
paths:
  - "**/nih_grant_matcher/scoring.py"
  - "**/nih_grant_matcher/config.py"
  - "**/nih_grant_matcher/filters.py"
---

# Scoring rules

- The keyword weights, the example sentences, and the classification thresholds are product behavior. The README documents the High, Medium, and Watchlist levels. Do not change a weight or a threshold as a side effect of another task.
- A change to a weight, a threshold, or a filter needs a matching case in `tests/test_scoring.py` or `tests/test_filters.py`.
- Keep every score explainable. A new signal adds a field to `ScoreBreakdown` in `models.py` and a line to the reasons.
- Pass `today` to `MLRelevanceScorer.score` and to `is_current_nih_hhs_opportunity` in tests, so that a test does not depend on the date it runs.
```

- [ ] **Step 2: Create `.claude/rules/streamlit.md`**

```markdown
---
paths:
  - "**/streamlit_app.py"
  - "**/tests/test_streamlit_app_static.py"
---

# Dashboard rules

- Store results under `st.session_state["scored_items"]`. Never read or write a session key named `items` with attribute access, because that name resolves to a method of the session object.
- `tests/test_streamlit_app_static.py` asserts literal strings in `streamlit_app.py`, including text inside comments. Run that test file after every edit to the dashboard.
- Keep the score bin labels as the strings `"0-25"`, `"25-45"`, `"45-70"`, and `"70-100"`.
```

- [ ] **Step 3: Check that the claims in the rules are true**

Run from `NIH Extractor/`: `grep -n "today: date | None = None" nih_grant_matcher/scoring.py nih_grant_matcher/filters.py`
Expected: at least one match in each file.

Run from `NIH Extractor/`: `uv run --no-project --with pytest pytest -q`
Expected: `13 passed`.

- [ ] **Step 4: Commit**

```bash
git add .claude/rules/scoring.md .claude/rules/streamlit.md
git commit -m "docs: add path-scoped rules for scoring and the dashboard"
```

---

### Task 5: Deny edits to generated output and add the stop hook

**Files:**
- Test: `NIH Extractor/tests/test_claude_hooks.py`
- Create: `.claude/hooks/verify-on-stop.sh`
- Create: `.claude/settings.json`

**Interfaces:**
- Consumes: the green suite from Task 1 and the CI job from Task 2.
- Produces: nothing that a later task uses.

Generated output is protected by `Edit` deny rules, not by a hook. A deny rule covers every built-in edit tool, needs no script, and holds in every permission mode. A `/path` pattern in project settings anchors at the repository root.

The stop hook receives one JSON object on standard input and reads `.stop_hook_active`. Exit code 2 sends Claude back to work with the hook's standard error as the reason. Exit code 0 lets the turn end.

Claude Code watches `.claude/settings.json`. If a Claude Code session executes this task in this repository, the deny rules and the stop hook take effect in that session a few seconds after Step 5.

- [ ] **Step 1: Write the failing tests in `NIH Extractor/tests/test_claude_hooks.py`**

```python
import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / ".claude" / "hooks" / "verify-on-stop.sh"
SETTINGS = REPO / ".claude" / "settings.json"
BASH = shutil.which("bash") or ""

needs_shell = pytest.mark.skipif(not BASH or shutil.which("jq") is None, reason="needs bash and jq")


def run_hook(payload: dict, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([BASH, str(HOOK)], input=json.dumps(payload), capture_output=True, text=True, env=env)


@needs_shell
def test_stop_hook_exits_when_already_active() -> None:
    assert run_hook({"stop_hook_active": True}).returncode == 0


@needs_shell
def test_stop_hook_skips_when_tools_are_missing(tmp_path: Path) -> None:
    assert run_hook({"stop_hook_active": False}, env={"PATH": str(tmp_path)}).returncode == 0


def test_settings_registers_stop_hook() -> None:
    stop = json.loads(SETTINGS.read_text(encoding="utf-8"))["hooks"]["Stop"][0]["hooks"][0]
    assert stop["type"] == "command"
    assert stop["command"].endswith("/.claude/hooks/verify-on-stop.sh")


def test_settings_denies_edits_to_generated_output() -> None:
    deny = json.loads(SETTINGS.read_text(encoding="utf-8"))["permissions"]["deny"]
    assert deny == ["Edit(/NIH Extractor/data/**)", "Edit(/NIH Extractor/outputs/**)", "Edit(/NIH Extractor/digests/**)"]
```

Do not add a test that sends `"stop_hook_active": false` to the hook with the real `PATH`. That call makes the hook run pytest, which runs the test again.

- [ ] **Step 2: Run the tests to see them fail**

Run from `NIH Extractor/`: `uv run --no-project --with pytest pytest -q tests/test_claude_hooks.py`
Expected: `4 failed`. The script and the settings file do not exist yet. `bash` exits with code 127 for a missing script, and the two settings tests raise `FileNotFoundError`.

- [ ] **Step 3: Create `.claude/hooks/verify-on-stop.sh`**

```bash
#!/bin/bash
INPUT=$(cat)
[ "$(echo "$INPUT" | jq -r '.stop_hook_active' 2>/dev/null)" = "true" ] && exit 0
command -v uv >/dev/null || exit 0
[ -z "$(git -C "$CLAUDE_PROJECT_DIR" status --porcelain -- '*.py')" ] && exit 0
cd "$CLAUDE_PROJECT_DIR/NIH Extractor" || exit 0
uv run --no-project --with pytest pytest -q -p no:cacheprovider 1>&2 || exit 2
```

The hook does nothing when the working tree has no changed or new `.py` file. After Claude commits, the tree is clean, and the CI job from Task 2 is the check.

- [ ] **Step 4: Make the script executable**

```bash
chmod +x .claude/hooks/verify-on-stop.sh
```

- [ ] **Step 5: Create `.claude/settings.json`**

```json
{
  "permissions": {
    "deny": [
      "Edit(/NIH Extractor/data/**)",
      "Edit(/NIH Extractor/outputs/**)",
      "Edit(/NIH Extractor/digests/**)"
    ]
  },
  "hooks": {
    "Stop": [
      {
        "hooks": [
          { "type": "command", "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/verify-on-stop.sh", "timeout": 120 }
        ]
      }
    ]
  }
}
```

- [ ] **Step 6: Run the full suite**

Run from `NIH Extractor/`: `uv run --no-project --with pytest pytest -q`
Expected: `17 passed`. That is the 13 tests from Task 1 and the 4 tests in `test_claude_hooks.py`.

- [ ] **Step 7: Check the stop hook by hand on a new untracked file**

Run from the repository root:

```bash
echo "x = 1" > "NIH Extractor/nih_grant_matcher/scratch_check.py"
echo '{"stop_hook_active":false}' | CLAUDE_PROJECT_DIR="$PWD" .claude/hooks/verify-on-stop.sh; echo "exit=$?"
rm "NIH Extractor/nih_grant_matcher/scratch_check.py"
```

Expected: pytest output that ends in `17 passed`, then `exit=0`. The pytest output proves that the hook saw the untracked file and ran the suite.

- [ ] **Step 8: Commit and push**

```bash
git add .claude/hooks .claude/settings.json "NIH Extractor/tests/test_claude_hooks.py"
git commit -m "feat: deny edits to generated output and run tests on stop"
git ls-files -s .claude/hooks
```

Expected from the last command: the script shows mode `100755`.

If the operator approved the push in Task 2, run `git push` and then `gh pr checks --repo jrmatherly/Research-Grant-Finder-Agent --watch`. Expected: both `pytest` jobs pass.

---

## Finish

- [ ] Every step above is checked.
- [ ] Reply to the operator with the pull request URL and the result of `gh pr checks`, or with the branch name if the operator declined the push.
- [ ] Tell the operator the one check that needs a person. In a new Claude Code session in this repository, `/context all` lists `CLAUDE.md` under **Memory files**, and `/hooks` lists one `Stop` hook from project settings. The spec already records a headless test of the same behavior, so this check confirms the real files and does not block the merge.

## Out of scope

The spec lists what this plan leaves out and why: the duplicated pipeline in `cli.py`, `datetime.utcnow()`, the `pyright` and `ruff check` findings, a format hook, custom subagents, and the "add a data source" skill.

## Changes after the final review

The whole-branch review found one defect and two inaccurate lines. The fixes are in the commit after Task 5, and the code blocks above still show the text as first built.

- `verify-on-stop.sh` gained `command -v jq >/dev/null || exit 0` as its second line. Without `jq` the hook could not read `stop_hook_active`, so a failing suite blocked every stop on a machine that has `uv` and no `jq`. The test `test_stop_hook_skips_without_jq_even_when_tests_would_fail` pins the fix. The suite now reports `18 passed`.
- `AGENTS.md` now says that the tests fail from the repository root, without the count of three. A bare `python -m pytest -q` from the root fails at collection for more files than three.
- `.claude/rules/scoring.md` now tells an assistant to give a new `ScoreBreakdown` field a default value, because `store.py` rebuilds `ScoreBreakdown` from saved rows.

## Changes after the second review

A second reviewer read `main` at `2fa0221`, and a headless session tested the committed files. The spec records the evidence as findings 18 to 25. The task text above still shows the first design.

- `verify-on-stop.sh` now runs the suite on every stop. It no longer asks git whether a `.py` file changed, and it finds the tests relative to its own path, so it does not read `CLAUDE_PROJECT_DIR`. Review Focus items 3 and 4 and Task 5 Step 7 described the old trigger and no longer apply.
- `test_claude_hooks.py` now has one test for each guard in the hook and one test that the hook blocks. Each test fails when its guard is deleted. Every test gives the hook a stub `uv`, so no test can start pytest inside pytest.
- `tests/test_sources.py` is new. It compiles every source file and imports `nih_grant_matcher.cli` and `nih_grant_matcher.workflow`.
- `AGENTS.md` now says to start the assistant at the repository root, names the fork as the only push target, and says that the CLI calls live APIs and writes files.
- `.claude/rules/scoring.md` now also loads for `models.py` and `store.py`. It says where a new `ScoreBreakdown` field goes, and that the dashboard repeats the thresholds.
- `.gitignore` now ignores `.claude/settings.local.json`.
- The suite reports `37 passed`.
- The constraint "Do not commit to `main`" was superseded. The operator chose a direct push to `main`.
