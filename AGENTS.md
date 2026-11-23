# Research Grant Finder Agent

The Python package `nih_grant_matcher` and a Streamlit dashboard live in `NIH Extractor/`. The directory name has a space, so quote it in shell commands.

## Commands

Start your coding assistant at the repository root, so that it loads the project settings in `.claude/`. Run the commands below from `NIH Extractor/`. The tests fail from the repository root, because pytest finds the package and `streamlit_app.py` relative to that directory.

- The project is a uv project. `uv sync` installs the dependencies and pytest into `.venv` from `uv.lock`.
- Run all tests: `uv run pytest -q`.
- Run one test file: `uv run pytest -q tests/test_scoring.py`
- Run the dashboard: `uv run streamlit run streamlit_app.py`
- Run the CLI: `uv run python -m nih_grant_matcher run --source nih-guide`. It calls live public APIs and writes `data/` and `digests/` under the current directory.
- Run in Docker, from the repository root: `docker compose up --build -d` serves the dashboard on `localhost:8501`. `docker compose run --rm app python -m nih_grant_matcher run` runs the CLI. `NIH Extractor/Dockerfile` installs from `pyproject.toml` and `uv.lock` and copies only `streamlit_app.py` and the package, so list a new runtime file in `NIH Extractor/.dockerignore`.

## CI

- `.github/workflows/tests.yml` runs pytest on Python 3.11, 3.13, and 3.14. Require the check `✅ Required checks passed`, not the matrix legs.
- `.github/workflows/docker-image.yml` lints the Dockerfile, builds the image, and pushes `ghcr.io/jrmatherly/nih-grant-matcher` on a push to `main` or a `v*` tag. A pull request builds without pushing.
- Pin every action to a commit with its tag in a comment, and start every step name with an emoji. Check a workflow change with `actionlint` and `zizmor .github/workflows`, and the Dockerfile with `hadolint`.
- `renovate.json` moves the action pins, the image digests, uv, and the packages in `pyproject.toml` and `uv.lock`. A raise of the Python version is a manual change to the Dockerfile tag, the CI matrix, and `pyproject.toml` together.

## Conventions

- Scoring stays explainable and uses no LLM. Every score keeps its `reasons`, its `matched_terms`, and its `ScoreBreakdown`.
- Match the dense style of the existing code. Do not reformat a line that you are not changing. The repository has no formatter config, and a formatter rewrites nearly every file.
- Ask before adding a dependency. The package uses the standard library. Only the dashboard needs `streamlit` and `pandas`.
- `uv.lock` pins the versions that CI and the Docker image install. Add a package with `uv add`, or `uv add --dev` for a test tool. After a hand edit of `pyproject.toml`, run `uv lock`. CI and the image fail when the lockfile is out of date.
- `pyproject.toml` sets `package = false`: uv installs the dependencies and does not build the project, so run commands from `NIH Extractor/`.
- `exclude-newer = "1 week"` in `pyproject.toml` and `minimumReleaseAge` in `renovate.json` are the same delay. Change them together.

## Gotchas

- This repository is a fork. Push and open pull requests against `jrmatherly/Research-Grant-Finder-Agent` only, never against the upstream repository.
- `NIH Extractor/data/`, `NIH Extractor/outputs/`, and `NIH Extractor/digests/` hold generated files. Change the code that writes them, not the files.
- `nih_grant_matcher/term_rarity.json` is generated. See `.claude/rules/scoring.md` before you rebuild it.
- `tests/test_streamlit_app_static.py` asserts literal strings in `streamlit_app.py`. A reworded line or comment in that file can fail a test.
