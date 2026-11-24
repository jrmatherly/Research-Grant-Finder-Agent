# Research Grant Finder Agent

The Python package `nih_grant_matcher` and a Streamlit dashboard live in `NIH Extractor/`. The directory name has a space, so quote it in shell commands.

## Commands

Start your coding assistant at the repository root, so that it loads the project settings in `.claude/`. Run the commands below from `NIH Extractor/`. The tests fail from the repository root, because pytest finds the package and `streamlit_app.py` relative to that directory.

- The project is a uv project. `uv sync` installs the dependencies and pytest into `.venv` from `uv.lock`.
- Run all tests: `uv run pytest -q`.
- Run one test file: `uv run pytest -q tests/test_scoring.py`
- Run the dashboard: `uv run streamlit run streamlit_app.py`
- Run the CLI: `uv run python -m nih_grant_matcher run --source nih-guide`. It calls live public APIs and writes `data/` and `digests/` under the current directory.
- Build the macOS app with `macos/build.sh` on an Apple silicon Mac. It writes `macos/dist/Grant Matcher.app` and `Grant Matcher.dmg`, and signs them with that identity when `CODESIGN_IDENTITY` is set, ad hoc otherwise. `docs/macos-app.md` is the user page. `macos/` is not part of the Docker image and needs no `COPY` line. The build runs on uv's own Python and fails when the app would read its CA certificates from a file that macOS does not ship. `.github/workflows/macos-build.yml` builds the app on a pull request, so read that check before you merge an update to the `macos` dependency group or to streamlit, whose licence files the build checks against `macos/streamlit-licenses.sha256`.
- `docs/docker.md` tells a user how to run the published image. Every command in it was run against the image. Run a command again before you change it.
- Run in Docker, from the repository root: `docker compose up --build -d` serves the dashboard on `localhost:8501`. `docker compose run --rm app python -m nih_grant_matcher run` runs the CLI. `NIH Extractor/Dockerfile` installs from `pyproject.toml` and `uv.lock` and copies only `streamlit_app.py` and the package. A new file inside the package needs nothing. A new runtime file beside it needs a `COPY` line, an entry in `NIH Extractor/.dockerignore`, and an entry in the `paths` list of `docker-image.yml`.

## CI

- `.github/workflows/tests.yml` runs pytest on Python 3.11, 3.13, and 3.15. Require the check `✅ Required checks passed`, not the matrix legs.
- `.github/workflows/docker-image.yml` lints the Dockerfile, builds the image, and pushes `ghcr.io/jrmatherly/nih-grant-matcher` on a `v*` tag and on a push to `main` that changes a file in its `paths` list. A pull request that changes one of those files builds without pushing. A weekly run rebuilds and pushes, so that the image takes Debian's security fixes. Every build is scanned with Trivy first, and a HIGH or CRITICAL vulnerability that has a fix fails the job.
- `.github/workflows/macos-release.yml` runs on a `v*` tag. It builds, signs and notarizes the macOS app on an Apple silicon runner and attaches the disk image and the update feed `appcast.xml` to the tag's release. Installed apps read the feed from the newest release that is not a pre-release, so a release without `appcast.xml` must not become the newest. It needs the six secrets that `docs/macos-app.md` lists, and the tag must equal `v` plus the `version` in `pyproject.toml`.
- `.github/workflows/macos-build.yml` builds the app with an ad hoc signature and no secret. It runs on a pull request into `main` that changes `NIH Extractor/macos/`, the package, `streamlit_app.py`, `pyproject.toml`, `uv.lock`, `.python-version` or either macOS workflow, and on a manual run. It keeps the disk image as an artifact for three days and publishes nothing. No other run builds the app before a tag, so read its check before you merge a change to what the app bundles or to how it is built.
- Pin every action to a commit with its tag in a comment, and start every step name with an emoji. Check a workflow change with `actionlint` and `zizmor .github/workflows`, and the Dockerfile with `hadolint`.
- `renovate.json` moves the action pins, the image digests, uv, and the packages in `pyproject.toml` and `uv.lock`. A raise of the Python version is a manual change to the Dockerfile tag, the CI matrix, and `pyproject.toml` together.

## Conventions

- Scoring stays explainable and uses no LLM. Every score keeps its `reasons`, its `matched_terms`, and its `ScoreBreakdown`.
- Match the dense style of the existing code. Do not reformat a line that you are not changing. The repository has no formatter config, and a formatter rewrites nearly every file.
- Ask before adding a dependency. The package uses the standard library. Only the dashboard needs `streamlit` and `pandas`.
- `uv.lock` pins the versions that CI and the Docker image install. Add a package with `uv add`, or `uv add --dev` for a test tool. After a hand edit of `pyproject.toml`, run `uv lock`. CI and the image fail when the lockfile is out of date.
- `pyproject.toml` sets `package = false`: uv installs the dependencies and does not build the project, so run commands from `NIH Extractor/`.
- `exclude-newer = "1 week"` in `pyproject.toml` and `minimumReleaseAge` in `renovate.json` are the same delay. Change them together.
- `nih_grant_matcher/ui/vendor/` holds driver.js 1.14.0, copied by hand and pinned by `tests/test_tour.py`. Renovate does not move it, and it is the only JavaScript in the package.

## Gotchas

- This repository is a fork. Push and open pull requests against `jrmatherly/Research-Grant-Finder-Agent` only, never against the upstream repository.
- `NIH Extractor/data/`, `NIH Extractor/outputs/`, and `NIH Extractor/digests/` hold generated files. Change the code that writes them, not the files.
- `nih_grant_matcher/term_rarity.json` is generated. See `.claude/rules/scoring.md` before you rebuild it.
- `tests/test_streamlit_app_static.py` asserts literal strings in `streamlit_app.py`. A reworded line or comment in that file can fail a test.
