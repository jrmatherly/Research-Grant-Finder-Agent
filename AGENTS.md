# Research Grant Finder Agent

The Python package `nih_grant_matcher` and a Streamlit dashboard live in `NIH Extractor/`. The directory name has a space, so quote it in shell commands.

## Commands

Start your coding assistant at the repository root, so that it loads the project settings in `.claude/`. Run the commands below from `NIH Extractor/`. The tests fail from the repository root, because pytest finds the package and `streamlit_app.py` relative to that directory.

- Run all tests: `python -m pytest -q`. When pytest is not installed, use `uv run --no-project --with pytest pytest -q`.
- Run one test file: `python -m pytest -q tests/test_scoring.py`
- Run the dashboard: `streamlit run streamlit_app.py`
- Run the CLI: `python -m nih_grant_matcher run --source nih-guide`. It calls the live NIH and Grants.gov APIs and writes `data/` and `digests/` under the current directory.

## Conventions

- Scoring stays explainable and uses no LLM. Every score keeps its `reasons`, its `matched_terms`, and its `ScoreBreakdown`.
- Match the dense style of the existing code. Do not reformat a line that you are not changing. The repository has no formatter config, and a formatter rewrites nearly every file.
- Ask before adding a dependency. The package uses the standard library. Only the dashboard needs `streamlit` and `pandas`.

## Gotchas

- This repository is a fork. Push and open pull requests against `jrmatherly/Research-Grant-Finder-Agent` only, never against the upstream repository.
- `_run` in `cli.py` repeats the pipeline in `fetch_score_opportunities` in `workflow.py`. Change both, or make `_run` call the workflow function.
- `NIH Extractor/data/`, `NIH Extractor/outputs/`, and `NIH Extractor/digests/` hold generated files. Change the code that writes them, not the files.
- `tests/test_streamlit_app_static.py` asserts literal strings in `streamlit_app.py`. A reworded line or comment in that file can fail a test.
