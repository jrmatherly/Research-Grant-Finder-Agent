# Research Grant Finder Agent

The Python package `nih_grant_matcher` and a Streamlit dashboard live in `NIH Extractor/`. The directory name has a space, so quote it in shell commands.

## Commands

Start your coding assistant at the repository root, so that it loads the project settings in `.claude/`. Run the commands below from `NIH Extractor/`. The tests fail from the repository root, because pytest finds the package and `streamlit_app.py` relative to that directory.

- Run all tests: `python -m pytest -q`. When pytest is not installed, use `uv run --no-project --with pytest pytest -q`. `tests/test_streamlit_app_run.py` runs the dashboard and is skipped when `streamlit` is not installed. To include it, add `--with-requirements requirements.lock` to the `uv` command.
- Run one test file: `python -m pytest -q tests/test_scoring.py`
- Run the dashboard: `streamlit run streamlit_app.py`
- Run the CLI: `python -m nih_grant_matcher run --source nih-guide`. It calls live public APIs and writes `data/` and `digests/` under the current directory.
- Run in Docker, from the repository root: `docker compose up --build -d` serves the dashboard on `localhost:8501`. `docker compose run --rm app python -m nih_grant_matcher run` runs the CLI. `NIH Extractor/Dockerfile` copies only `requirements.lock`, `streamlit_app.py`, and the package, so list a new runtime file in `NIH Extractor/.dockerignore`.

## CI

- `.github/workflows/tests.yml` runs pytest on Python 3.11, 3.13, and 3.14. Require the check `✅ Required checks passed`, not the matrix legs.
- `.github/workflows/docker-image.yml` lints the Dockerfile, builds the image, and pushes `ghcr.io/jrmatherly/nih-grant-matcher` on a push to `main` or a `v*` tag. A pull request builds without pushing.
- Pin every action to a commit with its tag in a comment, and start every step name with an emoji. Check a workflow change with `actionlint` and `zizmor .github/workflows`, and the Dockerfile with `hadolint`.
- `renovate.json` moves the action pins, the base image digest, and `requirements.lock`. A raise of the Python version is a manual change to the Dockerfile tag, the CI matrix, and `pyproject.toml` together.

## Conventions

- Scoring stays explainable and uses no LLM. Every score keeps its `reasons`, its `matched_terms`, and its `ScoreBreakdown`.
- Match the dense style of the existing code. Do not reformat a line that you are not changing. The repository has no formatter config, and a formatter rewrites nearly every file.
- Ask before adding a dependency. The package uses the standard library. Only the dashboard needs `streamlit` and `pandas`.
- `requirements.lock` pins the versions that CI and the Docker image install. After a change to `requirements.txt`, write it again with `uv pip compile requirements.txt --universal --python-version 3.11 -o requirements.lock`.

## Gotchas

- This repository is a fork. Push and open pull requests against `jrmatherly/Research-Grant-Finder-Agent` only, never against the upstream repository.
- `NIH Extractor/data/`, `NIH Extractor/outputs/`, and `NIH Extractor/digests/` hold generated files. Change the code that writes them, not the files.
- `tests/test_streamlit_app_static.py` asserts literal strings in `streamlit_app.py`. A reworded line or comment in that file can fail a test.
