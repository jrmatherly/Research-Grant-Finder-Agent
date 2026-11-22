# AI assistant guardrails spec

**Goal.** AI coding assistants that work in this repository follow its structure and standards, and a broken change cannot land unnoticed.

**Plan.** `docs/superpowers/plans/2026-11-22-ai-assistant-guardrails.md`

## The rule this spec applies

Claude Code's documentation splits every instruction into two kinds.

- Guidance that the model reads: `CLAUDE.md`, `AGENTS.md`, rules, and skills. The model usually follows guidance. Nothing guarantees it.
- Enforcement that the harness or CI runs: hooks, permission rules, and CI jobs. Enforcement runs every time.

Three points from the documentation set the size of this setup.

- Write down only what an assistant cannot find by reading the repository. Keep the instruction file under 200 lines.
- Use a hook only for a rule that has no exceptions. Keep the enforced set small.
- Add a skill or a subagent when a real trigger appears, such as the third time someone pastes the same procedure.

## Findings

Each finding was measured on 2026-11-22 at commit `bbaf366`. The command that reproduces it follows the finding.

1. The repository has no assistant configuration, no CI, and no pre-commit config. `ls CLAUDE.md AGENTS.md .claude .github .pre-commit-config.yaml` finds none of them.
2. One test fails at `bbaf366`. `test_streamlit_app_avoids_session_state_items_attribute` asserts that the string `st.session_state.items` is absent, and the comment at `NIH Extractor/streamlit_app.py:25` contains it. From `NIH Extractor/`, `uv run --no-project --with pytest pytest -q` reports 1 failed and 12 passed.
3. Rewording that comment makes the suite pass. In a scratch clone the same command then reports 13 passed on Python 3.14 and on Python 3.10.
4. The tests pass only from `NIH Extractor/`. From the repository root, `pytest "NIH Extractor/tests"` fails 3 tests, because `tests/test_streamlit_app_static.py` opens `streamlit_app.py` by relative path. A bare `pytest` from the root fails at collection.
5. `pytest` is not on `PATH` on the development machine. `command -v pytest` finds nothing. The tests need only `pytest`. They import neither `streamlit` nor `pandas`.
6. A formatter would rewrite the codebase. `ruff format --check "NIH Extractor"` flags 22 of 23 files, and the diff changes 1,042 lines. The repository has no formatter config.
7. Git does not ignore generated output. `git check-ignore "NIH Extractor/data/grants.sqlite3" "NIH Extractor/digests/latest.md" "NIH Extractor/outputs/x.xlsx"` matches nothing.
8. `cli.py` `_run` repeats the pipeline in `workflow.py` `fetch_score_opportunities`, including a second copy of the dedupe logic.
9. The repository is a fork. `origin` is `jrmatherly/Research-Grant-Finder-Agent`, and the README clone URL names `Quazi-07`.
10. Every file in the plan was built from the plan's own text in a scratch clone. The suite then reports 17 passed on Python 3.10, 3.13, and 3.14, `actionlint` accepts the workflow, and `jq` parses the settings file.
11. The stop hook blocks when a test fails. On a scratch clone with one new untracked `.py` file and the failing test from finding 2, the hook exits with code 2. On a clean tree it exits with code 0.

The next four findings come from headless `claude -p` sessions, Claude Code 2.1.330, in a temporary copy of the repository.

12. `Edit` deny rules work on a path that contains a space. With `Edit(/NIH Extractor/data/**)` in `.claude/settings.json`, the Write tool refused to create `NIH Extractor/data/test.txt` and created `NIH Extractor/tests/data/fixture.txt`.
13. The stop hook works in a live session. After an edit to `filters.py` on the red baseline, the hook sent the failing test output back to Claude, and the second stop passed with `stop_hook_active` set to true.
14. `CLAUDE.md` loads at session start, and the `AGENTS.md` that it imports loads with it. An `InstructionsLoaded` hook logged both, with the load reasons `session_start` and `include`.
15. A path-scoped rule loads when Claude reads a matching file. The same hook logged `path_glob_match` for the pattern `**/nih_grant_matcher/scoring.py` and for the pattern `NIH Extractor/streamlit_app.py`. A rule for a file that Claude did not read stayed out of context.
16. Claude Code does not load `CLAUDE.md`, `AGENTS.md`, or `.claude/rules/` from a session scratchpad directory. The debug log says so for each file. Test instruction files from another directory.
17. The current major versions of the GitHub actions are `actions/checkout@v7` and `actions/setup-python@v7`. `gh api repos/actions/checkout/releases/latest` reports `v7.0.1`.

The next findings come from the second review, after the first push to `main`, at commit `2fa0221`.

18. The CI job runs on the fork and passes. The first run on `main` reported 18 passed on Python 3.10 and on Python 3.13, so GitHub Actions is enabled and the runner provides `bash` and `jq`.
19. The committed instruction files load in a live session. From the repository root, an `InstructionsLoaded` hook logged `CLAUDE.md`, the imported `AGENTS.md`, and both rules on a path match.
20. A deny rule also stops a Bash redirect. `echo hi >` into `NIH Extractor/tests/data/` succeeded, and the same command into `NIH Extractor/outputs/` was refused.
21. No test imported or compiled `cli.py`, `workflow.py`, `agents.py`, `digest.py`, `__main__.py`, or `streamlit_app.py`. On a copy with a syntax error in `streamlit_app.py` and in `agents.py` and a bad import in `workflow.py`, the 13 original tests still passed.
22. Three of the five hook tests could not fail. With `CLAUDE_PROJECT_DIR` unset the old hook fell through to a `cd` that failed and exited with code 0, whatever the guards did.
23. The old stop hook skipped a turn that committed its own work, because it ran only when the working tree held a changed `.py` file. It also skipped edits to non-Python files that the tests cover, such as `.claude/settings.json`.
24. A session started in `NIH Extractor/` does not get the project settings. In a headless session started there, with a failing test in the tree, the stop hook did not run and a write to `data/x.txt` succeeded. An `InstructionsLoaded` hook showed that the root `CLAUDE.md` and the path-scoped rules still load there, and that the imported `AGENTS.md` does not. For that reason `CLAUDE.md` itself says to start at the repository root.
25. On the development machine `jq` and `uv` are mise shims. A shim does not run from a `PATH` that holds only the shim, so a hook test must put its stubs in front of the real `PATH` and not replace it.

## Decisions

| Piece | Decision | Reason |
| --- | --- | --- |
| Baseline | Fix the failing test and ignore generated output first | A stop hook or a CI job on a red baseline blocks every change (finding 11). |
| CI | One GitHub Actions job that runs `pytest` on Python 3.10 and 3.13 | Hooks bind only Claude Code. CI is the one check that binds every assistant and every person. |
| Instruction file | `AGENTS.md` at the root, plus a `CLAUDE.md` that holds `@AGENTS.md` | Other assistants read `AGENTS.md`. The import works on Windows clones, and a symlink does not. The repository ships Windows launchers. |
| Rules | Two path-scoped rules in `.claude/rules/`, one for scoring and one for the dashboard | Each rule loads only when an assistant opens a matching file. |
| Generated output | Three `Edit` deny rules in `.claude/settings.json` | The rule has no exceptions. A deny rule covers every built-in edit tool, holds in every permission mode, and needs no script. A `PreToolUse` hook script was the first design. It lost because it misses the NotebookEdit tool, needs `bash` and `jq`, and on Windows without Git Bash a failed `PreToolUse` hook blocks every edit. |
| Stop hook | One `command` hook that runs the tests every time Claude ends a turn | The harness runs it, not a model. The suite takes under one second. The first design ran only when the working tree held a changed `.py` file, and it lost because of finding 23. The hook finds the tests relative to its own path, and it exits with code 0 when `jq` or `uv` is missing. It blocks once per turn. A second stop passes even if the suite still fails, and CI is the check that cannot be skipped. |
| Source checks | `tests/test_sources.py` compiles every source file and imports `cli` and `workflow` | Finding 21. One test file covers the stop hook and CI together. |
| Format hook | Not built | Finding 6. The first edit would produce a 1,042-line diff against the upstream fork. |
| Skill | Deferred | The only candidate is "add a data source", which touches the client, the normalizer, the agent, `workflow.py`, `cli.py`, and a test. Build it the first time someone adds a source. |
| Subagents | Not built | The repository holds 1,267 lines of Python, and several review agents are already installed. No side task here floods the main context. |

## Owner's decisions

Each line is the default that the plan uses. Change a line here before execution, and the plan follows it.

1. `AGENTS.md` is the shared file and `CLAUDE.md` imports it.
2. The dependency rule reads "Ask before adding a dependency". The rule is inferred from `clients.py`, which uses `urllib`, and from `excel.py`, which writes the xlsx file by hand. It is not a recorded decision of the project.
3. The code keeps its dense style. No formatter is adopted.
4. The work lands on the fork. Nothing is sent to `Quazi-07`. The plan called for one pull request. The operator chose a direct push to `main` on 2026-11-22.
5. The stop hook needs `uv` and `jq`. On a machine without either one the hook does nothing, and CI is the check.

## What this spec does not cover

- Removing the duplicated pipeline in `cli.py`. The instruction file warns about it.
- Replacing `datetime.utcnow()`, which Python 3.12 deprecates.
- The 19 `pyright` errors and the 28 `ruff check` findings.
- The "add a data source" skill.

## Unverified

- How assistants other than Claude Code read `AGENTS.md` in this repository.
- Whether an interactive session started in `NIH Extractor/` offers to approve the `AGENTS.md` import. The documentation says an import outside the working directory needs a one-time approval. The headless test cannot show a dialog.
- How the stop hook behaves on Windows without Git Bash. The documentation says a failed `Stop` hook does not block, so the expected result is an error line and no check.

## Sources

- [Best practices for Claude Code](https://code.claude.com/docs/en/best-practices)
- [How Claude remembers your project](https://code.claude.com/docs/en/memory)
- [Automate actions with hooks](https://code.claude.com/docs/en/hooks-guide)
- [Extend Claude Code](https://code.claude.com/docs/en/features-overview)
- [Extend Claude with skills](https://code.claude.com/docs/en/skills)
- [Create custom subagents](https://code.claude.com/docs/en/sub-agents)

The `plugin-dev:hook-development` skill says that `.claude/settings.json` takes hook events at the top level, and it recommends `prompt` hooks. The documentation shows a `"hooks"` wrapper key and says that a `prompt` hook is not deterministic. This spec follows the documentation.
